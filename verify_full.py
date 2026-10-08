# -*- coding: utf-8 -*-
"""widget 清单式全量校验: 枚举所有可见组件, 验证 Strata 渲染路径逐个覆盖"""
import ast, json, urllib.request, psutil, time, re

SRC = r'D:\llama-monitor\monitor_gui.py'
src = open(SRC, encoding='utf-8').read()
fails = []
def check(n, c):
    print(('PASS ' if c else 'FAIL ') + n)
    if not c: fails.append(n)

ast.parse(src); check('语法', True)

# Strata 渲染方法体与 llama 路径体
strata_m = src[src.index('def _render_strata'):src.index('def refresh')]
llama_body = src[src.index('def refresh'):]

# ---- 可见 widget 清单: (名字, 必须出现的渲染调用) ----
WIDGETS = {
    'lb_model':    'set_txt(self.lb_model',
    'lb_think':    'set_txt(self.lb_think',
    'lb_health':   'set_txt(self.lb_health',
    'lb_clock':    'set_txt(self.lb_clock',
    'v_up':        'set_txt(self.v_up',
    'v_spd':       'set_txt(self.v_spd',
    'v_dft':       'set_txt(self.v_dft',
    'phase_lab':   'set_txt(self.phase_lab',
    'lb_phase_inline': 'set_txt(self.lb_phase_inline',
    'ctx_lab':     'set_txt(self.ctx_lab',
    'table':       'self.table.setRowCount',
    'GPU行×5':     'vm0_lab, self.vm0_val, self.bar_vm0',
    'CPU条':       'set_fmt(self.bar_cb',
    '内存条':      'set_fmt(self.bar_ph',
    '上下文条':    '"ctx"',
    '阶段条':      '"phase"',
}
print('---- Strata 路径覆盖 ----')
for name, call in WIDGETS.items():
    check(f'{name}', call in strata_m)

# ---- 写入纪律 ----
check('render 无裸 setText', '.setText(' not in strata_m)
check('render 无裸 setFormat', '.setFormat(' not in strata_m)
check('render 无裸 setValue', strata_m.count('setValue(') == 0)
check('表格签名防重建', '_tbl_sig' in strata_m)
check('CPU interval 实测', 'cpu_percent(0.2)' in strata_m)
check('内存 已用/总量 文本', '/ 2**30' in strata_m)
check('会话总量列 prompt_total', 'fmt_k(r.get("prompt_total"))' in strata_m)

# ---- 数据实盘 ----
d = json.load(urllib.request.urlopen('http://127.0.0.1:8081/metrics', timeout=3))
r0 = (d.get('requests') or [{}])[0]
check('prompt_total(会话总量)有值', (r0.get('prompt_total') or 0) > 0)
check('硬件在 metrics', len(d.get('hardware', {}).get('gpus') or []) >= 4)
import psutil as _ps
cpu = _ps.cpu_percent(0.3)
check(f'真实 CPU={cpu}% < 100', 0 <= cpu <= 100)
vm = _ps.virtual_memory()
check(f'内存 {vm.used/2**30:.0f}G/{vm.total/2**30:.0f}G 可算', vm.total > 0)
up = None
for pr in _ps.process_iter(['name', 'create_time']):
    if (pr.info['name'] or '').lower() == 'strata.exe':
        up = time.time() - pr.info['create_time']; break
check(f'uptime={int((up or 0)//60)}min 可算', up is not None)

print('\n====', f'全部通过({len(fails)==0})' if not fails else f'{len(fails)} 项失败: {fails}', '====')
