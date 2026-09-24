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
    "8080 · 主链路（代理→27B）": ("http://127.0.0.1:8080", r"E:\working\llama-cpp\llama-b11139\llama-server.log"),
    "8082 · 27B 直连":           ("http://127.0.0.1:8082", r"E:\working\llama-cpp\llama-b11139\llama-server.log"),
    "8083 · MiniCPM5-2B":        ("http://127.0.0.1:8083", r"E:\LM\small-8083.log"),
    "8084 · Spark-X2.5-4B":      ("http://127.0.0.1:8084", r"E:\LM\small-8084.log"),
    "8085 · Spark-X2.5-1.7B":    ("http://127.0.0.1:8085", r"E:\LM\small-8085.log"),
}
ENDPOINT   = PORTS["8080 · 主链路（代理→27B）"][0]
SERVER_LOG = PORTS["8080 · 主链路（代理→27B）"][1]
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

NGEN_RE = re.compile(r"task (\d+) \|\s+n_gen =\s+(\d+), tg =\s+([\d.]+) t/s, tg_3s =\s+([\d.]+)")
REQ_RE  = re.compile(r"task (\d+) \|\s+prompt eval time =\s+[\d.]+ ms /\s+(\d+) tokens")
GEN_RE  = re.compile(r"task (\d+) \|\s+eval time =\s+[\d.]+ ms /\s+(\d+) tokens \(\s+[\d.]+ ms per token,\s+([\d.]+) tokens per second\)")
ACC_RE  = re.compile(r"task (\d+) \|\s+draft acceptance = ([\d.]+)")
TOT_RE  = re.compile(r"task (\d+) \|\s+total time =\s+([\d.]+) ms")
STOP_RE = re.compile(r"release: id\s+\d+ \|\s+task (\d+) \|\s+stop processing: n_tokens = (\d+)")
ERR_RE  = re.compile(r"got exception: (.{0,100})")

def log_tail(n=400):
    try:
        with open(SERVER_LOG, "r", errors="replace") as f:
            return f.readlines()[-n:]
    except OSError:
        return []

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

def collect():
    d = {}
    d["running"] = server_running()
    d["health"] = get_json("/health")
    m = get_json("/v1/models")
    d["model"] = os.path.basename(m["data"][0]["id"]) if m and m.get("data") else "?"
    d["gpus"] = vram()
    d["slots"] = get_json("/slots") or []
    d["reqs"] = recent_requests(50)
    d["err"] = last_error()
    d["deaths"] = death_stats()
    d["up"] = uptime()
    # 全端口普查：每个端口的存活 + 模型名
    ports_stat = []
    for name, (url, log) in PORTS.items():
        ok, mid = False, ""
        try:
            with urllib.request.urlopen(url + "/health", timeout=1.5) as r:
                ok = (r.status == 200)
        except Exception:
            pass
        if ok:
            try:
                with urllib.request.urlopen(url + "/v1/models", timeout=1.5) as r:
                    mm = json.load(r)
                    mid = os.path.basename(mm["data"][0]["id"]) if mm.get("data") else ""
            except Exception:
                pass
        ports_stat.append({"name": name, "alive": ok, "model": mid})
    d["ports_stat"] = ports_stat
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
        self.tbl_ports = QTableWidget(0, 3)
        self.tbl_ports.setHorizontalHeaderLabels(["端口", "模型", "状态"])
        self.tbl_ports.verticalHeader().setVisible(False)
        self.tbl_ports.verticalHeader().setDefaultSectionSize(22)
        self.tbl_ports.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl_ports.setSelectionBehavior(QTableWidget.SelectRows)
        ph = self.tbl_ports.horizontalHeader(); ph.setSectionResizeMode(QHeaderView.Stretch)
        ph.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        ph.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        # 不锁高度：窗口够高显示五行，不够自动出滚动条
        self.tbl_ports.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
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

        # 阶段卡：两条大进度条
        phase, pv = self._card()
        self.ctx_row,  self.ctx_lab,  self.bar_ctx  = bar_row("上下文")
        self.phase_row, self.phase_lab, self.bar_phase = bar_row("阶段（预填充 / 解码）")
        for r in (self.ctx_row, self.phase_row):
            pv.addWidget(r)
        col.addWidget(phase)

        # 实时生成
        live, lv = self._card()
        h = QHBoxLayout()
        cap = QLabel("实时生成 · 含工具调用与代码"); cap.setProperty("class", "cap")
        self.lb_phase_inline = QLabel(""); self.lb_phase_inline.setProperty("class", "dim")
        h.addWidget(cap); h.addStretch(1); h.addWidget(self.lb_phase_inline)
        lv.addLayout(h)
        self.txt_live = QTextEdit(); self.txt_live.setReadOnly(True); self.txt_live.setFixedHeight(96)
        lv.addWidget(self.txt_live)
        col.addWidget(live)

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
        ENDPOINT, SERVER_LOG = PORTS[text]
        self.data = {}   # 立即重采
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
                main_link = ENDPOINT.endswith(":8080") or ENDPOINT.endswith(":8082")
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

    def fast_live(self):
        if not (ENDPOINT.endswith(":8080") or ENDPOINT.endswith(":8082")):
            return  # 直连小模型无代理，不截获内容
        try:
            txt = open(LIVE_FILE, encoding="utf-8").read()
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
        """所选端口死亡时，自动切到其他存活端口（有活口才切）"""
        alive = [p["name"] for p in ports_stat if p["alive"] and PORTS[p["name"]][0] != ENDPOINT]
        if alive:
            target = alive[0]
            self.on_port_changed(target)
            self._toast(f"↔ 目标端口已死，自动切换到 {target}")

    def refresh(self):
        d = self.data
        if not d:
            return
        if not (d.get("health")):
            self._autoswitch(d.get("ports_stat") or [])
        # 端口表整表重建：在线排最上，模型名/状态每秒写实
        stat = d.get("ports_stat") or []
        stat_sorted = sorted(stat, key=lambda p: 0 if p["alive"] else 1)
        self.tbl_ports.setRowCount(len(stat_sorted))
        for i, p in enumerate(stat_sorted):
            port_short = p["name"].split(" · ")[0]
            it0 = QTableWidgetItem(port_short)
            it0.setData(Qt.UserRole, p["name"])
            it1 = QTableWidgetItem(p["model"] or "-")
            it2 = QTableWidgetItem("● 在线" if p["alive"] else "○ 离线")
            it2.setForeground(Qt.green if p["alive"] else Qt.gray)
            for j, it in enumerate((it0, it1, it2)):
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
        proc = slots0.get("is_processing", False)
        used, ctx = slots0.get("n_prompt_tokens", 0), slots0.get("n_ctx", 0)
        pct = 100 * used // max(ctx, 1)

        # KPI
        up = d["up"]
        h, m = (int(up // 3600), int(up % 3600 // 60)) if up is not None else (0, 0)
        self.v_up.setText(f"{h}h{m:02d}m")
        self.v_ctx.setText(f"{pct}%")
        lg = live_gen(slots0.get("id_task")) if proc else None
        self.v_spd.setText(f"{lg[2]:.0f}" if lg else "—")
        reqs = d["reqs"]
        acc = [r["acc"] for r in reqs if r.get("acc") is not None]
        self.v_dft.setText(f"{sum(acc)/len(acc):.2f}" if acc else "—")
        g = d["gpus"]
        if len(g) >= 2:
            self.v_g0.setText(f"{g[0]['temp']}°C")
            self.v_g1.setText(f"{g[1]['temp']}°C")
        elif len(g) == 1:
            self.v_g0.setText(f"{g[0]['temp']}°C")

        # 进度条
        self.bar_ctx.setValue(pct)
        self.ctx_lab.setText(f"上下文  {fmt_k(used)} / {fmt_k(ctx)}   ({pct}%)")
        if lg:
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
        self.table.setRowCount(len(reqs))
        for i, r in enumerate(reqs):
            ms = r.get("ms")
            ms_s = (f"{ms/1000:.1f}s" + ("⚠" if ms >= 30000 else "")) if ms is not None else "-"
            busy = (i == 0 and proc)
            st = "▲" if busy else "✓"
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
    app = QApplication(sys.argv)
    app.setStyleSheet(load_qss())
    w = Win(); w.show()
    sys.exit(app.exec())
