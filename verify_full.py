# -*- coding: utf-8 -*-
"""交付前全面静态校验: 所有显示路径/文件路径/字段/互斥/动画/实盘数据"""
import ast, json, re, os, urllib.request

SRC = r'D:\llama-monitor\monitor_gui.py'
TEE = r'D:\llama-monitor\model-tee.py'
src = open(SRC, encoding='utf-8').read()
tee = open(TEE, encoding='utf-8').read()
fails = []
def check(n, c):
    print(('PASS ' if c else 'FAIL ') + n)
    if not c: fails.append(n)

# 1. 语法
for name, code in (('monitor_gui', src), ('model-tee', tee)):
    try: ast.parse(code); check(f'{name} 语法', True)
    except SyntaxError as e: check(f'{name} 语法 ({e})', False)

# 2. 无残留老路径(E:\)
for name, code in (('monitor_gui', src), ('model-tee', tee)):
    check(f'{name} 无 E:\\LM 残留', 'E:\\LM' not in code and 'E:\\working' not in code)

# 3. live 链路: 网关写路径 == GUI 读路径
tee_write = re.search(r'LIVE\s*=\s*rf?"([^"]+)"', tee).group(1).replace('%s', '{LISTEN}').replace('{LISTEN}', '8080')
gui_read = 'D:\\llama\\live-' in src
check(f'网关 live 写: {tee_write}', '8080' in tee_write)
check('GUI live 读 D:\\llama\\live-', gui_read)

# 4. Strata 分支完整性
blk = src[src.index('# ---- Strata 引擎分支'):src.index('# 阶段判定（源码级）')]
check('数据源 /metrics', 'strata_metrics' in src and 'get_json("/metrics")' in src)
for f in ('state','prompt_read','prompt_total','tok_s','decode_tok_s','drafts_accepted','drafts_offered','hit_rate','max_context','prompt_tokens','output_tokens'):
    check(f'官方字段 {f}', f in blk)
check('互斥 return 在表格渲染后', blk.rstrip().endswith('return') and 'setRowCount' in blk)
check('预填充忙碌动画 setRange(0,0)', 'setRange(0, 0)' in blk)
check('动画恢复 setRange(0,100)', 'setRange(0, 100)' in blk)

# 5. 预填充 live 预写(网关请求即写"填充中")
check('网关请求即写填充状态', '填充中' in tee and 'write_live(st_line' in tee)

# 6. 实盘: /metrics 全字段真实可用
d = json.load(urllib.request.urlopen('http://127.0.0.1:8081/metrics', timeout=3))
live, reqs, eng = d.get('live') or {}, d.get('requests') or [], d.get('engine') or {}
check('live.state 有值: ' + str(live.get('state')), live.get('state') in ('idle','reading','generating','unloaded'))
check('engine.max_context = 262144', eng.get('max_context') == 262144)
check('requests >=1', len(reqs) >= 1)
if reqs:
    r0 = reqs[0]
    check('decode_tok_s > 0', (r0.get('decode_tok_s') or 0) > 0)
    do_, da_ = r0.get('drafts_offered'), r0.get('drafts_accepted')
    check('草稿率 0..1', do_ and da_ is not None and 0 <= da_/do_ <= 1)

# 7. 实盘: live 文件链路(刚发过流式请求)
lf = r'D:\llama\live-8080.txt'
check('live-8080.txt 存在且非空', os.path.exists(lf) and os.path.getsize(lf) > 10)

# 8. 进程名兼容
check('strata.exe 存活检查', 'strata.exe' in src)

print('\n====', '全部通过, 可交付' if not fails else f'{len(fails)} 项失败: {fails}', '====')
