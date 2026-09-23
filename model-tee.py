# -*- coding: utf-8 -*-
"""model-tee：8080 -> 8082 流式透传代理
- 客户端照常连 http://127.0.0.1:8080（OpenAI/Anthropic 协议均透传）
- 转发同时把生成增量 tee 到 live-gen.txt（监控台实时显示）
- usage 流水追加 tee-usage.jsonl
"""
import http.server, json, os, time, urllib.request, urllib.error

UPSTREAM = "http://127.0.0.1:8082"
LIVE  = r"E:\working\llama-cpp\llama-b11139\live-gen.txt"
USAGE = r"E:\working\llama-cpp\llama-b11139\tee-usage.jsonl"

def write_live(text):
    with open(LIVE, "w", encoding="utf-8") as f:
        f.write(text[-4000:])

def handle_sse_line(line, out_txt):
    if not line.startswith("data: ") or line[6:] == "[DONE]":
        return
    try:
        d = json.loads(line[6:])
    except json.JSONDecodeError:
        return
    if d.get("type") == "content_block_start":
        blk = d.get("content_block") or {}
        if blk.get("type") == "tool_use":
            out_txt.append(f"\n[{blk.get('name','tool')}] ")
    elif d.get("type") == "content_block_delta":
        delta = d.get("delta") or {}
        dt = delta.get("type")
        if dt == "input_json_delta":          # Anthropic 工具参数流（写文件/代码在这里）
            out_txt.append(delta.get("partial_json") or "")
        elif dt == "text_delta":
            out_txt.append(delta.get("text") or "")
        elif dt == "thinking_delta":
            out_txt.append(delta.get("thinking") or "")
        else:
            out_txt.append(delta.get("text") or delta.get("thinking") or "")
    elif d.get("object") == "chat.completion.chunk":
        for ch in d.get("choices") or []:
            m = ch.get("delta") or {}
            out_txt.append(m.get("content") or m.get("reasoning_content") or "")
            # OpenAI 工具调用参数流
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                if fn.get("name"):
                    out_txt.append(f"\n[{fn['name']}] ")
                if fn.get("arguments"):
                    out_txt.append(fn["arguments"])

class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _relay(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        # nothink 模式下剥掉请求级思考参数（客户端可覆盖服务端默认，代理层焊死）
        try:
            with open(r"E:\working\llama-cpp\llama-b11139\server-mode.txt", encoding="utf-8") as f:
                mode = f.read().strip()
        except OSError:
            mode = "think"
        if mode == "nothink" and body:
            try:
                d = json.loads(body)
                if isinstance(d, dict):
                    for k in ("reasoning_effort", "reasoning_budget", "thinking", "enable_thinking"):
                        d.pop(k, None)
                    ctk = d.pop("chat_template_kwargs", None)
                    if isinstance(ctk, dict):
                        ctk.pop("enable_thinking", None)
                        ctk.pop("thinking", None)
                        if ctk:
                            d["chat_template_kwargs"] = ctk
                    body = json.dumps(d, ensure_ascii=False).encode("utf-8")
                    self.headers.replace_header("Content-Length", str(len(body)))
            except Exception:
                pass
        headers = {k: v for k, v in self.headers.items() if k.lower() != "host"}
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
        for k, v in up.headers.items():
            if k.lower() in ("transfer-encoding", "content-length", "connection"):
                continue
            self.send_header(k, v)
        stream = "text/event-stream" in (up.headers.get("Content-Type") or "")
        if stream:
            self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        is_chat = "/chat/completions" in self.path or "/messages" in self.path
        raw_buf, sse_buf, out_txt, t0 = [], [], [], time.time()
        last_flush = 0.0
        def flush_live(force=False):
            nonlocal last_flush
            if out_txt and (force or time.time() - last_flush > 0.15):
                write_live("".join(out_txt))
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
                    # 跨块按行切分，1KB 读边界会切碎 JSON 行
                    sse_buf.append(chunk)
                    text = b"".join(sse_buf).decode("utf-8", "ignore")
                    lines = text.split("\n")
                    tail = lines.pop()
                    sse_buf[:] = [tail.encode()] if tail else []
                    for line in lines:
                        handle_sse_line(line.strip(), out_txt)
                    flush_live()  # 流式中实时落盘（150ms 节流）
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
            write_live(txt)
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
    TS(("127.0.0.1", 8080), Handler).serve_forever()
