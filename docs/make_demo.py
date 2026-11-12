# -*- coding: utf-8 -*-
"""Regenerate docs/demo-diary.png from the REAL diary-block builder.

The task list is synthetic, but the right-hand block is produced by
`scripts/dida_to_obsidian.py:build_block()` — i.e. the same code path that
writes real daily notes. The page is rendered by headless Microsoft Edge and
captured as a PNG, so the image is a genuine screenshot of the output, not a
hand-drawn mockup.

    python3 docs/make_demo.py
"""
import html
import io
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import dida_to_obsidian as D  # noqa: E402

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    shutil.which("msedge"),
]

TASKS = [
    ("09:12", "10:42", "🔬 Draft Chapter 3 §3.2"),
    ("10:55", "11:40", "🔍 Review SEM images (48)"),
    ("13:30", "15:05", "🧪 Cutting trial #7"),
    ("15:20", "16:10", "📅 Weekly report PDF"),
    ("16:30", "17:05", "🔧 Fix worklog pipeline"),
    ("17:10", "17:25", "📷 Organize figures (12)"),
]

DATE = "2026-11-12"


def fake_tasks():
    out = []
    for i, (s, e, title) in enumerate(TASKS):
        out.append({
            "id": "demo%d" % i,
            "projectId": "demo",
            "title": title,
            "startDate": "%sT%s:00+0800" % (DATE, s),
            "dueDate": "%sT%s:00+0800" % (DATE, e),
            "completedTime": "%sT%s:00+0800" % (DATE, e),
            "isAllDay": False,
        })
    return out


CSS = """
* { box-sizing: border-box; }
body { margin:0; background:#f5f7fa; font-family:'Segoe UI','Microsoft YaHei','Segoe UI Emoji',sans-serif; color:#1f2937; }
.wrap { width:1120px; height:600px; padding:28px 32px; display:flex; gap:56px; }
.card { background:#fff; border-radius:14px; box-shadow:0 2px 10px rgba(15,23,42,.08); width:520px; height:520px; overflow:hidden; }
.hdr { background:#2f6feb; color:#fff; padding:18px 28px 14px; font-size:20px; font-weight:600; }
.sub { padding:14px 28px 0; color:#64748b; font-size:14px; }
.row { display:flex; align-items:center; padding:10px 28px; font-size:15px; }
.row .t { flex:1; }
.row .h { color:#94a3b8; font-size:13px; }
.check { width:18px; height:18px; border:2px solid #16a34a; border-radius:50%; margin-right:16px; position:relative; }
.check:after { content:''; position:absolute; left:4px; top:4px; width:7px; height:4px; border-left:2px solid #16a34a; border-bottom:2px solid #16a34a; transform:rotate(-45deg); }
.note { font-size:12px; color:#94a3b8; padding:16px 28px; }
.titlebar { background:#eef2f7; padding:8px 16px; font-size:12px; color:#64748b; }
pre { margin:16px 20px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:16px; font-family:Consolas,'Cascadia Mono','Segoe UI Emoji',monospace; font-size:13px; line-height:1.85; color:#334155; white-space:pre-wrap; }
.foot { position:absolute; bottom:12px; left:0; right:0; text-align:center; font-size:12px; color:#94a3b8; }
"""


def build_html():
    block = D.build_block(fake_tasks(), updated_at="2026-11-12 17:30", run_count=6)
    rows = []
    for s, e, title in TASKS:
        rows.append(
            '<div class="row"><div class="check"></div>'
            '<div class="t">%s</div><div class="h">%s–%s</div></div>'
            % (html.escape(title), s, e))
    return """<!doctype html><html><head><meta charset="utf-8"><style>%s</style></head><body>
<div class="wrap">
  <div class="card">
    <div class="hdr">Dida365 · Completed</div>
    <div class="sub">%s · %d items</div>
    %s
    <div class="note">Each row carries a real evidence-derived time window.</div>
  </div>
  <div class="card">
    <div class="titlebar">2026-11-12.md — Obsidian</div>
    <pre>%s</pre>
    <div class="note">The block is replaced idempotently every run.</div>
  </div>
</div>
<div class="foot">Real output of dida_to_obsidian.build_block() on synthetic tasks — not a hand-drawn mockup.</div>
</body></html>""" % (CSS, DATE, len(TASKS), "\n".join(rows), html.escape(block))


def find_edge():
    for p in EDGE_CANDIDATES:
        if p and os.path.exists(p):
            return p
    raise SystemExit("Microsoft Edge not found")


def main():
    out = os.path.join(ROOT, "docs", "demo-diary.png")
    tmp = tempfile.mkdtemp(prefix="wl_demo_")
    page = os.path.join(tmp, "demo.html")
    with io.open(page, "w", encoding="utf-8") as f:
        f.write(build_html())
    profile = os.path.join(tmp, "profile")
    cmd = [find_edge(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
           "--force-device-scale-factor=1", "--window-size=1120,600",
           "--user-data-dir=" + profile,
           "--screenshot=" + out,
           "file:///" + page.replace("\\", "/")]
    p = subprocess.run(cmd, capture_output=True, timeout=120)
    if not os.path.exists(out):
        sys.stderr.write(p.stderr.decode("utf-8", "replace")[-800:])
        return 1
    print("wrote", out, os.path.getsize(out), "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
