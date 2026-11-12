#!/usr/bin/env python3
"""提取指定日期本地 Claude 会话证据。

关键点（2026-10-29 修）：
1. 按**每条消息自己的 timestamp** 归属日期，不按会话首条消息——长会话会跨天，
   否则今天的工作会被算到几天前。
2. 排除**自动化自身**的会话：其 user 消息里含 `worklog_prompt.md` 指令文本。

用法: python worklog_extract.py --date 2026-10-29 [--out 路径]
退出码: 0 = 有证据; 2 = 当天无会话; 1 = 出错
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
DEFAULT_OUT_DIR = wl_config.DATA_DIR
# 自动化自身会话：只要任意一条 user 消息里出现这些指令文件名，整个 session 跳过。
# weekly_prompt.md 于 2026-11-05 加入（周总结任务也是自动化，不该被记成"做了工作"）。
AUTO_MARK = ('worklog_prompt', 'weekly_prompt')

NOISE = re.compile(
    r'^API Error|^Look at the available-skills|^\[Image|^Caveat|^This session is being continued|'
    r'^<|^\s*$|^请继续|^continue$|^reply (with exactly)?[: ]|^OK$|^PS-OK$|'
    r'^Please analyze this codebase and create a CLAUDE.md', re.I)

# 图片占位符不是内容，但同一条消息里的文字是（2026-11-07 修：`[Image #2] 添加日程`
# 原来整条被 ^\[Image 规则丢掉，导致「加观影日程」这类带图指令完全不可见）
IMG_TOKEN = re.compile(r'\[Image[^\]]*\]')


def clean(t):
    t = IMG_TOKEN.sub(' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def to_local(ts):
    """Claude 转录的 timestamp 是 UTC（...Z）；必须转本地时区。
    直接按 UTC 用会让显示时间晚 8 小时、凌晨 00:00-08:00 的会话算到前一天。"""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone()
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', required=True, help='YYYY-MM-DD')
    ap.add_argument('--out', default=None)
    ap.add_argument('--max-per-session', type=int, default=6)
    args = ap.parse_args()

    target = args.date
    files = glob.glob(os.path.join(wl_config.CLAUDE_PROJECTS, '**', '*.jsonl'), recursive=True)

    found = {}
    skipped_auto = 0
    for p in files:
        proj = os.path.basename(os.path.dirname(p))
        sess = os.path.basename(p)[:8]
        try:
            if os.path.getmtime(p).__lt__(
                    __import__('datetime').datetime.strptime(target, '%Y-%m-%d').timestamp()):
                continue
        except OSError:
            continue

        prompts = []   # (ts, text)
        is_auto = False
        try:
            for line in open(p, encoding='utf-8'):
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get('type') != 'user':
                    continue
                c = (rec.get('message') or {}).get('content')
                txt = ''
                if isinstance(c, str):
                    txt = c
                elif isinstance(c, list):
                    for b in c:
                        if isinstance(b, dict) and b.get('type') == 'text':
                            txt += b.get('text', '')
                if any(m in txt for m in AUTO_MARK):
                    is_auto = True
                    break
                txt = clean(txt)
                # 阈值 6→4（2026-11-07）：`添加日程` 这类 4 字指令是实质工作，不该被当噪声
                if not txt or NOISE.search(txt) or 'system-reminder' in txt[:80] or len(txt) < 4:
                    continue
                ts = rec.get('timestamp') or ''
                dt = to_local(ts)
                if dt and dt.strftime('%Y-%m-%d') == target:
                    prompts.append((dt, txt))
        except OSError:
            continue

        if is_auto:
            skipped_auto += 1
            continue
        if not prompts:
            continue
        prompts.sort()
        t1 = prompts[0][0].strftime('%H:%M')
        t2 = prompts[-1][0].strftime('%H:%M')
        span = t1 if t1 == t2 else f'{t1}-{t2}'
        found[sess] = (span, proj, [t for _, t in prompts])

    if not found:
        print(f"NO_SESSIONS {target}")
        return 2

    out = args.out or os.path.join(DEFAULT_OUT_DIR, f'worklog_evidence_{target}.txt')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(f"# 日期: {target}\n")
        f.write(f"# 会话数: {len(found)}（已排除自动化自身会话 {skipped_auto} 个）\n")
        f.write("# 只列该日期当天的用户输入；跨会长会话已按消息时间切分\n")
        f.write("# 会话行头 `HH:MM` 或 `HH:MM-HH:MM` 是该会话当天首/末条消息的时间\n")
        for sess, (tm, proj, prs) in sorted(found.items(), key=lambda x: x[1][0]):
            f.write(f"\n-- {tm} [{proj[:20]}] {sess}\n")
            for t in prs[:args.max_per_session]:
                f.write(f"   * {t[:150]}\n")
    print(f"OK {target} sessions={len(found)} skipped_auto={skipped_auto} -> {out}")
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        print(f"ERROR {e}")
        sys.exit(1)
