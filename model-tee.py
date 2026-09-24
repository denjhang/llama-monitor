# -*- coding: utf-8 -*-
"""model-tee：8080 -> 8082 流式透传代理（状态机版）
- 客户端照常连 http://127.0.0.1:8080（OpenAI/Anthropic 协议均透传）
- 智能状态识别：填充中/读图中/压缩中/思考中/输出文字中/工具调用中/写入参数中
- 状态行 + 内容实时写 live-gen.txt（监控台显示）
- nothink 模式下剥掉请求级思考参数（防客户端覆盖）
- usage 流水 tee-usage.jsonl
"""
import http.server, json, os, time, urllib.request, urllib.error

import sys as _sys
_args = _sys.argv[1:]
LISTEN   = _args[0] if len(_args) > 0 else "8080"
UPSTREAM = "http://127.0.0.1:" + (_args[1] if len(_args) > 1 else "8082")
LIVE  = rf"E:\LM\live-{LISTEN}.txt" if _args else r"E:\working\llama-cpp\llama-b11139\live-gen.txt"
USAGE = rf"E:\LM\tee-usage-{LISTEN}.jsonl" if _args else r"E:\working\llama-cpp\llama-b11139\tee-usage.jsonl"
MODE_FILE = r"E:\working\llama-cpp\llama-b11139\server-mode.txt"

COMPACT_KEYS = ("summarize the conversation", "conversation summary", "compact",
                "历史对话", "压缩", "总结以上对话", "生成摘要")

def write_live(text):
    with open(LIVE, "w", encoding="utf-8") as f:
        f.write(text[-4000:])

def mode():
    try:
        return open(MODE_FILE, encoding="utf-8").read().strip()
    except OSError:
        return "think"

def _flatten(c):
    """content 可能是 str 或 [{type:...}] 块列表，统一拍平成纯文本"""
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for x in c:
            if isinstance(x, dict):
                t = x.get("type")
                if t == "text" or "text" in x:
                    parts.append(x.get("text", ""))
                elif t in ("image_url", "image"):
                    parts.append("[图片]")
                elif t == "tool_result":
                    parts.append("[工具结果] " + _flatten(x.get("content")))
                elif t == "tool_use":
                    parts.append("[调用工具 %s] %s" % (x.get("name"), x.get("input")))
        return " ".join(parts)
    return str(c)

def classify_request(d):
    """请求进来时判定：读图/压缩/普通填充，返回（状态行, 预览文本）"""
    msgs = d.get("messages") or []
    last_user = next((m for m in reversed(msgs) if m.get("role") == "user"), None)
    c = last_user.get("content") if last_user else None
    has_image = False
    text = ""
    if isinstance(c, list):
        for x in c:
            if isinstance(x, dict):
                if x.get("type") in ("image_url", "image") or "image_url" in x:
                    has_image = True
                text += x.get("text", "") + " "
    elif isinstance(c, str):
        text = c
    # 压缩判定：系统提示或用户消息带总结指令
    all_text = text + " "
    for m in msgs[:3]:
        cc = m.get("content")
        if isinstance(cc, str):
            all_text += cc + " "
    is_compact = any(k in all_text.lower() for k in COMPACT_KEYS)
    text_flat = " ".join(text.split())
    est_tok = len(text_flat) // 2
    # 轮次与角色分布：让"填充的是什么"一目了然
    roles, total_chars = {}, 0
    for m in msgs:
        r = m.get("role") or "?"
        roles[r] = roles.get(r, 0) + 1
        total_chars += len(_flatten(m.get("content")) or "")
    dist = " / ".join(f"{r}×{n}" for r, n in roles.items())
    est_all = total_chars // 2
    if is_compact:
        st = f"● 压缩中（上下文整理，~{est_tok} tok 新输入 / 全history ~{est_all} tok，{len(msgs)} 条消息）"
    elif has_image:
        st = f"● 读图中（多模态嵌入 + 预填充，~{est_tok} tok 文本 / 全history ~{est_all} tok，{len(msgs)} 条消息）"
    else:
        st = f"● 填充中（~{est_tok} tok 新输入 / 全history ~{est_all} tok，{len(msgs)} 条消息）"
    # 最新一条非 assistant 消息的长预览（agent 循环里通常是 tool 结果）
    last_in = next((m for m in reversed(msgs) if m.get("role") != "assistant"), None)
    lines = [f"— 消息分布: {dist}"]
    if last_in is not None:
        lines.append(f"— 最新[{last_in.get('role')}]: " + _flatten(last_in.get("content"))[:1500])
    return st, text_flat + "\n" + "\n".join(lines)

def strip_thinking(body):
    """nothink 模式：剥掉请求级思考参数"""
    if mode() != "nothink" or not body:
        return body
    try:
        d = json.loads(body)
        if isinstance(d, dict):
            for k in ("reasoning_budget", "thinking", "enable_thinking"):
                d.pop(k, None)
            # 不是删 effort 而是强制 none：某些模板(3.5系)只有它能压思考
            d["reasoning_effort"] = "none"
            ctk = d.pop("chat_template_kwargs", None)
            if isinstance(ctk, dict):
                ctk.pop("enable_thinking", None)
                ctk.pop("thinking", None)
                if ctk:
                    d["chat_template_kwargs"] = ctk
            return json.dumps(d, ensure_ascii=False).encode("utf-8")
    except Exception:
        pass
    return body

def handle_sse_line(line, out_txt, st):
    """解析一行 SSE，累积内容并更新当前状态 st['cur']"""
    if not line.startswith("data: ") or line[6:] == "[DONE]":
        return
    try:
        d = json.loads(line[6:])
    except json.JSONDecodeError:
        return
    if d.get("type") == "content_block_start":
        blk = d.get("content_block") or {}
        if blk.get("type") == "tool_use":
            st["cur"] = f"● 工具调用中 [{blk.get('name', 'tool')}]"
            out_txt.append(f"\n[{blk.get('name','tool')}] ")
    elif d.get("type") == "content_block_delta":
        delta = d.get("delta") or {}
        dt = delta.get("type")
        if dt == "input_json_delta":
            st["cur"] = "● 写入参数中（代码/文件内容）"
            out_txt.append(delta.get("partial_json") or "")
        elif dt == "text_delta":
            st["cur"] = "● 输出文字中"
            out_txt.append(delta.get("text") or "")
        elif dt == "thinking_delta":
            st["cur"] = "● 思考中"
            out_txt.append(delta.get("thinking") or "")
        else:
            t = delta.get("text")
            if t:
                st["cur"] = "● 输出文字中"
                out_txt.append(t)
            elif delta.get("thinking"):
                st["cur"] = "● 思考中"
                out_txt.append(delta["thinking"])
    elif d.get("object") == "chat.completion.chunk":
        for ch in d.get("choices") or []:
            m = ch.get("delta") or {}
            if m.get("reasoning_content"):
                st["cur"] = "● 思考中"
                out_txt.append(m["reasoning_content"])
            elif m.get("content"):
                st["cur"] = "● 输出文字中"
                out_txt.append(m["content"])
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                if fn.get("name"):
                    st["cur"] = f"● 工具调用中 [{fn['name']}]"
                    out_txt.append(f"\n[{fn['name']}] ")
                if fn.get("arguments"):
                    st["cur"] = "● 写入参数中（代码/文件内容）"
                    out_txt.append(fn["arguments"])

class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _relay(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        is_chat = "/chat/completions" in self.path or "/messages" in self.path
        # 请求阶段：状态预判（填充/读图/压缩）写 live 区
        if is_chat and body:
            try:
                d0 = json.loads(body)
                st_line, preview = classify_request(d0)
                write_live(st_line + ("\n" + preview[:2000] if preview else ""))
            except Exception:
                pass
        body = strip_thinking(body)
        # 剥参后 body 变长，原 Content-Length 必须丢弃，urllib 会按新 data 自动重设
        headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length")}
        req = urllib.request.Request(UPSTREAM + self.path, data=body if body else None,
                                     headers=headers, method=self.command)
        try:
            up = urllib.request.urlopen(req, timeout=600)
        except urllib.error.HTTPError as e:
            up = e
        except Exception as e:
            self.send_error(502, str(e))
            return
        self.send_response(up.status)
        stream = "text/event-stream" in (up.headers.get("Content-Type") or "")
        up_len = up.headers.get("Content-Length")
        for k, v in up.headers.items():
            if k.lower() in ("transfer-encoding", "connection"):
                continue
            # 流式由我们重新分块；非流式必须原样透传 Content-Length，
            # 否则 keep-alive 客户端（Zcode 等）会永久挂起等响应结束
            if k.lower() == "content-length" and not stream:
                self.send_header(k, v)
            elif k.lower() != "content-length":
                self.send_header(k, v)
        if stream:
            self.send_header("Transfer-Encoding", "chunked")
        else:
            self.send_header("Connection", "close")
        self.end_headers()

        raw_buf, sse_buf, out_txt, t0 = [], [], [], time.time()
        st = {"cur": ""}   # 当前解码状态
        last_flush = 0.0
        def flush_live():
            nonlocal last_flush
            if time.time() - last_flush > 0.15:
                head = st["cur"] + "\n" if st["cur"] else ""
                write_live(head + "".join(out_txt))
                last_flush = time.time()
        while True:
            chunk = up.read(1024)
            if not chunk:
                break
            if stream:
                self.wfile.write(b"%x\r\n" % len(chunk) + chunk + b"\r\n")
            else:
                self.wfile.write(chunk)
            if is_chat:
                raw_buf.append(chunk)
                if stream:
                    sse_buf.append(chunk)
                    text = b"".join(sse_buf).decode("utf-8", "ignore")
                    lines = text.split("\n")
                    tail = lines.pop()
                    sse_buf[:] = [tail.encode()] if tail else []
                    for line in lines:
                        handle_sse_line(line.strip(), out_txt, st)
                    flush_live()
        if stream:
            self.wfile.write(b"0\r\n\r\n")
        if is_chat and not stream and raw_buf:
            try:
                d = json.loads(b"".join(raw_buf))
                if isinstance(d, dict):
                    if d.get("choices"):
                        m = d["choices"][0].get("message") or {}
                        out_txt.append(m.get("content") or "")
                    elif d.get("content"):
                        out_txt.append("".join(c.get("text", "") for c in d["content"]))
            except Exception:
                pass
        txt = "".join(out_txt)
        if txt:
            write_live((st["cur"] + "\n" if st["cur"] else "") + txt)
        try:
            with open(USAGE, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "path": self.path, "stream": stream,
                                    "ms": int((time.time() - t0) * 1000),
                                    "out_chars": len(txt)}, ensure_ascii=False) + "\n")
        except Exception:
            pass

    do_GET = do_POST = do_DELETE = _relay

class TS(http.server.ThreadingHTTPServer):
    daemon_threads = True

if __name__ == "__main__":
    write_live("")
    TS(("127.0.0.1", int(LISTEN)), Handler).serve_forever()
