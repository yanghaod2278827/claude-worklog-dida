#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""周总结证据提取（2026-11-05）

把某一周（周一~周日）Obsidian 日记里的 `## 滴答清单` 块抽出来，连同程序侧统计，
写成一份 markdown 证据文件，供 `weekly_prompt.md` 驱动的 claude -p 生成结构化周总结。

为什么不用 LLM 自己算统计：条数 / 类目分布 / 时段总长这类数字必须由程序算，
否则模型会「估」，而本项目铁律是「完成度必须算出来，不能估」。

用法:
  python weekly_extract.py --week-end 2026-11-01 [--out 路径] [--vault 路径]
  # --week-end 传该周任意一天即可，自动吸附到该 ISO 周的周日

退出码: 0 = 有证据; 2 = 该周日记一条记录都没有; 1 = 出错
"""
import sys, io, os, re, argparse, datetime
from collections import defaultdict, Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wl_config

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wl_config

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

HOME = os.path.expanduser('~')
VAULT = wl_config.VAULT
DATA_DIR = wl_config.DATA_DIR

BEGIN = '<!-- dida365:begin (auto-generated) -->'
END = '<!-- dida365:end -->'

WEEKDAY_CN = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

# 与 dida_to_obsidian.py 的 ORDER 保持一致（emoji 语义同一套）
EMOJI_NAME = {
    '🔬': '科研/论文', '🧪': '实验/仿真', '🔍': '表征检测', '📚': '文献/资料',
    '📅': '汇报/PPT', '💼': '求职', '💰': '财务', '🛒': '采购/快递',
    '🔧': '系统与工具', '📷': '素材归档', '✈️': '出行', '📝': '笔记整理',
    '🍽️': '生活事务', '🎬': '电影', '📺': '剧集',
}
EMOJI_ORDER = list(EMOJI_NAME.keys())

DAY_FILE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}\.md$')
SPAN_RE = re.compile(r'^(\d{1,2}):(\d{2})[–-](\d{1,2}):(\d{2})\s+')
ONE_TIME_RE = re.compile(r'^(\d{1,2}):(\d{2})\s+')


def find_day_file(vault, d):
    """日记双路径：vault 根目录优先，其次 07-日记/，兼容旧名 日记/。"""
    for sub in ('', '07-日记', '日记', os.path.basename(wl_config.LEGACY_DAILY_DIR)):
        p = os.path.join(vault, sub, f'{d}.md') if sub else os.path.join(vault, f'{d}.md')
        if os.path.exists(p):
            return p
    return None


def split_block(text):
    """返回 (块内行, 块外行)。没有块时块内为空。"""
    i, j = text.find(BEGIN), text.find(END)
    if i < 0 or j < 0 or j <= i:
        return [], text.splitlines()
    inner = text[i + len(BEGIN):j]
    outside = text[:i] + '\n' + text[j + len(END):]
    return inner.splitlines(), outside.splitlines()


def strip_frontmatter(lines):
    if lines and lines[0].strip() == '---':
        for k in range(1, len(lines)):
            if lines[k].strip() == '---':
                return lines[k + 1:]
    return lines


def parse_span(line):
    """'- 08:46–10:12 🔬 xxx' -> (start_min, end_min) 或 None（无时刻/全天）"""
    line = line[2:] if line.startswith('- ') else line
    m = SPAN_RE.match(line)
    if m:
        s = int(m.group(1)) * 60 + int(m.group(2))
        e = int(m.group(3)) * 60 + int(m.group(4))
        if e < s:          # 跨零点
            e += 24 * 60
        return s, e
    m = ONE_TIME_RE.match(line)
    if m:
        s = int(m.group(1)) * 60 + int(m.group(2))
        return s, s
    return None


def item_emoji(line):
    body = line[2:].strip()  # 去掉 '- '
    body = SPAN_RE.sub('', body, count=1)
    body = ONE_TIME_RE.sub('', body, count=1)
    for e in EMOJI_ORDER:
        if body.startswith(e):
            return e
    return None


def fmt_min(m):
    return f'{m // 60:02d}:{m % 60:02d}'


def union_minutes(spans):
    """区间取并集后的总分钟数。直接相加会因多个任务时段重叠而虚高（实测一周 304h>168h）。"""
    if not spans:
        return 0
    total = 0
    cur_s, cur_e = None, None
    for s, e in sorted(spans):
        if cur_s is None:
            cur_s, cur_e = s, e
        elif s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            total += cur_e - cur_s
            cur_s, cur_e = s, e
    total += cur_e - cur_s
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--week-end', required=True, help='该周任意一天（YYYY-MM-DD），自动吸附到周日')
    ap.add_argument('--vault', default=VAULT)
    ap.add_argument('--out', default=None)
    args = ap.parse_args()

    anchor = datetime.date.fromisoformat(args.week_end)
    # 周一=0 ... 周日=6 -> 本周周日
    week_end = anchor + datetime.timedelta(days=(6 - anchor.weekday()))
    week_start = week_end - datetime.timedelta(days=6)
    iso = week_end.isocalendar()
    week_key = f'{iso.year}-W{iso.week:02d}'

    days = []
    for i in range(7):
        d = week_start + datetime.timedelta(days=i)
        ds = d.isoformat()
        path = find_day_file(args.vault, ds)
        items, handwritten = [], []
        if path:
            text = open(path, encoding='utf-8').read()
            inner, outside = split_block(text)
            for ln in inner:
                s = ln.strip()
                if s.startswith('- '):
                    items.append(s)
            for ln in strip_frontmatter(outside):
                s = ln.strip()
                # 保留 `#` 标题：早期日记没有滴答块，全靠手写，标题是唯一的主题线索。
                if not s or s.startswith('<!--'):
                    continue
                handwritten.append(s)
        days.append({'date': ds, 'dow': WEEKDAY_CN[i], 'path': path,
                     'items': items, 'handwritten': handwritten})

    total_items = sum(len(x['items']) for x in days)
    covered = sum(1 for x in days if x['items'])
    file_days = sum(1 for x in days if x['path'])
    hand_days = sum(1 for x in days if x['handwritten'])
    if total_items == 0 and not any(x['handwritten'] for x in days):
        print(f'NO_DATA {week_key} {week_start}..{week_end}')
        return 2

    # ---- 程序侧统计（模型只许引用，不许改写）----
    cat_items = Counter()
    per_day = []
    spans = []
    for x in days:
        day_spans = []
        for ln in x['items']:
            e = item_emoji(ln)
            cat_items[e or '未分类'] += 1
            sp = parse_span(ln)
            if sp:
                spans.append(sp)
                day_spans.append(sp)
        per_day.append((x['date'], x['dow'], len(x['items']), union_minutes(day_spans)))

    all_min = sum(p[3] for p in per_day)
    earliest = fmt_min(min(s for s, _ in spans)) if spans else '-'
    latest = fmt_min(max(e for _, e in spans)) if spans else '-'

    out = args.out or os.path.join(DATA_DIR, f'weekly_evidence_{week_key}.md')
    os.makedirs(os.path.dirname(out), exist_ok=True)

    L = []
    L.append(f'# 周总结证据 {week_key}')
    L.append(f'# 范围: {week_start.isoformat()}（周一）~ {week_end.isoformat()}（周日）')
    L.append(f'# 覆盖: 7 天中 {file_days} 天有日记文件；{covered} 天有滴答条目；{hand_days} 天有手写内容')
    L.append(f'# 条目: {total_items} 条（滴答块内；手写内容不计入）')
    L.append('# 说明: 每条来自 Obsidian 日记 `## 滴答清单` 块，标题原样保留（含 emoji 与时刻前缀）')
    L.append('')
    for x in days:
        L.append(f'## {x["date"]} {x["dow"]}（{len(x["items"])} 条）')
        if not x['path']:
            L.append('- （当天没有日记文件）')
        elif not x['items']:
            L.append('- （当天没有滴答清单块内容）')
        else:
            L.extend(x['items'])
        L.append('')

    if any(x['handwritten'] for x in days):
        L.append('## 日记手写内容（滴答清单块之外）')
        for x in days:
            if x['handwritten']:
                L.append(f'### {x["date"]}')
                L.extend(x['handwritten'][:40])
                if len(x['handwritten']) > 40:
                    L.append(f'- ...（另有 {len(x["handwritten"]) - 40} 行）')
        L.append('')

    L.append('## 程序统计（数字由脚本算出，总结里引用时不得改写）')
    L.append(f'- 活跃天数: {covered}/7')
    L.append(f'- 手写覆盖: {sum(1 for x in days if x["handwritten"])}/7 天（不计入条目数）')
    L.append(f'- 记录条目: {total_items}')
    L.append(f'- 最早开始 / 最晚结束: {earliest} / {latest}')
    L.append(f'- 一周有记录时段: {all_min // 60} 小时 {all_min % 60} 分'
             '（每天内区间取并集后相加；是"有记录的时间跨度"，不等于连续工作时长）')
    L.append('- 每日有记录时段: ' + ' | '.join(
        f'{d} {m // 60}h{m % 60:02d}m' for d, _, _, m in per_day))
    L.append('- 按类目条目数: ' + (' | '.join(
        f'{e} {EMOJI_NAME.get(e, "未分类")} {cat_items.get(e, 0)}'
        for e in EMOJI_ORDER if cat_items.get(e)) if cat_items else '（无）'))
    L.append('- 逐日条目数: ' + ' | '.join(f'{d}({n})' for d, _, n, _ in per_day))
    L.append('')

    open(out, 'w', encoding='utf-8', newline='\n').write('\n'.join(L))
    print(f'OK week={week_key} range={week_start}..{week_end} days={covered} items={total_items} -> {out}')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f'ERROR {e}')
        sys.exit(1)
