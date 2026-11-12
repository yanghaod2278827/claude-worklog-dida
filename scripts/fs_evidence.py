#!/usr/bin/env python3
"""全机文件改动证据扫描（2026-10-30）

用途：把「当天全机文件被修改 / 新建」这一事实作为**补充证据**，交给 worklog agent
判断哪些是实质工作。只读文件元数据（mtime / 创建时间），不读内容、不移动、不删除任何文件。

标注规则（用户选择：保留但标注「疑似自动」）
- 跳过整棵系统 / 构建 / 缓存目录树（Windows、Program Files、AppData、node_modules、.git、venv...）
- 其余文件按 [人为] / [疑似自动] 标注：
    * 疑似自动：缓存/日志/临时/锁文件扩展名、备份与日志目录、批量生成、Office 锁文件
    * 人为：默认
- 同一目录内 >= BATCH_N 个文件且 mtime 跨度 <= BATCH_SECS 秒 -> 整组标「批量」（疑似自动）
- 有 Office 锁文件 `~$xxx.docx` 时，同目录的 `xxx.docx` 标为 [人为] 并注明「正在编辑」

扫描范围自适应（用户要求：先全盘，逐渐收窄到常用，但要能发现新增常用）
- 前 BOOTSTRAP_DAYS(7) 天：每次全盘
- 之后：只扫「常用目录」(hot) + 每轮轮询 1 个冷门顶层分支
- 每 FULL_REFRESH_DAYS(7) 天做一次全盘，用来发现新增常用目录
- 常用目录按「当天出现人为文件」累计评分；90 天未命中且低分淘汰

输出
- 按目录聚合的证据段追加到 --append-to 指定的证据文件
- 明细写 data/fs_detail_<date>.json（便于事后核对）
- stdout 一行摘要，含 sig（供 daily_worklog.ps1 判断「有没有新改动」）

退出码: 0=有候选; 3=无候选; 1=出错
"""
import sys, io, os, json, re, hashlib, time, argparse, datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wl_config

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wl_config

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

HOME = os.path.abspath(os.path.expanduser('~'))
PROJECT = wl_config.ROOT
DATA_DIR = wl_config.DATA_DIR

# ---------------- scan scope ----------------
# 注意：这里必须是「单个反斜杠」的普通字符串；写成 r'C:\\' 会得到双反斜杠，
# 扫描出的路径会带 'C:\\Windows' 形式，和跳过前缀对不上 -> 整个系统盘被扫（2026-10-30 实测踩过）。
ROOTS = list(wl_config.CFG.get('scan_roots') or ['C:\\', 'D:\\', 'E:\\'])

# whole-subtree skips (absolute, normalized lowercase, no trailing sep)
SKIP_ABS_PREFIX = [
    os.path.normcase(os.path.join(HOME, 'AppData')),
    os.path.normcase(os.path.join(HOME, '.claude')),
    os.path.normcase(os.path.join(HOME, '.agents')),
    os.path.normcase(os.path.join(HOME, '.baoyu-skills')),
    os.path.normcase(os.path.join(HOME, '.cursor')),
    os.path.normcase(os.path.join(HOME, 'venvs')),
    os.path.normcase(os.path.join(HOME, 'models')),
    os.path.normcase(PROJECT),
    r'c:\windows',
    r'c:\program files',
    r'c:\program files (x86)',
    r'c:\programdata',
    r'c:\$recycle.bin',
    r'c:\system volume information',
    r'c:\recovery',
    r'c:\perflogs',
    r'c:\users\all users',
    r'c:\users\default',
    r'c:\users\default user',
    r'd:\$recycle.bin',
    r'd:\system volume information',
    r'e:\$recycle.bin',
    r'e:\system volume information',
]
SKIP_ABS_PREFIX += [os.path.normcase(wl_config.expand(p)) for p in (wl_config.CFG.get('scan_skip') or [])]

# skipped at any depth
# ⚠️ 只按「明确名字」跳过构建/缓存目录，**绝不按 '.' 前缀批量跳过**：
#    以点开头的目录也可能是核心工作区（例如 D:\.work），必须扫描，不要按前缀批量跳过。
SKIP_DIR_NAMES = {
    'node_modules', '__pycache__', '.git', '.svn', '.hg', '.venv', 'venv', 'env',
    'site-packages', 'dist-info', 'egg-info', '.cache', '.conda', '.cargo', '.npm',
    'gradle', '.gradle', '.m2', '.ollama', '.trash', '.trash-1000', '.next', '.nuxt',
    '.pytest_cache', '.mypy_cache', '.ruff_cache', '.idea', '.vs', '.vscode',
    'obj', '.terraform', '.turbo', '.parcel-cache', '.angular', '.expo', 'coverage',
    'htmlcov', 'logs', 'log', 'tmp', 'temp', '.obsidian', '.stfolder',
}

# auto-ish path markers (substring match on lowercase path)
AUTO_MARKERS = (
    '\\temp\\', '\\tmp\\', '\\logs\\', '\\log\\', '\\cache', '\\backup', '\\备份',
    '\\_备份', '\\appdata\\', '\\programdata\\', '\\$recycle.bin', '\\.claude\\',
    '\\.obsidian\\', '\\models\\', '\\site-packages\\', '\\node_modules\\',
    '\\__pycache__\\', '\\.git\\', '\\.baiduyun', '\\everything\\', '\\softwaredistribution\\',
    # 通讯/参考/截图工具的程序数据（内容由程序生成，不是人手逐个改的）
    '\\xwechat_files', '\\telegram desktop\\tdata', '\\nt_qq\\', '\\zotero\\',
    '\\snipaste', '\\history\\snip',
    '\\wps cloud', '\\wpsdrive', 'wps云盘', 'wps企业云盘',
    # 自动下载项目的工作目录（下载过程中的临时落点）；档案成品目录不标自动
    '\\xins原图视频下载\\',
    # 注意：不要把整个 D:\Multimedia\image\ 标成自动——用户会手工整理图片，
    # 之前这样标导致「整理图片」整段被当自动跳过（2026-10-30 实测）。
)

AUTO_EXT = {
    '.log', '.tmp', '.temp', '.bak', '.pyc', '.pyo', '.pyd', '.swp', '.swo', '.lock',
    '.crdownload', '.part', '.partial', '.download', '.dwl', '.dwl2', '.db-wal',
    '.db-shm', '.db-journal', '.etl', '.evtx', '.dmp', '.stackdump', '.pid', '.sock',
    '.sqlite-wal', '.sqlite-shm', '.ldb', '.sst', '.pma',
}
AUTO_NAMES = {
    'thumbs.db', 'desktop.ini', '.ds_store', 'everything.db', '.coverage',
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
    # browser profile internals (Chrome/Edge/Playwright persistent profiles)
    'preferences', 'secure preferences', 'history', 'cookies', 'local state',
    'variations', 'variationsseedv2', 'variationssafeseedv2', 'dips',
    'network persistent state', 'ukm_db', 'settings.dat', 'log',
}
AUTO_NAME_RE = (
    (re.compile(r'^manifest-\d+$'), '浏览器配置'),
    (re.compile(r'^browsermetrics-'), '浏览器配置'),
    (re.compile(r'^data_\d+$'), '缓存'),
)

BATCH_N = 30
BATCH_SECS = 900
HOT_DEPTH = 3
MAX_GROUPS = 60
MAX_FILES = 6
MAX_DETAIL = 20000
BOOTSTRAP_DAYS = 7
FULL_REFRESH_DAYS = 7
HOT_MAX = 80
HOT_STALE_DAYS = 90


def norm(p):
    return os.path.normcase(os.path.abspath(p))


SKIP_SET = set(SKIP_ABS_PREFIX)

# exact files to ignore (set in main): the day's Obsidian diary is written by this very
# automation in step 6, so counting it as "human file change" would self-excite.
EXCLUDE_FILES = set()

# weekly summaries (2026-11-05): ObsidianVault\07-日记\<YYYY>-W<NN>_周总结.md is written by
# weekly_summary.ps1. Matching by name anywhere under the vault keeps it from being
# archived as human work on the day it is generated.
WEEKLY_SUMMARY_RE = re.compile(r'^\d{4}-W\d{2}_周总结\.md$')


def is_auto_artifact(path_l, name):
    if WEEKLY_SUMMARY_RE.match(name) and 'obsidianvault' in path_l:
        return True
    return False


def under_skip(path_l):
    for p in SKIP_ABS_PREFIX:
        if path_l == p or path_l.startswith(p + '\\'):
            return True
    return False


# ---------------- scanning ----------------

def iter_files(base):
    """Yield ('d'|'f', path, stat). DirEntry.stat is cached from scandir."""
    stack = [base]
    while stack:
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        if e.is_symlink():
                            continue
                        is_j = getattr(e, 'is_junction', None)
                        if is_j and is_j():
                            continue
                        dl = os.path.normcase(e.path)
                        if e.name.lower() in SKIP_DIR_NAMES or under_skip(dl):
                            continue
                        yield 'd', e.path, e.stat(follow_symlinks=False)
                        stack.append(e.path)
                    elif e.is_file(follow_symlinks=False):
                        yield 'f', e.path, e.stat(follow_symlinks=False)
                except OSError:
                    continue


def collect(dirs, start, end, max_secs):
    t0 = time.time()
    scanned = 0
    cands = []
    dirhits = []
    partial = False
    for base in dirs:
        if not os.path.isdir(base):
            continue
        for kind, p, st in iter_files(base):
            if max_secs and time.time() - t0 > max_secs:
                partial = True
                break
            if kind == 'd':
                # directory mtime changes on add/remove/rename - the only trace of a pure move
                if start <= st.st_mtime < end:
                    dirhits.append((p, st.st_mtime))
                continue
            scanned += 1
            if os.path.normcase(os.path.abspath(p)) in EXCLUDE_FILES:
                continue
            if is_auto_artifact(os.path.normcase(os.path.abspath(p)), os.path.basename(p)):
                continue
            mt = st.st_mtime
            bt = getattr(st, 'st_birthtime', st.st_ctime)
            if start <= mt < end:
                cands.append({'p': p, 'mt': mt, 'bt': bt, 'kind': 'mtime'})
            elif start <= bt < end:
                cands.append({'p': p, 'mt': mt, 'bt': bt, 'kind': 'new'})
        if partial:
            break
    return cands, dirhits, scanned, time.time() - t0, partial


# ---------------- tagging ----------------

def classify(cands):
    by_dir = defaultdict(list)
    for c in cands:
        by_dir[os.path.dirname(c['p'])].append(c)

    for d, lst in by_dir.items():
        # office lock files: ~$name.docx means name.docx is being edited by a human
        locks = set()
        for c in lst:
            n = os.path.basename(c['p'])
            if n.startswith('~$'):
                locks.add(n[2:].lower())
        # batch detection
        is_batch = False
        if len(lst) >= BATCH_N:
            span = max(x['mt'] for x in lst) - min(x['mt'] for x in lst)
            is_batch = span <= BATCH_SECS
        for c in lst:
            name = os.path.basename(c['p'])
            low = c['p'].lower()
            reasons = []
            if name.lower() in locks:
                c['tag'] = 'human'
                c['reason'] = '正在编辑(有 Office 锁文件)'
                c['batch'] = False
                continue
            if name.startswith('~$'):
                reasons.append('锁文件')
            ext = os.path.splitext(name)[1].lower()
            if ext in AUTO_EXT or name.lower() in AUTO_NAMES or '.bak' in name.lower():
                reasons.append('类型')
            for rx, why in AUTO_NAME_RE:
                if rx.match(name.lower()):
                    reasons.append(why)
                    break
            if any(m in low for m in AUTO_MARKERS):
                reasons.append('路径')
            # browser/automation persistent profiles: any dir segment ending with _profile
            if any(seg.endswith('_profile') for seg in low.split(os.sep)):
                reasons.append('浏览器配置')
            if is_batch:
                reasons.append('批量')
            c['tag'] = 'auto' if reasons else 'human'
            c['reason'] = '+'.join(reasons)
            c['batch'] = is_batch
    return by_dir


# ---------------- hot dirs ----------------

def hot_key(path):
    for r in ROOTS:
        rl = r.lower()
        if path.lower().startswith(rl):
            rest = path[len(r):]
            parts = [x for x in rest.split(os.sep) if x]
            return os.path.join(r, *parts[:HOT_DEPTH])
    return os.path.dirname(path)


def load_state(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(path, st):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def fmt_time(ts):
    return datetime.datetime.fromtimestamp(ts).strftime('%H:%M:%S')


def build_section(cands, dirhits, by_dir, scanned, secs, mode, partial, date, detail_path):
    human = [c for c in cands if c['tag'] == 'human']
    auto = [c for c in cands if c['tag'] == 'auto']

    groups = []
    for d, lst in by_dir.items():
        h = [c for c in lst if c['tag'] == 'human']
        a = [c for c in lst if c['tag'] == 'auto']
        is_batch = bool(lst) and all(c['batch'] for c in lst)
        groups.append((d, lst, h, a, is_batch))

    def sort_key(g):
        d, lst, h, a, is_batch = g
        return (-len(h), -max((c['mt'] for c in lst), default=0))

    groups.sort(key=sort_key)

    lines = []
    lines.append(f"## 文件改动证据（{date}）")
    lines.append(f"# 扫描 {scanned:,} 个文件，命中 {len(cands)} 个（人为 {len(human)} / 疑似自动 {len(auto)}），"
                 f"模式 {mode}，用时 {secs:.1f}s" + ("，**扫描超时未完成**" if partial else ""))
    lines.append("# 标注: [人为]=通常由人操作产生; [疑似自动]=缓存/日志/程序生成/批量; [新建]=当天创建")
    lines.append("# 明细: " + detail_path)

    shown = 0
    omitted_dirs = 0
    omitted_files = 0
    for d, lst, h, a, is_batch in groups:
        if shown >= MAX_GROUPS:
            omitted_dirs += 1
            omitted_files += len(lst)
            continue
        shown += 1
        dshort = d if len(d) <= 110 else d[:52] + '...' + d[-55:]
        if h:
            lines.append(f"### [人为 {len(h)}] {dshort}")
            for c in sorted(h, key=lambda x: -x['mt'])[:MAX_FILES]:
                new = '[新建]' if c['kind'] == 'new' else ''
                note = f"  ({c['reason']})" if c['reason'] else ''
                lines.append(f"   [人为]{new} {fmt_time(c['mt'])} {os.path.basename(c['p'])}{note}")
            if len(h) > MAX_FILES:
                lines.append(f"   ... 另有 {len(h) - MAX_FILES} 个同类文件")
        if a:
            if is_batch:
                lo = min(c['mt'] for c in a)
                hi = max(c['mt'] for c in a)
                ex = '、'.join(os.path.basename(c['p']) for c in sorted(a, key=lambda x: -x['mt'])[:2])
                lines.append(f"### [疑似自动 {len(a)}] {dshort}")
                lines.append(f"   [疑似自动] {fmt_time(lo)}~{fmt_time(hi)} 批量 {len(a)} 个（示例: {ex}）")
            else:
                lines.append(f"### [疑似自动 {len(a)}] {dshort}")
                for c in sorted(a, key=lambda x: -x['mt'])[:min(2, MAX_FILES)]:
                    new = '[新建]' if c['kind'] == 'new' else ''
                    note = f"  ({c['reason']})" if c['reason'] else ''
                    lines.append(f"   [疑似自动]{new} {fmt_time(c['mt'])} {os.path.basename(c['p'])}{note}")
                if len(a) > 2:
                    lines.append(f"   ... 另有 {len(a) - 2} 个")
    if omitted_dirs:
        lines.append(f"# 另有 {omitted_dirs} 个目录 / {omitted_files} 个文件未列出（见明细 JSON）")

    # directory-level changes: entries added/removed/renamed, no file timestamps changed directly.
    # this is the only trace of a pure move/rename (same-volume moves keep mtime AND birthtime).
    file_dirs = set(by_dir.keys())
    human_dh, auto_dh = [], []
    for d, mt in dirhits:
        if d in file_dirs:
            continue
        low = d.lower()
        if any(m in low for m in AUTO_MARKERS) or \
                any(seg.endswith('_profile') for seg in low.split(os.sep)):
            auto_dh.append((d, mt))
        else:
            human_dh.append((d, mt))
    if human_dh:
        lines.append("")
        lines.append("## 目录变动（目录内条目被增删/改名，没有文件时间戳变化；可能是移动/重命名/新建文件夹）")
        for d, mt in sorted(human_dh, key=lambda x: -x[1])[:40]:
            lines.append(f"   [目录变动] {fmt_time(mt)} {d}")
        if len(human_dh) > 40:
            lines.append(f"   ... 另有 {len(human_dh) - 40} 个")
    if auto_dh:
        lines.append(f"# 另有 {len(auto_dh)} 个疑似自动目录变动未列出")
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', required=True, help='YYYY-MM-DD')
    ap.add_argument('--append-to', default=None, help='证据文件路径（不存在则新建）')
    ap.add_argument('--state', default=os.path.join(DATA_DIR, 'fs_scope.json'))
    ap.add_argument('--detail', default=None)
    ap.add_argument('--roots', default=None, help='调试用：逗号分隔的根目录，覆盖默认')
    ap.add_argument('--full', action='store_true', help='强制全盘扫描')
    ap.add_argument('--max-secs', type=int, default=300)
    ap.add_argument('--no-state', action='store_true',
                    help='历史回填：不读写 fs_scope.json、强制全盘（避免污染常用目录学习）')
    args = ap.parse_args()
    global ROOTS, EXCLUDE_FILES
    EXCLUDE_FILES = {
        os.path.normcase(os.path.abspath(os.path.join(wl_config.DAILY_NOTE_DIR, f'{args.date}.md'))),
        os.path.normcase(os.path.abspath(os.path.join(wl_config.LEGACY_DAILY_DIR, f'{args.date}.md'))),
    }

    date = args.date
    day = datetime.datetime.strptime(date, '%Y-%m-%d')
    start = day.timestamp()
    end = (day + datetime.timedelta(days=1)).timestamp()

    roots = [r.strip() for r in args.roots.split(',')] if args.roots else [r for r in ROOTS if os.path.isdir(r)]
    if args.roots:
        ROOTS = roots

    st = {} if args.no_state else load_state(args.state)
    today = date
    first_run = st.get('first_run') or today
    if 'full_until' not in st:
        try:
            fu = datetime.datetime.strptime(first_run, '%Y-%m-%d') + datetime.timedelta(days=BOOTSTRAP_DAYS)
            st['full_until'] = fu.strftime('%Y-%m-%d')
        except Exception:
            st['full_until'] = today
    st['first_run'] = first_run

    hot = st.get('hot') or []
    last_full = st.get('last_full')
    do_full = bool(args.full) or args.no_state or today <= st['full_until']
    if not do_full and last_full:
        try:
            do_full = (datetime.datetime.strptime(today, '%Y-%m-%d') -
                       datetime.datetime.strptime(last_full, '%Y-%m-%d')).days >= FULL_REFRESH_DAYS
        except Exception:
            do_full = True
    if not do_full and not last_full:
        do_full = True

    if do_full:
        dirs = roots
        mode = 'full'
    else:
        dirs = [h['p'] for h in hot if os.path.isdir(h['p'])]
        # explore one cold top-level branch per run (round robin)
        tops = []
        for r in roots:
            try:
                with os.scandir(r) as it:
                    for e in it:
                        try:
                            if not e.is_dir(follow_symlinks=False):
                                continue
                            nl = os.path.normcase(e.path)
                            if e.name.lower() in SKIP_DIR_NAMES or under_skip(nl):
                                continue
                            if any(nl == h['p'].lower() or nl.startswith(h['p'].lower() + '\\') for h in hot):
                                continue
                            tops.append(e.path)
                        except OSError:
                            continue
            except OSError:
                continue
        tops.sort()
        if tops:
            cur = int(st.get('cursor') or 0) % len(tops)
            dirs.append(tops[cur])
            st['cursor'] = cur + 1
        mode = 'adaptive'

    t_all = time.time()
    cands, dirhits, scanned, secs, partial = collect(dirs, start, end, args.max_secs)
    by_dir = classify(cands)

    sig_items = [f"{c['p']}|{int(c['mt'])}|{int(c['bt'])}" for c in sorted(cands, key=lambda x: x['p'])]
    sig_items += [f"D|{d}|{int(mt)}" for d, mt in sorted(dirhits)]
    sig = hashlib.sha1('\n'.join(sig_items).encode('utf-8', 'replace')).hexdigest()[:16] \
        if sig_items else 'empty'

    # update hot dirs
    hot_map = {h['p'].lower(): h for h in hot}
    day_hits = defaultdict(int)
    for c in cands:
        if c['tag'] == 'human':
            day_hits[hot_key(c['p'])] += 1
    for k, n in day_hits.items():
        ent = hot_map.get(k.lower())
        if not ent:
            ent = {'p': k, 'score': 0, 'last': today, 'days': 0}
            hot_map[k.lower()] = ent
            hot.append(ent)
        if ent.get('last') != today:
            ent['score'] = int(ent.get('score') or 0) + min(n, 5)
            ent['days'] = int(ent.get('days') or 0) + 1
            ent['last'] = today
    # prune
    cutoff = (day - datetime.timedelta(days=HOT_STALE_DAYS)).strftime('%Y-%m-%d')
    hot = [h for h in hot if os.path.isdir(h['p']) and not (h.get('score', 0) < 2 and h.get('last', '') < cutoff)]
    hot.sort(key=lambda h: (-int(h.get('score') or 0), h.get('last') or ''))
    st['hot'] = hot[:HOT_MAX]
    if do_full:
        st['last_full'] = today
    st['mode'] = mode
    st['last_run'] = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    if not args.no_state:
        save_state(args.state, st)

    if not cands and not dirhits:
        print(f"NO_CANDIDATES {date} mode={mode} scanned={scanned} secs={secs:.1f} sig=empty")
        return 3

    os.makedirs(DATA_DIR, exist_ok=True)
    detail = args.detail or os.path.join(DATA_DIR, f'fs_detail_{date}.json')
    with open(detail, 'w', encoding='utf-8') as f:
        json.dump([
            {'p': c['p'], 'tag': c['tag'], 'reason': c['reason'],
             'kind': c['kind'], 'mt': fmt_time(c['mt']), 'batch': c.get('batch')}
            for c in cands[:MAX_DETAIL]
        ], f, ensure_ascii=False, indent=0)

    section = build_section(cands, dirhits, by_dir, scanned, secs, mode, partial, date, detail)

    if args.append_to:
        if not os.path.exists(args.append_to):
            with open(args.append_to, 'w', encoding='utf-8') as f:
                f.write(f"# 日期: {date}\n# 会话数: 0（当天无 Claude 会话）\n")
        with open(args.append_to, 'a', encoding='utf-8') as f:
            f.write('\n' + section)

    human_n = sum(1 for c in cands if c['tag'] == 'human')
    print(f"OK {date} mode={mode} scanned={scanned} files={len(cands)} human={human_n} "
          f"auto={len(cands) - human_n} secs={time.time() - t_all:.1f} sig={sig}")
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"ERROR {e}")
        sys.exit(1)
