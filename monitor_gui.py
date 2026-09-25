# -*- coding: utf-8 -*-
"""llama-server 监控台 GUI v3：KPI 仪表盘设计（PySide6）
- 顶部：模型名 + 状态胶囊 + 时钟
- KPI 瓷砖行：大数字 + 小标题（存活/上下文/速度/draft/GPU0/GPU1）
- 阶段卡：预填/解码大进度条
- 实时生成：等宽代码区流式滚动（200ms）
- 请求表：斑马纹
- 底部：复活狗一行
"""
import json, os, re, subprocess, sys, threading, time, datetime, urllib.request

from PySide6.QtCore import Qt, QTimer, QRect, QSize
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QLabel, QProgressBar, QTableWidget,
                               QTableWidgetItem, QHeaderView, QFrame, QTextEdit,
                               QSizePolicy, QGridLayout, QPushButton, QDialog,
                               QRubberBand, QComboBox, QCheckBox)

# 可监控端口表：url + 各自日志（小模型日志在 E:\LM\small-<端口>.log）
PORTS = {
    "8080 · 统一网关": ("http://127.0.0.1:8080", r"E:\working\llama-cpp\llama-b11139\llama-server.log", "对外入口（按模型路由）"),
    "8092 · SGLang-27B (WSL)": ("http://127.0.0.1:8092", r"\\wsl.localhost\Ubuntu-24.04\root\sglang-best.log", "WSL SGLang TP=2 补丁版"),
    "8083 · LFM2.5-2.6B": ("http://127.0.0.1:8083", r"E:\LM\small-8183.log", "直连（真实服务）"),
    "8084 · Ministral14B": ("http://127.0.0.1:8084", r"E:\LM\small-8184.log", "直连（真实服务）"),
    "8085 · MiniCPM5-1B-Fable5微调":    ("http://127.0.0.1:8085", r"E:\LM\small-8085.log", "直连（真实服务）"),
}
ENDPOINT   = PORTS["8080 · 统一网关"][0]
SERVER_LOG = PORTS["8080 · 统一网关"][1]
LIVE_FILE  = r"E:\working\llama-cpp\llama-b11139\live-gen.txt"
LIVE_FILE  = r"E:\working\llama-cpp\llama-b11139\live-gen.txt"
EVENTS_LOG = r"E:\working\llama-cpp\llama\watchdog-events.log"
MODE_FILE  = r"E:\working\llama-cpp\llama-b11139\server-mode.txt"
EXE        = "llama-server.exe"
CFG_FILE   = r"E:\working\llama-cpp\llama\monitor-gui-cfg.json"

QSS_FILE = r"E:\working\llama-cpp\llama\monitor-gui.qss"

def load_qss():
    try:
        return open(QSS_FILE, encoding="utf-8").read()
    except OSError:
        return ""

# ---------------- 数据层（与 v2 相同） ----------------
def run_cmd(args):
    r = subprocess.run(args, capture_output=True, creationflags=0x08000000)
    return (r.stdout or b"").decode("utf-8", "replace")

def get_json(path, timeout=3):
    try:
        with urllib.request.urlopen(ENDPOINT + path, timeout=timeout) as r:
            return json.load(r)
    except Exception:
        return None

# SGLang（WSL）日志与 live 源：监控 8080 网关或 8092 tee 时都指向 WSL 侧
WSL_SGLANG_LOG = r"\\wsl.localhost\Ubuntu-24.04\root\sglang-best.log"

def sg_log_path():
    """SGLang 后端日志：8092 走 PORTS 表；8080 网关后端是 SGLang 时用 WSL 日志"""
    port = ENDPOINT.rsplit(":", 1)[-1]
    if port == "8080":
        return WSL_SGLANG_LOG
    return SERVER_LOG

NGEN_RE = re.compile(r"task (\d+) \|\s+n_gen =\s+(\d+), tg =\s+([\d.]+) t/s, tg_3s =\s+([\d.]+)")
REQ_RE  = re.compile(r"task (\d+) \|\s+prompt eval time =\s+[\d.]+ ms /\s+(\d+) tokens")
GEN_RE  = re.compile(r"task (\d+) \|\s+eval time =\s+[\d.]+ ms /\s+(\d+) tokens \(\s+[\d.]+ ms per token,\s+([\d.]+) tokens per second\)")
ACC_RE  = re.compile(r"task (\d+) \|\s+draft acceptance = ([\d.]+)")
TOT_RE  = re.compile(r"task (\d+) \|\s+total time =\s+([\d.]+) ms")
STOP_RE = re.compile(r"release: id\s+\d+ \|\s+task (\d+) \|\s+stop processing: n_tokens = (\d+)")
ERR_RE  = re.compile(r"got exception: (.{0,100})")

# ---- SGLang 日志格式（与 llama.cpp 完全不同）----
SG_DECODE  = re.compile(r"Decode batch,.*?#running-req:\s*(\d+),.*?#full token:\s*(\d+),.*?accept len:\s*([\d.]+), accept rate:\s*([\d.]+).*?gen throughput \(token/s\):\s*([\d.]+)")
SG_PREFILL = re.compile(r"Prefill batch,.*?#new-token:\s*(\d+),.*?#running-req:\s*(\d+)")
SG_PREFILL_TPS = re.compile(r"input throughput \(token/s\):\s*([\d.]+)")
SG_KV      = re.compile(r"KV Cache is allocated.*?#tokens:\s*(\d+)")
SG_TS      = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")
SG_ERR     = re.compile(r"ERROR|Traceback|CUDA out of memory")

SGLANG_PORTS = {"8092"}

# 端口存活缓存：{name: (alive, ts)}。连续 2 次失败的端口 60s 内跳过探测（死端口延迟拒绝 ~2s 拖慢 collect）
_port_cache = {}
# 端口连续失败计数：只有连续失败才写入离线缓存（防单次抖动误判）
_port_fail = {}

def is_sglang(model_info=None):
    """8092 tee 直连 SGLang；8080 网关在其后端是 SGLang 时也按 SGLang 解析
    （网关 /health 同样返回 200 空 body、无 /slots，走 llama.cpp 路径必误判掉线）"""
    port = ENDPOINT.rsplit(":", 1)[-1]
    if port in SGLANG_PORTS:
        return True
    if port == "8080":
        m = model_info if model_info is not None else get_json("/v1/models")
        if not m:
            return False
        first = (m.get("data") or [{}])[0]
        # SGLang 返回 owned_by=sglang；llama.cpp 引擎名不同
        return str(first.get("owned_by", "")).lower() == "sglang"
    return False

def log_tail_path(path, n=400):
    try:
        with open(path, "r", errors="replace") as f:
            return f.readlines()[-n:]
    except OSError:
        return []

def sglang_stats():
    """解析 SGLang 日志：运行中请求数 / 上下文占用 / 接受率 / 速度 / KV 池
    注意：收尾行会出现 #full token: 0 / gen throughput: 0.2x 的空转值，
    必须【只采信有实际 token 的行】，否则监控全是 0 和负号。"""
    lines = log_tail_path(sg_log_path(), 2000)
    out = {"running": 0, "used": 0, "ctx": 0, "acc_len": None, "acc_rate": None,
           "tps": None, "queue": 0, "last_ts": None, "err": "",
           "prefill_tps": None, "new_token": None, "last_active_ts": None}
    # KV 池行只在服务启动时打印一次，早已滚出尾部 2000 行 → 单独扫日志头部
    if not out["ctx"]:
        try:
            with open(sg_log_path(), "r", errors="replace") as f:
                head = f.readlines()[:4000]
            for l in head:
                m = SG_KV.search(l)
                if m:
                    out["ctx"] = int(m.group(1))
        except OSError:
            pass
    for l in lines:
        m = SG_KV.search(l)
        if m:
            out["ctx"] = int(m.group(1))
    # 跳过启动期无害报错
    for l in reversed(lines):
        if SG_ERR.search(l):
            if any(s in l for s in ("torchcodec", "libavutil", "libtorchcodec")):
                continue
            out["err"] = l.strip()[:120]
            break
    # ---- 阶段判定（prefill / decode / idle）----
    # 取【最后一条 batch 行】。关键：SGLang 预填充时 #running-req 仍为 0
    # （请求尚未进入 decode running 集合），只看 #running-req 会导致
    # 预填充永远显示"空闲"（2026-09-25 用户报障）。正确信号：
    #   · Decode batch  + #running-req > 0        → 解码中
    #   · Prefill batch + #pending-token > 0      → 预填充中（长 prompt 分块预填）
    #   · Prefill batch + #new-token > 1          → 预填充中（单批大 token）
    #   · Prefill batch + #new-token = 1 & pending 0 → 空闲心跳（SGLang 每 3s 打印）
    # 另加时间新鲜度：最后一条 batch 行超过 15s 前 → 视作空闲。
    last_batch = None
    for l in reversed(lines):
        if SG_TS.match(l) and ("Decode batch" in l or "Prefill batch" in l):
            last_batch = l
            break
    phase, batch_running, pending_tok = "idle", 0, 0
    if last_batch:
        ts_b = SG_TS.match(last_batch).group(1)
        out["last_ts"] = ts_b
        is_decode = "Decode batch" in last_batch
        mr = re.search(r"#running-req:\s*(\d+)", last_batch)
        batch_running = int(mr.group(1)) if mr else 0
        mp = re.search(r"#pending-token:\s*(\d+)", last_batch)
        pending_tok = int(mp.group(1)) if mp else 0
        mn = re.search(r"#new-token:\s*(\d+)", last_batch)
        new_tok = int(mn.group(1)) if mn else 0
        try:
            t_b = datetime.datetime.strptime(ts_b, "%Y-%m-%d %H:%M:%S")
            fresh = (datetime.datetime.now() - t_b).total_seconds() <= 15
        except ValueError:
            fresh = False
        if fresh:
            if is_decode and batch_running > 0:
                phase = "decode"
            elif (not is_decode) and (pending_tok > 0 or new_tok > 1):
                phase = "prefill"
    out["phase"] = phase
    out["pending_tok"] = pending_tok
    # 预填充时 #running-req 恒为 0（请求还没进 decode 集合），但"有活跃请求"
    # 这一点必须体现在 running 上——否则槽位/活跃请求数显示为空。
    out["running"] = 0 if phase == "idle" else max(batch_running, 1)
    # ---- 最近的 decode：只认有实际生成量的行（供速度显示）----
    best_tps = None
    for l in reversed(lines):
        m = SG_DECODE.search(l)
        if not m:
            continue
        running, used, alen, arate, tps = (int(m.group(1)), int(m.group(2)),
                                           float(m.group(3)), float(m.group(4)), float(m.group(5)))
        mt = SG_TS.match(l)
        ts = mt.group(1) if mt else None
        # 有效生成行：有 token 且速度像样（>1 t/s）
        if used > 0 and tps > 1.0:
            out["used"] = used
            out["acc_len"] = alen
            out["acc_rate"] = arate
            out["tps"] = tps
            out["last_active_ts"] = ts
            break
        if best_tps is None and tps > 1.0:
            best_tps = tps
    # 没有有效 decode 时，退回最近一次 prefill 的输入吞吐
    for l in reversed(lines):
        m = SG_PREFILL.search(l)
    # 最近一次有实际量的 prefill 块（末块常是 new-token 很小的收尾，
    # 其 tps 分母是块时延会被算成畸高，须跳过；再设上限挡掉同秒多行的残余值）
    for l in reversed(lines):
        m = SG_PREFILL.search(l)
        if not m:
            continue
        nt = int(m.group(1))
        if nt <= 1:
            continue
        m2 = SG_PREFILL_TPS.search(l)
        if m2:
            tps = float(m2.group(1))
            # 预填充合理区间：< 20000 tok/s（本机实测 300~1200，>2 万必是空转/收尾行）
            if 1.0 < tps < 20000:
                out["prefill_tps"] = tps
        out["new_token"] = nt
        break
    # 预填充阶段的 KV 显示：把本次请求各 prefill 块的 new-token 累加为已处理量，
    # 加上 #pending-token（剩余）即该 prompt 总长。
    # 从后往前扫，累计所有 prefill 块；遇到空闲心跳行（new≤1 且 pending=0）
    # 或 Decode 行（上一请求的边界）才停——不能见 pending=0 就停，
    # 那只是最后一块（会少算前面所有块）。
    if out.get("phase") == "prefill":
        acc = 0
        for l in reversed(lines):
            if "Decode batch" in l:
                break                 # 越过上一请求的解码行 = 请求边界
            mm = re.search(r"Prefill batch.*?#new-token:\s*(\d+).*?#pending-token:\s*(\d+)", l)
            if not mm:
                continue
            nt, pend = int(mm.group(1)), int(mm.group(2))
            if nt <= 1 and pend == 0:
                break                 # 空闲心跳行 = 本次请求起点
            acc += nt
        out["prefill_acc"] = acc
        total = acc + out.get("pending_tok", 0)
        if total > 0:
            out["used"] = total
    if out["last_ts"] is None:
        out["err"] = ""
    return out

def recent_requests_sglang(n=50):
    """SGLang /health 探针每 3s 一条涌进 usage 文件，尾 50 行全是 health，
    —— 导致 n=50 条全是探测行、被全跳过 → 请求表"基本空"。
    修法：反向扫文件，凑够 n 条真实推理再停（上限 3000 行防 OOM）。"""
    port = ENDPOINT.rsplit(":", 1)[-1]
    usage_file = r"E:\LM\tee-usage-8080.jsonl" if port == "8080" else r"E:\LM\sglang-usage.jsonl"
    rows = []
    try:
        with open(usage_file, encoding="utf-8") as f:
            lines = f.readlines()
        # 反向扫，只收 chat/messages 行，凑够 n 条
        for l in reversed(lines):
            if len(rows) >= n:
                break
            l = l.strip()
            if not l:
                continue
            if "chat/completions" not in l and "/messages" not in l:
                continue
            try:
                rows.insert(0, json.loads(l))   # 保持时间正序
            except Exception:
                continue
    except OSError:
        pass

    out = []
    for u in rows:   # 已是正序，无需 reversed
        el = u.get("elapsed") or (u.get("ms") / 1000 if u.get("ms") else None)
        out.append({
            "id": u.get("ts") or "-",
            "code": str(u.get("code") or ""),
            "pt": u.get("prompt_tokens"),
            "ct": u.get("completion_tokens"),
            "tps": u.get("tps"),
            "acc": None,
            "total": (u.get("prompt_tokens") or 0) + (u.get("completion_tokens") or 0) or None,
            "ms": int(el * 1000) if el else None,
        })
    # 最近一条补上 decode 接受率
    stats = sglang_stats()
    if out and stats.get("acc_rate") is not None:
        out[0]["acc"] = stats["acc_rate"]
    return out[:n]


def log_tail(n=400):
    try:
        with open(SERVER_LOG, "r", errors="replace") as f:
            return f.readlines()[-n:]
    except OSError:
        return []

def last_speed():
    """日志里最近一条 n_gen 的瞬时速度（跨任务）"""
    for l in reversed(log_tail(80)):
        m = NGEN_RE.search(l)
        if m:
            return float(m.group(4))
    return None

def live_gen(task_id):
    for l in reversed(log_tail(30)):
        m = NGEN_RE.search(l)
        if m and m.group(1) == str(task_id):
            return int(m.group(2)), float(m.group(3)), float(m.group(4))
    return None

def recent_requests(n=50):
    reqs, order = {}, []
    for l in log_tail(600):
        m = REQ_RE.search(l)
        if m and m.group(1) not in reqs:
            reqs[m.group(1)] = {"pt": int(m.group(2))}; order.append(m.group(1))
        m = GEN_RE.search(l)
        if m:
            r = reqs.setdefault(m.group(1), {})
            r["ct"] = int(m.group(2)); r["tps"] = float(m.group(3))
        m = ACC_RE.search(l)
        if m:
            reqs.setdefault(m.group(1), {})["acc"] = float(m.group(2))
        m = TOT_RE.search(l)
        if m:
            reqs.setdefault(m.group(1), {})["ms"] = int(float(m.group(2)))
        m = STOP_RE.search(l)
        if m:
            reqs.setdefault(m.group(1), {})["total"] = int(m.group(2))
    out = []
    for t in reversed(order[-n:]):
        r = reqs.get(t, {})
        r.setdefault("pt", None); r.setdefault("ct", None); r["id"] = t
        out.append(r)
    return out

def last_error():
    for l in reversed(log_tail(120)):
        m = ERR_RE.search(l)
        if m:
            return m.group(1)
    return ""

def server_running():
    return EXE.lower() in run_cmd(["tasklist", "/FI", f"IMAGENAME eq {EXE}"]).lower()

def vram():
    out = run_cmd(["nvidia-smi", "--query-gpu=index,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw",
                   "--format=csv,noheader,nounits"])
    gpus = []
    for l in out.strip().splitlines():
        f = [x.strip() for x in l.split(",")]
        if len(f) == 6:
            gpus.append({"i": f[0], "used": int(f[1]), "tot": int(f[2]), "util": f[3], "temp": f[4], "pw": f[5]})
    return gpus

def death_stats():
    n_down = n_restart = 0
    last_verdict, last_time = "-", "-"
    try:
        with open(EVENTS_LOG, encoding="utf-8") as f:
            for l in f:
                if "CRASH (WER)" in l or "SILENT EXIT" in l:
                    n_down += 1
                    head = l.split("] ", 1)
                    last_time = head[0].lstrip("[")
                    last_verdict = (head[1].splitlines()[0] if len(head) > 1 else "?")
                elif "auto-restart triggered" in l:
                    n_restart += 1
    except OSError:
        pass
    return n_down, n_restart, last_verdict, last_time

def uptime():
    import ctypes, ctypes.wintypes as wt
    k32 = ctypes.windll.kernel32
    csv = run_cmd(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/FO", "CSV", "/NH"])
    for line in csv.splitlines():
        f = [x.strip().strip('"') for x in line.split('","')]
        if not f or not f[0].lower().startswith(EXE.lower()):
            continue
        try:
            pid = int(f[1])
        except (IndexError, ValueError):
            continue
        h = k32.OpenProcess(0x0400, False, pid)
        if not h:
            continue
        try:
            ct, et, kt, ut = wt.FILETIME(), wt.FILETIME(), wt.FILETIME(), wt.FILETIME()
            if k32.GetProcessTimes(h, ctypes.byref(ct), ctypes.byref(et), ctypes.byref(kt), ctypes.byref(ut)):
                EPOCH = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)
                t0 = EPOCH + datetime.timedelta(microseconds=(ct.dwHighDateTime << 32 | ct.dwLowDateTime) / 10)
                return (datetime.datetime.now(datetime.timezone.utc) - t0).total_seconds()
        finally:
            k32.CloseHandle(h)
    return None

def restart_server():
    try:
        mode = open(MODE_FILE, encoding="utf-8").read().strip()
    except OSError:
        mode = "think"
    arg = ["nothink"] if mode == "nothink" else []
    subprocess.Popen(["pythonw", r"E:\working\llama-cpp\llama\server-headless.pyw"] + arg,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)

def restart_proxy():
    subprocess.Popen(["pythonw", r"E:\working\llama-cpp\llama\model-tee.py"],
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)

def uptime_sglang():
    """SGLang 在 WSL 里，用日志首个带时间戳的行估算存活时长（8080 网关须读 WSL 日志）
    注意：日志首行可能是 Python warning，不带时间戳，须往后扫。"""
    try:
        with open(sg_log_path(), encoding="utf-8", errors="replace") as f:
            for _ in range(200):
                l = f.readline()
                if not l:
                    break
                m = SG_TS.match(l)
                if m:
                    t0 = datetime.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                    return max(0, (datetime.datetime.now() - t0).total_seconds())
    except OSError:
        pass
    return None

def health_ok(url=None):
    """只看 HTTP 状态码：SGLang 的 /health 返回 200 但 body 为空，不能用 get_json"""
    try:
        with urllib.request.urlopen((url or ENDPOINT) + "/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False

def collect():
    d = {}
    # 全端口普查（并发 + 离线缓存）放最前：串行时死端口各等 ~2s，5 个端口要 8s ≫ 1s 刷新
    import concurrent.futures as _cf

    def probe_one(item):
        name, (url, log, role) = item
        ok, mid = False, ""
        try:
            # 超时须 ≥ SGLang /health 的固有延迟（实测 ~1.0s），否则活端口被误判离线
            with urllib.request.urlopen(url + "/health", timeout=2.5) as r:
                ok = (r.status == 200)
        except Exception:
            ok = False
        if ok:
            try:
                with urllib.request.urlopen(url + "/v1/models", timeout=2.5) as r:
                    mm = json.load(r)
                    ids = [os.path.basename(m.get("id") or m.get("name") or "") for m in (mm.get("data") or [])]
                    ids = [i for i in ids if i]
                    mid = ", ".join(dict.fromkeys(ids)) if ids else ""
            except Exception:
                pass
        return {"name": name, "alive": ok, "model": mid, "role": role}

    # 离线端口缓存：死端口连接被延迟拒绝（Windows ~2s），每轮都探会把 collect 拖到 4s。
    # 活端口每轮照探；仅【连续 2 次失败】才缓存为离线 60s（单次超时多是瞬时抖动，
    # 若一次失败就锁 60s，会把活端口误标离线整整一分钟）。
    now = time.time()

    def probe_cached(item):
        name, (url, log, role) = item
        last = _port_cache.get(name)
        if last is not None and last[0] is False and now - last[1] < 60:
            return {"name": name, "alive": False, "model": "", "role": role, "_cached": True}
        r = probe_one(item)
        if r["alive"]:
            _port_cache[name] = (True, now)
            _port_fail[name] = 0
        else:
            # 失败计数：连续 2 次才写离线缓存
            prev_fail = _port_fail.get(name, 0) + 1
            _port_fail[name] = prev_fail
            if prev_fail >= 2:
                _port_cache[name] = (False, now)
        return r

    ports_stat = []
    try:
        with _cf.ThreadPoolExecutor(max_workers=len(PORTS)) as ex:
            for r in ex.map(probe_cached, PORTS.items()):
                ports_stat.append(r)
    except Exception:
        ports_stat = [{"name": n, "alive": False, "model": "", "role": v[2]} for n, v in PORTS.items()]
    d["ports_stat"] = ports_stat
    # 当前端点健康 = 普查结果里该端口那一行（避免再单独探一次 health，重复耗时 ~1s）
    cur_alive = next((p["alive"] for p in ports_stat if PORTS.get(p["name"], (None,))[0] == ENDPOINT), None)

    m = get_json("/v1/models")
    sg = is_sglang(m)
    d["is_sglang"] = sg
    d["model"] = os.path.basename(m["data"][0]["id"]) if m and m.get("data") else "?"
    d["gpus"] = vram()
    if sg:
        # SGLang 路径：无 /slots，改从日志解析
        st = sglang_stats()
        d["health"] = bool(cur_alive) if cur_alive is not None else health_ok()
        d["running"] = bool(d["health"]) or st["running"] > 0
        d["reqs"] = recent_requests_sglang(50)
        # 只报"启动完成后"的错误（启动期 torchcodec 无害报错不算）
        d["err"] = "" if st.get("last_ts") else st["err"]
        d["slots"] = [{"is_processing": st["running"] > 0,
                       "n_prompt_tokens": st["used"],
                       "n_ctx": st["ctx"] or 262144,
                       "id_task": None,
                       "_sg": st}]
    else:
        d["running"] = server_running()
        d["health"] = get_json("/health")
        d["slots"] = get_json("/slots") or []
        d["reqs"] = recent_requests(50)
        d["err"] = last_error()
    d["deaths"] = death_stats()
    d["up"] = uptime_sglang() if sg else uptime()
    try:
        d["mode"] = open(MODE_FILE, encoding="utf-8").read().strip()
    except OSError:
        d["mode"] = "think"
    return d

def fmt_k(n):
    if n is None or n == "-":
        return "-"
    n = int(n)
    return f"{n/1000:.1f}K" if n >= 1000 else str(n)

def fmt_gb(mib):
    """显存 MiB → GB（nvidia-smi 返回 MiB）"""
    try:
        return f"{int(mib)/1024:.1f}G"
    except (TypeError, ValueError):
        return "-"

def kpi_tile(caption):
    """大数字 KPI 瓷砖：标题在上（小灰字），数值在下（大字）"""
    f = QFrame(); f.setProperty("class", "tile")
    f.setAttribute(Qt.WA_StyledBackground, True)
    v = QVBoxLayout(f); v.setContentsMargins(12, 8, 12, 8); v.setSpacing(2)
    cap = QLabel(caption); cap.setProperty("class", "cap"); cap.setAlignment(Qt.AlignHCenter)
    val = QLabel("-"); val.setProperty("class", "kpi"); val.setAlignment(Qt.AlignHCenter)
    v.addWidget(cap); v.addWidget(val)
    return f, val

def bar_row(title):
    """带标题的进度条行"""
    w = QWidget()
    v = QVBoxLayout(w); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(3)
    lab = QLabel(title); lab.setProperty("class", "cap")
    bar = QProgressBar(); bar.setTextVisible(False)
    v.addWidget(lab); v.addWidget(bar)
    return w, lab, bar

def vram_row(title):
    """带标题 + 右侧数值的进度条行（显存条：标题含温度，右侧显示 已用/总量 与百分比）"""
    w = QWidget()
    v = QVBoxLayout(w); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(3)
    hr = QHBoxLayout(); hr.setContentsMargins(0, 0, 0, 0)
    lab = QLabel(title); lab.setProperty("class", "cap")
    val = QLabel(""); val.setProperty("class", "dim")
    hr.addWidget(lab); hr.addStretch(1); hr.addWidget(val)
    bar = QProgressBar(); bar.setTextVisible(False)
    v.addLayout(hr); v.addWidget(bar)
    return w, lab, val, bar

class Win(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("llama 监控")
        self.resize(860, 600)
        self.setMinimumSize(560, 420)
        self.data = {}
        self.was_running = None
        self.was_proxy = None
        self.build()
        self.load_geometry()
        t = QTimer(self); t.timeout.connect(self.refresh); t.start(1000)
        tf = QTimer(self); tf.timeout.connect(self.fast_live); tf.start(200)
        self._init_dragcopy()
        threading.Thread(target=self.looper, daemon=True).start()

    # ---------- UI ----------
    def build(self):
        root = QWidget(); root.setObjectName("root"); self.setCentralWidget(root)
        col = QVBoxLayout(root); col.setContentsMargins(12, 12, 12, 12); col.setSpacing(10)

        # 头部：模型名（大） | 状态胶囊 · 思考 · 时钟
        head = QHBoxLayout(); head.setSpacing(10)
        self.lb_model = QLabel("…"); self.lb_model.setProperty("class", "big")
        head.addWidget(self.lb_model); head.addStretch(1)
        self.lb_think = QLabel("思考 关"); self.lb_think.setProperty("class", "dim")
        self.lb_health = QLabel("服务正常"); self.lb_health.setProperty("class", "pill_ok")
        self.lb_clock = QLabel(); self.lb_clock.setProperty("class", "dim")
        self.lb_clock = QLabel(); self.lb_clock.setProperty("class", "dim")
        head.addWidget(self.lb_think); head.addWidget(self.lb_health); head.addWidget(self.lb_clock)
        col.addLayout(head)

        # 监控目标列表（仿 model-gateway：端口+模型+状态，点击切换；在线排最上）
        tgt, tv = self._card()
        cap = QLabel("监控目标（点击切换，在线优先排序）"); cap.setProperty("class", "cap"); tv.addWidget(cap)
        self.tbl_ports = QTableWidget(0, 4)
        self.tbl_ports.setHorizontalHeaderLabels(["端口", "属性", "模型", "状态"])
        self.tbl_ports.verticalHeader().setVisible(False)
        self.tbl_ports.verticalHeader().setDefaultSectionSize(22)
        self.tbl_ports.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl_ports.setSelectionBehavior(QTableWidget.SelectRows)
        ph = self.tbl_ports.horizontalHeader(); ph.setSectionResizeMode(QHeaderView.Stretch)
        ph.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        ph.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        # 固定三行高：在线的排最上所以前三行就是重点，其余靠滚动条
        self.tbl_ports.setFixedHeight(3 * 22 + 32)
        self.tbl_ports.cellClicked.connect(self._pick_port)
        tv.addWidget(self.tbl_ports)
        col.addWidget(tgt)

        # KPI 瓷砖行（6 块）
        kpis = QHBoxLayout(); kpis.setSpacing(8)
        self.t_up,  self.v_up  = kpi_tile("存活时间")
        self.t_ctx, self.v_ctx = kpi_tile("上下文占用")
        self.t_spd, self.v_spd = kpi_tile("生成速度")
        self.t_dft, self.v_dft = kpi_tile("DRAFT 命中")
        self.t_g0,  self.v_g0  = kpi_tile("GPU 0")
        self.t_g1,  self.v_g1  = kpi_tile("GPU 1")
        for t in (self.t_up, self.t_ctx, self.t_spd, self.t_dft, self.t_g0, self.t_g1):
            kpis.addWidget(t, stretch=1)
        col.addLayout(kpis)

        # 上下文 + 实时生成 合并卡：左窄条=两条进度条，右宽区=实时输出（整体高度给足）
        merged, mv = self._card()
        h = QHBoxLayout()
        left = QVBoxLayout()
        self.ctx_row,  self.ctx_lab,  self.bar_ctx  = bar_row("上下文")
        self.phase_row, self.phase_lab, self.bar_phase = bar_row("阶段（预填充 / 解码）")
        left.addWidget(self.ctx_row); left.addWidget(self.phase_row)
        # 两条显存条（GPU0/GPU1）：标题含温度，右侧显示 已用/总量 (百分比)
        self.vm0_row, self.vm0_lab, self.vm0_val, self.bar_vm0 = vram_row("GPU 0 显存")
        self.vm1_row, self.vm1_lab, self.vm1_val, self.bar_vm1 = vram_row("GPU 1 显存")
        left.addSpacing(6)
        left.addWidget(self.vm0_row); left.addWidget(self.vm1_row)
        left.addStretch(1)
        left_w = QWidget(); left_w.setLayout(left); left_w.setFixedWidth(230)
        right = QVBoxLayout()
        hr = QHBoxLayout()
        cap = QLabel("实时生成 · 含工具调用与代码"); cap.setProperty("class", "cap")
        self.lb_phase_inline = QLabel(""); self.lb_phase_inline.setProperty("class", "dim")
        hr.addWidget(cap); hr.addStretch(1); hr.addWidget(self.lb_phase_inline)
        right.addLayout(hr)
        self.txt_live = QTextEdit(); self.txt_live.setReadOnly(True)
        self.txt_live.setMinimumHeight(200)   # 保底高度，缩小三行给请求表让位
        right.addWidget(self.txt_live)
        h.addWidget(left_w); h.addLayout(right, 1)
        mv.addLayout(h)
        col.addWidget(merged, 3)

        # 请求表
        tbl, tbv = self._card()
        cap = QLabel("最近请求"); cap.setProperty("class", "cap"); tbv.addWidget(cap)
        self.table = QTableWidget(0, 8)
        self.table.setAlternatingRowColors(True)
        self.table.setHorizontalHeaderLabels(["task", "输入tok", "生成tok", "tok/s", "draft", "会话总量", "耗时", "状态"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(19)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        hh = self.table.horizontalHeader(); hh.setSectionResizeMode(QHeaderView.Stretch)
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        tbv.addWidget(self.table)
        self.table.setMinimumHeight(4 * 19 + 30)   # 至少完整显示四行 + 表头
        col.addWidget(tbl, stretch=1)

        # 底部：狗状态条（胶囊 + 结构化小项）
        dogcard, dv = self._card()
        dh = QHBoxLayout(); dh.setSpacing(14)
        self.chk_revive = QCheckBox("复活狗（勾选才自动拉活）")
        self.chk_revive.setChecked(False)
        dh.addWidget(self.chk_revive)
        self.lb_dog = QLabel("看门狗"); self.lb_dog.setProperty("class", "dog")
        dh.addWidget(self.lb_dog)
        def stat(cap):
            pair = QLabel(f"{cap} -")
            pair.setProperty("class", "stat")
            dh.addWidget(pair)
            return pair
        self.st_alive = stat("存活")
        self.st_reld  = stat("重载")
        self.st_dead  = stat("死亡")
        self.st_cause = stat("死因")
        self.st_speed = stat("均速")
        dh.addStretch(1)
        dv.addLayout(dh)
        col.addWidget(dogcard)
        self.lb_toast = QLabel(""); self.lb_toast.setProperty("class", "toast")
        col.addWidget(self.lb_toast)

    def _card(self):
        f = QFrame(); f.setProperty("class", "card")
        f.setAttribute(Qt.WA_StyledBackground, True)
        v = QVBoxLayout(f); v.setContentsMargins(12, 8, 12, 10); v.setSpacing(6)
        return f, v

    # ---------- BAT 式拖框复制（全窗口任意角落，空白处也可） ----------
    def _init_dragcopy(self):
        QApplication.instance().installEventFilter(self)
        self._sel_origin = None      # centralWidget 坐标
        self._sel_global = None      # 全局坐标
        self._rb = QRubberBand(QRubberBand.Rectangle, self.centralWidget())

    def _interactive(self, w):
        """真交互控件不抢：表格/文本区/按钮/滚动条"""
        while w is not None and w is not self:
            if isinstance(w, (QTableWidget, QTextEdit, QPushButton)):
                return True
            w = w.parentWidget()
        return False

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        t = ev.type()
        if t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
            gp = ev.globalPosition().toPoint()
            w = QApplication.widgetAt(gp)
            if w is not None and self.isAncestorOf(w) and not self._interactive(w):
                root = self.centralWidget()
                self._sel_global = gp
                self._sel_origin = root.mapFromGlobal(gp)
                self._rb.setGeometry(QRect(self._sel_origin, QSize(0, 0)))
                self._rb.show()
        elif t == QEvent.MouseMove and self._sel_global is not None:
            root = self.centralWidget()
            p = root.mapFromGlobal(ev.globalPosition().toPoint())
            x, y = min(self._sel_origin.x(), p.x()), min(self._sel_origin.y(), p.y())
            self._rb.setGeometry(QRect(x, y, abs(p.x() - self._sel_origin.x()), abs(p.y() - self._sel_origin.y())))
        elif t == QEvent.MouseButtonRelease and self._sel_global is not None:
            g = self._rb.geometry()
            self._rb.hide()
            self._sel_global = None
            if g.width() > 6 and g.height() > 6:
                self._copy_selected_text(g)
        return super().eventFilter(obj, ev)

    def _toast(self, msg):
        """底部复制提示，3 秒后自动消失"""
        self.lb_toast.setText(msg)
        QTimer.singleShot(3000, lambda: self.lb_toast.setText(""))

    def _copy_selected_text(self, sel):
        """收集与选区相交的所有 QLabel 文本（从上到下、从左到右），复制进剪贴板"""
        root = self.centralWidget()
        items = []
        for lab in root.findChildren(QLabel):
            if not lab.text().strip():
                continue
            lg = QRect(lab.mapTo(root, lab.rect().topLeft()), lab.size())
            if lg.intersects(sel):
                items.append((lg.y(), lg.x(), lab.text().strip()))
        items.sort()
        text = "\n".join(t for _, _, t in items)
        if text:
            QGuiApplication.clipboard().setText(text)
            self._toast(f"✓ 框选内容已复制（{len(items)} 项文字，Ctrl+V 粘贴）")

    def _pick_port(self, row, col):
        """点击端口表切换监控目标（行数据带端口名）"""
        it = self.tbl_ports.item(row, 0)
        if it is None:
            return
        name = it.data(Qt.UserRole)
        if name and name in PORTS:
            self.on_port_changed(name)
            self._toast(f"→ 已切换监控目标：{name}")

    def _cur_port_row(self):
        for r in range(self.tbl_ports.rowCount()):
            it = self.tbl_ports.item(r, 0)
            if it and PORTS.get(it.data(Qt.UserRole), (None,))[0] == ENDPOINT:
                return r
        return -1

    def on_port_changed(self, text):
        global ENDPOINT, SERVER_LOG
        ENDPOINT, SERVER_LOG, _role = PORTS[text]
        # 保留旧数据直到下轮 collect() 返回新端口数据（清空会导致 UI 闪烁/全空）
        try:
            self.txt_live.setPlainText("")
        except Exception:
            pass

    # ---------- 持久化 ----------
    def load_geometry(self):
        try:
            cfg = json.load(open(CFG_FILE, encoding="utf-8"))
            g = cfg.get("geometry")
            if g and len(g) == 4:
                x, y, w, h = g
                self.setGeometry(x, y, max(w, 460), max(h, 360))
        except Exception:
            pass
        self._save_timer = QTimer(self, singleShot=True, interval=500)
        self._save_timer.timeout.connect(self.save_geometry)
        # QSS 热重载：监听样式文件，改动即时应用，窗口不关不动
        self._qss_mtime = 0
        tq = QTimer(self, interval=1000)
        tq.timeout.connect(self.hot_reload_qss)
        tq.start()

    def hot_reload_qss(self):
        try:
            mt = os.path.getmtime(QSS_FILE)
        except OSError:
            return
        if mt != self._qss_mtime:
            self._qss_mtime = mt
            QApplication.instance().setStyleSheet(load_qss())

    def save_geometry(self):
        try:
            g = self.geometry()
            json.dump({"geometry": [g.x(), g.y(), g.width(), g.height()]},
                      open(CFG_FILE, "w", encoding="utf-8"))
        except Exception:
            pass

    def moveEvent(self, ev):
        self._save_timer.start(); super().moveEvent(ev)

    def resizeEvent(self, ev):
        self._save_timer.start(); super().resizeEvent(ev)

    def closeEvent(self, ev):
        self.save_geometry(); super().closeEvent(ev)

    # ---------- 数据 ----------
    def looper(self):
        while True:
            try:
                d = collect()
                revive = self.chk_revive.isChecked() if hasattr(self, "chk_revive") else False
                # SGLang(WSL) 不归复活狗管：它是 WSL 进程，Windows 侧重启脚本不适用
                main_link = (not d.get("is_sglang")) and (ENDPOINT.endswith(":8080") or ENDPOINT.endswith(":8082"))
                proxy_ok = bool(d["health"])
                if revive and main_link:
                    if self.was_running is True and d["running"] is False:
                        restart_server()
                        self._log_evt("GUI auto-restart triggered (revive ON)")
                    if self.was_proxy is True and not proxy_ok and d["running"] and ENDPOINT.endswith(":8080"):
                        restart_proxy()
                        self._log_evt("GUI proxy-restart triggered (revive ON)")
                self.was_proxy = proxy_ok
                self.was_running = d["running"]
                self.data = d
            except Exception as e:
                import traceback
                try:
                    with open(r"E:\LM\gui-errors.log", "a", encoding="utf-8") as f:
                        f.write(traceback.format_exc() + "\n")
                except Exception:
                    pass
            time.sleep(1)

    def _log_evt(self, msg):
        try:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(EVENTS_LOG, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")
        except OSError:
            pass

    def _live_file(self):
        """按当前端口选 live 文件。

        坑（2026-09-25 用户发现）：8080 网关与 8092 tee 是两个独立代理，各写各的
        live 文件，但都指向同一后端 8082——于是点 8080 和 8092 看到的实时内容不同
        （各自只记录经过自己的请求，另一个文件的旧内容显得"反直觉"）。
        修法：同一后端的端口共享实时视图，取其中最新的那个文件。"""
        port = ENDPOINT.rsplit(":", 1)[-1]
        # 同后端代理组：8080 网关与 8092 tee 都转发到 8082，实时视图应一致
        group = {"8080": ["8080", "8092"], "8092": ["8080", "8092"]}.get(port, [port])
        best, best_mt = None, -1
        for p in group:
            f = rf"E:\LM\live-{p}.txt"
            try:
                mt = os.path.getmtime(f)
            except OSError:
                continue
            if mt > best_mt:
                best, best_mt = f, mt
        return best or rf"E:\LM\live-{port}.txt"

    def fast_live(self):
        try:
            txt = open(self._live_file(), encoding="utf-8").read()
        except OSError:
            return
        txt = txt.replace("\\n", "\n").replace("\\t", "  ")
        lines = [l for l in txt.rstrip().splitlines() if l.strip()]
        cur = "\n".join(lines[-6:])
        if cur and cur != self.txt_live.toPlainText():
            self.txt_live.setPlainText(cur)
            sb = self.txt_live.verticalScrollBar(); sb.setValue(sb.maximum())

    # ---------- 渲染 ----------
    def _autoswitch(self, ports_stat):
        """所选端口连续 3 轮探测失败才自动切换（防抖：单次抖动不切，避免端口来回跳）"""
        self._down_streak = getattr(self, "_down_streak", 0) + 1
        if self._down_streak < 3:
            return
        alive = [p["name"] for p in ports_stat if p["alive"] and PORTS[p["name"]][0] != ENDPOINT]
        if alive:
            target = alive[0]
            self._down_streak = 0
            self.on_port_changed(target)
            self._toast(f"↔ 目标端口连续 3 次无响应，自动切换到 {target}")

    def _reset_down_streak(self):
        self._down_streak = 0

    def refresh(self):
        d = self.data
        if not d:
            return
        if not (d.get("health")):
            self._autoswitch(d.get("ports_stat") or [])
        else:
            self._reset_down_streak()
        # 端口表整表重建：在线排最上，模型名/状态每秒写实
        stat = d.get("ports_stat") or []
        stat_sorted = sorted(stat, key=lambda p: 0 if p["alive"] else 1)
        self.tbl_ports.setRowCount(len(stat_sorted))
        for i, p in enumerate(stat_sorted):
            port_short = p["name"].split(" · ")[0]
            it0 = QTableWidgetItem(port_short)
            it0.setData(Qt.UserRole, p["name"])
            it1 = QTableWidgetItem(p.get("role") or "-")
            it2 = QTableWidgetItem(p["model"] or "-")
            it3 = QTableWidgetItem("● 在线" if p["alive"] else "○ 离线")
            it3.setForeground(Qt.green if p["alive"] else Qt.gray)
            for j, it in enumerate((it0, it1, it2, it3)):
                self.tbl_ports.setItem(i, j, it)
        cur = self._cur_port_row()
        if cur >= 0:
            self.tbl_ports.selectRow(cur)
        self.lb_clock.setText(datetime.datetime.now().strftime("%m-%d %H:%M:%S"))
        self.lb_model.setText(d["model"])
        self.lb_think.setText("思考 开" if d["mode"] == "think" else "思考 关")

        ok = d["running"] and d["health"]
        if ok:
            ht, cls = "服务正常", "pill_ok"
        elif d["running"]:
            ht, cls = "代理断·自动拉起", "pill_warn"
        else:
            ht, cls = "服务停止·自动拉起", "pill_bad"
        self.lb_health.setText(ht)
        self.lb_health.setProperty("class", cls)
        self.lb_health.style().unpolish(self.lb_health); self.lb_health.style().polish(self.lb_health)

        slots0 = d["slots"][0] if d["slots"] else {}
        sg = d.get("is_sglang")
        sgst = slots0.get("_sg") or {}
        proc = slots0.get("is_processing", False)
        used, ctx = slots0.get("n_prompt_tokens", 0), slots0.get("n_ctx", 0)
        pct = 100 * used // max(ctx, 1)

        # KPI
        up = d["up"]
        h, m = (int(up // 3600), int(up % 3600 // 60)) if up is not None else (0, 0)
        self.v_up.setText(f"{h}h{m:02d}m" if up is not None else "—")
        self.v_ctx.setText(f"{pct}%")
        if sg:
            # SGLang：直接读日志解析出的速度 / 接受率（已过滤空转行）
            if sgst.get("tps") is not None:
                # 运行中显示当前速度；空闲显示最近一次有效速度并加 · 标记
                mark = "" if proc else "·"
                self.v_spd.setText(f"{sgst['tps']:.0f}{mark}")
            elif sgst.get("prefill_tps"):
                self.v_spd.setText(f"—")  # 只有 prefill，还没进入解码
            else:
                self.v_spd.setText("—")
            self.v_dft.setText(f"{sgst['acc_len']:.2f}" if sgst.get("acc_len") is not None else "—")
            lg = None
        else:
            lg = live_gen(slots0.get("id_task")) if proc else None
            if lg:
                self.v_spd.setText(f"{lg[2]:.0f}")
            else:
                last = last_speed()
                self.v_spd.setText(f"{last:.0f}·" if last else "—")
            reqs = d["reqs"]
            acc = [r["acc"] for r in reqs if r.get("acc") is not None]
            self.v_dft.setText(f"{sum(acc)/len(acc):.2f}" if acc else "—")
        g = d["gpus"]
        if len(g) >= 2:
            self.v_g0.setText(f"{g[0]['temp']}°C")
            self.v_g1.setText(f"{g[1]['temp']}°C")
        elif len(g) == 1:
            self.v_g0.setText(f"{g[0]['temp']}°C")
        # 显存条：标题带温度，右侧 已用/总量 (百分比)，条长=占用率
        for row_i, (lab, val, bar) in enumerate(
                ((self.vm0_lab, self.vm0_val, self.bar_vm0),
                 (self.vm1_lab, self.vm1_val, self.bar_vm1))):
            if row_i < len(g):
                gp = g[row_i]
                pctv = 100 * gp["used"] // max(gp["tot"], 1)
                lab.setText(f"GPU {gp['i']} 显存 · {gp['temp']}°C")
                val.setText(f"{fmt_gb(gp['used'])} / {fmt_gb(gp['tot'])}  ({pctv}%)")
                bar.setValue(pctv)
            else:
                lab.setText(f"GPU {row_i} 显存 · —")
                val.setText("—")
                bar.setValue(0)

        # 进度条
        if sg:
            # SGLang：KV 池是 143K 级别，用百分比只会常年显示 0%，
            # 改为「活跃 token / KV 池」+ 池占用率，两个数字都真实可见
            pool_pct = 100 * used // max(ctx, 1)
            self.bar_ctx.setValue(pool_pct)
            self.ctx_lab.setText(f"KV 池  {fmt_k(used)} / {fmt_k(ctx)}   ({pool_pct}%)  活跃请求 {sgst.get('running') or 0}")
        else:
            self.bar_ctx.setValue(pct)
            self.ctx_lab.setText(f"上下文  {fmt_k(used)} / {fmt_k(ctx)}   ({pct}%)")
        if sg:
            phase = sgst.get("phase") or ("decode" if proc else "idle")
            if phase == "decode" and sgst.get("tps") is not None:
                self.bar_phase.setValue(100)
                self.phase_lab.setText(f"解码生成  {fmt_k(sgst.get('used') or 0)} tok @ {sgst['tps']:.0f} tok/s（接受率 {sgst.get('acc_rate') or 0:.2f}）")
                self.lb_phase_inline.setText(f"解码中 {fmt_k(sgst.get('used') or 0)} tok @ {sgst['tps']:.0f} t/s")
            elif phase == "prefill":
                # 预填充进度：与 llama.cpp 同款「百分比（已处理 / 总长 tok）」显示
                done = sgst.get("prefill_acc") or 0
                pend = sgst.get("pending_tok") or 0
                tot = done + pend
                p_pct = 100 * done // tot if tot > 0 else 30
                self.bar_phase.setValue(max(5, min(99, p_pct)))
                ptps = sgst.get("prefill_tps")
                tp = f" @ {ptps:.0f} tok/s" if ptps else ""
                self.phase_lab.setText(f"预填充  {p_pct}%（{fmt_k(done)} / {fmt_k(tot)} tok）{tp}")
                self.lb_phase_inline.setText(f"预填中 {p_pct}%")
            else:
                self.bar_phase.setValue(0)
                self.phase_lab.setText(f"阶段  空闲（KV 池 {fmt_k(ctx)}）")
                self.lb_phase_inline.setText("")
        elif lg:
            self.bar_phase.setValue(100)
            self.phase_lab.setText(f"解码生成  {fmt_k(lg[0])} tok @ {lg[2]:.0f} tok/s（均速 {lg[1]:.0f}）")
            self.lb_phase_inline.setText(f"解码中 {fmt_k(lg[0])} tok @ {lg[2]:.0f} t/s")
        elif proc:
            ptot = slots0.get("n_prompt_tokens", 0)
            pdone = slots0.get("n_prompt_tokens_processed", 0)
            pp = 100 * pdone // max(ptot, 1)
            self.bar_phase.setValue(pp)
            self.phase_lab.setText(f"预填充  {pp}%（{fmt_k(pdone)} / {fmt_k(ptot)} tok）")
            self.lb_phase_inline.setText(f"预填中 {pp}%")
        else:
            self.bar_phase.setValue(0)
            self.phase_lab.setText("阶段  空闲")
            self.lb_phase_inline.setText("")

        # 表
        reqs = d["reqs"]
        self.table.setRowCount(len(reqs))
        for i, r in enumerate(reqs):
            ms = r.get("ms")
            ms_s = (f"{ms/1000:.1f}s" + ("⚠" if ms >= 30000 else "")) if ms is not None else "-"
            busy = (i == 0 and proc)
            st = "▲" if busy else "✓"
            if sg:
                code = r.get("code")
                st = "▲" if code == "200" and busy else ("✓" if code == "200" else f"✗{code}")
            vals = [r["id"], fmt_k(r.get("pt")), fmt_k(r.get("ct")),
                    f"{r['tps']:.1f}" if r.get("tps") else "-",
                    f"{r['acc']:.2f}" if r.get("acc") is not None else "-",
                    fmt_k(r.get("total", "-")), ms_s, st]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                if j == len(vals) - 1:
                    it.setForeground(Qt.green if busy else Qt.darkGray)
                self.table.setItem(i, j, it)

        # 狗（一行）
        if sg:
            # SGLang 是 WSL 里的实验实例，复活狗不介入；显示 WSL 状态与 KV 池
            self.lb_dog.setText("WSL 实验狗")
            self.lb_dog.setProperty("class", "dog_watch")
            self.lb_dog.style().unpolish(self.lb_dog); self.lb_dog.style().polish(self.lb_dog)
            self.st_alive.setText(f"存活 {h}h{m:02d}m" if up is not None else "存活 —")
            self.st_reld.setText("TP=2")
            self.st_dead.setText(f"KV池 {fmt_k(ctx)}")
            self.st_cause.setText(f"接受率 {sgst.get('acc_rate') or 0:.2f} · 无自动重启")
            self.st_speed.setText(f"均速 {sgst.get('tps') or 0:.1f} t/s")
            if d["err"]:
                self.lb_toast.setText(f"⚠ {d['err'][:90]}")
            elif self.lb_toast.text().startswith("⚠"):
                self.lb_toast.setText("")
            return
        nd, nr, verdict, t = d["deaths"]
        v_short = "CRASH(WER)" if "CRASH" in verdict else ("静默退出" if "SILENT" in verdict else "无")
        if nr > 0 and up is not None and up < 3600:
            dog = "复活狗"
        elif up is not None and up >= 3600:
            dog = "幸运狗"
        else:
            dog = "看门狗"
        tps = [r["tps"] for r in reqs if r.get("tps")]
        avg_t = sum(tps)/len(tps) if tps else 0
        self.lb_dog.setText(dog)
        cls = {"幸运狗": "dog_lucky", "复活狗": "dog_revive"}.get(dog, "dog_watch")
        self.lb_dog.setProperty("class", cls)
        self.lb_dog.style().unpolish(self.lb_dog); self.lb_dog.style().polish(self.lb_dog)
        self.st_alive.setText(f"存活 {h}h{m:02d}m")
        self.st_reld.setText(f"重载 {nr}")
        self.st_dead.setText(f"死亡 {nd}")
        self.st_cause.setText(f"死因 {v_short} · {t[11:] if len(t) > 11 else t}")
        self.st_speed.setText(f"均速 {avg_t:.1f} t/s")
        if d["err"]:
            self.lb_toast.setText(f"⚠ {d['err']}")
        elif self.lb_toast.text().startswith("⚠"):
            self.lb_toast.setText("")

if __name__ == "__main__":
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("llama.monitor.gui")  # 任务栏图标独立生效
    app = QApplication(sys.argv)
    app.setStyleSheet(load_qss())
    from PySide6.QtGui import QIcon
    app.setWindowIcon(QIcon(r"E:\working\llama-cpp\llama\llama-monitor.ico"))
    w = Win(); w.show()
    sys.exit(app.exec())
