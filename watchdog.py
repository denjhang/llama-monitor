# -*- coding: utf-8 -*-
"""llama-server 监控台 v3（学 model-gateway monitor 风格）
全屏重绘 + 中英对齐表格；关掉本窗口不影响后台服务；
服务死亡自动抓快照并醒目告警，恢复后自动转绿。
用法: python watchdog.py [刷新间隔秒, 默认5]
"""
import datetime, json, os, re, select, subprocess, sys, time, unicodedata, urllib.request

try:
    import msvcrt  # Windows 键盘监听
except ImportError:
    msvcrt = None

def key_pressed():
    """非阻塞读键，返回按下的字符（小写）或 None"""
    if msvcrt and msvcrt.kbhit():
        ch = msvcrt.getwch()
        return ch.lower() if len(ch) == 1 else None
    return None

def stop_server():
    """确认无任务在跑后停止 llama-server"""
    try:
        slots = get_json("/slots")
        busy = any(s.get("is_processing") for s in (slots or []))
        if busy:
            return False, "有请求正在生成，拒绝停止"
    except Exception:
        pass
    subprocess.run(["taskkill", "/IM", EXE, "/F"], capture_output=True)
    return True, "已停止 llama-server"

LLAMA_DIR  = r"E:\working\llama-cpp\llama"
MODE_FILE  = r"E:\working\llama-cpp\llama-b11139\server-mode.txt"
SERVER_LOG = r"E:\working\llama-cpp\llama-b11139\llama-server.log"
EVENTS_LOG = os.path.join(LLAMA_DIR, "watchdog-events.log")
SNAP_DIR   = os.path.join(LLAMA_DIR, "crash-snapshots")
ENDPOINT   = "http://127.0.0.1:8080"
EXE        = "llama-server.exe"

BS = chr(92)  # 反斜杠
_last_pdone = 0  # 预填充进度判断：pdone 是否仍在增长
_live_task = None   # 当前在生成的 task id
_live_buf = []      # 实时生成内容滚动缓冲

def sample_live():
    """解码期高频采样 next_token 攒实时内容（0.5s 一次，两次采样间的 token 会漏，仅预览用）"""
    global _live_task
    slots = get_json("/slots")
    if not slots:
        return
    sl = slots[0]
    if not sl.get("is_processing"):
        return
    tid = sl.get("id_task")
    if tid != _live_task:
        _live_task = tid
        _live_buf.clear()
    tok = sl.get("next_token")
    if tok:
        _live_buf.append(tok)
        if len(_live_buf) > 400:
            del _live_buf[:200]

def dw(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in str(s))

def pad(s, w, align="l"):
    s = str(s)
    fill = max(0, w - dw(s))
    return (" " * fill + s) if align == "r" else (s + " " * fill)

def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def run_cmd(args):
    r = subprocess.run(args, capture_output=True)
    return (r.stdout or b"").decode("utf-8", errors="replace")

def get_json(path, timeout=3):
    try:
        with urllib.request.urlopen(ENDPOINT + path, timeout=timeout) as r:
            return json.load(r)
    except Exception:
        return None

def vram():
    out = run_cmd(["nvidia-smi", "--query-gpu=index,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw",
                   "--format=csv,noheader,nounits"])
    parts = []
    for l in out.strip().splitlines():
        f = [x.strip() for x in l.split(",")]
        if len(f) == 6:
            parts.append(f"GPU{f[0]} {f[1]}/{f[2]}M {f[3]}% {f[4]}C {f[5]}W")
    return "  ".join(parts)

def log_tail(n=400):
    try:
        with open(SERVER_LOG, "r", errors="replace") as f:
            return f.readlines()[-n:]
    except OSError:
        return []

NGEN_RE = re.compile(r"task (\d+) \| n_gen =\s+(\d+), tg =\s+([\d.]+) t/s, tg_3s =\s+([\d.]+)")
REQ_RE  = re.compile(r"task (\d+) \|\s+prompt eval time =\s+[\d.]+ ms /\s+(\d+) tokens")
GEN_RE  = re.compile(r"task (\d+) \|\s+eval time =\s+[\d.]+ ms /\s+(\d+) tokens \(\s+[\d.]+ ms per token,\s+([\d.]+) tokens per second\)")
ACC_RE  = re.compile(r"task (\d+) \|\s+draft acceptance = ([\d.]+)")
TOT_RE  = re.compile(r"task (\d+) \|\s+total time =\s+([\d.]+) ms")
STOP_RE = re.compile(r"release: id\s+\d+ \|\s+task (\d+) \|\s+stop processing: n_tokens = (\d+)")
ERR_RE  = re.compile(r"got exception: (.{0,110})")

def live_gen(task_id):
    """当前任务实时生成进度：已生成tok/瞬时速度（日志 n_gen 行，约3s一行）"""
    try:
        with open(SERVER_LOG, "r", errors="replace") as f:
            lines = f.readlines()[-30:]
    except OSError:
        return None
    for l in reversed(lines):
        m = NGEN_RE.search(l)
        if m and m.group(1) == str(task_id):
            return int(m.group(2)), float(m.group(3)), float(m.group(4))
    return None

def recent_requests(n=8):
    """从日志解析最近完成的请求（最新在上）"""
    reqs, order = {}, []
    for l in log_tail():
        m = REQ_RE.search(l)
        if m:
            t = reqs.setdefault(m.group(1), {})
            if "pt" not in t:
                t["pt"] = int(m.group(2)); order.append(m.group(1))
        m = GEN_RE.search(l)
        if m:
            reqs.setdefault(m.group(1), {})["ct"] = int(m.group(2))
            reqs[m.group(1)]["tps"] = float(m.group(3))
        m = ACC_RE.search(l)
        if m:
            reqs.setdefault(m.group(1), {})["acc"] = float(m.group(2))
        m = TOT_RE.search(l)
        if m:
            reqs.setdefault(m.group(1), {})["ms"] = int(float(m.group(2)))
        m = STOP_RE.search(l)
        if m:
            reqs.setdefault(m.group(1), {})["total"] = int(m.group(2))
    return [reqs[t] | {"id": t} for t in reversed(order[-n:])]

def last_error():
    for l in reversed(log_tail(100)):
        m = ERR_RE.search(l)
        if m:
            return m.group(1)
    return None

def fmt_k(n):
    if n is None: return "-"
    n = int(n)
    return f"{n/1000:.1f}K" if n >= 1000 else str(n)

def server_uptime_sec():
    """llama-server 进程已存活秒数"""
    out = run_cmd(["powershell", "-NoProfile", "-Command",
                   "(Get-Process llama-server -ErrorAction SilentlyContinue).StartTime.ToString('yyyy-MM-dd HH:mm:ss')"])
    try:
        import datetime
        return (datetime.datetime.now() - datetime.datetime.strptime(out.strip(), "%Y-%m-%d %H:%M:%S")).total_seconds()
    except Exception:
        return None

def dog_state():
    """多狗状态：刚复活=复活狗，稳定1h+=幸运狗，平时=看门狗"""
    up = server_uptime_sec()
    if not up:
        return "看门狗"
    if up >= 3600:
        return "幸运狗"
    return "看门狗"

def death_stats():
    """从事件日志统计：死亡次数/最近死因/自动重载次数"""
    n_down = n_restart = 0
    last_verdict, last_time = "-", "-"
    try:
        with open(EVENTS_LOG, encoding="utf-8") as f:
            for l in f:
                if "CRASH (WER)" in l or "SILENT EXIT" in l:
                    n_down += 1
                    head = l.split("] ", 1)
                    last_time = head[0].lstrip("[")
                    last_verdict = head[1] if len(head) > 1 else "?"
                elif "auto-restart triggered" in l:
                    n_restart += 1
    except OSError:
        pass
    return n_down, n_restart, last_verdict.splitlines()[0] if last_verdict else "-", last_time

def server_running():
    return EXE.lower() in run_cmd(["tasklist", "/FI", f"IMAGENAME eq {EXE}"]).lower()

def restart_server():
    """按崩溃前的模式自动拉起服务（pythonw 无头）"""
    try:
        with open(r"E:\working\llama-cpp\llama-b11139\server-mode.txt", encoding="utf-8") as f:
            mode = f.read().strip()
    except OSError:
        mode = "think"
    arg = ["nothink"] if mode == "nothink" else []
    subprocess.Popen(["pythonw", r"E:\working\llama-cpp\llama\server-headless.pyw"] + arg,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    return mode

def snapshot():
    os.makedirs(SNAP_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = run_cmd(["wevtutil", "qe", "Application",
                   "/q:*[System[(EventID=1000 or EventID=1001)]]", "/f:text", "/c:3", "/rd:true"])
    crash = "llama-server" in out.lower()
    verdict = "CRASH (WER)" if crash else "SILENT EXIT"
    path = os.path.join(SNAP_DIR, f"last-{ts}.log")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"=== llama-server DOWN at {now()} === verdict: {verdict}\n")
        if crash:
            f.write(out + "\n")
        f.write("".join(log_tail(200)))
    with open(EVENTS_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{now()}] {verdict}\n  snapshot: {path}\n")
    return path

def render(running):
    os.system("cls" if os.name == "nt" else "clear")
    print("=" * 100)
    health = get_json("/health")
    model = get_json("/v1/models")
    name = os.path.basename(model["data"][0]["id"]) if model and model.get("data") else "?"
    dot = "🟢 服务正常" if (running and health) else "🔴 服务已停止"
    print(f"  llama-server 监控   {now()}   {ENDPOINT}   {dot}   X两次=停止模型并退出  Ctrl+C=仅退监控")
    print("=" * 100)
    if not running or not health:
        print("  [!] 服务不可达。后台服务已无窗口化运行，如需拉起: start-server-headless.bat")
        return
    print(f"  模型 {name}")
    print(f"  显存 {vram()}")
    slots0 = (get_json("/slots") or [{}])[0]
    prm = slots0.get("params", {}) or {}
    try:
        mode = open(MODE_FILE, encoding="utf-8").read().strip()
    except OSError:
        mode = "think"
    def f2(v):
        if isinstance(v, (int, float)):
            return f"{v:.2f}"
        return "-"
    th_s = "开" if mode == "think" else "关(reasoning-budget 0)"
    print(f"  参数 思考:{th_s} | temp {f2(prm.get('temperature'))} | top_p {f2(prm.get('top_p'))} | top_k {prm.get('top_k','-')} | min_p {f2(prm.get('min_p'))}")
    print( "  配置 上下文 262K | KV q4_0 | 投机 draft-dflash×4 | 视觉 mmproj Q4_K_M | 单槽")
    try:
        with open(r"E:\working\llama-cpp\llama-b11139\live-gen.txt", encoding="utf-8") as f:
            txt = f.read()
    except OSError:
        txt = ""
    if txt:
        # 还原工具参数里的转义换行，按行展示尾部
        txt = txt.replace(BS + "n", "\n").replace(BS + "t", "  ")
        lines = [l for l in txt.rstrip().splitlines() if l.strip()]
        print("▎实时/最近生成内容（含工具调用/代码，尾部 6 行）")
        for l in lines[-6:]:
            show = l if len(l) <= 180 else l[:180] + "…"
            print("  " + show)
        print("-" * 100)
    reqs_all = recent_requests(50)
    if reqs_all:
        tps_list = [r["tps"] for r in reqs_all if r.get("tps")]
        acc_list = [r["acc"] for r in reqs_all if r.get("acc") is not None]
        avg_tps = sum(tps_list) / len(tps_list) if tps_list else 0
        avg_acc = sum(acc_list) / len(acc_list) if acc_list else 0
        print(f"  统计 已服务请求(近50): {len(reqs_all)} | 平均速度 {avg_tps:.1f} tok/s | 平均draft命中 {avg_acc:.2f}")
    slots = get_json("/slots")
    print("-" * 100)
    if slots:
        print("▎槽位状态")
        print(pad("slot", 6) + pad("状态", 12) + pad("上下文占用", 30, "r")
              + pad("投机", 6, "r") + pad("阶段进度", 46))
        for s in slots:
            used, ctx = s.get("n_prompt_tokens", 0), s.get("n_ctx", 0)
            pct = 100 * used // max(ctx, 1)
            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
            st = "生成中" if s.get("is_processing") else "空闲"
            # LM Studio 式阶段进度：预填充或生成
            prog = ""
            if s.get("is_processing"):
                ptot = s.get("n_prompt_tokens", 0)
                pdone = s.get("n_prompt_tokens_processed", 0)
                # 硬判据：当前 task 在日志出现 n_gen 行 = 已在解码（预填期不可能有）
                lg = live_gen(s.get("id_task"))
                if lg:
                    prog = f"解码 已生成 {fmt_k(lg[0])} tok @ {lg[2]:.0f} tok/s (均速 {lg[1]:.0f})"
                else:
                    ppct = 100 * pdone // max(ptot, 1)
                    pbar = "█" * (ppct // 10) + "░" * (10 - ppct // 10)
                    prog = f"预填充 {pbar} {ppct}% ({fmt_k(pdone)}/{fmt_k(ptot)} tok)"
            print(pad(s.get("id", "?"), 6) + pad(st, 12)
                  + pad(f"{fmt_k(used)}/{fmt_k(ctx)} {bar} {pct}%", 30, "r")
                  + pad("开" if s.get("speculative") else "关", 6, "r")
                  + pad(prog, 46))
    print("-" * 100)
    print("▎最近请求（最新在上，速度/命中率来自 llama-server.log）")
    reqs = recent_requests()
    if reqs:
        print(pad("task", 8) + pad("输入tok", 10, "r") + pad("生成tok", 10, "r")
              + pad("速度tok/s", 12, "r") + pad("draft命中", 12, "r") + pad("会话总量", 10, "r")
              + pad("耗时", 10, "r"))
        for r in reqs:
            ms = r.get("ms")
            if ms is None:
                ms_s = "-"
            else:
                ms_s = f"{ms/1000:.1f}s" + ("⚠" if ms >= 30000 else "")
            print(pad(r["id"], 8) + pad(fmt_k(r.get("pt")), 10, "r") + pad(fmt_k(r.get("ct")), 10, "r")
                  + pad(f"{r.get('tps', 0):.1f}" if r.get("tps") else "-", 12, "r")
                  + pad(f"{r.get('acc', 0):.2f}" if r.get("acc") is not None else "-", 12, "r")
                  + pad(fmt_k(r.get("total")), 10, "r")
                  + pad(ms_s, 10, "r"))
    else:
        print("  （暂无请求记录）")
    print("-" * 100)
    err = last_error()
    if err:
        print(f"▎最近异常: {err}")
    nd, nr, verdict, t = death_stats()
    up = server_uptime_sec()
    if nr > 0 and up is not None and up < 3600:
        dog = "复活狗（刚拽回来）"
    elif up is not None and up >= 3600:
        dog = "幸运狗（稳定运行1h+）"
    else:
        dog = "看门狗"
    print(f"▎{dog}")
    v_short = "CRASH(WER)" if "CRASH" in verdict else ("静默退出" if "SILENT" in verdict else "无")
    print(f"  死亡重载次数 : {nr}")
    print(f"  累计死亡     : {nd} 次")
    print(f"  最近死亡原因 : {v_short}  ({t})")
    if up is not None:
        h, m = int(up // 3600), int(up % 3600 // 60)
        print(f"  本次已存活   : {h}h{m:02d}m")

def main():
    interval = float(sys.argv[1]) if len(sys.argv) > 1 else 5
    with open(EVENTS_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{now()}] revive-dog v3 started, server_running={server_running()}\n")
    was = server_running()
    while True:
        running = server_running()
        if was and not running:
            path = snapshot()
            print(f"\n[!] 服务死亡，快照: {path}")
        elif not was and running:
            with open(EVENTS_LOG, "a", encoding="utf-8") as f:
                f.write(f"[{now()}] server UP\n")
        was = running
        render(running)
        time.sleep(interval)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n退出监控（后台服务不受影响）。")
