#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import re
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

SEARCH_FIELDS = [
    'title',
    'authors',
    'year',
    'category',
    'collections',
    'tags',
    'abstract_original',
    'abstract_summary_zh',
    'filename',
    'source_note',
]

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


def paper_brief(paper):
    return {
        'id': paper.get('id'),
        'title': paper.get('title'),
        'authors': paper.get('authors', []),
        'year': paper.get('year'),
        'category': paper.get('category'),
        'collections': paper.get('collections', []),
        'tags': paper.get('tags', []),
        'filename': paper.get('filename'),
        'source_note': paper.get('source_note', ''),
    }


def search_papers(query, limit=20):
    query = (query or '').strip().lower()
    if not query:
        return []
    data = load_library()
    results = []
    for paper in data.get('papers', []):
        hay = []
        for key in SEARCH_FIELDS:
            value = paper.get(key)
            if isinstance(value, list):
                hay.extend(str(x) for x in value)
            elif value is not None:
                hay.append(str(value))
        text = ' '.join(hay).lower()
        if query in text:
            score = 0
            title = str(paper.get('title', '')).lower()
            if query in title:
                score += 5
            if query in str(paper.get('category', '')).lower():
                score += 2
            score += max(0, 1000 - text.find(query)) / 1000
            results.append((score, paper))
    results.sort(key=lambda x: (-x[0], str(x[1].get('added_at', ''))), reverse=False)
    return [paper_brief(p) for _, p in results[:limit]]


def parse_console_command(command):
    text = (command or '').strip()
    if not text:
        return {'mode': 'empty'}
    if text.startswith('<') and text.endswith('>'):
        inner = text[1:-1].strip()
        if inner.startswith('改'):
            payload = inner[1:].strip()
            m = re.match(r'(.+?)\s+(标题|作者|年份|分类|分类集|标签|摘要|备注)\s*[:：=]\s*(.+)', payload)
            if not m:
                return {'mode': 'invalid_command', 'raw': text, 'message': '修改命令格式错误'}
            paper_ref, field_zh, value = m.groups()
            field_map = {
                '标题': 'title',
                '作者': 'authors',
                '年份': 'year',
                '分类': 'category',
                '分类集': 'collections',
                '标签': 'tags',
                '摘要': 'abstract_summary_zh',
                '备注': 'source_note',
            }
            return {
                'mode': 'update',
                'paper_ref': paper_ref.strip(),
                'field': field_map[field_zh],
                'value': value.strip(),
            }
        if inner.startswith('删'):
            return {'mode': 'unsupported', 'raw': text, 'message': '第一版暂不支持删除'}
        if inner.startswith('增'):
            return {'mode': 'unsupported', 'raw': text, 'message': '第一版暂不支持新增'}
        return {'mode': 'invalid_command', 'raw': text, 'message': '未知命令'}
    return {'mode': 'search', 'query': text}


def find_paper_by_ref(paper_ref):
    data = load_library()
    paper_ref = (paper_ref or '').strip().lower()
    exact = None
    fuzzy = []
    for paper in data.get('papers', []):
        if paper_ref == str(paper.get('id', '')).lower():
            exact = paper
            break
        fields = [paper.get('title', ''), paper.get('filename', ''), paper.get('id', '')]
        text = ' '.join(str(x) for x in fields).lower()
        if paper_ref and paper_ref in text:
            fuzzy.append(paper)
    if exact:
        return exact, []
    if len(fuzzy) == 1:
        return fuzzy[0], []
    return None, [paper_brief(p) for p in fuzzy[:10]]


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

        length = int(self.headers.get('Content-Length', '0'))
        raw = self.rfile.read(length) if length else b'{}'
        try:
            payload = json.loads(raw.decode('utf-8'))
        except Exception:
            self._send(400, {'ok': False, 'error': 'invalid_json'})
            return

        if path == '/api/papers/update':
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
            return

        if path == '/api/console':
            command = str(payload.get('command') or '').strip()
            parsed = parse_console_command(command)
            mode = parsed.get('mode')
            if mode == 'empty':
                self._send(400, {'ok': False, 'error': 'empty_command'})
                return
            if mode == 'search':
                results = search_papers(parsed.get('query', ''))
                self._send(200, {'ok': True, 'mode': 'search', 'query': parsed.get('query', ''), 'results': results})
                return
            if mode == 'update':
                paper, candidates = find_paper_by_ref(parsed.get('paper_ref', ''))
                if not paper:
                    self._send(200, {
                        'ok': False,
                        'mode': 'update',
                        'error': 'paper_not_resolved',
                        'message': '没有唯一匹配到文献',
                        'candidates': candidates,
                    })
                    return
                ok, result = update_paper(paper.get('id'), {parsed['field']: parsed['value']})
                if not ok:
                    self._send(400, result)
                    return
                rebuild = rebuild_and_sync()
                code = 200 if rebuild.get('ok') else 500
                self._send(code, {
                    'ok': rebuild.get('ok', False),
                    'mode': 'update',
                    'target': paper_brief(paper),
                    'update': result,
                    'rebuild': rebuild,
                })
                return
            self._send(200, {'ok': False, **parsed})
            return

        self._send(404, {'ok': False, 'error': 'not_found'})


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f'library_api listening on http://{HOST}:{PORT}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
