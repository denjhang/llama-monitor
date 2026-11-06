# API 端点文档（本地 + 公网穿透）

> 2026-11-04 更新。网关采用**精确模型名匹配**（model 字段全等，非关键词包含）。
> 当前拓扑：Strata 已下线，网关唯一后端 = **X2.6 治疗版 v6（8083）**，同时是默认兜底。

## 一、网关入口（推荐用法）

| 环境 | Base URL | API Key |
|---|---|---|
| **本地** | `http://127.0.0.1:8080/v1` | 任意非空（无鉴权） |
| **公网穿透** | `http://18c23w6n.zjz-service.cn:28024/v1` | 同上 |

## 二、可用模型（精确名称，一字不差）

| model 参数 | 后端 | 上下文 | 说明 |
|---|---|---|---|
| **`spark-therapy-4b`** | llama.cpp 8083（**当前唯一 / 默认兜底**） | 256K | Spark-X2.6 治疗版 v6，皇冠测试 3/4 PASS，decode ≈112 t/s（单卡 GPU4） |

已下线（要恢复见第五节）：
| `spark-therapy-v3h` | llama.cpp 8083 | 256K | 旧版 v3h，脚本 `D:\llama\start-xinghuo-v3h-q6k.bat` |
| `qwen3.6-35b-therapy` | ik_llama 8085 | 256K (YaRN) | 脚本 `D:\llama\start-qwen36-35b-therapy.bat` |
| `qwen3.8-flash-next-iq3_s` | Strata 8081 | 256K 原生 | 桌面 `启动Swift真分片.bat`，曾为默认 |

- OpenAI 兼容协议：`/v1/chat/completions`、`/v1/models`
- Anthropic 协议：`/v1/messages`（ZCode 走这条；`tool_use` 已验证正常）
- 模型列表聚合：`GET /v1/models`

## 三、调用示例

**curl（公网）**：
```bash
curl -X POST http://18c23w6n.zjz-service.cn:28024/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer any" \
  -d '{
    "model": "spark-therapy-4b",
    "messages": [{"role": "user", "content": "你好"}],
    "max_tokens": 512
  }'
```

**Python (openai SDK)**：
```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8080/v1", api_key="any")

r = client.chat.completions.create(
    model="spark-therapy-4b",           # 精确名称，见上表
    messages=[{"role": "user", "content": "写一个贪吃蛇游戏"}],
    max_tokens=512,
)
print(r.choices[0].message.content)
print(r.choices[0].message.reasoning_content)   # 思考内容（llama.cpp 单独返回）
```

**ZCode / Cursor 等客户端**：Settings → 自定义 OpenAI 兼容 Provider →
- Base URL：`http://127.0.0.1:8080/v1`
- API Key：随便填非空（如 `any`）
- Model：手填 `spark-therapy-4b`

若客户端走 Anthropic 协议，Base URL 用同一地址（`.../v1`，客户端会自动拼 `/messages`），Key 同样随便填。

## 四、直连端点（绕过网关）

| 服务 | Base URL | 说明 |
|---|---|---|
| **X2.6 治疗版 v6** | `http://127.0.0.1:8083/v1` | 无网关中转，延迟最低；别名同 `spark-therapy-4b` |
| Flash-Next（已停） | `http://127.0.0.1:8081/v1` | Strata 引擎，支持视觉 |

## 五、注意事项

1. **`max_tokens` 要给够**：这是思考模型，`reasoning_content` 和 `content` 共用 `max_tokens`。
   给 300 时实测可能 300 全被思考吃掉、`content` 为空串——不是模型坏了。建议 **≥512**。
2. **不要在启动脚本加 `--reasoning-budget 0`**：那会让思考一开始就被强制收尾。
   当前 `start-x26-v6.bat` 不带这个参数（默认 -1 = 不限）。
3. **公网速度约 17-20 t/s**（穿透中转税），本地全速；重要任务走本地。
4. **公网无鉴权**，全网可达——不要把敏感数据直发公网端点。
5. 模型启停：
   - X2.6 v6：`D:\working\spark-therapy\start-x26-v6.bat`
   - 网关：桌面 `2-启动网关8080.bat` 或 `D:\llama\restart-gateway.bat`
   - 内网穿透：桌面 `4-启动内网穿透.bat`
6. **网关路由表在 `D:\llama-monitor\model-tee.py` 的 `ROUTES` / `DEFAULT_PORT`**，改动后须重启网关。
   当前 `DEFAULT_PORT = 8083`；**恢复 Strata 时要改回 8081**，否则不带 model 名的请求打不到 Strata（会 502）。
