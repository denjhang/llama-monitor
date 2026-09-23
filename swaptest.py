# -*- coding: utf-8 -*-
"""swaptest.py <config_name> [swap_count]
按配置启动 llama-server，建会话A（多轮），再发无关会话B 触发 KV 换血，判定崩溃。
用法: python swaptest.py baseline 5
"""
import json, os, subprocess, sys, time, urllib.request, urllib.error

BIN   = r"E:\working\llama-cpp\llama-b11139\llama-server.exe"
WORK  = r"E:\working\llama-cpp\llama-b11139"
MODEL = r"E:\working\models-E\Merkyor\Qwen3.8-27B-EfficientThink-Q3-LynnStyle\Qwen3.8-27B-EfficientThink-SimPO-Q3-LynnStyle.gguf"
MMPROJ= r"E:\working\gguf-sidecars\qwen38-27b\mmproj-Qwen3.8-27B-Q4_K_M.gguf"
DRAFT = r"E:\working\gguf-sidecars\qwen38-27b\dflash2-qwen38-27b-Q8_0.gguf"
PORT  = "8090"

CONFIGS = {
    # 与线上配置一致（预期崩）
    "baseline": ["--mmproj", MMPROJ, "--model-draft", DRAFT, "--spec-type", "draft-dflash",
                 "--spec-draft-n-max", "4", "-ctk", "q4_0", "-ctv", "q4_0", "-fa", "on"],
    # 去掉投机
    "nodraft":  ["--mmproj", MMPROJ, "-ctk", "q4_0", "-ctv", "q4_0", "-fa", "on"],
    # 去掉视觉
    "nommproj": ["--model-draft", DRAFT, "--spec-type", "draft-dflash",
                 "--spec-draft-n-max", "4", "-ctk", "q4_0", "-ctv", "q4_0", "-fa", "on"],
    # KV 不压缩
    "kv8":      ["--mmproj", MMPROJ, "--model-draft", DRAFT, "--spec-type", "draft-dflash",
                 "--spec-draft-n-max", "4", "-ctk", "q8_0", "-ctv", "q8_0", "-fa", "on"],
    # 关 flash attn
    "nofa":     ["--mmproj", MMPROJ, "--model-draft", DRAFT, "--spec-type", "draft-dflash",
                 "--spec-draft-n-max", "4", "-ctk", "q4_0", "-ctv", "q4_0", "-fa", "off"],
}

def health():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False

def ask(msgs, max_tokens=400, timeout=300):
    body = {"model": "x", "max_tokens": max_tokens, "messages": msgs}
    r = urllib.request.urlopen(urllib.request.Request(
        f"http://127.0.0.1:{PORT}/v1/chat/completions",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}), timeout=timeout)
    return json.load(r)

def alive(proc):
    return proc.poll() is None

def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    swaps = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    log = open(os.path.join(WORK, f"swaptest-{name}.log"), "wb")
    args = [BIN, "-m", MODEL] + CONFIGS[name] + [
        "-ngl", "99", "-ngld", "99", "-c", "262144", "-np", "1", "--jinja",
        "--reasoning-budget", "0", "--host", "127.0.0.1", "--port", PORT]
    print(f"[{name}] starting ...")
    proc = subprocess.Popen(args, cwd=WORK, stdout=log, stderr=log,
                            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    t0 = time.time()
    while not health():
        if not alive(proc):
            print(f"[{name}] DIED AT LOAD"); return 1
        if time.time() - t0 > 300:
            print(f"[{name}] load timeout"); proc.kill(); return 1
        time.sleep(3)
    print(f"[{name}] ready in {time.time()-t0:.0f}s")

    # 会话A：大文本灌上下文（真实规模），prefill 为主不生成
    filler = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "swaptest-filler.txt"), encoding="utf-8").read()
    convA = [{"role": "user", "content": "参考资料如下，读完只回复ok：\n" + filler}]
    try:
        t0 = time.time()
        r = ask(convA, max_tokens=10, timeout=900)
        pt = r["usage"]["prompt_tokens"]
        print(f"[{name}] convA built: prompt {pt} tok in {time.time()-t0:.0f}s")
        if pt < 20000:
            print(f"[{name}] filler too small, abort"); proc.kill(); return 1
        convA.append({"role": "assistant", "content": "ok"})
    except Exception as e:
        print(f"[{name}] convA ERR: {e}"); proc.kill(); return 1
    # 塞一张真图进会话A（复现线上带图会话）
    import base64
    try:
        png = r"E:\working\vgm-play\Brandish_3_-_Spirit_of_Balcan_(NEC_PC-9801)\Brandish 3 - Spirit of Balcan.png"
        img = base64.b64encode(open(png, "rb").read()).decode()
        msg = {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + img}},
            {"type": "text", "text": "一句话描述这张图"}]}
        convA.append(msg)
        r = ask(convA, max_tokens=60, timeout=300)
        print(f"[{name}] image turn ok, ctx:", r["usage"]["total_tokens"])
    except Exception as e:
        print(f"[{name}] image turn ERR: {e}")

    # 无关会话B：量子物理 → 触发 LCP 低相似度换血
    topics = ["解释量子隧穿效应和它的工程应用。",
              "分析罗马帝国三世纪危机的经济原因。",
              "写一个Rust的线程池实现思路。",
              "比较PostgreSQL和MySQL的MVCC实现。",
              "解释CRISPR基因编辑的分子机制。"]
    import base64 as _b64
    _png = r"E:\workinggm-play\Brandish_3_-_Spirit_of_Balcan_(NEC_PC-9801)\Brandish 3 - Spirit of Balcan.png"
    _img = _b64.b64encode(open(_png, "rb").read()).decode()
    for i, t in enumerate(topics[:swaps]):
        if not alive(proc):
            print(f"[{name}] RESULT: CRASHED at swap {i}")
            return 2
        try:
            # 换血请求自带图片（复现 Zcode 截图流）
            _msg = {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + _img}},
                {"type": "text", "text": t}]}
            ask([_msg], max_tokens=250, timeout=180)
            print(f"[{name}] swap {i} survived")
            time.sleep(2)
        except Exception as e:
            if not alive(proc):
                print(f"[{name}] RESULT: CRASHED at swap {i} ({e})")
                return 2
            print(f"[{name}] swap {i} request err but server alive: {e}")
    proc.kill()
    print(f"[{name}] RESULT: SURVIVED all {swaps} swaps")
    return 0

if __name__ == "__main__":
    sys.exit(main())
