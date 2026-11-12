# -*- coding: utf-8 -*-
"""Dependency-free self test, run locally and in CI.

    python3 scripts/tools/selftest.py

Checks (no network, no model calls):
  1. every Python file compiles
  2. config.example.json parses and keeps the keys the code relies on
  3. both prompt languages render with a synthetic config (no {{leftovers}})
  4. missing backend ids fail loudly instead of producing an empty tool name
  5. the committed demo screenshot is a real PNG
PowerShell files are parsed by the CI workflow on the Windows runner.
"""
import compileall
import io
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FAILS = []


def check(ok, name, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (("  <- " + detail) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main():
    # 1. compile
    ok = compileall.compile_dir(os.path.join(ROOT, "scripts"), quiet=1, force=True)
    check(bool(ok), "python files compile")

    # 2. example config
    path = os.path.join(ROOT, "config.example.json")
    try:
        with io.open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        ok = all(k in cfg for k in ("vault", "dida", "task_tools", "prompt_lang", "schedule"))
    except ValueError as e:
        cfg, ok = {}, False
        check(False, "config.example.json parses", str(e))
    check(ok, "config.example.json has required keys")

    # 3/4. render both languages
    good = {"dida": {"inbox_project_id": "inboxTEST", "inbox_column_id": "colTEST"}}
    bad = {"dida": {"inbox_project_id": "", "inbox_column_id": ""}}
    for name, payload, expect in (("valid ids", good, 0), ("missing ids", bad, 2)):
        cfg_path = os.path.join(tempfile.mkdtemp(), "cfg.json")
        with io.open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        env = dict(os.environ, WORKLOG_CONFIG=cfg_path)
        for lang in ("zh", "en"):
            out = os.path.join(tempfile.mkdtemp(), "rendered.md")
            r = subprocess.run(
                [sys.executable, os.path.join(ROOT, "scripts", "render_prompt.py"),
                 "--template", os.path.join(ROOT, "scripts", "worklog_prompt.%s.md" % lang),
                 "--out", out],
                capture_output=True, env=env)
            detail = r.stderr.decode("utf-8", "replace")[:200]
            check(r.returncode == expect, "render %s (%s)" % (lang, name), detail)
            if expect == 0 and r.returncode == 0:
                with io.open(out, encoding="utf-8") as f:
                    text = f.read()
                check("{{" not in text, "no unresolved placeholders (%s)" % lang)

    # 5. demo screenshot
    png = os.path.join(ROOT, "docs", "demo-diary.png")
    sig = b""
    if os.path.exists(png):
        with open(png, "rb") as f:
            sig = f.read(8)
    check(sig == b"\x89PNG\r\n\x1a\n", "demo screenshot is a PNG")

    print("\n%d failed" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
