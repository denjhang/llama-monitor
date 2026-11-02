# 桌面启动 BAT 备份（更新于 2026-11-02）

本目录备份桌面所有启动脚本 + 关键配置文件，便于换机/重装恢复。

## 文件清单

| 文件 | 用途 | 端口 | 卡 |
|---|---|---|---|
| `启动Swift真分片.bat` | **Swift-1.5 四卡四段真分片（推荐）** | 8081 | GPU0-3 + GPU4 视觉 |
| `启动FlashNext.bat` | 同上（英文注释版，历史） | 8081 | GPU0-3 + GPU4 视觉 |
| `start-flashnext-4gpu.bat` | 同上的英文版（历史，配置指向已过时） | 8081 | GPU0-3 |
| `启动35B治疗版.bat` | Qwen3.6-35B-A3B 治疗版 | 8085 | GPU2/3 |
| `启动星火治疗版.bat` | Spark X2.5 v3h 治疗版 | 8083 | GPU4 |
| `启动llama监控.bat` | llama-monitor Qt 监控 GUI | — | — |
| `启动内网穿透.bat` | frp 内网穿透 | — | — |
| `start-coder390.bat` | Coder390 27B + DFlash2 | 8084 | GPU2/3 |

配置文件在 `E:\strata-src\`：
- `strata-swift-iq3_s-4gpu.json` — **定版生产配置**（四段真分片 + pipeline-windows 2 + CPU share）
- `strata-swift-iq3_s-4gpu.bak-kv20480` — 旧"假分片"配置备份（回退用）

## 关键约定

- **BAT 延时必须用 `ping -n N 127.0.0.1`，不能用 `timeout /t`** —— 在 Git Bash 环境下 GNU timeout 会抢解析导致失败（已踩坑多次）。
- **BAT 必须 CRLF 换行**，LF 换行的 bat 在 cmd 下会解析异常。
- **日志重定向路径要放到 `E:\strata-src\`**。早前写 `D:\llama\` 时 PowerShell 的
  `Start-Process -RedirectStandardOutput` 会静默失败，导致 BAT 健康检查一直显示 FAIL 而引擎其实没起。

## 分片方案演进（重要）

| 时间 | 方案 | decode 长输出 | 说明 |
|---|---|---|---|
| 2026-10-19 ~ 11-01 | 四卡**假分片**：`--layer-split 24 --split-device 0` + `--remote-expert-opt` + `--expert-cache-device1/2/3` | 40.9 t/s | GPU0 跑全部 48 层，GPU1-3 只当专家仓库。GPU0 成串行瓶颈 |
| **2026-11-02 起** | 四卡**四段真分片**：`--layer-split 12,24,36 --split-device 1,2,3` + `--pipeline-windows 2` | **110.8 t/s** | 每卡 12 层，相邻 stage 跨窗口重叠 |

`--layer-split` 的 K 是**每张后续卡的第一层编号**（4 卡写 `12,24,36`，不是 `24,12,6,6`）。
`--pipeline-windows 2` 要求 `parallel: 1`（`--batch` 会让它自动关闭）。
完整实测数据与排查过程见 `docs/Strata-四卡真分片提速定论.md`。
