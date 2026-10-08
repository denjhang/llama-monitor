# -*- coding: utf-8 -*-
"""控制台监控校验 v2: 数据源 = Strata 官方 /metrics (serve/server.py 2586行)"""
import json, time, urllib.request, threading

def get(path, base="http://127.0.0.1:8081"):
    try:
        with urllib.request.urlopen(base + path, timeout=3) as r:
            return json.load(r)
    except Exception:
        return None

def fire():
    time.sleep(2)
    body = json.dumps({"model": "x", "messages": [{"role": "user", "content": "Write two sentences about oceans."}],
                       "max_tokens": 120, "reasoning_effort": "none"}).encode()
    req = urllib.request.Request("http://127.0.0.1:8081/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            r.read()
    except Exception as e:
        print("fire:", e)

def show(d, tag):
    eng, live, reqs = d.get("engine") or {}, d.get("live") or {}, d.get("requests") or []
    hw = d.get("hardware") or {}
    print(f"\n===== {tag} =====")
    print(f" 模型          {eng.get('model')}  ctx={eng.get('max_context')}  images={eng.get('images')}")
    st = live.get("state")
    if st == "reading":
        pr, pt = live.get("prompt_read") or 0, live.get("prompt_total") or 0
        phase = f"预填充 {pr}/{pt} ({100*pr//max(pt,1)}%)  {live.get('prefill_tok_s_mean')} tok/s"
    elif st == "generating":
        phase = f"解码 {live.get('generated')}/{live.get('max_tokens')} @ {live.get('tok_s')} tok/s (均{live.get('tok_s_mean')})"
    else:
        phase = st
    print(f" 阶段(官方)    {phase}")
    if reqs:
        r0 = reqs[0]
        do, da = r0.get("drafts_offered"), r0.get("drafts_accepted")
        acc = f"{da}/{do} = {da/do:.2f}" if do and da is not None else "-"
        used = (r0.get("prompt_tokens") or 0) + (r0.get("output_tokens") or 0)
        print(f" 最近请求      prompt {r0.get('prompt_tokens')} + 生成 {r0.get('output_tokens')}"
              f" @ {r0.get('decode_tok_s')} t/s  用时{r0.get('duration_s')}s  草稿{acc}")
        print(f" 命中率        {r0.get('hit_rate')}")
        print(f" 上下文占用    {used} / {eng.get('max_context')} ({100*used//max(eng.get('max_context') or 1,1)}%)")
    else:
        print(" 最近请求      (尚无完成请求)")
    tot = d.get("totals") or {}
    print(f" 累计          {tot.get('requests')}次 生成{tot.get('output_tokens')}tok")
    g = hw.get("gpus") or "?"
    print(f" GPU           {g}  util={hw.get('gpu_util')}  mem={hw.get('gpu_mem_used')}/{hw.get('gpu_mem_total')}  温度={hw.get('gpu_temp')}")

if __name__ == "__main__":
    threading.Thread(target=fire, daemon=True).start()
    for tag, delay in [("空闲态", 1), ("请求中(3s后)", 4), ("请求中(6s后)", 3), ("完成后", 8)]:
        time.sleep(delay)
        d = get("/metrics")
        if d:
            show(d, tag)
        else:
            print(f"\n===== {tag} ===== /metrics 不可达!")
