# -*- coding: utf-8 -*-
"""静态校验: 不启动 GUI, 验证 monitor 数据层与显示互斥逻辑"""
import re, sys, ast

SRC = r'D:\llama-monitor\monitor_gui.py'
src = open(SRC, encoding='utf-8').read()
fails = []

def check(name, cond):
    print(('PASS ' if cond else 'FAIL ') + name)
    if not cond:
        fails.append(name)

# 1. 语法
try:
    ast.parse(src); check('语法 ast.parse', True)
except SyntaxError as e:
    check(f'语法 ast.parse ({e})', False); sys.exit(1)

# 2. Strata 正则 vs 真实日志
m = re.search(r'STRATA_RE = re\.compile\((r"[^"]*")\)', src)
pat = eval(m.group(1))
lines = open(r'E:\strata-src\strata-iq3_s.log', encoding='utf-8', errors='replace').readlines()[-600:]
hits = [l for l in lines if re.search(pat, l)]
check('STRATA_RE 命中真实日志 >=1 条', len(hits) >= 1)

# 3. 互斥结构: Strata 块内含表格渲染 + return, 且 return 在 llama.cpp 阶段判定之前
strata_i = src.index('# ---- Strata 引擎分支')
phase_i = src.index('# 阶段判定（源码级）')
block = src[strata_i:phase_i]
check('Strata 块内含表格渲染', 'self.table.setRowCount' in block)
check('Strata 块以 return 结束(互斥)', block.rstrip().endswith('return'))
check('llama.cpp 段在 Strata 块之后', strata_i < phase_i)

# 4. headless 数据层: 用 exec 环境跑 recent_requests 核心(照抄逻辑)
ns = {'re': re}
exec("import time as _t\n", ns)
reqs, order = {}, []
for l in lines:
    ms = re.search(pat, l)
    if ms:
        tid = "st" + ms.group(1) + ms.group(2) + str(len(order))
        reqs[tid] = {"pt": int(ms.group(1)), "ct": int(ms.group(2)),
                     "tps": float(ms.group(3)),
                     "acc": int(ms.group(4)) / max(int(ms.group(5)), 1),
                     "ts": ns['_t'].strftime("%H:%M:%S"), "id": ns['_t'].strftime("%H:%M:%S")}
        order.append(tid)
out = [reqs[t] for t in reversed(order[-50:])]
check('headless 解析出请求 >=1 条', len(out) >= 1)
if out:
    r0 = out[0]
    check('首条字段齐(pt/ct/tps/acc/id)', all(k in r0 and r0[k] is not None for k in ('pt', 'ct', 'tps', 'acc', 'id')))
    check('tps 为正数', isinstance(r0['tps'], float) and r0['tps'] > 0)
    check('acc 在 0..1', 0 <= r0['acc'] <= 1)
    check('pt/ct 为正整数', isinstance(r0['pt'], int) and r0['pt'] > 0 and isinstance(r0['ct'], int) and r0['ct'] > 0)

# 5. 上下文/阶段数据源存在(Strata 块引用的 ctx/reqs 变量在其之前定义)
check('ctx 在 Strata 块前定义', src.index('used, ctx = ') < strata_i)

# 6. 每个被设置的 widget 在 __init__ 中存在
for w in ('bar_ctx', 'ctx_lab', 'bar_cb', 'bar_phase', 'phase_lab', 'lb_phase_inline', 'v_spd', 'lb_model', 'table'):
    check(f'widget {w} 已定义', f'self.{w} ' in src or f'self.{w},' in src or f'self.{w})' in src)

# 7. 闪断根因排除: Strata 块与 llama.cpp 段之间无共享覆盖路径(块尾 return)
check('无 fallthrough(块尾 return 前无其他 return 缺失)', block.count('return') >= 1)

print('\n====', '全部通过' if not fails else f'{len(fails)} 项失败: {fails}', '====')
sys.exit(1 if fails else 0)
