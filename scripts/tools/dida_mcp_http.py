#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过 HTTP 直连 dida365 MCP（复用 Claude Code 已存的 OAuth token）。

用途：当会话里 MCP 工具没有被注册/加载（ToolSearch 查不到 mcp__dida365__*）时，
用这个脚本直接调 MCP 的 tools/call，参数与 MCP 工具完全一致。

用法：
    python3 dida_mcp_http.py <tool_name> '<json_args>'
    python3 dida_mcp_http.py list_completed_tasks_by_date '{"search":{...},"client_timezone":"Asia/Shanghai"}'

输出：打印工具返回的原始 JSON（UTF-8）。
"""
import sys, io, os, json, re, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wl_config

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

CRED = wl_config.expand(wl_config.CFG['dida']['credentials'])
KEY = os.environ.get('WORKLOG_DIDA_MCP_KEY') or (wl_config.CFG['dida'].get('mcp_key') or '')


def load_token():
    if not KEY:
        raise SystemExit('set dida.mcp_key in config.json (e.g. "dida365|<id>") '
                         'or the WORKLOG_DIDA_MCP_KEY environment variable')
    d = json.load(open(CRED, encoding='utf-8'))
    return d['mcpOAuth'][KEY]['accessToken'], d['mcpOAuth'][KEY]['serverUrl'].rstrip('/')


def parse_body(raw, ctype):
    """解析 JSON 或 SSE 响应体，返回 JSON-RPC 消息列表。"""
    text = raw.decode('utf-8', errors='replace')
    msgs = []
    if 'text/event-stream' in (ctype or ''):
        buf = []
        for line in text.splitlines():
            if line.startswith('data:'):
                buf.append(line[5:].strip())
            elif line.strip() == '' and buf:
                try:
                    msgs.append(json.loads('\n'.join(buf)))
                except Exception:
                    pass
                buf = []
        if buf:
            try:
                msgs.append(json.loads('\n'.join(buf)))
            except Exception:
                pass
    else:
        try:
            msgs.append(json.loads(text))
        except Exception:
            for line in text.splitlines():
                line = line.strip()
                if line.startswith('{'):
                    try:
                        msgs.append(json.loads(line))
                    except Exception:
                        pass
    return msgs


def post(url, payload, token, session=None, extra_headers=None):
    data = json.dumps(payload).encode('utf-8')
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream',
        'Authorization': 'Bearer ' + token,
    }
    if session:
        headers['Mcp-Session-Id'] = session
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return parse_body(r.read(), r.headers.get('Content-Type', '')), r.headers
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'replace')
        raise SystemExit('HTTP %s: %s' % (e.code, body[:500]))


def main():
    if len(sys.argv) < 3:
        raise SystemExit('usage: dida_mcp_http.py <tool> <json-args>')
    tool = sys.argv[1]
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    token, base = load_token()

    init = {
        'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
        'params': {
            'protocolVersion': '2024-11-05',
            'capabilities': {},
            'clientInfo': {'name': 'worklog-helper', 'version': '1.0'},
        },
    }
    msgs, hdrs = post(base + '/', init, token)
    session = hdrs.get('Mcp-Session-Id') or hdrs.get('mcp-session-id')

    # 发送 initialized 通知（不需要回包，失败忽略）
    try:
        post(base + '/', {'jsonrpc': '2.0', 'method': 'notifications/initialized'}, token, session)
    except SystemExit:
        pass

    call = {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
            'params': {'name': tool, 'arguments': args}}
    msgs, _ = post(base + '/', call, token, session)

    for m in msgs:
        if m.get('id') == 2:
            if 'error' in m:
                print(json.dumps(m['error'], ensure_ascii=False))
                raise SystemExit(1)
            res = m.get('result', {})
            # 展平 text 内容
            if isinstance(res, dict) and 'content' in res:
                parts = []
                for c in res['content']:
                    if c.get('type') == 'text':
                        parts.append(c.get('text', ''))
                out = '\n'.join(parts)
                try:
                    parsed = json.loads(out)
                    out = json.dumps(parsed, ensure_ascii=False)
                except Exception:
                    pass
                print(out)
            else:
                print(json.dumps(res, ensure_ascii=False))
            return
    print(json.dumps(msgs, ensure_ascii=False))


if __name__ == '__main__':
    main()
