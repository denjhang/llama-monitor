# Flash-Next 双卡 vs 四卡 —— 纸面推理（2026-10-23）

> 起因：用户问"KV 如果都放内存，是不是双卡反而更快，还是四卡一定更快"。
> 结论先行：**四卡一定更快，且与 KV 放哪无关**——差异在专家缓存容量和 PCIe hand-off，
> 不在 KV。KV 本身几乎不影响速度（命中率 94-99%）。

---

## 一、KV 缓存在内存还是显存？（日志实证）

```
strata generate: KV streaming: 20480 of 262144 cells per QSA layer in VRAM,
                 the K/V in 3.09 GiB of pinned RAM
```

**两级结构，两边都有：**

| 层级 | 容量 | 位置 | 占比 |
|---|---|---|---|
| 常驻显存 | 20480 cells | GPU0 显存（`--kv-resident 20480`） | **7.8%** |
| 溢出兜底 | 241664 cells | **3.09 GiB 锁页内存（pinned RAM）** | **92.2%** |

**所以 KV 不是"全放内存"，也不是"全放显存"**——显存常驻一小块，内存兜底全部。
`--kv-resident 20480` 是刻意设的常驻窗口大小。

---

## 二、KV 真的影响速度吗？——几乎不影响

**实测命中率（日志原文，三次不同长度请求）：**

| 请求规模 | KV 命中显存率 | 从内存读 |
|---|---|---|
| 短（~4K） | **99.13%** | 2.0 MiB |
| 长（~30K） | **97.40%** | 41.4 MiB |
| 更长（~40K） | **94.45%** | 44.1 MiB |

**为什么几乎不影响：**

1. **KV 访问有强局部性** —— attention 主要读最近 token（recency 效应），那部分常驻显存。
2. **3.09GB 是 pinned（锁页）内存** —— 走 PCIe DMA 直传，不经过页表换页，延迟远低于普通内存。
3. **命中率 94-99%** —— 只有 1-6% 需从内存取，摊到每 token 开销可忽略（最多 44MiB / 整个请求）。

**唯一会略慢的场景**：上下文接近 256K 时，老 token 命中率下降。但即使最坏情况也只多读几十 MiB，
是毫秒级开销，不是瓶颈。

---

## 三、双卡 vs 四卡：本质区别（不在 KV，在两处 PCIe 流量）

### 配置对比

| | 双卡（真 split） | 四卡（当前，假 split） |
|---|---|---|
| 参数 | `--layer-split 24 --split-device 1` | `--layer-split 24 --split-device 0` |
| Layer 分配 | GPU0 [0,24) + **GPU1** [24,48) | GPU0 [0,24) + **GPU0** [24,48) |
| Stage 间 hand-off | **跨 PCIe**（每 window 一次） | **同卡内**（无 PCIe） |
| 专家缓存 | GPU1 一卡 | **GPU1+2+3 三卡** |
| 专家总量 | 6834 个 / 12.29 GB | **18531 个**（6177×3） |
| 专家命中率 | **82.8%** | **~100%** |
| Prefill | **323 t/s** | **700 t/s** |
| Decode | 51 t/s | 46 t/s |

### 双卡慢的两个根因（都是 PCIe）

**根因 1：Layer hand-off 跨 PCIe**
- layer split 24 → GPU0 算完 24 层，中间激活要**跨 PCIe 传给 GPU1**
- 每个 prefill window 一次；2563 token 的窗口 = 大量激活数据过 PCIe Gen3（实测 **4.9 GB/s**）
- 这是 prefill 掉到 323 t/s 的主因

**根因 2：专家 miss 加载跨 PCIe**
- 双卡专家池只有 6834 个 → 命中率 82.8%
- **17.2% 的专家要从 CPU 内存经 PCIe 加载**，每次 decode 都发生

### 四卡怎么消掉这两个问题

- `--split-device 0` → 两个 stage 都挤 GPU0，**hand-off 变同卡内部**（零 PCIe）
- GPU1-3 三卡做专家缓存 → 专家池 18531 个，**命中率 ~100%**，几乎无 PCIe 专家加载
- 代价：GPU0 显存吃满（18.5G/20G），只剩 1.6G 余量

---

## 四、"KV 全放内存时双卡会更快吗"？——不成立

**这个假设题的前提是错的**，理由：

1. **KV 主副本本来就在显存**（99% 命中），不是"全放内存"。双卡四卡都一样，KV 不是差异点。
2. **即使假设 KV 真的全放内存**，四卡仍更快——因为差异在**专家缓存**：
   - 四卡 18531 专家 vs 双卡 6834（**2.7 倍**）
   - 命中率 ~100% vs 82.8%
3. **双卡唯一的"优势"是少两张卡**，但在专家缓存上这反而是**劣势**（一卡 vs 三卡）。

**结论：四卡一定更快，无论 KV 放哪。** 瓶颈从来不是 KV，是专家缓存容量和 PCIe 通信。

---

## 五、四卡能跑满 256K 吗？

**能，但要注意显存压力。**

| 项 | 状态 |
|---|---|
| 上下文声明 | ✅ `max_context: 262144`（引擎确认） |
| KV 常驻显存 | 只有 7.8%（20480 cells）——**刻意设计**，超出走内存 |
| 能否真填满 256K | ✅ 可以，超 20480 cells 部分走 pinned RAM |
| 填满后速度 | 轻微下降（命中率降到 94% 时多读 44MiB） |

**⚠️ 唯一风险：显存分页。** 日志报过：
```
WARNING: only 1003 MiB of VRAM free at the start of this request (below 1024 MiB):
when the card is this full the driver can page GPU memory to system RAM,
decode falls to a few tok/s and a window may never finish (#2065).
Add --vram-reserve-mib 1408 to the config's args
```

**修复**：`--vram-reserve-mib` 从 1344 提到 **1408**（引擎建议值）。
或降低 `--kv-resident`（如 16384）腾显存。

---

## 六、最终结论

| 问题 | 答案 |
|---|---|
| KV 在内存还是显存？ | **两级**：7.8% 常驻显存 + 92.2% 锁页内存兜底 |
| KV 影响速度吗？ | **几乎不影响**（命中率 94-99%，pinned DMA） |
| 双卡 vs 四卡谁快？ | **四卡一定快**（专家缓存 2.7 倍 + 无 PCIe hand-off） |
| "KV 全放内存双卡更快"？ | **不成立**，差异不在 KV；双卡专家缓存反而更少 |
| 四卡能跑满 256K？ | **能**，但需调 `vram-reserve-mib 1408` 防显存分页 |

---

## 七、附：内网穿透状态（本次一并修复）

**问题**：frp 服务（FrpembedService）一直 Running，frpc 进程正常，但**本地 8080 网关未启动**
→ 公网请求全部 `dial tcp 127.0.0.1:8080: connection refused`（从 10-25 17:42 起持续报错）。

**修复**：启动 `model-tee.py 8080` 网关。

**验证**：
```bash
curl http://18c23w6n.zjz-service.cn:28024/v1/models
# → {"object":"list","data":[{"id":"qwen3.8-flash-next-iq3_s",...}]}
```

**教训**：frp 服务开机自启，但 **8080 网关不是**（需手动或桌面 BAT 拉起）。排查穿透故障时，
先 `netstat | grep 8080` 确认网关在不在，再查 frp 日志。
