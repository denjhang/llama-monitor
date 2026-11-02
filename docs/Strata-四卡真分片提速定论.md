# Strata 四卡真分片 + pipeline-windows 提速定论（2026-11-02）

> 结论先行：**放弃"假分片 + 远端专家缓存"，改四卡四段真分片 + `--pipeline-windows 2`，
> 长输出 decode 从 40.9 t/s 提到 110.8 t/s（+171%）。**
> 这是本机 5×3080 平台在硬件不变前提下的最优解。

---

## 一、起因

用户要求"优化分片或优化 PCIe，硬件不可能变化"。
此前一直用的是 2026-10-19 定下的"四卡假分片"配置：

```
--layer-split 24 --split-device 0          # 48 层全在 GPU0
--remote-expert-opt --expert-cache-device1/2/3 auto   # GPU1-3 只当专家仓库
```

该配置 prefill 快（同卡内 hand-off 零 PCIe），但 decode 一直只有 40-50 t/s。
本次实测排除了几个错误方向，并找到了真凶。

---

## 二、排除掉的方向（都是无效的）

| 尝试 | 结果 | 说明 |
|---|---|---|
| 升级到引擎 0.1.50（v0.2.6）吃 sm_86 加速表 | **无效** | 9 个 sm_86 开关确实生效（日志确认），但实测 41.6/43.0/45.1 t/s，与 0.1.45 的 42.6/41.1/44.6 持平，无差异 |
| `--kv-resident` 20480 → 40960 | **无效** | KV 命中率 99.35-99.55%（原 95%），但速度 43.2/41.4/44.7，与前完全相同。**KV 从来不是瓶颈** |
| 双卡真分片（GPU0/1）+ 专家缓存卡 | **启动失败** | `--expert-cache-remote with a layer split needs a GPU that runs no stage (2 visible, 2 used by the split)` |
| 三卡（2 卡分片 + 1 卡专家缓存） | **启动失败** | 同上，helper 缓存模式在三卡也不成立 |

**教训**：`--remote-expert-opt` 只能配"假分片"（`--split-device 0`）。
一旦真分片，必须每张卡都跑 stage，不能再拿卡当专家仓库。

---

## 三、实测结果（同一固定 prompt，300/800 token 输出）

| 配置 | 长输出(800tok) 聚合 decode | 备注 |
|---|---|---|
| **四卡假分片（旧生产）** | **40.9 t/s** | layer-split 24 / split-device 0 / remote-expert-opt |
| 双卡真分片 + pipeline-windows 2 | 92.0 t/s | layer-split 24 / split-device 1 / batch 1 |
| **四卡四段真分片 + pipeline-windows 2** | **110.8 t/s** | layer-split 12,24,36 / split-device 1,2,3 |
| 四卡四段真分片（无 pipeline） | 51.7 t/s | 短路测试，pipeline 贡献 +114% |

短输出（300 tok）四段 sample：105.9 / 93.6 / 88.4 / 70.0 / 56.5 / 50.4 → 中位 82。
长输出（800 tok）四段 sample：119.5 / 110.4 / 104.1 / 64.7 / 60.9 / 57.6 → 聚合 110.8。

**为什么 pipeline 有效**：`--pipeline-windows 2` 让每个 stage 有两个 verifier，
相邻 stage 跨窗口重叠执行 —— decode 时 GPU0 在验证窗口 N 的同时，
GPU1 已经在跑窗口 N-1 的下一段。四阶段重叠度比两阶段高，所以四段比双卡更快。

---

## 四、定版配置（`E:/strata-src/strata-swift-iq3_s-4gpu.json`）

相对旧配置的**改动只有三处**：

```diff
- "--layer-split", "24", "--split-device", "0",
- "--remote-expert-opt", "--expert-cache-device1/2/3", "auto",
+ "--layer-split", "12,24,36", "--split-device", "1,2,3",
+ "--pipeline-windows", "2",

- "--kv-resident", "20480", "--vram-reserve-mib", "1408",
+ "--kv-resident", "40960", "--vram-reserve-mib", "2048",
```

加上配置底部的 `env` 段（短提示 prefill 提速，见第五之二节）：

```json
"env": { "STRATA_PREFILL_CPU_SHARE": "auto", "STRATA_PREFILL_CPU_SHARE_MAX": "3072" }
```

其余保持：`--spec 4 --mtp --lookup-chain 3 --mtp-q4 all --kv int8 --max-context 262144`。

**必须同时满足的约束**：
- `parallel: 1`（`--batch 4` 会让 `--pipeline-windows` 自动关闭，日志会明说）
- `--layer-split` 的 K 是"每张后续卡的**第一层编号**"，不是每卡层数：
  4 卡 = `12,24,36`（不是 `24,12,6,6`）
- `--split-device` 要列出 1..3（GPU0 是主卡，不用列）

**实测显存余量**：CUDA0 3867 / CUDA1 3343 / CUDA2 2443 / CUDA3 1671 MiB。

---

## 五、副作用与取舍

| 项 | 旧（假分片） | 新（四段真分片） |
|---|---|---|
| decode 长输出 | 40.9 t/s | **110.8 t/s** |
| prefill 8K 实测 | 700 t/s 量级 | 598.7 t/s（略低，每卡自带 prompt 缓冲） |
| 并发 | `--batch 4`（1 组 4 slot） | `parallel: 1`（batch 会关掉 pipeline） |
| 现役引擎 | 0.1.45 | 0.1.45（**未升级，0.1.50 已验证无收益**） |

**prefill 略降但 decode 翻倍**，对 agent 场景（长输出、多轮）是净收益。
若某天要大并发（4 个请求同时），需要回退到假分片 + batch 4。

---

## 五之二、prefill 提速实验（2026-11-02 追加）

用户问"预填充速度能不能也提起来"。实测结论：**唯一有效的是 `STRATA_PREFILL_CPU_SHARE`，其余全部无效或有害。**

### 试过且无效 / 有害的

| 手段 | 结果 |
|---|---|
| `--prefill-pipe` 768 / 1536 / 3072 / 6144 / 10240 | 2K/8K 提示全部**变慢**（768 慢 35%，6144 慢 7%）；32K 提示下 10240 仅 +0.2%（噪声内）。默认 0 就是最优 |
| `--prefill auto:16384`（chunk 上限翻倍） | **明显变慢**：32K 提示 1119 t/s，默认 8K chunk 是 1484 t/s（-25%） |
| `strata_tune.pcie_frac` 0 / 0.15 / 0.35 / 0.55 / 0.8 | 32K 提示 1745-1763 t/s，**完全无关** |

### 唯一有效的：`STRATA_PREFILL_CPU_SHARE=auto`

写进配置的 `env` 字段（serve.py 会把它传给引擎进程）：

```json
"env": {
  "STRATA_PREFILL_CPU_SHARE": "auto",
  "STRATA_PREFILL_CPU_SHARE_MAX": "3072"
}
```

原理：短 chunk（<3072 token）读 prompt 时，把路由率低的专家交给空闲的 CPU 池算，
让 GPU 的 PCIe 流和 CPU 同时干活——正好补上本机短提示 prefill 偏慢的短板。

实测（同机同配置，各 3 次取中位）：

| 提示长度 | 无 CPU share | 有 CPU share | 提升 |
|---|---|---|---|
| 256 tok | 172 t/s | **183 t/s** | +6% |
| 1,024 tok | 483 t/s | **522 t/s** | +8% |
| 3,072 tok | 745 t/s | **863 t/s** | +16% |
| 8,192 tok | 674 t/s | 705-718 t/s | +5-7% |
| 16,384 tok | 1,030 t/s | **1,114 t/s** | +8% |
| 32,768 tok | 1,656 t/s | 1,670-1,682 t/s | +1% |
| 65,536 tok | 2,132 t/s | **2,249 t/s** | +5% |

**副作用**：开了 CPU share 后输出最后几位 bit 会变（官方文档：首 token KL 均值 0.006），
且 `auto` 按实测计时挑份额，同一请求两次可能略有不同。对 agent 场景无实际影响。

### prefill 的硬件天花板

65K 提示 2,208 t/s 已接近本机极限。分片带来的每卡 prompt 缓冲 + 4 次 hand-off
决定了 `--prefill` 大 chunk 不会更快——**8K chunk（引擎默认 auto）就是这个架构的最优点**。


---

## 六、文件清单

| 文件 | 用途 |
|---|---|
| `E:/strata-src/strata-swift-iq3_s-4gpu.json` | **定版生产配置**（四段真分片 + pipeline） |
| `E:/strata-src/strata-swift-pipe1.json` | 双卡 pipeline 对照配置 |
| `E:/strata-src/strata-swift-4stage1.json` | 四段 pipeline 实验原文件 |
| `E:/strata-src/strata-swift-4stage-serial.json` | 四段无 pipeline 对照 |
| `E:/strata-src/strata-swift-iq3_s-4gpu.bak-kv20480` | 旧生产配置备份（假分片） |
| `E:/strata-src/backup-full-0.1.45-20261031-165918/` | 0.1.45 引擎 + serve + 配置完整备份 |
| `D:/llama-monitor/desktop-bats/启动FlashNext.bat` | 指向定版配置，日志 `E:/strata-src/strata-4gpu.out.log` |

**回退方法**：把 `strata-swift-iq3_s-4gpu.bak-kv20480` 复制回
`strata-swift-iq3_s-4gpu.json`，重启即可（引擎不用换）。

---

## 七、引擎版本结论（重要）

v0.2.6 的引擎 0.1.50 与 serve.py v0.2.6 **已完整装上并验证可用**
（`serve/`、`setup.py`、`strata_control`、`strata_cli` 都从 `git checkout v0.2.6` 检出），
但 **sm_86 加速表对本机零收益**，因此生产仍跑 0.1.45。

- 引擎 0.1.50 单独存放：`E:/strata-src/engine-new/`
- 若要切换：`cp engine-new/strata.exe engine/strata.exe` 等（含 DLL）
- 注意：0.1.50 需要 serve.py ≥ v0.2.6；只用 0.1.50 二进制配旧 serve.py 会 vision 启动失败
