#!/usr/bin/env python3
"""把滴答清单已完成任务同步到 Obsidian 日记（vault 根目录 YYYY-MM-DD.md）。

数据来源：MCP 查询结果落盘的 JSON（~/.claude/projects/*/tool-results/mcp-dida365-list_completed*.txt）
用法:
  python dida_to_obsidian.py --scan-results            # 扫描所有落盘结果并同步
  python dida_to_obsidian.py --json-file X.json        # 指定输入
  ... --from 2026-08-04 --to 2026-10-28 [--dry-run] [--create]
日期口径: 优先 dueDate（任务计划当天），退回 startDate，最后 completedTime。
"""
import sys, io, os, json, glob, re, argparse
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wl_config

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wl_config

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

HOME = os.path.expanduser('~')
VAULT = wl_config.VAULT
RESULTS_DIR = wl_config.CLAUDE_PROJECTS

def _diary_subdirs():
    names = ['07-日记', '日记']
    legacy = os.path.basename(wl_config.LEGACY_DAILY_DIR.rstrip('/\\'))
    if legacy and legacy not in names:
        names.append(legacy)
    return names


def _diary_subdirs():
    names = ['07-日记', '日记']
    legacy = os.path.basename(wl_config.LEGACY_DAILY_DIR.rstrip('/\\'))
    if legacy and legacy not in names:
        names.append(legacy)
    return names


BEGIN = '<!-- dida365:begin (auto-generated) -->'
END = '<!-- dida365:end -->'

# 类目排序：科研 -> 实验 -> 表征 -> 文献 -> 汇报 -> 求职 -> 财务 -> 采购 -> 运维 -> 素材 -> 笔记 -> 生活 -> 影视
ORDER = ['🔬', '🧪', '🔍', '📚', '📅', '💼', '💰', '🛒', '🔧', '📷', '✈️', '📝', '🍽️', '🎬', '📺']


def task_date(t):
    for k in ('dueDate', 'startDate', 'completedTime'):
        v = t.get(k) or ''
        if len(v) >= 10:
            return v[:10]
    return None


def sort_key(title):
    first = title[:2]
    for i, e in enumerate(ORDER):
        if title.startswith(e):
            return (i, title)
    return (len(ORDER), title)


def _hm(v):
    """'2026-10-30T10:24:00+0800' -> '10:24' (None if all-day/absent)"""
    if not v or len(v) < 16:
        return None
    hm = v[11:16]
    return None if hm == '00:00' else hm


def task_span(t):
    """Return (title, 'HH:MM–HH:MM' or '') using startDate and completedTime."""
    start = _hm(t.get('startDate'))
    end = _hm(t.get('completedTime'))
    if t.get('isAllDay') or not start or not end:
        return t['title'].strip(), ''
    if start == end:
        return t['title'].strip(), start
    return t['title'].strip(), f'{start}–{end}'


def build_block(tasks, updated_at=None, run_count=None):
    """Block layout:
    <!-- dida365:begin -->
    ## 滴答清单
    > 最后更新：YYYY-MM-DD HH:MM（第 N 次归档）
    - ...
    <!-- dida365:end -->
    updated_at defaults to now (local); run_count omitted when None.
    """
    stamp = updated_at or datetime.now().strftime('%Y-%m-%d %H:%M')
    meta = f'> 最后更新：{stamp}'
    if run_count:
        meta += f'（第 {run_count} 次归档）'
    lines = [BEGIN, '## 滴答清单', meta]
    # 同日同名合并：保留最早开始、最晚结束
    agg = {}
    for t in tasks:
        title, span = task_span(t)
        if title not in agg:
            agg[title] = {'n': 0, 'start': t.get('startDate') or '', 'end': t.get('completedTime') or '',
                          'span': span}
        a = agg[title]
        a['n'] += 1
        st, en = t.get('startDate') or '', t.get('completedTime') or ''
        if st and (not a['start'] or st < a['start']):
            a['start'] = st
        if en and (not a['end'] or en > a['end']):
            a['end'] = en
    def time_key(title):
        a = agg[title]
        s0 = _hm(a['start']) if a['start'] else None
        # timed first (by clock), untimed last (by emoji category, then title)
        if not s0:
            return (1, '99:99', sort_key(title))
        return (0, s0, sort_key(title))

    for title in sorted(agg, key=time_key):
        a = agg[title]
        span = a['span']
        if a['start'] and a['end'] and not span:
            s0, e0 = _hm(a['start']), _hm(a['end'])
            if s0 and e0:
                span = s0 if s0 == e0 else f'{s0}–{e0}'
        prefix = f'{span} ' if span else ''
        lines.append(f'- {prefix}{title}' + (f' ×{a["n"]}' if a['n'] > 1 else ''))
    lines.append(END)
    return '\n'.join(lines)


def upsert(path, block, create):
    if os.path.exists(path):
        raw = open(path, encoding='utf-8').read()
    else:
        if not create:
            return 'skip(no-file)'
        raw = ''
    if BEGIN in raw and END in raw:
        new = re.sub(re.escape(BEGIN) + r'.*?' + re.escape(END), block, raw, flags=re.S)
        action = 'replace'
    else:
        sep = '' if raw.endswith('\n') or raw == '' else '\n'
        new = (raw + sep + ('\n' if raw.strip() else '') + block + '\n')
        action = 'append'
    if new != raw:
        open(path, 'w', encoding='utf-8', newline='\n').write(new)
        return action
    return 'unchanged'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scan-results', action='store_true')
    ap.add_argument('--json-file', action='append', default=[])
    ap.add_argument('--from', dest='dfrom', default='2026-08-04')
    ap.add_argument('--to', dest='dto', default=None)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--create', action='store_true', help='日记不存在时是否新建')
    ap.add_argument('--updated-at', default=None, help='最后更新时间戳（YYYY-MM-DD HH:MM），默认当前时刻')
    ap.add_argument('--run-count', type=int, default=None, help='当天第几次归档（可选）')
    args = ap.parse_args()

    files = list(args.json_file)
    if args.scan_results or not files:
        files += glob.glob(os.path.join(RESULTS_DIR, '**', 'tool-results',
                                        'mcp-dida365-list_completed*.txt'), recursive=True)

    seen = {}
    for f in files:
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

    dto = args.dto or datetime.now().strftime('%Y-%m-%d')
    byday = defaultdict(list)
    for t in seen.values():
        d = task_date(t)
        if not d or d < args.dfrom or d > dto:
            continue
        byday[d].append(t)

    print(f"载入任务 {len(seen)} 条；落在 {args.dfrom}..{dto} 的日期 {len(byday)} 天")
    stats = defaultdict(int)
    for d in sorted(byday):
        path = os.path.join(VAULT, f'{d}.md')
        # 回退：根目录没有、但归档日记目录里有，就写到那里（避免同一天两处日记）
        # 2026-11-02 vault 目录重组后改为 07-日记/，旧名 日记/ 兼容保留
        if not os.path.exists(path):
            for sub in _diary_subdirs():
                alt = os.path.join(VAULT, sub, f'{d}.md')
                if os.path.exists(alt):
                    path = alt
                    break
        block = build_block(byday[d], updated_at=args.updated_at, run_count=args.run_count)
        if args.dry_run:
            exists = os.path.exists(path)
            stats['(dry)existing' if exists else '(dry)missing'] += 1
            if not exists:
                print(f"  MISSING {d}  ({len(byday[d])} 条)")
            continue
        r = upsert(path, block, args.create)
        stats[r] += 1
        if r in ('replace', 'append'):
            print(f"  {d}  {r:7s} {len(byday[d])} 条")
    print("汇总:", dict(stats))


if __name__ == '__main__':
    main()
