#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path.home() / 'Desktop' / '文献管理html'
LIB_DIR = BASE_DIR / 'literature-library'
PAPERS_JSON = LIB_DIR / 'papers.json'
UPDATE_SCRIPT = BASE_DIR / 'scripts' / 'update_library.py'
HOST = '127.0.0.1'
PORT = 8766

EDITABLE_FIELDS = {
    'title',
    'authors',
    'year',
    'category',
    'collections',
    'tags',
    'abstract_summary_zh',
    'source_note',
}

ARRAY_FIELDS = {'authors', 'collections', 'tags'}


def load_library():
    return json.loads(PAPERS_JSON.read_text(encoding='utf-8'))


def save_library(data):
    PAPERS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def normalize_array(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        parts = []
        for chunk in value.replace('\n', ',').split(','):
            s = chunk.strip()
            if s:
                parts.append(s)
        return parts
    return [str(value).strip()] if str(value).strip() else []


def normalize_updates(updates):
    normalized = {}
    for key, value in updates.items():
        if key not in EDITABLE_FIELDS:
            continue
        if key in ARRAY_FIELDS:
            normalized[key] = normalize_array(value)
        else:
            normalized[key] = '' if value is None else str(value).strip()
    return normalized


def update_paper(paper_id, updates):
    data = load_library()
    papers = data.get('papers', [])
    target = None
    for paper in papers:
        if paper.get('id') == paper_id:
            target = paper
            break
    if target is None:
        return False, {'ok': False, 'error': 'paper_not_found', 'id': paper_id}

    normalized = normalize_updates(updates)
    if not normalized:
        return False, {'ok': False, 'error': 'no_valid_updates', 'id': paper_id}

    locked = set(target.get('locked_fields') or [])
    for key, value in normalized.items():
        target[key] = value
        locked.add(key)
    target['manual_edit'] = True
    target['locked_fields'] = sorted(locked)
    if not target.get('source_note'):
        target['source_note'] = '网页人工校正'

    save_library(data)
    return True, {'ok': True, 'updated_id': paper_id, 'updated_fields': sorted(normalized.keys())}


def rebuild_and_sync():
    proc = subprocess.run(
        ['python3', str(UPDATE_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = (proc.stdout or '').strip()
    stderr = (proc.stderr or '').strip()
    parsed = None
    if stdout:
        try:
            parsed = json.loads(stdout)
        except Exception:
            parsed = {'raw_stdout': stdout[:2000]}
    return {
        'returncode': proc.returncode,
        'stdout': stdout[:2000],
        'stderr': stderr[:2000],
        'result': parsed,
        'ok': proc.returncode == 0,
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(200, {'ok': True})

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/health':
            self._send(200, {
                'ok': True,
                'papers_json': PAPERS_JSON.exists(),
                'update_script': UPDATE_SCRIPT.exists(),
            })
            return
        self._send(404, {'ok': False, 'error': 'not_found'})

    def do_POST(self):
        path = urlparse(self.path).path
        if path != '/api/papers/update':
            self._send(404, {'ok': False, 'error': 'not_found'})
            return

        length = int(self.headers.get('Content-Length', '0'))
        raw = self.rfile.read(length) if length else b'{}'
        try:
            payload = json.loads(raw.decode('utf-8'))
        except Exception:
            self._send(400, {'ok': False, 'error': 'invalid_json'})
            return

        paper_id = str(payload.get('id') or '').strip()
        updates = payload.get('updates') or {}
        if not paper_id:
            self._send(400, {'ok': False, 'error': 'missing_id'})
            return
        if not isinstance(updates, dict):
            self._send(400, {'ok': False, 'error': 'invalid_updates'})
            return

        ok, result = update_paper(paper_id, updates)
        if not ok:
            self._send(400, result)
            return

        rebuild = rebuild_and_sync()
        code = 200 if rebuild.get('ok') else 500
        self._send(code, {
            'ok': rebuild.get('ok', False),
            'update': result,
            'rebuild': rebuild,
        })


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f'library_api listening on http://{HOST}:{PORT}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
