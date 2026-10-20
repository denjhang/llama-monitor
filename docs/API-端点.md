# API 端点文档（本地 + 公网穿透）

> 2026-10-20 更新。网关采用**精确模型名匹配**（model 字段全等，非关键词包含），未知模型名一律路由到默认 Flash-Next。

## 一、网关入口（推荐用法）

| 环境 | Base URL | API Key |
|---|---|---|
| **本地** | `http://127.0.0.1:8080/v1` | 任意非空（无鉴权） |
| **公网穿透** | `http://18c23w6n.zjz-service.cn:28024/v1` | 同上 |

## 二、可用模型（精确名称，一字不差）

| model 参数 | 后端 | 上下文 | 速度 | 显卡 |
|---|---|---|---|---|
| `qwen3.8-flash-next-iq3_s` | Strata 8081（**默认**） | 256K 原生 | 66-75 t/s | GPU0/1 |
| `qwen3.6-35b-therapy` | ik_llama 8085 | 256K (YaRN) | 108-110 t/s | GPU2/3 |
| `spark-therapy-v3h` | llama.cpp 8083 | 256K | 114 t/s | GPU4 |

- OpenAI 兼容协议：`/v1/chat/completions`、`/v1/models`
- Anthropic 协议：`/v1/messages`（model-tee 透传）
- 模型列表聚合：`GET /v1/models`

## 三、调用示例

**curl（公网）**：
```bash
curl -X POST http://18c23w6n.zjz-service.cn:28024/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer any" \
  -d '{
    "model": "qwen3.6-35b-therapy",
    "messages": [{"role": "user", "content": "你好"}],
    "max_tokens": 512
  }'
```

**Python (openai SDK)**：
```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8080/v1", api_key="any")

r = client.chat.completions.create(
    model="spark-therapy-v3h",          # 精确名称，见上表
    messages=[{"role": "user", "content": "写一个贪吃蛇游戏"}],
)
print(r.choices[0].message.content)
```

**ZCode / Cursor 等客户端**：Settings → 自定义 OpenAI 兼容 Provider → Base URL 填上表任一，模型名手填精确名称。

## 四、直连端点（绕过网关）

| 服务 | Base URL | 说明 |
|---|---|---|
| Flash-Next | `http://127.0.0.1:8081/v1` | Strata 引擎，支持视觉 |
| 星火治疗版 | `http://127.0.0.1:8083/v1` | 无网关中转，延迟最低 |
| 35B 治疗版 | `http://127.0.0.1:8085/v1` | 支持视觉（mmproj） |

## 五、注意事项

1. **公网速度约 17-20 t/s**（穿透中转税），本地全速；重要任务走本地
2. 公网无鉴权，全网可达——不要把敏感数据直发公网端点
3. 星火为治疗版实验模型（v3h），长链任务偶发思考残留属已知特性
4. 35B 的 256K 为 YaRN 外推（原生 128K），超长输入靠后部分质量可能略降
5. 模型启停：桌面 BAT（启动FlashNext / 启动35B治疗版 / 启动星火治疗版 / 启动内网穿透）
6. 网关路由表在 `D:\llama-monitor\model-tee.py` 的 `ROUTES`，改动后重启网关（桌面"启动内网穿透.bat"即可）
