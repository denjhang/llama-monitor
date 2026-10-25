# Flash-Next 治"雷霆思考"社区版本选型

**日期**：2026-10-26
**背景**：当前生产载入 `Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S`（E:/Strata-data/models/IQ3_S，79GB 两分片 + 0.91GB mmproj，8081 端口，Strata 四卡）。原版 Qwen3.8-Flash-Next 有"雷霆思考"毛病（思考 token 爆炸、过度思考），用户要求找一个**量化档位接近当前 IQ3_S（79GB）**的治思考社区版本。

---

## 一、结论（先看这个）

**首选：`ukisai/Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-GGUF` 的 IQ3_S 档**

| 项 | 值 |
|---|---|
| 仓库 | `ukisai/Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-GGUF` |
| 量化档 | IQ3_S，分片 44.90GB + 38.84GB = **83.7GB** |
| 格式 | **GSQ-RCO**（与当前载入模型完全同格式，Strata 直接吃） |
| 治思考效果 | 思考 token **平均 ↓63.4%（中位）**，精度损失 <1% |
| 加速 | 1.8x（官方 demo：建游戏 8'52" → 4'56"） |
| 定位 | 专门为 **coding / long-horizon agent（终端、软件工程）** 后训练 |

**次选：`bottlecapai/ThinkingCap-Qwen3.8-Flash-Next-GGUF` 的 IQ4_XS 档**

| 项 | 值 |
|---|---|
| 量化档 | IQ4_XS，8 分片合计 **89.0GB** |
| 格式 | 普通 GGUF（**非 GSQ-RCO**，Strata 需另配 pack 或走 llama.cpp） |
| 治思考效果 | 思考 token 平均 ↓38.5%，精度 89.8→88.8（↓1 点） |
| 缺点 | 比当前大 10GB；无 GSQ-RCO 格式；无 IQ3_S 档 |

**推荐 Swift-1.5**：量化档更接近（83.7 vs 79GB）、同格式（GSQ-RCO）、治思考更强（63.4% vs 38.5%）、且专攻 agent/coding（正对 ZCode 用途）。

---

## 二、候选全清单（2026-10-26 实测）

### 2.1 治思考（post-training，非纯量化）——只有两家

| 仓库 | 治思考强度 | 有 IQ3_S？ | 有 GSQ-RCO？ | 说明 |
|---|---|---|---|---|
| `ukisai/Swift-1.5-...-GSQ-RCO-GGUF` | **↓63.4%** | ✅ IQ3_S 83.7GB | ✅ | **首选**，agent/coding 专用 |
| `ukisai/Swift-1.5-...-GGUF` | 同上 | ✅ 多档 | ❌ 普通 GGUF | 同上但非 GSQ-RCO |
| `bottlecapai/ThinkingCap-...-GGUF` | ↓38.5% | ❌（最低 IQ4_XS 89GB） | ❌ | 次选 |
| `bottlecapai/ThinkingCap-...`（BF16 源） | ↓38.5% | — | — | 360GB，可本地转 IQ3_S |
| `Baekpica/ThinkingCap-...-Mixed-Quant-GGUF` | ↓38.5% | ❌（混合 Q5，125GB） | ❌（自研 SSD-PLE 格式） | 体积大，不划算 |

### 2.2 纯量化（不改思考行为，排除）

`ISTA-DASLab/...-GSQ-RCO-GGUF`（当前模型来源）、`boxrunner/...-IQ3_S-GGUF`、`pentacoxian-dev/...-IQ3E-Q8D-MTP-GGUF`、`Jundot/...-oQ4e-mtp`、`Maximilian228/...-Q8_0-Strata` 等——都只是原版量化，雷霆思考毛病照旧。

### 2.3 反向（加重思考，排除）

`DavidAU/...-Turbo-Brilliance-50x-Reasoning-Instruct-GSQ-RCO-GGUF`——"50x 推理"，与治思考目标相反。

### 2.4 abliterated/uncensored（不治思考，排除）

`SC117/...-GSQ-RCO-abliterated-GGUF`（254万下载）、`huihui-ai/...-abliterated-GGUF`、`jimmy31chen/RVN-...-Abliterated-Uncensored-IQ3_S-Strata`（39万下载）等——去审查，不治思考。

---

## 三、Swift-1.5 官方评测（BF16 对比 base）

思考 token 平均下降，精度几乎不掉，个别项反升：

| Benchmark | Base 分 | Swift 分 | token 中位降幅 |
|---|---|---|---|
| GPQA-Diamond | 89.80% | 89.60% | ↓63.4% |
| MMLU-Pro | 87.75% | 87.20% | ↓24.0% |
| C-Eval | 93.27% | **93.60%** | ↓7.1% |
| IFBench | 73.20% | 70.13% | ↓55.6% |
| AIME 2026 | 98.67% | 96.67% | ↓51.1% |
| HMMT Nov2025 | 98.00% | 97.33% | ↓54.7% |
| ERQA（多模态） | 70.80% | 69.30% | ↓47.7% |
| LiveCodeBench v6 | 88.40% | **90.39%** | ↓52.0% |
| Terminal-Bench 2.1 | 67.64% | **69.66%** | ↓17.9%（总输出 token） |

训练方法（官方）：**定位与"病态过度思考"关联的 token 并惩罚它们，而非直接砍推理长度**，再用 RL + OPD 把精度找回——所以"压缩"了 token 但保住了准确率。对 coding/终端/软件工程做了专项后训练。

---

## 四、下载与部署要点

### 4.1 PLE 分片不能复用（已实测）

- 当前 IQ3_S 的 PLE 分片（00002，28.80GB）本地 SHA256 = `316b46f3a2dbd68c900f43136ab9449f9dcc3725dfd8c794847c204bc161e113`
- ThinkingCap 各档 00002 分片 SHA256 = `71d6e51fc4d8c5f9a591532bc480db5f3a29b25538a6b7792941fd92278173d6`
- Swift-1.5 IQ3_S 00002 = `5b8379b8b25718d0a76982111749b999c6146b482f802667f400e817e97b415f`（38.84GB，连 PLE 都重量化了）
- **结论**：三个都不同 → 必须整包下载，无分片复用空间。

### 4.2 下载（已完成，落在 J 盘）

**决策**：2026-10-26 用户批准，下载到 **J 盘**（429GB 空闲，唯一放得下的盘）。
**已完成并校验通过**（2026-10-26 07:04）：

| 文件 | 字节 | SHA256（官方 SHA256SUMS 权威） |
|---|---|---|
| `...-IQ3_S-00001-of-00002.gguf` | 44,900,816,736 | `46cb3996cd1a17fe8bc5ae1f9bb16869480de5a03f17f868d6047a20a46edd3b` ✅ |
| `...-IQ3_S-00002-of-00002.gguf` | 38,842,920,384 | `70ce6fb48a94fe34bd7e9a53a526be68066c64b5a5077cdc82fb31350b66b608` ✅ |
| `mmproj-Swift-Qwen3.8-Flash-Next-BF16.gguf` | 907,543,520 | `cd1140f4abba943ce8d9fa92fed8407e389954d26907efde7b72153c75bd8a60` ✅ |

路径：`J:/Swift15-IQ3_S/`（脚本 `download.sh` + `resume.sh` + `SHA256SUMS.official`）。

**下载踩坑（重要教训）**：
1. **hf-mirror 对 ~40GB 大文件的尾部限速**：多连接下到 99% 时速度从 30MB/s 掉到 0.08MB/s，卡死。中途切 7892 代理直连 huggingface.co 可恢复，但代理尾部同样慢。
2. **不要删 `.aria2` 控制文件用 curl 续传**：aria2c 多连接会留中间稀疏空洞，删控制文件后 curl 从末尾续传只补尾部，中间空洞仍在 → SHA256 必失败。**正确做法**：保留 `.aria2`，反复用同一 aria2c `-c` 续传直到字节数达标。
3. **hf-mirror 的 ETag ≠ SHA256**（这些文件走 Xet 存储，HF API 显示 `no-lfs`）→ 必须从仓库根目录的官方 `SHA256SUMS` 取权威哈希，否则会误判 FAILED。
4. 实测 hf-mirror 直连速度可达 84MB/s，限速是 CDN 临时行为，可重试。

### 4.3 磁盘账（2026-10-26）

| 盘 | 总量 | 已用 | 空闲 | 备注 |
|---|---|---|---|---|
| D: | 676G | 655G | 22G | 系统盘，紧张（D:/working 379G 最大） |
| E: | 239G | 221G | 19G | 当前 IQ3_S 79GB 在此 |
| F: | 234G | 191G | 44G | F:/备份 87G、F:/working 40G |
| **J:** | **1.9T** | **1.6T** | **325G** | **新模型已落此** |
| H: | 932G | 503G | 430G | 备用 |
| I: | 1.9T | 1.7T | 222G | 备用 |
| G: | 1.9T | 1.8T | 35G | 满 |

**旧的 E:/Strata-data/models/IQ3_S（79GB）暂不删**——等新模型验证可用后再与用户沟通替换（用户规则：废弃产物先沟通不自己删）。

### 4.4 下一步：pack/mtp 复用性评估

新模型是 GSQ-RCO 同格式、同 base（Qwen3.8-Flash-Next），但权重经治思考后训练有变化。启动前需实测：
- `E:/Strata-data/packs/iq3_s`（dense.bin + expert 索引）——结构大概率兼容，但 expert 权重变了，**很可能需重新生成 pack**
- `E:/Strata-data/mtp/rt`（MTP 草稿头）——**几乎肯定需重生成**（训练改了权重）
- 先直接用现有 pack/mtp 试启动，若报校验错再重生成

Strata 配置可直接套用 `E:/strata-src/strata-iq3_s-4gpu.json`，只改 `--native` / `--ple-gguf` 指向 J 盘新文件名，并加 `--vision` 的 mmproj 路径。

---

## 五、附带议题：四卡 Flash-Next 下能否再挂双卡 coder390（保 256K）

**用户问**：当前 Flash-Next 占 GPU0-3 跑 256K，能否再载入双卡 coder390 并保 256K？

### 5.1 coder390 @256K 显存账（基于其加载日志精算）

coder390 是 `qwen35` 混合架构（SSM + 全注意力，`full_attention_interval=4`，65 层里 16 层带全注意力 KV）：

| 项 | GiB | 依据 |
|---|---|---|
| 权重（66 层全 offload） | 16.1 | GGUF 17.304GB |
| DFlash2 草稿（须同首卡） | 1.9 | 2.056GB |
| mmproj | 0.6 | 0.629GB |
| **KV @256K** | **4.50** | 实测 32K=576MiB → 18KiB/token |
| compute buffer（-ub 2048） | 2.59 | 日志 CUDA2 468 + CUDA3 2020 + Host 168 MiB |
| 余量 | 0.6 | |
| **合计** | **26.3** | **每卡 ~13.2 GiB** |

**关键**：coder390 的 KV 只要 4.5 GiB（16 层全注意力 + q4_0 KV），**KV 不是瓶颈，权重才是**。要两张连续卡各 13.2 GiB。

### 5.2 当前各卡空闲（Flash-Next 四卡运行时）

| 卡 | 已用 | 空闲 | 说明 |
|---|---|---|---|
| GPU0 | 18.6 | 1.6 | layer-split 主段 + 首层专家缓存 |
| GPU1/2/3 | 各 12.5 | 各 7.5 | 专家缓存各 11.48 GiB |
| GPU4 | 1.8 | 18.0 | 桌面卡 |

### 5.3 结论：**原配置硬塞必崩**

- 双卡需连续两卡各 13.2 GiB，**无任何两张满足**（GPU1+2 仅 15 GiB，差 11 GiB）
- GPU4 单卡 18 GiB 也不够 26.3，且单卡实测坍塌到 5-7 t/s
- 硬塞会触发驱动往系统内存分页，速度掉到几 t/s

### 5.4 两条可行路（都需重启 Flash-Next 改配置）

**方案 A：Flash-Next 降 2 卡（GPU0,1），coder390 用 GPU2,3**
- GPU2/3 各释放 20.5 GiB → coder390 双卡装得下，且回到原计算卡，桌面卡不受影响
- 代价：Flash-Next 专家缓存 3 层→1 层，命中率从当前 100% 明显下降，速度降低

**方案 B：Flash-Next 降 3 卡（GPU0,1,2），coder390 用 GPU3+GPU4**
- GPU3(20.5)+GPU4(18.0)=38.5 GiB，宽裕
- Flash-Next 只丢 1 层专家缓存，损失较小
- 代价：coder390 跑在桌面卡 GPU4，用户上网/看视频时会抢资源略卡

**取舍**：看重 Flash-Next 性能 → 选 B；不让 coder390 碰桌面卡 → 选 A。

---

## 六、待用户决策

1. ~~是否下载 Swift-1.5 IQ3_S？~~ ✅ **已下载并校验通过**（`J:/Swift15-IQ3_S/`）
2. **下一步**：是否用 Swift-1.5 替换当前生产的 IQ3_S？需先试启动验证 pack/mtp 复用性，旧的 E: IQ3_S 暂不删。
3. **coder390 共存**：选方案 A（Flash-Next 2 卡 + coder390 计算卡）还是方案 B（Flash-Next 3 卡 + coder390 含桌面卡）？
4. 备选：ThinkingCap IQ4_XS（89GB，非 GSQ-RCO）——Swift-1.5 更优，一般不必再考虑。
