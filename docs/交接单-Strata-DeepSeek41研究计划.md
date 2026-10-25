# 交接单：Strata v0.2.6 支持 DeepSeek-V4.1-Flash —— 研究计划

> 写给下一个窗口。任务：评估用 Strata 新版跑 **DeepSeek-V4.1-Flash-1017** 是否可行、怎么跑。
> 日期：2026-10-23。**尚未开工，本文档=已核实的事实 + 研究计划。**

---

## 零、一句话结论

**磁盘是唯一门槛，且本机大概率卡住。** DeepSeek 最小档需 **239GB 连续空闲空间**，
而本机三块 SSD 全满（D 21G / E 18G / F 12G），空闲空间都在**机械盘**上（J 635G / H 429G / I 221G）。
DeepSeek 的 111GB n-gram 表**每生成一个词都要从 SSD 随机读**，机械盘会拖垮速度。

**先做的一件事：确认能否腾出 239GB 连续 NVMe 空间。腾不出，这条路基本不通。**

---

## 一、已核实的事实（不用再查）

### 1.1 Strata 版本

| 项 | 值 |
|---|---|
| 本机现役 | **0.1.45.3**（`E:/strata-src/CMakeLists.txt` project VERSION） |
| 远端最新 | **v0.2.6**（`git ls-remote --tags` 确认） |
| 源码目录 | `E:/strata-src`（git，remote 走 gh-proxy.org） |
| 引擎 exe | `E:/strata-src/engine/strata.exe` + `strata-vision.exe` |
| 旧版备份 | `E:/strata-src/backup-0.1.41-20261019/engine/` |
| 仓库 | `https://github.com/Niko1221/Strata` |

**注意：v0.1.45.3 → v0.2.6 跨了 0.1→0.2 大版本**，配置格式/启动方式可能变了，升级前先看 release notes。

### 1.2 DeepSeek-V4.1-Flash 模型信息（来自 v0.2.6 的 docs/DEEPSEEK41.md）

**模型结构**：MoE，40 层，每层 384 专家（每词激活 6 个），外加一个 **203GB 的 n-gram 表（Engram）**。

**三个官方量化档（ISTA-DASLab，IQ 系）**：

| 档 | bpw | 模型 | +Engram | +DSpark | **总磁盘** | 质量 |
|---|---|---|---|---|---|---|
| `ist-das-1.75bpw` (IQ1_M) | 1.75 | 121 GB | 111 GB | 8 GB | **239 GB** | ppl +21%，散文弱（+53%） |
| `ist-das-2.00bpw` (IQ2_XXS) | 2.00 | 138 GB | 111 GB | 8 GB | **257 GB** | ppl +15.5%，code +8.6% |
| `ist-das-2.25bpw` (IQ2_XS) | 2.25 | 155 GB | 111 GB | 8 GB | **274 GB** | ppl +7.3%，code +3.2%（最优） |
| `UD-Q8_K_XL`（Unsloth） | — | 508 GB | — | — | 533 GB | 需多卡+大量内存 |

**关键**：111GB 的 Engram 表**三档共用**（只下一次），8GB DSpark 草稿模型也是。

**跑法（官方命令）**：
```sh
./setup.sh --family deepseek41 --model IST-DAS-2.00bpw   # 下载+打包，可断点续传+SHA256
strata launch --model ist-das-2.00bpw --plan             # 先看显存/内存怎么分，不动任何东西
strata launch --model ist-das-2.00bpw                    # 正式启动
```

**内存去向（关键！）**：
- **路由专家（288.8GB，15360 个）**：能进显存的进显存，**剩下的在 CPU 上算**（原地从模型文件读）
- **注意力+稠密权重（16.8GB）**：全进显存，每卡一块（4 卡时每卡 ~3.9GB）
- **n-gram 表（202.8GB，Engram）**：**放 SSD**，每写一个词随机读几行 —— **慢盘拖慢每一个词，必须 NVMe**

### 1.3 官方实测速度（Strata 0.2.5，2.00bpw）

| 硬件 | 输出 | 提示词 |
|---|---|---|
| RTX 5070 12GB + 64GB 内存 | 4-6 t/s | ~110 t/s (4K) |
| RTX 3060 12GB + 46GB 内存 | 9-11 t/s | ~155 t/s (4K) |
| 1× Radeon R9700 + 251GB 内存 | 21-25 t/s | 320-360 t/s (8K) |
| 4× Radeon R9700 | 74-77 t/s | 400-450 t/s (8K) |

**注意**：RTX 3060（12GB/46GB 内存）只有 **9-11 t/s** —— 这是最接近本机的参照（本机 5×3080 20GB + 256GB 内存）。
**本机内存 256GB 远超 3060 的 46GB，理论上专家能多缓一些，速度可能好于 9-11，但别期待奇迹。**

### 1.4 本机硬件底细

| 项 | 值 | 对 DeepSeek 的影响 |
|---|---|---|
| GPU | 5× RTX 3080 20GB（**支持**，官方说 RTX 30 系可用） | 80GB 显存可放专家 |
| 内存 | **256GB** | 够（> 官方 46GB 参照） |
| CPU | E5-2673 v4 ×2（40C/80T，2.3GHz） | 大量专家要 CPU 算，**老 Xeon 是隐忧** |
| 磁盘 | **见下** | **真正的瓶颈** |

**磁盘现状（关键）**：

| 盘 | 类型 | 空闲 |
|---|---|---|
| C/D | Kingchuxing 1TB **SSD** | C 128G / **D 21G** |
| E/F | SUPERM2SSD 512GB **SSD** | E 18G / F 12G |
| **H** | ST310005 **机械盘** | **429G** |
| **I** | ST2000VX **机械盘** | **221G** |
| **J** | WDC WD20 **机械盘** | **635G** |
| G | SAMSUNG 1863G 机械盘 | 34G |
| P | WDC WD10 机械盘 | 154G |

**三块 SSD 全满（合计仅 51G 空闲），空闲空间全在机械盘上。**

---

## 二、核心矛盾：磁盘

DeepSeek 需要 **239-274GB 连续空间**，且官方明确说：

> "It is not counted in RAM, but a slow disk slows every word, so keep the model files on an NVMe drive"

（111GB Engram 表每生成一个词都要随机读，机械盘会让每个词都卡）

**本机现状**：
- SSD 只剩 51GB，远不够 239GB
- 机械盘有空间（J 635G）但慢 —— **Engram 放机械盘 = 灾难**

**所以第一件事是解决空间，三条路**：

1. **腾 SSD**：D 盘 654G 已用（模型都在里面），E 盘 220G 已用。看能否把已有模型迁到机械盘，腾出 239GB+ 的 SSD 空间。
2. **加 SSD**：本机主板是 Intel AI-8PLUS（矿板），看有没有空 M.2/PCIe 槽可插新 NVMe。
3. **混合方案**：模型 shard 放 SSD、Engram 放机械盘 —— **不推荐**，Engram 是随机读最频繁的。

---

## 三、研究计划（按顺序，每步有明确产出）

### 阶段 0：先读 release notes（30 分钟）
- 看 v0.2.0 → v0.2.6 的发行说明，确认：升级是否破坏现有 0.1.45.3 配置？Flash-Next 还能不能跑？
- **重要**：现役 8081 是 Flash-Next（Strata 0.1.45.3，decode 66-75 t/s）。升级 Strata 会不会影响它？
- 产出：升级风险评估（要不要保留 0.1.45.3 双版本共存）

### 阶段 1：解决磁盘（决定成败，1-2 小时）
- 统计 D/E 盘模型占用，规划迁移
- 目标：腾出 **≥240GB 连续 NVMe 空间**（跑 1.75bpw 最小档）
- 产出：磁盘方案（腾哪个盘 / 是否加盘）+ 实际可用空间数

### 阶段 2：dry-run 规划（不需下载，30 分钟）
```sh
strata launch --model ist-das-2.00bpw --plan
```
- 这个命令**不下载任何东西**，只报告模型在本机会怎么分配（多少专家进显存、多少留 CPU、需要多少内存）
- 产出：本机的专家分配预测（显存能放多少 / CPU 要算多少）

### 阶段 3：下载最小档试跑（数小时-1天，取决于网速）
- 先下 **1.75bpw（239GB）**，因为它最小且质量损失主要在散文（code 只 +8.9%）
- 下载可断点续传 + SHA256 校验
- 产出：能否跑起来的定性结论

### 阶段 4：实测 + 判定
- 测 decode / prefill 速度
- 对照官方 RTX 3060 的 9-11 t/s 参照
- **判定标准**：本机 256GB 内存 + 5×3080 80GB 显存，若 decode < 5 t/s → 不值得生产部署
- 产出：速度数据 + 是否上生产的结论

---

## 四、待答问题（开工后填）

- [ ] 本机 SSD 能否腾出 239GB？还是要加盘？
- [ ] `strata launch --plan` 预测本机放多少专家进显存？
- [ ] E5-2673 v4（老 Xeon，2.3GHz）算 CPU 专家会不会太慢？
- [ ] 升级到 v0.2.6 会不会破坏现役 8081 Flash-Next？
- [ ] 1.75bpw 的 code 质量（+8.9%）实际用起来如何？
- [ ] DSpark 草稿在本机显存下能不能开（官方说 3060 上要 `--dspark on` 才 +2-13%）

---

## 五、关键路径备忘

| 项 | 路径 |
|---|---|
| Strata 源码 | `E:/strata-src`（git，v0.2.6 已 fetch 到本地 tag） |
| 现役引擎 | `E:/strata-src/engine/strata.exe`（0.1.45.3） |
| 现役配置 | `E:/strata-src/strata-iq3_s.json`（Flash-Next，8081） |
| 旧版备份 | `E:/strata-src/backup-0.1.41-20261019/engine/` |
| DeepSeek 文档 | `git show v0.2.6:docs/DEEPSEEK41.md` |
| 本机模型目录 | `D:/working/models/`、`E:/Strata-data/models/` |
| 磁盘空间 | 机械盘 J 635G / H 429G / I 221G；SSD 仅 51G |

---

## 六、参考

- Strata 仓库：`https://github.com/Niko1221/Strata`（v0.2.6 支持 deepseek41 家族）
- 启动命令：`strata launch --family deepseek41 --model ist-das-2.00bpw`
- 相关记忆：[[strata-prefill-bottleneck]]（Flash-Next prefill 实验，700 t/s 硬件极限）
- 相关文档：`D:/llama-monitor/docs/Strata-FlashNext-提速复盘.md`
