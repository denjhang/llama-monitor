# 投机解码判据：dense 赢、MoE 输（2026-10-20 定律）

> 三台服务、六轮控制变量实验（含清场复测）得出的硬规律：**要不要上投机解码，先看模型是 dense 还是 MoE 小激活，再测无 spec 裸速基线。**

## 实验总表（全部 RTX 3080 20G × 5，ik_llama v36）

| 模型 | 类型 | 无 spec 基线 | 最优投机 | 结论 |
|---|---|---|---|---|
| Coder390 27B Q3 | **dense** | 31 t/s | **DFlash2 同卡 45-52**（+50%） | 投机是解药 |
| Qwen36-35B-A3B 治疗版 Q5_K_M | **MoE 3B 激活** | **87-112 t/s** | 无（全负收益） | 投机是毒药 |
| Spark-therapy v3h 4B Q6_K | dense 4B 小模型 | **100.5** | 无（draft ±1% 全持平） | 投机无益 |

## 35B-A3B 各方案实测（清场复测数字）

| 配置 | decode | 根因 |
|---|---|---|
| **无 spec @128K** | **96.7-112.4 t/s** | MoE 每 token 只激活 3B 专家，带宽压力天生小 |
| DFlash2 @32K | 52.8-73.7 | host_ring 2G，草稿开销 > 带宽节省 |
| MTP n_max=3 @128K | 29-31 | 草稿每步跨卡同步（layer split） |
| DFlash2 @128K | **2.3-2.4** | **host_ring 8.2G 走主存，每步 PCIe 往返** |

### 星火 4B 明细（2026-10-20 清场实测）

| 配置 | decode |
|---|---|
| 无 draft（GPU4 单卡） | 100.4-100.7 |
| 1.7B draft 跨卡（原生产） | 101.5-101.8 |
| 1.7B draft 同卡 | 100.2-101.0 |

历史 114 t/s 未复现。定版无 draft：速度持平但**省出 GPU3**。判据扩展：不只是 MoE，**任何基线 ≥100 的小/快模型投机都无益**——带宽没到瓶颈就没有红利可抵草稿成本。

DFlash2 的 host_ring 随上下文线性涨：32K→2G、128K→8.2G。**上下文越大 DFlash2 越不可用**。

## 为什么 dense 赢 MoE 输

- **dense 27B**：每 token 读全部 24G 权重 → 带宽是瓶颈 → 基线慢（31）→ 投机验证一次顶多步带宽 → 大赚
- **MoE 3B 激活**：每 token 只读激活的专家 → 基线快（100+）→ 草稿+验证的固定开销没有红利可抵 → 净亏

## 部署军规

1. **先测无 spec 基线**（对照组必须有，否则会把 30 t/s 的病态当正常——35B 部署首日就犯过）
2. dense 大模型基线慢 → 试 DFlash2 专用草稿，**草稿必须与主模型同卡**（`--device-draft` = 主模型首卡）
3. MoE 小激活基线快 → 不要投机，直接裸跑
4. 测速前**清场 + 三证核验**（tasklist / netstat / nvidia-smi）；llama.cpp 会在所有卡留初始化上下文，别误判为第三方占用
5. 草稿模型必须同 tokenizer（跨模型族直接 `unknown architecture` 报错）

## 本机草稿模型位置

- `D:\working\gguf-sidecars\qwen38-27b\dflash2-qwen38-27b-Q8_0.gguf`（配 Coder390/27B）
- `D:\working\gguf-sidecars\qwen36-35b\dflash2-q8_0.gguf`（配 35B-A3B，实测负收益留档）
- `D:\working\models\spark-draft\Spark-X2.5-1.7B-Q8_0.gguf`（配星火 4B）
