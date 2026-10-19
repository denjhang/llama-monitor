# Strata Flash-Next 提速复盘（2026-10-19）

> 结论：**引擎 0.1.41 → 0.1.45 + fast config 参数，decode 46 → 52-57 t/s（+15~24%），prefill 763 t/s @63K。**
> 4 卡方案（GPU0 主模型 + GPU1-3 专家缓存）保持不变，仍是本机最优。

## 更新内容

- 源码：zip 前缀法更新到 0.2.0-beta（git fetch 走 gh-proxy 报 invalid index-pack，zip 可行）
- 引擎：v0.1.45 release 的 `strata-windows-x64.zip`（CUDA 13.0，arch 75/86/89/120）
- 旧版备份：`E:\strata-src\backup-0.1.41-20261019\`（引擎 + 配置）
- 本地 setup.py 补丁已存 `E:\strata-src\local-setup-py.patch`（跳过 MTP 在线校验）
- ⚠️ 启动必须用 venv：`E:\strata-src\.venv\Scripts\python.exe`（系统 Python 缺 regex 等模块）

## 引擎 0.1.41→0.1.45 关键变更（官方 changelog）

- v0.1.42: `STRATA_ROUTE_TAIL_SKIP=7` 默认开（CUDA **decode +13-16%**）
- v0.1.42.1: 双路 NUMA 判定（E5 双路平台受益）
- v0.1.43.1: 修复 pinned-host 桌面 decode 塌陷
- v0.1.44: **流水线化 decode 与延迟优化**
- v0.1.45: Qwen3.6 并行请求与图片

## 实测数据（4 卡，IQ3_S，262K ctx）

| 配置 | decode t/s | 备注 |
|---|---|---|
| 旧 0.1.41（生产基线） | 46 | |
| 新 0.1.45（原参数） | 48.5-53.3 | |
| **+lookup-chain 3 +mtp-q4 all +vram-reserve 1344** | **53.4-57.2** | 草稿接受率 67%→80% ✅ |
| 再改 --spec 5 | 48.8-52.8 | ❌ 更慢，回退 |

Prefill：12K prompt 631 tok/s；63K 生产流量 764 tok/s。

## 定版配置要点（strata-iq3_s.json）

- `--vram-reserve-mib 1344`（原 700 会触发"GPU0 仅剩 383MiB"警告，#2065 驱动换页降速风险）
- `--lookup-chain 3` `--mtp-q4 all`（来自官方 maintainers' fast config，见 docs/STRIX_HALO.md §5-6；WMMA 系列开关是 AMD 专用不要加）
- `--spec 4 --spec-min-p 0.5` 保持（spec 5 实测负收益）

## 社区参照

2×TITAN RTX 24G（E5-2696 v4，IQ3_S 262K）：decode 70.9-77.3 t/s（docs/COMMUNITY_BENCHMARKS.md 2026-10-08 报告）。TITAN RTX 24G×2=48G 全驻留 vs 我们 3080 20G×4 混合 RAM 层，差距主要在显存容量/带宽层，属硬件边界。

## 是否还有更佳方案？

- **4 卡专家缓存（当前）**：52-57 t/s，262K 全上下文 —— 保持
- 纯 2 卡 layer split：旧实验 323 t/s prefill（vs 4卡 700），decode 未测但不占优
- 更小量化（IQ2_XS/Gyro-M）：质量换速度，不在本次范围
- 社区 70+ t/s 需要更大显存卡全驻留，硬件边界
