# ik_llama Coder390 decode 提速复盘（2026-10-19）

> 结论先行：**27B 密集模型的 decode 是多 GPU split 的天敌，却正好是投机解码的舞台。**
> 最终把 DFlash2 专用草稿放回**与主模型同一张卡**，decode 从 28 t/s 提到 **45-52 t/s（+50%）**。

## 背景

- 模型：`Qwen3.8-27B-Coder390-EfficientThink-Q3LynnStyle`（27B 密集 VL，Q3 量化，17GB 权重 + 0.6GB mmproj）
- 硬件：5×RTX 3080 20GB
- 引擎：ik_llama.cpp（本次一并把二进制从 `a313ddc`/v1 更新到 `38c333c`/v36）

## 关键结论（按重要度排序）

### 1. 草稿模型必须与主模型同卡（决定性）

| DFlash2 草稿位置 | decode 实测 |
|---|---|
| 跨卡（`--device-draft CUDA1`，主模型 GPU2/3） | 20-35 t/s，抖动大 |
| **同卡（`--device-draft CUDA2`，与主模型首卡一致）** | **45-52 t/s** |

原因：DFlash2 每步都要把 target feature 从主模型传到草稿模型，跨 PCIe Gen3 传输让带宽饿死（社区 3090 报告同样现象：MTP 在 32K 上下文倒挂 -46%，`nvidia-smi` 显示 `11.3 GB/s rx`，非算力瓶颈而是 PCIe 饿死）。

### 2. 多 GPU split 对 decode 是负收益

| 配置 | decode 实测 | 说明 |
|---|---|---|
| 单卡 CUDA2 | 31.3 t/s | 带宽瓶颈在单卡 |
| 双卡 CUDA2/3（layer split） | 31-32 t/s | 与单卡持平，PCIe 转发吃掉了并行收益 |
| 4 卡 CUDA0-3 | **4-13 t/s** | 严重劣化，-70% |
| 4 卡 graph split | 10-12 t/s | 同样劣化 |

decode 是严格的串行单流：每生成一个 token 都要读一遍全部权重，多卡 split 只是把「读权重」变成「跨卡读权重 + 传激活」，不会更快。**27B 密集模型多卡提速只在 prefill 有效**（4 卡 prefill 172 t/s vs 双卡 90 t/s，+1.9x）。

### 3. MTP 头内投机在 27B 上是负收益

| 配置 | decode 实测 |
|---|---|
| 无投机（基线） | 31-32 t/s |
| MTP `n_max=2` | 23-25 t/s (-25%) |
| MTP `n_max=4` | 25-27 t/s |

原因：MTP 头挂在主模型内，草稿生成本身要跑一次 27B 前向，草稿成本 ≈ 验证成本，接受率（0.64-0.74）不足以摊平。**MTP 适合小/中模型或带宽强的大卡，不适合 27B 密集 + 3080。**

### 4. 单卡装不下 MTP（20GB 显存硬约束）

27B Q3 权重 13.9GB + MTP 上下文 + compute buffer 必然超 20GB。加 MTP 就 OOM，无论开不开关视觉、降到 16K 上下文都不行。

## 最终生产配置（start-coder390.bat）

```
--device CUDA2,CUDA3          # 主模型 layer split 双卡
--device-draft CUDA2          # ★ DFlash2 草稿与主模型首卡同卡
--model-draft .../dflash2-qwen38-27b-Q8_0.gguf
--spec-type dflash:n_max=4
-c 32768                      # 32K 上下文（host_ring 3.2GB；128K 会涨到 12.8GB）
```

实测：decode 45-52 t/s（400 tok 时 51-52），prefill 40-100 t/s。

## 草稿模型配对铁律

**投机解码的草稿模型不能跨模型族通用**，必须与主模型共享同一 tokenizer/vocab：

- ❌ `Spark-X2.5-1.7B-Q8_0.gguf` 搭 Qwen 主模型 → 启动报 `unknown model architecture: 'spark2_5'`
- ✅ `z-lab/Qwen3.8-27B-DFlash2-GGUF`（本机 `D:\working\gguf-sidecars\qwen38-27b\dflash2-qwen38-27b-Q8_0.gguf`）——z-lab 专为 Qwen3.8-27B 训练的 DFlash2 草稿

## ik_llama 二进制更新记录

- 旧：`version 1 (a313ddc)`，2026-10-06 编译
- 新：`version 36 (38c333c)`，2026-10-13 源码 + 本次重编译
- 源码 HEAD 早已领先 36 个 commit，二进制一直没重新编译，导致 `--spec-type`/FlashAttn 等新版功能缺失
- 旧版备份：`D:\llama-ik\backup-a313ddc-20261019\bin\{llama-server.exe,ggml.dll}`
- 编译命令（需 vcvars64 + CUDA 12.6 + Ninja，arch 86）：
  ```bat
  call "C:\VS2022BT\VC\Auxiliary\Build\vcvars64.bat"
  cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON -DGGML_BLAS=OFF -DCMAKE_CUDA_ARCHITECTURES=86 -DGGML_NATIVE=ON
  cmake --build build --config Release --parallel 40
  ```

## 数据速查

| 指标 | 值 |
|---|---|
| Coder390 decode（最终） | 45-52 t/s |
| Coder390 decode（旧基线） | 28 t/s |
| Coder390 prefill（最终） | 40-100 t/s |
| DFlash2 接受率 | 0.65-0.72 |
| DFlash2 host_ring（32K） | 3.2GB |

## 参考文献

- 社区 MTP 全量扫频：https://github.com/sudoingX/qwen38-mtp（关键：32K 上下文 MTP 倒挂源自 PCIe 饿死）
- DFlash2 专用草稿：https://huggingface.co/z-lab/Qwen3.8-27B-DFlash2-GGUF

---

## 补充实验（2026-10-23）：参数空间穷举后的定论

> 起因：社区改版后端（NInfer 等）宣称同类卡 decode 远超 llama.cpp，回来系统排查本机还有无
> 优化余地。结论：**当前配置已接近本机硬件上限，参数层没有免费提速空间了。**
> 详见 [`改版后端vs本机-可借鉴性调查.md`](改版后端vs本机-可借鉴性调查.md)。

### 实测矩阵（agent coding 负载，双卡 CUDA2,3，32K，q4_0 KV）

| 配置 | decode | 草稿接受率 | 判定 |
|---|---|---|---|
| 无草稿基线 | 33.2 t/s | — | 参照 |
| **DFlash2 n_max=3** | **36-39 t/s** | 0.64-0.77 | **本机最优** |
| DFlash2 n_max=4（现役） | 32.1 t/s | 0.69 | 可用，略低于 n=3 |
| DFlash2 n_max=2 | 23-30 t/s | 0.80-0.87 | 窗口太小，验证开销占比高 |
| MTP n_max=1（自带头） | 28-30 t/s | 0.78-0.94 | 接受率高但每轮只 +1 token |
| MTP n_max=2 | 31-32 t/s | 0.74-0.76 | 不如 DFlash2 |
| MTP n_max=3 | 32-36 t/s | 0.60-0.73 | 不如 DFlash2 |
| graph split（=TP 式） | 19.4 t/s | — | **-42%，否决** |
| 单卡（主+草稿同卡） | 5-7 t/s | — | **显存竞争坍塌，否决** |

### 新定论（四条，都是实测否决）

1. **KV 量化不是瓶颈**：`q4_0` vs `q8_0` 在双卡上完全无差异（33.18 vs 33.21 t/s）。
   NInfer 的 INT8 KV 收益在本机复现不出来——**别再折腾 KV dtype**。
2. **线程数完全无关**：`-t 10/20/40/80` 全在噪声内（33.15-33.27）。全量 offload 到 GPU 后
   CPU 不参与 decode。**CPU 弱不是本机 decode 的瓶颈**（与 prefill 相反）。
3. **graph split 是负收益**（19.4 vs 33.2，-42%）：PCIe 3.0 下 TP 式分片吃通信开销。
   NInfer 靠 NVLink 玩 TP2 的前提本机没有——**多卡 TP 路线彻底否决**。
4. **单卡装不下主+草稿**：27B Q3（15G）+ 草稿（1.95G）+ KV = 17.7G，仅剩 3G，
   decode 因显存压力塌到 5-7 t/s。**双卡 layer split 是必需的**。

### 速度的真实杠杆：草稿接受率

所有数据指向同一个规律——**decode 速度直接由接受率决定**，与窗口大小呈倒 U 型：

- 接受率 0.85-0.95（历史长会话续写）→ 45-52 t/s
- 接受率 0.64-0.77（独立新请求）→ 32-39 t/s
- 接受率 0.80-0.87 但窗口 n=2（每轮 token 太少）→ 23-30 t/s

**历史 45-52 t/s 不是配置差异，是负载差异**——那是 ZCode agent 长会话（同项目连续续写，
草稿高度可预测），本次是独立新代码请求。同一配置两种负载能差 40%。

### 唯一剩下的优化方向（需改源码）

接受率是唯一杠杆，而提升它只能靠**更好的草稿头**（NInfer 的"优化 proposal head / 索引式"
把接受率推到 97-99%）。ik_llama 未暴露此参数，需改 `llama-dflash.cpp`。
**评估：收益可能 +30-50%，但成本高（需理解 DFlash2 草稿头实现 + 重编译），列为备选。**

### 生产配置建议

`start-coder390.bat` 的 `n_max=4` 可改为 **`n_max=3`**（本次实测 36-39 vs 32.1）。
差异在噪声边缘（历史 45-52 时 n=4 也表现良好），建议 A/B 后定夺。其余参数**保持不动**。