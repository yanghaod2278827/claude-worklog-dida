#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 .ps1 补 UTF-8 BOM（幂等）。

为什么必须：PS 5.1 打开**无 BOM** 的脚本时按 GBK 解码，项目路径含中文，
会静默变成乱码，`Test-Path` 返回 False，脚本看似什么都没做。
用 Edit/Write 工具直接改 .ps1 会丢 BOM，所以改完跑一次这个。

用法: python ensure_bom.py <file.ps1> [more.ps1 ...]
"""
import sys, io, os

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BOM = b'\xef\xbb\xbf'

for p in sys.argv[1:]:
    with open(p, 'rb') as f:
        data = f.read()
    if data.startswith(BOM):
        print(f'BOM ok   {p}')
        continue
    # 顺带把 CRLF 统一（PS 对纯 LF 一般能吃，但混用容易出怪问题）
    text = data.decode('utf-8-sig')
    text = text.replace('\r\n', '\n').replace('\n', '\r\n')
    with open(p, 'wb') as f:
        f.write(BOM + text.encode('utf-8'))
    print(f'BOM added {p}')
