# 桌面启动 BAT 备份（2026-10-23）

本目录备份桌面所有启动脚本 + 关键配置文件，便于换机/重装恢复。

## 文件清单

| 文件 | 用途 | 端口 | 卡 |
|---|---|---|---|
| `start-flashnext-4gpu.bat` | **Flash-Next 四卡（当前主力）** | 8081 | GPU0-3 + GPU4 视觉 |
| `strata-iq3_s-4gpu.json` | 四卡配置文件（配合上面的 bat） | — | — |
| `启动FlashNext.bat` | Flash-Next 双卡（旧，保留参考） | 8081 | GPU0/1 |
| `启动35B治疗版.bat` | Qwen3.6-35B-A3B 治疗版 | 8085 | GPU2/3 |
| `启动星火治疗版.bat` | Spark X2.5 v3h 治疗版 | 8083 | GPU4 |
| `启动llama监控.bat` | llama-monitor Qt 监控 GUI | — | — |
| `启动内网穿透.bat` | frp 内网穿透 | — | — |
| `start-coder390.bat` | Coder390 27B + DFlash2 | 8084 | GPU2/3 |

## 关键约定

- **BAT 延时必须用 `ping -n N 127.0.0.1`，不能用 `timeout /t`** —— 在 Git Bash 环境下 GNU timeout 会抢解析导致失败（已踩坑多次）。
- **BAT 用 ASCII 编码**，中文注释易导致 cmd 解析乱码（`chcp 65001` 也救不了某些情况）。
- 四卡配置的核心：`--layer-split 24 --split-device 0`（两 stage 都挤 GPU0 避开 PCIe）+ `--expert-cache-device1/2/3 auto`（GPU1-3 做专家缓存）。
