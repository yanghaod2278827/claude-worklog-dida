#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reset the completedTime of one task (maintenance tool).

Why this exists
---------------
Other clients can silently move an *old* completed task's `completedTime` to
"now". The Obsidian DidaSync plugin (v1.7.6) does exactly that: its
`updateTaskInDidaList()` ends with `if (task.status === 2) await
completeTaskInDida(task)`, i.e. every re-push of an already-completed task calls

    POST https://api.dida365.com/open/v1/project/{projectId}/task/{taskId}/complete

and the server stamps `completedTime = now`. Its "reverse completion" bookkeeping
re-pushes tasks that are missing from the remote *active* list — which is every
completed task — so old items periodically surface as "completed today".

Downstream effect: `list_completed_tasks_by_date` returns them for today, and the
hourly worklog agent faithfully writes them into the diary block (timeless line,
because they are all-day tasks).

Usage
-----
    # read-only: show the task and what would be written
    python3 tools/fix_task_completed_time.py --date 2026-11-18 --title 关键字

    # restore: completedTime = createdTime's HH:MM:SS on the original due date
    python3 tools/fix_task_completed_time.py --date 2026-11-18 --title 关键字 --apply

    # explicit timestamp
    python3 tools/fix_task_completed_time.py --date 2026-11-18 --title 关键字 \
        --completed 2026-07-23T00:08:00+0800 --apply

`--date` is the day the task currently shows up under (search window for the
completed list). Requires config.json (`dida.mcp_key`) — see tools/dida_mcp_http.py.
"""
import sys
import io
import os
import json
import argparse
import subprocess

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
HELPER = os.path.join(HERE, 'dida_mcp_http.py')


def call(tool, args, timeout=180):
    p = subprocess.run(
        [sys.executable, '-I', HELPER, tool, json.dumps(args, ensure_ascii=False)],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    if p.returncode != 0:
        raise SystemExit('MCP helper failed rc=%s: %s' % (p.returncode, (p.stderr or p.stdout)[:600]))
    return p.stdout.strip()


def parse_concat(text):
    """The MCP endpoint streams several concatenated JSON objects, not an array."""
    dec = json.JSONDecoder()
    out, i, n = [], 0, len(text)
    while i < n:
        while i < n and text[i] in ' \t\r\n':
            i += 1
        if i >= n:
            break
        obj, end = dec.raw_decode(text, i)
        out.append(obj)
        i = end
    return out


def find_task(day, title):
    raw = call('list_completed_tasks_by_date',
               {'search': {'fromDate': day, 'toDate': day}, 'client_timezone': 'Asia/Shanghai'})
    items = [o for o in parse_concat(raw) if isinstance(o, dict) and o.get('title')]
    return [t for t in items if title in (t.get('title') or '')]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', required=True, help='day the task currently appears under (yyyy-MM-dd)')
    ap.add_argument('--title', required=True, help='title substring (must match exactly one task)')
    ap.add_argument('--completed', default=None,
                    help='target completedTime, e.g. 2026-07-23T00:08:00+0800 '
                         '(default: createdTime HH:MM:SS on the original due date)')
    ap.add_argument('--apply', action='store_true', help='actually write (default: read-only)')
    a = ap.parse_args()

    hits = find_task(a.date, a.title)
    if len(hits) != 1:
        print('matched %d task(s), need exactly 1:' % len(hits))
        for t in hits:
            print('  ', t.get('id'), t.get('title'), t.get('completedTime'))
        raise SystemExit(2)

    t = hits[0]
    print('target task:')
    for k in ('id', 'projectId', 'title', 'content', 'startDate', 'dueDate', 'isAllDay',
              'status', 'completedTime', 'createdTime', 'etag'):
        print('  %-14s %s' % (k, t.get(k)))

    if not a.apply:
        print('\n[read-only] add --apply to write')
        return

    if a.completed:
        target = a.completed
    else:
        created = t.get('createdTime') or ''
        hhmmss = created[11:19] if len(created) >= 19 else '00:00:00'
        plan_day = (t.get('startDate') or created or a.date)[:10]
        # TZ suffix comes from the remote value when possible
        tz = created[19:] if len(created) > 19 else '+0800'
        target = '%sT%s%s' % (plan_day, hhmmss, tz)

    # update_task takes {task_id, task}; task must carry projectId + etag or the
    # API answers "resource_not_found: task not found" (misleading, see README).
    payload = {
        'task_id': t['id'],
        'task': {
            'projectId': t['projectId'],
            'id': t['id'],
            'etag': t.get('etag'),
            'status': 2,
            'completedTime': target,
            'startDate': t.get('startDate'),
            'dueDate': t.get('dueDate'),
            'isAllDay': bool(t.get('isAllDay')),
        },
    }
    print('\nwriting completedTime -> %s' % target)
    print(call('update_task', payload)[:800])

    still = find_task(a.date, a.title)
    print('\nverify: %d match(es) left in the %s completed list' % (len(still), a.date))
    for x in still:
        print('  ', x.get('id'), x.get('title'), x.get('completedTime'))


if __name__ == '__main__':
    main()
