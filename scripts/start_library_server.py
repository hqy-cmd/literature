#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import http.server
import socketserver
import webbrowser
from pathlib import Path

PORT = 8765
BASE_DIR = Path.home() / 'Desktop' / '文献管理html'
ROOT = BASE_DIR / 'literature-library'

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

with socketserver.TCPServer(('127.0.0.1', PORT), Handler) as httpd:
    url = f'http://127.0.0.1:{PORT}/index.html'
    print(url, flush=True)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    httpd.serve_forever()
