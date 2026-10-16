# llama.cpp 本地推理栈 · 项目文档

> 双 RTX 3080 20G · Qwen3.8-27B 治疗版（EfficientThink Q3-LynnStyle）· Windows 原生
> 维护记录始于 2026-09-22，本文档为唯一权威操作手册


## 🚀 2026-10-11 发布版（v1.0）

**独立 exe 发布**：`pyinstaller --noconsole --onefile --icon llama-monitor.ico --name llama-monitor monitor_gui.py`
产物 `dist/llama-monitor.exe`（48M，双击即用，可固定任务栏——exe 有独立应用身份）。

- 监控 GUI = 唯一需要看见的窗口；网关/模型一律 pythonw 后台常驻（**严禁 python.exe 弹控制台——窗口被关=进程陪葬**）
- 起停套件：start-monitor.bat / restart-gateway.bat / start-strata.bat / stop-strata.bat
- 当前架构：8080 网关（model-tee，按 model 名路由）→ 8081 Strata Flash-Next 42t/s / 8083 spark-therapy-4b（治疗版+--reasoning-budget 2048 保险丝）；8082 备用
- 监控数据源：Strata=GET /metrics；llama.cpp=/slots+/metrics；live 实时输出=live-8080-<port>.txt 专文件（专文件存在即无条件优先，勿比 mtime）


## 📦 版本历史（Release 各版并存，展示进化）

| 版本 | 包 | 里程碑 |
|---|---|---|
| [v1.0](https://github.com/denjhang/llama-monitor/releases/tag/v1.0) | llama-monitor-v1.0.exe | 首个独立 exe：可固定任务栏、网关多模型路由、live 分文件防混流 |
| [v1.2](https://github.com/denjhang/llama-monitor/releases/tag/v1.2) | llama-monitor-v1.2.exe | 显存 8 槽位（未插入占位）+父层裁剪修复、端口表防闪动、冷启动数据 30-40s→4s、「上下文」独立列、速度单值 |
| [v1.1](https://github.com/denjhang/llama-monitor/releases/tag/v1.1) | llama-monitor-v1.1.exe | 配置化：⚙ 设置对话框增删改端点、配置文件热重载、最近请求导出 CSV、后端类型化（strata/llama.cpp/ik/sglang） |

## ⚙ 配置文件（2026-10-11 起）

监控端点不再写死：`monitor-config.json`（exe 同目录，首次运行自动生成模板），**保存后 GUI 自动热重载**，无需重启。

```json
{
  "default_port": "8081 · Strata Flash-Next",
  "live_dir": "D:/llama",
  "events_log": "D:/llama/watchdog-events.log",
  "exe": "D:/llama/llama-server.exe",
  "ports": [
    {"name": "8081 · Strata Flash-Next", "url": "http://127.0.0.1:8081",
     "log": "E:/strata-src/strata-iq3_s.log", "engine": "Strata",
     "tps": "42 t/s @262K", "type": "strata"}
  ]
}
```

### 支持的后端 type

| type | 引擎 | 数据源 | 说明 |
|---|---|---|---|
| `strata` | Strata（Flash-Next 专用） | `GET /metrics` 单端点 | live.state/prompt_read/requests/hardware 全包；进程识别走 strata.exe |
| `llama.cpp` | llama-server（主线） | `/slots` + `/metrics` gauge | 阶段判定源码级；含 spark 等无草稿模型 |
| `ik` | ik_llama.cpp | 同 llama.cpp | 兼容主线接口，含 MTP/DFlash 草稿统计 |
| `sglang` | SGLang（WSL） | WSL 侧日志解析 | Decode/Prefill batch 行；`log` 留空走默认 WSL 路径 |

字段说明：`name` 端口表显示名（任意）；`url` 探测地址；`log` 该端点引擎日志（最近请求表数据源）；`engine`/`tps` 仅显示用；`type` 决定渲染路径。网关 8080 的实时输出按上游端口分文件（`live-8080-<端口>.txt`，存 `live_dir`），点哪个端口看哪个模型的生成。

### 窗口几何

窗口位置/大小仍持久化在 `D:\llama\monitor-gui-cfg.json`（与端点配置互不影响）。样式 `monitor-gui.qss` 改动即时热生效。

## 一、架构总览

```
Zcode / WorkBuddy 等客户端
        │  http://127.0.0.1:8080（客户端只认这个）
        ▼
┌─────────────────────┐
│ model-tee.py 代理    │  8080 → 8082 流式透传
│ (pythonw 常驻)       │  · tee 生成内容 → live-gen.txt（实时预览数据源）
│                     │  · usage 流水 → tee-usage.jsonl
└────────┬────────────┘
         ▼
┌─────────────────────┐
│ llama-server b11139 │  8082 真正的服务
│ (pythonw 无头常驻)   │  Q3-LynnStyle + mmproj(Q4) + draft-dflash + KV q4_0 + 262K
└─────────────────────┘
         ▲
┌────────┴────────────┐
│ monitor_gui.py      │  监控台 GUI（PySide6，唯一可见窗口）
│ (pythonw)           │  内嵌复活狗：模型死→拉模型；代理死→拉代理
└─────────────────────┘
```

**关键原则：客户端永远连 8080。** 8082 只是内部端口。代理负责截获实时生成内容（llama-server 的 /slots 不暴露输出文本，必须从 SSE 流截）。

## 二、文件清单（E:\working\llama-cpp\llama\）

| 文件 | 作用 |
|---|---|
| `server-headless.pyw` | 无头载入器。参数 `nothink` = 关思考（--reasoning-budget 0）。写 server-mode.txt 供监控读取。监听 8082 |
| `model-tee.py` | 流式透传代理 8080→8082。截获四路内容：OpenAI content/reasoning_content/tool_calls.arguments + **Anthropic text_delta/thinking_delta/input_json_delta（Zcode 走的就是这条路，漏接=只显文字不显代码）**。流式中 150ms 节流写 live-gen.txt |
| `monitor_gui.py` | 监控台 GUI v3。KPI 仪表盘布局，1s 全量刷新 + 200ms 实时内容刷新。窗口几何持久化（monitor-gui-cfg.json，拖动即存） |
| `start-server-headless.bat` | 拉起模型（思考版），薄壳调 pyw |
| `start-server-nothink.bat` | 拉起模型（无思考版） |
| `start-monitor.bat` | 拉起监控 GUI |
| `watchdog.py` | 控制台版监控（GUI 出问题时的回退，X两次=停模型退出） |
| `swaptest.py` | 崩溃复现实验台（配置：baseline/nodraft/nommproj/kv8/nofa） |

llama.cpp 本体在 `E:\working\llama-cpp\llama-b11139\`（CUDA 12.4 + 旧目录的 cublas DLL），日志 `llama-server.log` 同目录。旧版 b11076 在 `E:\working\llama-cpp\llama\` 保留可回退。

## 三、日常操作

```bash
# 开机后全套启动（三件套，缺一个客户端不通）
start-server-nothink.bat      # 或 start-server-headless.bat
# model-tee.py 需单独拉起 → 若忘了，监控 GUI 的代理狗会自动补拉
start-monitor.bat             # 监控台

# 切换思考/无思考
taskkill /IM llama-server.exe /F   # 先确认监控台槽位为"空闲"再杀！
start-server-nothink.bat           # 或 headless 版

# 紧急全停
taskkill /IM llama-server.exe /F
```

## 四、监控台说明

- **状态胶囊**三态：绿=正常 / 黄=代理断(自动拉起中) / 红=服务停(自动拉起中)
- **KPI 瓷砖**：存活时间 / 上下文占用% / 实时速度 / draft 命中 / GPU 温度
- **阶段进度条**：预填充（爬条=在算 KV，耐心等）/ 解码（已生成 N tok @ 速度）。判据=当前 task 在日志出现 n_gen 行（硬判据，本 build 的 /slots 数字在解码期会抽风，不可信）
- **实时生成**：含工具调用（[write_file] 标记 + 代码参数流），200ms 流式滚动
- **复活狗**：正常=看门狗 / 重载后<1h=复活狗 / 稳定1h+=幸运狗

## 五、已知问题与坑（重要！）

1. **换会话崩溃（未根治，已防守）**：llama-server 单槽位下，不相干新会话触发 KV 全量换血（日志签名 `f_keep=0.001`）时有概率 abort（WER 0xc0000409）。b11076/b11139 均存在。触发面窄（合成复现 73K+图+换血 5 次不崩）。**防守=复活狗自动重载**，损失=一次失败的请求+缓存。
2. **压缩后首轮 prefill 很慢是正常的**：60K 上下文 @ ~350 tok/s ≈ 3 分钟，期间客户端零输出。监控台预填进度条可确认存活。
3. **Zcode 写大文件时前端转圈不出"+N行"**：llama-server 的工具调用需完整 JSON 才下发（无法增量流式），但监控台的实时生成区能看到逐字代码。
4. **Git Bash curl 直发中文 = GBK 乱码**（会打出 500 parse error 进日志被监控显示），中文请求必须走 Python。
5. **批量杀 pythonw 会误杀 model-tee 代理**——代理狗会自动拉回，但客户端会断几秒。
6. **LM Studio 备选**：`lms load qwen3.8-27b-efficientthink-lynnstyle --gpu max`（1234 端点，视觉自带，识图验证过；但无法硬关思考、无 DFlash2 ~25 t/s）。崩溃风暴时的保底方案。

## 六、Qt/PySide6 踩坑全记录（血泪，别再踩）

1. **动态属性选择器语法**：`setProperty("class", "pill_ok")` 必须配 `QLabel[class="pill_ok"]`。
   `QLabel.pill_ok` 匹配的是 **C++ 子类名**，动态属性永远匹配不上——**静默失效**，不报错不警告，
   整组样式作废，界面半裸。本项目曾因此"怎么调都丑"四轮。写完 QSS 必须肉眼验证第一个样式是否生效。

2. **禁止全局 `QWidget { background: ... }`**：会给所有子控件（每个 QLabel）刷不透明底色，
   文字后面出现一格格深色矩形（用户怒斥的"黑底"）。正确做法：背景只画在 `QMainWindow`、
   根容器（`#root` 需 setObjectName）和卡片 QFrame 上；`QLabel { background: transparent }` 全局兜底。

3. **QFrame/QWidget 用 QSS 背景必须 `setAttribute(Qt.WA_StyledBackground, True)`**，
   否则样式背景不绘制（或渲染异常）。

4. **圆角 >4px 在部分 Windows 渲染路径产生黑角残影**（角落不做透明裁剪）。
   深色主题用 4px 以内或直角。胶囊→改方角芯片。

5. **pythonw 下所有 subprocess 必须 `creationflags=0x08000000`（CREATE_NO_WINDOW）**：
   tasklist/nvidia-smi 每秒一次，不加=每秒闪黑窗，用户会杀了你。

6. **查进程信息禁用 powershell 子进程**（慢+闪窗）：ctypes GetProcessTimes 直查。
   **FILETIME 是 UTC**，拿本地时间减会虚报时区差（中国 +8h）。

7. **GBK 编码地狱**：Windows 命令行输出（tasklist/wevtutil）是 GBK，Python utf-8 解码直接崩；
   Git Bash curl 发中文必乱码。一律 `decode("utf-8", errors="replace")` + 中文请求走 Python。

8. **PrintWindow 截 Qt 窗口抓到的是遮挡内容/别的窗口纹理**，ImageGrab 区域抓取也抓的是最顶层。
   别隔空截屏诊断 UI——直接读代码。

9. **样式迭代必须热重载**：QSS 抽成外部文件（monitor-gui.qss），GUI 内 mtime 监听（1s），
   改文件即时 setStyleSheet，**窗口不关不弹位置不动**。禁止"改一次样式关窗开窗一次"。

10. **最重要的一条**：起手就套成熟模板库（qdarkstyle / Qt-Material，pip 可装），
    从零手搓 QSS = 把 Qt 二十年的坑重踩一遍。本项目教训的教训。

（布局/逻辑代码改动仍需重启进程；QSS 样式改动热重载即时生效。）

## 七、数据与性能基线（2026-09-24 实测）

- 稳态 26~50 tok/s（draft 命中 0.4~0.85；短输入续写命中高、新素材 prefill 后命中低）
- 预填 ~350 tok/s；262K 上下文 + KV q4_0 双卡共 ~29.5GB
- 无思考模式：agent 工作流效率 ~10x（像素鸟 3 分钟一次性可玩），代价=陷阱盲判（9.11 vs 9.9 答错）
- WSL2 + SGLang 提速方案（90-200 t/s）搁置中，等 E 盘腾空间 + 重启日

## 八、内网穿透部署（公网访问）

### 方案选型

使用 frp（Fast Reverse Proxy）实现内网穿透，将本地 8080 网关暴露到公网。

**服务商**：任意 frp 服务提供商（需自行注册账号）
**协议**：TCP 或 HTTP
**客户端**：frpc（Windows 版）

### 部署步骤

1. **下载 frp 客户端**

   解压到工具目录（例如 `D:\tools\frp\`），通常包含：
   - `frpc.exe` — 客户端主程序
   - `frpc.toml` — 配置文件（由服务商后台生成）
   - 安装/卸载脚本（需管理员权限）

2. **运行安装脚本**

   ```bash
   # 右键"以管理员身份运行"安装脚本
   # 会自动下载 frpc.exe、nssm.exe 等组件，并注册为 Windows 服务
   ```

3. **获取设备码**

   运行"获取设备码"脚本，复制输出的设备码（例如 `3005054869f8`）。

4. **配置隧道**

   登录服务商后台：
   - 绑定设备码
   - 添加隧道：
     - 本地地址：`127.0.0.1`
     - 本地端口：`8080`
     - 隧道类型：`TCP`（推荐）或 `HTTP`
   - 保存后会生成 `frpc.toml` 配置文件

5. **重启服务**

   ```powershell
   Restart-Service -Name FrpembedService -Force
   ```

   服务会自动读取 `frpc.toml` 并连接到服务商节点。

6. **验证连通**

   ```bash
   # 假设分配的公网地址为 example.com:28024
   curl http://example.com:28024/v1/models
   ```

   应返回本地模型列表。

### 配置文件示例

`frpc.toml`（由服务商后台自动生成，示例结构）：

```toml
serverAddr = "frp-server.example.com"
serverPort = 7000
user = "your_username"

[metadatas]
  secretPassword = "your_secret_hash"

[[proxies]]
  localIP = "127.0.0.1"
  localPort = 8080
  name = "ai"
  remotePort = 28024  # 公网端口
  type = "tcp"
```

### 安全注意事项

- **无鉴权**：当前网关 8080 无认证机制，穿透后全网可访问
- **防护建议**：
  - 使用服务商提供的访问控制（IP 白名单）
  - 网关层添加 API key 验证（修改 `model-tee.py`）
  - 定期更换公网端口
- **设备码保密**：设备码可绑定任意账号，勿泄露

### 性能参考

公网访问速度取决于：
- 本地上行带宽
- 服务商节点质量
- 客户端到节点的网络延迟

实测（家庭宽带 + BGP 节点）：
- 本地直连：46 t/s
- 公网穿透：17 t/s（含中转税 + 上行带宽限制）

### 故障排查

```bash
# 检查服务状态
Get-Service -Name FrpembedService | Select-Object Status

# 查看日志（如果有）
tail -f D:\tools\frp\frpc.log

# 测试本地 8080 是否正常
curl http://127.0.0.1:8080/v1/models

# 测试公网地址
curl http://your-domain:port/v1/models
```

后台显示"否"（未在线）→ 检查 `frpc.toml` 是否生成 → 重启服务

---

## 九、相关文档

- 工作区总记忆：`K:\本地量化模型\modelscope\AGENTS.md`
- 提速研究：`K:\本地量化模型\modelscope\_tools\qwen38-speedup\提速研究笔记.md`
- 崩溃快照/事件：`llama-b11139\crash-snapshots\`（full-*.log 为全量日志）、`watchdog-events.log`
