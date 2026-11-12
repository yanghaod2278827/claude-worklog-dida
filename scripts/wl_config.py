# -*- coding: utf-8 -*-
"""Shared config loader. One optional `config.json` at the repo root.

Resolution order (later wins):
    DEFAULTS -> <repo>/config.json -> $WORKLOG_CONFIG (if set, replaces the file)

Keep this module dependency-free (json + os): the whole project is stdlib-only.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULTS = {
    "vault": "~/ObsidianVault",
    "daily_note_dir": "~/ObsidianVault",
    "legacy_daily_dir": "~/ObsidianVault/日记",
    "weekly_dir": "~/ObsidianVault/07-日记",
    "claude_projects": "~/.claude/projects",
    # Empty list -> every fixed drive on Windows (tests os.path.isdir anyway).
    "scan_roots": [],
    "scan_skip": [],
    "timezone": "Asia/Shanghai",
    "tz_offset": "+0800",
    "task_manager": "dida365",
    # Tool names resolved into the prompt by render_prompt.py. Point these at
    # another MCP backend without touching the rules text.
    "task_tools": {
        "list_completed": "mcp__dida365__list_completed_tasks_by_date",
        "add": "mcp__dida365__batch_add_tasks",
        "update": "mcp__dida365__batch_update_tasks",
    },
    "dida": {
        "credentials": "~/.claude/.credentials.json",
        "mcp_key": "",
        "inbox_project_id": "",
        "inbox_column_id": "",
    },
    "prompt_lang": "zh",
    "claude": {
        "command": "claude",
        "cost_script": "~/.claude/scripts/cc_cny_peak.py",
        "max_runtime_min": 10,
    },
    "schedule": {
        "task_folder": "\\个人自动化\\",
        "worklog_task": "ClaudeCode-DailyWorkLog",
        "weekly_task": "ClaudeCode-WeeklySummary",
    },
}


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load():
    path = os.environ.get("WORKLOG_CONFIG") or os.path.join(ROOT, "config.json")
    data = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except ValueError as e:
            raise SystemExit("config.json is not valid JSON: %s" % e)
    return _merge(DEFAULTS, data)


def expand(p):
    """~ / %VAR% / $VAR -> absolute path. Empty stays empty."""
    if not p:
        return p
    return os.path.abspath(os.path.expanduser(os.path.expandvars(str(p))))


CFG = load()

VAULT = expand(CFG["vault"])
DAILY_NOTE_DIR = expand(CFG["daily_note_dir"])
LEGACY_DAILY_DIR = expand(CFG["legacy_daily_dir"])
WEEKLY_DIR = expand(CFG["weekly_dir"])
CLAUDE_PROJECTS = expand(CFG["claude_projects"])
DATA_DIR = os.path.join(ROOT, "data")
