# 桌面启动 BAT 备份（更新于 2026-11-06）

本目录备份桌面所有启动脚本 + 关键配置文件，便于换机/重装恢复。

## 文件清单

| 文件 | 用途 | 端口 | 卡 |
|---|---|---|---|
| `set-gpu-power-200w.bat` | **开机必跑：五卡功耗限 200W**（电源只 2000W） | — | GPU0-4 |
| `启动Swift真分片.bat` | **Swift-1.5 四卡四段真分片（推荐）** | 8081 | GPU0-3 + GPU4 视觉 |
| `启动FlashNext.bat` | 同上（英文注释版，历史） | 8081 | GPU0-3 + GPU4 视觉 |
| `start-flashnext-4gpu.bat` | 同上的英文版（历史，配置指向已过时） | 8081 | GPU0-3 |
| `启动35B治疗版.bat` | Qwen3.6-35B-A3B 治疗版 | 8085 | GPU2/3 |
| `启动星火治疗版.bat` | Spark X2.5 v3h 治疗版 | 8083 | GPU4 |
| `启动llama监控.bat` | llama-monitor Qt 监控 GUI | — | — |
| `启动内网穿透.bat` | frp 内网穿透 | — | — |
| `start-coder390.bat` | Coder390 27B + DFlash2 | 8084 | GPU2/3 |

桌面上的 `5-设置显卡功耗200W.bat` 是个转调壳（3 行 call），真正的脚本是本目录的
`set-gpu-power-200w.bat` —— 桌面用中文名保持编号秩序，实际逻辑放 ASCII 路径，
避免计划任务的编码问题。

配置文件在 `E:\strata-src\`：
- `strata-swift-iq3_s-4gpu.json` — **定版生产配置**（四段真分片 + pipeline-windows 2 + CPU share）
- `strata-swift-iq3_s-fakesplit.json` — 假分片配置（对比测速用，42.6 t/s）
- `strata-swift-iq3_s-4gpu.bak-kv20480` — 旧"假分片"配置备份（回退用）

## 功耗铁律（2026-11-06 新增，最重要）

**电源总额定只有 2000W，五卡必须限到 200W，否则整机会硬断电。**

| 项 | 320W 上限（默认） | 200W 上限（当前） |
|---|---|---|
| 5 × RTX3080 | 1600W | 1000W（实测只用到 766W） |
| 2 × Xeon + 外设 | ~450W | ~450W |
| **整机峰值** | **~2050W ⚠️ 超额定** | **~1216W，余量 40%** |

症状：`Kernel-Power 41` + `BugcheckCode=0` + 无 minidump（电源硬断电，不是蓝屏/软件 bug）。
实测 decode 无损失：200W 下真分片 **138 t/s**（250W 时 127.6）。
完整诊断：`docs/11-06-整机意外重启诊断.md`。

**已注册开机任务**（重启后自动执行，不需要手动跑）：
```
任务名: GPU-PowerLimit-200W
触发  : AtStartup + 延迟 30 秒
身份  : SYSTEM / 最高权限
动作  : cmd /c "D:\llama-monitor\desktop-bats\set-gpu-power-200w.bat"
```
删掉它：`Unregister-ScheduledTask -TaskName GPU-PowerLimit-200W -Confirm:$false`

## 启动顺序

```
开机 → (任务自动限功耗) → 1 引擎 → 2 网关8080 → 3 监控 → 4 内网穿透
```

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
