# -*- coding: utf-8 -*-
"""Render a prompt template with values from config.json.

Templates keep the backend-specific bits as placeholders so the same rules can
drive a different task manager without editing prose:

    {{LIST_COMPLETED}}  {{ADD_TASKS}}  {{UPDATE_TASKS}}
    {{INBOX_PROJECT_ID}}  {{INBOX_COLUMN_ID}}
    {{TIMEZONE}}  {{TZ_OFFSET}}

Usage:
    python3 render_prompt.py --template worklog_prompt.zh.md --out <rendered.md>
"""
import argparse
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wl_config  # noqa: E402

REQUIRED = ("LIST_COMPLETED", "ADD_TASKS", "UPDATE_TASKS")


def build_values():
    tools = wl_config.CFG.get("task_tools") or {}
    dida = wl_config.CFG.get("dida") or {}
    return {
        "LIST_COMPLETED": tools.get("list_completed", ""),
        "ADD_TASKS": tools.get("add", ""),
        "UPDATE_TASKS": tools.get("update", ""),
        "INBOX_PROJECT_ID": dida.get("inbox_project_id", ""),
        "INBOX_COLUMN_ID": dida.get("inbox_column_id", ""),
        "TIMEZONE": wl_config.CFG.get("timezone", "Asia/Shanghai"),
        "TZ_OFFSET": wl_config.CFG.get("tz_offset", "+0800"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with io.open(args.template, encoding="utf-8", newline=None) as f:
        text = f.read()

    values = build_values()
    missing = []
    for name in REQUIRED:
        if "{{%s}}" % name in text and not values[name]:
            missing.append("task_tools.%s" % name)
    for name in ("INBOX_PROJECT_ID", "INBOX_COLUMN_ID"):
        if "{{%s}}" % name in text and not values[name]:
            missing.append("dida.%s" % name.lower())

    if missing:
        sys.stderr.write(
            "prompt needs backend values that are empty in config.json: %s\n"
            "See README 'Adapters' for where to find them.\n" % ", ".join(missing))
        return 2

    for name, value in values.items():
        text = text.replace("{{%s}}" % name, str(value))
    leftovers = [n for n in values if "{{%s}}" % n in text]
    if leftovers:
        sys.stderr.write("unresolved placeholders: %s\n" % ", ".join(leftovers))
        return 2

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with io.open(args.out, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
