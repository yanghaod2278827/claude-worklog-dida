#!/usr/bin/env python3
"""从 Obsidian 日记抽取手写条目，找出滴答清单当天没有的，补录进滴答。

只读盘: python obsidian_to_dida.py --dry-run
生成待补清单: python obsidian_to_dida.py --emit   -> dida_backfill_from_diary.json
"""
import sys, io, os, json, glob, re, argparse
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wl_config

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wl_config
from collections import defaultdict

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

HOME = os.path.expanduser('~')
VAULT = wl_config.VAULT
RESULTS = wl_config.CLAUDE_PROJECTS

BEGIN = '<!-- dida365:begin'
END = '<!-- dida365:end -->'

LIST_RE = re.compile(r'^\s*(?:[-*+]|\d+[.、)])\s*')
EMOJI_RE = re.compile('[\U0001F300-\U0001FAFF☀-➿️]')
PUNCT_RE = re.compile(r'[，。、；：！？…—\-·「」『』（）()《》〈〉“”"\'’‘\s]')
CN_NUM = str.maketrans('一二三四五六七八九', '123456789')

# 白名单：含工作动词/工作名词才算「任务」，否则列入「存疑」不自动补
TASK_HINT = re.compile(
    '统计|整理|转写|仿真|拍摄|咨询|汇报|周报|月报|简历|论文|专利|PPT|ppt|SEM|sem|报销|采购|购买|'
    '项目|初稿|考试|测评|笔试|测试|准备|优化|重构|踩点|拍鸟|拍飞机|拍|搬|安装|调试|文献|样品|'
    '数据|实验|组会|甘特|时间节点|申请|提交|出库|发票|发货|快递|简历|投递|面试|校招|代码|脚本|配置')


EMOJI_RULES = [
    ('💼', r'简历|投递|面试|考试|测评|笔试|性格测试|求职|校招'),
    ('💰', r'报销|发票|出库单|账单'),
    ('🛒', r'^买|购买|采购|咨询.*(买|购)|发货|快递'),
    ('📚', r'文献|书稿|检索'),
    ('🔬', r'论文|初稿|专利|框架|思维导图|摘要'),
    ('📅', r'周报|组会|汇报|PPT|ppt|甘特|时间节点'),
    ('🔍', r'SEM|sem|接触角|电镜|拉曼|XRD|表征'),
    ('🧪', r'仿真|实验|润湿'),
    ('📷', r'相册|拍鸟|拍飞机|拍摄|摄影|图片'),
]


def guess_emoji(t):
    for e, p in EMOJI_RULES:
        if re.search(p, t, flags=re.I):
            return e
    return '🔧'


def norm(s):
    s = EMOJI_RE.sub('', s)
    s = s.translate(CN_NUM)
    s = PUNCT_RE.sub('', s)
    return s.strip().lower()


def similar(a, b):
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    sa, sb = set(na), set(nb)
    inter = len(sa & sb)
    return inter / min(len(sa), len(sb)) >= 0.75


def parse_diary(path):
    raw = open(path, encoding='utf-8').read()
    # 去掉自动块
    raw = re.sub(re.escape(BEGIN) + r'.*?' + re.escape(END), '', raw, flags=re.S)
    # 去掉 YAML frontmatter
    raw = re.sub(r'^---\n.*?\n---\n', '', raw, flags=re.S)
    items = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith('#') or s.startswith('<!--'):
            continue
        s = LIST_RE.sub('', s).strip()
        s = re.sub(r'^\*\*|\*\*$', '', s).strip()
        if len(s) < 2 or len(s) > 60:
            continue
        items.append(s)
    return items


def load_dida():
    seen = {}
    for f in glob.glob(os.path.join(RESULTS, '**', 'tool-results',
                                    'mcp-dida365-list_completed*.txt'), recursive=True):
        try:
            data = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        tasks = data.get('result') if isinstance(data, dict) else data
        if not isinstance(tasks, list):
            continue
        for t in tasks:
            if isinstance(t, dict) and t.get('id') and t.get('title'):
                seen[t['id']] = t
    byday = defaultdict(list)
    for t in seen.values():
        # 三个日期都登记：任务可能计划在某天、实际做在另一天
        for k in ('dueDate', 'startDate', 'completedTime'):
            v = t.get(k) or ''
            if len(v) >= 10:
                byday[v[:10]].append(t['title'])
    return byday


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--emit', action='store_true')
    ap.add_argument('--dfrom', default='2026-08-04')
    # 默认到今天（曾写死 '2026-10-28'，过了那天盘点会静默截断）
    ap.add_argument('--dto', default=None)
    args = ap.parse_args()

    if not args.dto:
        args.dto = dt.date.today().isoformat()

    dida = load_dida()
    files = {}
    for p in glob.glob(os.path.join(VAULT, '[0-9][0-9][0-9][0-9]-*.md')) + glob.glob(os.path.join(VAULT, os.path.basename(wl_config.LEGACY_DAILY_DIR), '[0-9][0-9][0-9][0-9]-*.md')):
        d = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(p)).group(1)
        files.setdefault(d, p)

    missing = defaultdict(list)
    stats = {'days': 0, 'items': 0, 'covered': 0, 'nontask': 0, 'missing': 0}
    for d in sorted(files):
        if d < args.dfrom or d > args.dto:
            continue
        stats['days'] += 1
        items = parse_diary(files[d])
        # 同一天 + 前后两天内的滴答任务都算「已覆盖」（任务可能被标在相邻日期）
        titles = list(dida.get(d, []))
        dd = dt.date.fromisoformat(d)
        for off in (-2, -1, 1, 2):
            titles += dida.get((dd + dt.timedelta(days=off)).isoformat(), [])
        for it in items:
            stats['items'] += 1
            if any(similar(it, t) for t in titles):
                stats['covered'] += 1
            elif TASK_HINT.search(it):
                stats['missing'] += 1
                missing[d].append(('MISS', it))
            else:
                stats['nontask'] += 1
                missing[d].append(('AMBIG', it))

    print("=== 盘点 ===")
    print(f"日记天数 {stats['days']}  手写条目 {stats['items']}")
    print(f"  已被滴答覆盖 {stats['covered']}")
    print(f"  疑似非任务   {stats['nontask']}")
    print(f"  滴答缺失     {stats['missing']}")
    print("\n=== 缺失条目明细 ===")
    for d in sorted(missing):
        print(f"\n{d}  (滴答已有 {len(dida.get(d, []))} 条)")
        for kind, it in missing[d]:
            print(f"   [{'存疑' if kind == 'AMBIG' else '缺失 '}] {it}")

    if args.emit:
        raw = [(d, it) for d in sorted(missing) for k, it in missing[d] if k == 'MISS']
        # 去重：同标题 / 高度相似且相隔 ≤2 天 -> 合并到最早那天
        clusters = []  # [date, title, [other_dates]]
        for d, it in raw:
            d0 = dt.date.fromisoformat(d)
            hit = None
            for c in clusters:
                if abs((dt.date.fromisoformat(c[0]) - d0).days) > 2:
                    continue
                if norm(it) == norm(c[1]) or similar(it, c[1]):
                    hit = c
                    break
            if hit is None:
                clusters.append([d, it, []])
            else:
                hit[2].append(d)

        out = []
        for d, it, others in clusters:
            note = ''
            if others:
                note = '（日记亦记于 ' + '、'.join(sorted(set(others))) + '）'
            out.append({
                'date': d,
                'title': guess_emoji(it) + ' ' + it,
                'content': f'依据 Obsidian 日记补录：{it}{note}',
            })
        json.dump(out, open(os.path.join(wl_config.DATA_DIR, 'dida_backfill_from_diary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f"\n原始 {len(raw)} 条 -> 去重后 {len(out)} 条")
        for o in out:
            print(f"  {o['date']}  {o['title']}")


if __name__ == '__main__':
    main()
