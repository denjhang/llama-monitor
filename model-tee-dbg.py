# -*- coding: utf-8 -*-
"""model-tee：8082 -> 8080 流式透传代理
- 客户端把 base 指到 http://127.0.0.1:8082 即可（OpenAI/Anthropic 协议均透传）
- 转发的同时把生成增量 tee 到 live-gen.txt（监控台读取显示）
- usage 流水追加到 tee-usage.jsonl（时间/输入输出token/耗时）
"""
import http.server, json, os, time, urllib.request, threading

UPSTREAM = "http://127.0.0.1:8080"
HERE     = os.path.dirname(os.path.abspath(__file__))
LIVE     = os.path.join(HERE, "live-gen.txt")
USAGE    = os.path.join(HERE, "tee-usage.jsonl")

def write_live(text):
    with open(LIVE, "w", encoding="utf-8") as f:
        f.write(text[-4000:])

class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _relay(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        # 透传除 Host 外的请求头
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
        buf, out_txt, t0 = [], [], time.time()
        usage_d = {}
        while True:
            chunk = up.read(1024)
            if not chunk:
                break
            if stream:
                self.wfile.write(b"%x\r\n" % len(chunk) + chunk + b"\r\n")
            else:
                self.wfile.write(chunk)
            if is_chat:
                buf.append(chunk)
                try:
                    txt = chunk.decode("utf-8", "ignore")
                    for line in txt.splitlines():
                        if line.startswith("data: ") and line[6:] != "[DONE]":
                            try:
                                d = json.loads(line[6:])
                                if d.get("type") == "content_block_delta":
                                    delta = d.get("delta", {})
                                    out_txt.append(delta.get("text") or delta.get("thinking") or "")
                                elif d.get("object") == "chat.completion.chunk":
                                    for ch in d.get("choices", []):
                                        m = (ch.get("delta") or {})
                                        out_txt.append(m.get("content") or m.get("reasoning_content") or "")
                                    if d.get("usage"):
                                        usage_d = d["usage"]
                            except json.JSONDecodeError:
                                pass
                except Exception:
                    pass
        if stream:
            self.wfile.write(b"0\r\n\r\n")
        # 非流式：一次性解析
        if is_chat and not stream and buf:
            try:
                d = json.loads(b"".join(buf))
                if isinstance(d, dict) and d.get("choices"):
                    m = d["choices"][0].get("message", {})
                    out_txt.append(m.get("content") or "")
                    usage_d = d.get("usage") or {}
                elif isinstance(d, dict) and d.get("content"):
                    out_txt.append("".join(c.get("text", "") for c in d["content"]))
                    usage_d = d.get("usage") or {}
            except Exception:
                pass
        txt = "".join(out_txt)
        if txt:
            write_live(txt)
        try:
            with open(USAGE, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "path": self.path, "stream": stream,
                                    "ms": int((time.time() - t0) * 1000),
                                    "out_chars": len(txt),
                                    "usage": usage_d}, ensure_ascii=False) + "\n")
        except Exception:
            pass

    do_GET = do_POST = do_DELETE = _relay

class TS(http.server.ThreadingHTTPServer):
    daemon_threads = True

if __name__ == "__main__":
    write_live("")
    TS(("127.0.0.1", 8082), Handler).serve_forever()
