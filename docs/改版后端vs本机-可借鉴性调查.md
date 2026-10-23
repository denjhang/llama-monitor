# 改版推理后端 vs 本机 ik_llama —— 可借鉴性调查（2026-10-23）

> 起因：社区出现一批"专用推理后端"（NInfer 全家桶、SGLang 定制补丁），宣称在同类显卡上
> decode 远超 llama.cpp。本文回答：**它们快在哪、有多少是引擎功劳、本机（5×RTX3080 20G，
> Windows，PCIe 3.0，无 NVLink）能借鉴什么**。
> 结论先行：**引擎贡献真实且可量化（约 +40%），但核心提速机制依赖本机没有的硬件（NVLink /
> NVFP4 / sm_70 手写内核）；本机能落地的只有 KV 量化与草稿窗口调优。**

---

## 一、决定性对照：同一个 Coder390，两套后端

| 项目 | 本机（双 3080） | 双 V100-SXM2（NVLink） |
|---|---|---|
| 引擎 | ik_llama（llama.cpp 系通用内核） | NInfer（单模型手写内核） |
| 模型 | Coder390 Q3 LynnStyle | Coder390 **Q6_K** |
| decode | **45–52 tok/s** | **82.3 tok/s** |
| prefill | 40–100 tok/s | 1501 tok/s |
| 显存带宽 | 760 GB/s（GDDR6X） | 900 GB/s（HBM2） |
| 卡间互联 | PCIe 3.0（本机实测 gen1×4~×8 空载） | **NVLink 300GB/s 双向** |

**关键推理**：显存带宽只差 1.18 倍，decode 却差 1.6 倍。**多出的约 40% 就是引擎定制的贡献**——
不是纯硬件差。注意 V100 用的是**更高比特的 Q6_K**（权重更大、本该更慢），却仍然快 1.6 倍，
说明引擎差距被低估了。

---

## 二、那 40% 具体来自哪里（四个机制）

来自 NInfer 的 `docs/v100.md` 与源码（`plus1998/NInfer-V100-Duo`）：

### 1. INT8 group-64 KV + D256 Hadamard 变换
- 不是单纯省显存：**KV 量化前先做 Hadamard 旋转**，把能量摊平、削掉峰值，再量化误差更小
- 原文：*"INT8 group-64 KV applies the registered normalized D256 Hadamard transform to both
  persistent K and transient Q before the flash calculation"*
- 对标：SGLang 补丁（kk-pcl）的"逐头 FP8 校准"是同一思路的轻量版

### 2. 优化 proposal head（索引式草稿头）—— decode 提速最大头
- 把 MTP 接受率拉到 **97–99%**（本机 DFlash2 接受率低，大量草稿白算）
- 索引式：草稿头只算 top-k 索引而非全词表 logits，草稿成本骤降
- 实测 K 扫描：K=1 时 decode **219 tok/s**、接受率 99.2%（合成语料上限）
- 真实文本甜点 K=3

### 3. CUDA Graph 全程应用
- decode 全程 graph 重放，消除逐 token 的 kernel 调度开销
- 本机 ik_llama 有 `-gr`（默认开），但 NInfer 把 graph 用得更彻底（含 draft 阶段）

### 4. NVFP4 + QPN 预排列
- 权重加载时按 Volta 张量核片段顺序**预重排**（QPN fragment order），decode 直接吃排好的布局
- 覆盖 code 和 scale 两个平面，运行时不再做排列

---

## 三、哪些是硬件锁死的（本机抄不到）

| 机制 | 为什么抄不到 |
|---|---|
| **NVLink TP2** | V100-SXM2 有 NVLink（300GB/s 双向）；本机 3080 走 PCIe 3.0，实测空载 gen1×4~×8。双卡 TP 通信带宽差 ~37 倍，多卡 TP 注定吃亏 |
| **NVFP4 / QPN** | V100 靠 QPN 用 FP16 张量核模拟 FP4；本机 3080 也无 FP4 硬件，且无对应内核 |
| **sm_70 / sm_120a 手写内核** | NInfer 只为这两种 arch 写 kernel，构建**直接拒绝其他 arch**。3080 的 sm_86 不在支持表 |
| **`.ninfer` 私有格式** | 与 GGUF 生态完全不通用，需转换，且官方转换器只针对其支持的模型 |

**本机 5×3080 的正确路线始终是「多模型并行」（单卡一个模型），不是多卡 TP 一个模型。**
这是 PCIe 3.0 平台下的最优解，现役布局（8081/8083/8085/8086 各占卡）已经是对的。

---

## 四、本机能落地的优化（立刻可做）

### 4.1 KV 量化升级：q4_0 → q8_0（零成本，优先做）
- 现状：`-ctk q4_0 -ctv q4_0`
- ik_llama 支持 q8_0（int8 级）。32K 上下文只多占约 2.3GB，但：
  - 压 decode 中的 KV 反量化误差（质量）
  - **Q8 反量化比 Q4 简单，可能反而更快**
- 这是 NInfer 用 INT8 KV 的同款收益，ik_llama 原生支持，改一个参数即可

### 4.2 草稿窗口扫描（DFlash2 n_max）
- 现状 `--spec-type dflash:n_max=4`，未做系统扫描
- NInfer 的 K 扫描显示：**合成语料窄窗口赢，真实文本 K=3 是甜点**
- 本机应扫 n_max=2/3/4/6，取真实 coding 负载下的最优

### 4.3 线程/批参数（本机 CPU 是短板）
- CPU：E5-2673 v4 ×2（40核80线程，2.3GHz，AVX2）
- 现状 `-t` 默认 40。可试 `-t 20`（物理核）vs `-t 40`（含超线程）、`-tb`/`-td` 分离
- `-ub`/`-b`：现状 2048/8192，可试更大 ub 换 prefill

### 4.4 需要改源码才能做的（成本高，暂缓）
- 优化 proposal head（索引式草稿头）：ik_llama 没暴露参数，得改 `llama-dflash.cpp`
- KV 的 Hadamard 变换：ik_llama 无此路径，需在 flash-attn 前插入旋转

---

## 五、平台差异（控制变量提醒）

NInfer 作者机器与本机**不是完全控制变量**，除显卡外还有：

| 项 | 本机 | 说明 |
|---|---|---|
| CPU | E5-2673 v4 ×2 @2.3GHz（40C/80T） | 老 Xeon，单核弱；NInfer 设计吃 CPU 单核 |
| 内存 | 256GB DDR4-2133（8×32G） | 频率低 |
| 主板 | Intel AI-8PLUS（矿板） | PCIe 3.0，插槽带宽分配受限 |
| 驱动 | 610.62 | 新，不是瓶颈 |

**所以"NInfer 快"里有一部分是本机 CPU/主板拖累的对照偏差**，不能全归给引擎。但 KV 量化、
草稿窗口这两项与硬件无关，纯粹是引擎行为差异，可以放心借鉴。

---

## 六、参考仓库清单

| 仓库 | ★ | 用途 |
|---|---|---|
| `Neroued/ninfer` | 3142 | 上游，仅 5090/Linux/sm_120a |
| `plus1998/NInfer-V100-Duo` | 34 | 双 V100 TP2 基础（Linux） |
| `Xxx-Bin/NInfer-V100-Duo-Win` | 1 | **双 V100 Windows 原生**，无需 WSL2，含 REBUILD 配方 |
| `ww485000/ninfer-windows-v100` | 11 | 单 V100 Windows 移植，228 tok/s（含 MTP3 99.17% 接受率） |
| `lurenakillgore9-web/NInfer-Qwen3.8-27B-IQ3S-sm86-win64` | 10 | **sm86 + Windows 整合包**（27B IQ3_S，prefill 1300-1400） |
| `5258MF/ninfer-rtx3060-27b` | 42 | RTX30系 sm86 + Win，**有源码** |
| `kk-pcl/sglang-qwen38-dual-3080-patch` | 18 | SGLang 双 3080 补丁（per-head FP8 KV + TP 分片 draft） |
| `huangserva/ninfer-v100-tpx` | 16 | 双 V100 跑到 100 tok/s（唯一多卡案例） |

---

## 七、下一步

- [ ] Coder390 KV 量化 q4_0 → q8_0，对照 decode/prefill/显存
- [ ] DFlash2 n_max 扫描 2/3/4/6（真实 coding 负载）
- [ ] 线程参数对照（-t 20 vs 40）
- [ ] 若 KV 量化有收益，同步应用到 8085(35B) / 8083(星火)
- [ ] 评估是否值得改 ik_llama 源码做索引式 proposal head
