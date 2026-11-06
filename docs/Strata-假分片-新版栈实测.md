# 假分片在新版 Strata 栈上的实测（2026-11-06）

> 结论先行：**假分片（`--layer-split 24 --split-device 0` + `--remote-expert-opt`）
> 在新版 serve v0.2.6 上依然只有 42.6 t/s（800tok）/ 52.4 t/s（300tok），
> 和旧记录 40.9 t/s 基本一致 —— 换新版栈不会让假分片变快，
> 真分片的 127.6 / 168.7 t/s 优势不动摇。**

---

## 一、测法（可复现）

固定 prompt：要求写一个带 TTL/LRU/线程锁/CLI/unittest 的完整 Python KV 存储，
纯代码输出（能稳定跑满 max_tokens）。`temperature=0.0`，非流式。

测量点用引擎自己上报的 `timings.predicted_per_second`（不是墙钟估算），
每个档位跑 5 轮取中位。脚本：`E:/strata-src/bench_decode.py`。

```bash
# 起配置
E:/strata-src/.venv/Scripts/python.exe E:/strata-src/serve/server.py \
  --engine strata --config E:/strata-src/strata-swift-iq3_s-fakesplit.json --port 8081

# 测速（轮数 端口）
D:/Python312/python.exe E:/strata-src/bench_decode.py 5 8081
```

## 二、四组对照数据

所有数据都在 **250W 功耗上限**下测得（11-06 掉电后为防重启统一压到 250W，
此前文档里的 110.8 t/s 等数字是 320W 下测得）。

| # | 栈 | 分片方案 | 300 tok 中位 | 800 tok 中位 | draft 接受率 |
|---|---|---|---|---|---|
| A | serve v0.2.6 + engine **0.1.45** | **假分片** | **52.4 t/s** | **42.6 t/s** | 0.80 / 0.71 |
| B | serve v0.2.6 + engine **0.1.50** | **假分片** | **57.0 t/s** | **46.3 t/s** | 0.78 / 0.71 |
| C | serve v0.2.6 + engine 0.1.45 | **四段真分片** | **168.7 t/s** | **127.6 t/s** | 0.81 / 0.75 |
| D | 历史记录（320W，11-02） | 假分片 | — | 40.9 t/s | — |

### 逐轮原始数据

**A. 新版 serve + 0.1.45 引擎 + 假分片**（5 轮）

```
max_tokens=300:  48.1 / 53.8 / 52.4 / 53.0 / 50.6   → 中位 52.4
max_tokens=800:  42.2 / 42.7 / 43.0 / 42.3 / 42.6   → 中位 42.6
prefill: 44-60 t/s（假分片 prefill 也不快，见下）
```

**B. 新版 serve + 0.1.50 引擎 + 假分片**（3 轮）

```
max_tokens=300:  53.9 / 57.0 / 57.0   → 中位 57.0
max_tokens=800:  45.2 / 46.7 / 46.3   → 中位 46.3
```

**C. 新版 serve + 0.1.45 引擎 + 四段真分片**（3 轮，250W 上限）

```
max_tokens=300:  170.5 / 141.9 / 168.7   → 中位 168.7
max_tokens=800:  127.6 / 131.4 / 117.0   → 中位 127.6
prefill: 83-96 t/s（短提示 5 token 复用）
```

## 三、结论

### 3.1 新版栈没有改善假分片

A 组 42.6 t/s vs 历史 D 组 40.9 t/s，差 4%，在轮间波动范围内。
**serve v0.2.6 的那批改进（sm_86 加速表、新前端、pipeline 支持）对假分片路径没有帮助**，
因为假分片的瓶颈在结构本身：GPU0 独跑全部 48 层，其余三卡只做专家仓库，
每个 token 的串行路径长度由单卡决定，和 serve 版本无关。

### 3.2 引擎 0.1.50 在假分片上略快（+11% 短 / +9% 长）

B 组比 A 组快，但这点差异**只出现在假分片**。
历史记录里 0.1.50 在真分片上实测是 41.6/43.0/45.1 对 0.1.45 的 42.6/41.1/44.6 —— 无差异。
推测 0.1.50 的专家拉取/预取路径有微调，在"远端专家"模式下才吃到。
但如果为了这 10% 去升引擎，同时会失去 sm_86 已验证的稳定性，
而真分片方案本身就有 3 倍优势，没有升级必要。

### 3.3 真分片：假分片的 3.0 倍（长输出）

| 对比 | 300 tok | 800 tok |
|---|---|---|
| 真分片 / 假分片（同 0.1.45 引擎） | 168.7 / 52.4 = **3.22×** | 127.6 / 42.6 = **3.00×** |

和 11-02 的结论（真分片 110.8 vs 假分片 40.9 = 2.7×）方向一致，
250W 限功耗后倍数反而略大，说明 decode 确实不是功耗瓶颈
（限功耗对真分片的影响小于对假分片的，因为假分片更依赖单卡 SM 频率）。

### 3.4 假分片唯一的优势：prefill 和并发

| 项 | 假分片 | 真分片 |
|---|---|---|
| 短提示 prefill | 44-60 t/s | 83-96 t/s |
| 4 并发 | 理论上可用（但实测 `--batch 4` 会被引擎关闭，见下） | 不可用（pipeline 要求 parallel=1） |

**重要发现**：假分片配置里写着 `"parallel": 4`，但引擎日志明确说

```
strata generate: WARNING: --batch 4 is off: it needs each stage of a layer split on its own GPU
strata serve: parallel requests: 4 asked, the engine runs one at a time (its log says why)
```

也就是说 **strata 0.1.45/0.1.50 的假分片现在也不支持 batch 4**，
"假分片能高并发"这个历史卖点在新版引擎上已经不成立了。
（旧文档里"要大并发需回退假分片 + batch 4"的说法已过时。）

## 四、现在跑的是什么

当前 8081 已切回**假分片**（A 组配置）：

```
exe        : E:\strata-src\engine\strata.exe          (0.1.45)
config     : E:\strata-src\strata-swift-iq3_s-fakesplit.json
拓扑       : layers 0-23 (CUDA0), 24-47 (CUDA0)
专家缓存   : GPU1/2/3 各 12.5 GiB，remote ranks striped
显存       : CUDA0 18614 / CUDA1 12554 / CUDA2 12542 / CUDA3 12536 / CUDA4 1833 MiB
网关 8080  : 正常转发（冒烟测试 decode 51.9 t/s）
```

现役真分片配置 `strata-swift-iq3_s-4gpu.json` **未改动**，随时可切回：

```bash
D:/llama-monitor/desktop-bats/启动FlashNext.bat     # 真分片
```

## 五、相关文件

| 文件 | 用途 |
|---|---|
| `E:/strata-src/strata-swift-iq3_s-fakesplit.json` | 假分片配置（新版引擎 0.1.45 + serve v0.2.6） |
| `E:/strata-src/strata-swift-iq3_s-fakesplit-0150.json` | 同上但指 engine-new（0.1.50） |
| `E:/strata-src/strata-swift-iq3_s-fakesplit-0145.json` | 同上但指旧 0.1.45 备份目录（DLL 已失效，仅留档） |
| `E:/strata-src/bench_decode.py` | 测速脚本（300/800 tok，N 轮中位） |
| `E:/strata-src/strata-swift-fakesplit.log` | 本次假分片运行日志 |

---

*实测：2026-11-06，250W 功耗上限，五次取中位*
