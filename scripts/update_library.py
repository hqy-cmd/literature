#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from datetime import datetime
from html.parser import HTMLParser

BASE_DIR = Path.home() / 'Desktop' / '文献管理html'
LIB_DIR = BASE_DIR / 'literature-library'
PAPERS_JSON = LIB_DIR / 'papers.json'
INDEX_HTML = LIB_DIR / 'index.html'
FILES_DIR = LIB_DIR / 'files'
INCOMING_DIR = BASE_DIR / 'incoming'
PROCESSED_DIR = BASE_DIR / 'processed'
SERVER_PORT = 8765
DEPLOY_CONFIG = BASE_DIR / 'config' / 'deploy_config.json'

MENU_GROUPS = {
    '灵巧手': ['机器人抓取', '视觉触觉融合', '多智能体强化学习'],
    '脑肿瘤': ['脑组织', '电免疫治疗', '可注射水凝胶', '生物可吸收材料'],
    '肿瘤消融': ['温度成像', '荧光纳米温度计']
}

FLAT_COLLECTIONS = sorted({k for k in MENU_GROUPS} | {x for v in MENU_GROUPS.values() for x in v})

COLLECTION_RULES = [
    ('脑组织', ['brain tissue', 'brain', '脑组织', '脑部']),
    ('脑肿瘤', ['glioblastoma', 'brain tumor', 'glioma', '脑肿瘤', '胶质母细胞瘤']),
    ('肿瘤消融', ['tumor ablation', 'microwave ablation', 'thermal ablation', '肿瘤消融', '消融']),
    ('温度成像', ['temperature imaging', 'thermometer', 'thermometry', '温度成像', '测温']),
    ('荧光纳米温度计', ['nanothermometer', 'fluorescence', '荧光纳米温度计', '荧光温度计']),
    ('灵巧手', ['dexterous hand', 'multi-fingered hand', '灵巧手', '多指手']),
    ('机器人抓取', ['grasp', 'grasping', 'robotic hand', '机器人抓取', '抓取']),
    ('视觉触觉融合', ['visuo-tactile', 'visual and tactile', 'tactile feedback', '视觉触觉', '触觉反馈']),
    ('多智能体强化学习', ['multi-agent deep reinforcement learning', 'madrl', 'maddpg', 'reinforcement learning', '多智能体强化学习', '强化学习']),
    ('可注射水凝胶', ['injectable hydrogel', 'injectable conductive hydrogel', '可注射水凝胶', '导电水凝胶']),
    ('生物可吸收材料', ['bioresorbable', 'biodegradable', '生物可吸收', '可降解材料']),
    ('电免疫治疗', ['electroimmunotherapy', 'electrotherapy', '电免疫治疗', '电治疗'])
]

HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>__TITLE__</title>
  <style>
    :root { --bg:#f6f8fc; --panel:#fff; --text:#18212f; --muted:#667085; --line:#d7deea; --accent:#246bff; --accent-soft:#eef4ff; --tag:#eef2f7; --shadow:0 8px 24px rgba(16,24,40,.06); }
    * { box-sizing:border-box; } body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Noto Sans SC","Helvetica Neue",Arial,sans-serif; background:var(--bg); color:var(--text); line-height:1.6; }
    .layout { display:grid; grid-template-columns:300px 1fr; min-height:100vh; }
    .sidebar { background:var(--panel); border-right:1px solid var(--line); padding:18px 14px; position:sticky; top:0; height:100vh; overflow:auto; }
    .search { width:100%; border:1px solid var(--line); border-radius:12px; padding:12px 14px; font-size:15px; margin-bottom:12px; }
    .statbar { display:flex; gap:8px; flex-wrap:wrap; margin:0 6px 14px; } .pill { background:var(--accent-soft); color:var(--accent); border-radius:999px; padding:6px 10px; font-size:12px; font-weight:700; }
    details.group { border:1px solid var(--line); border-radius:14px; background:#fff; margin:10px 0; overflow:hidden; }
    details.group>summary { cursor:pointer; list-style:none; padding:12px 14px; font-weight:800; background:#fbfcff; } details.group>summary::-webkit-details-marker { display:none; }
    .menu-body { padding:10px; display:grid; gap:8px; }
    .filter-btn { width:100%; text-align:left; border:1px solid var(--line); background:#fff; color:var(--text); border-radius:12px; padding:10px 12px; cursor:pointer; font-size:14px; display:flex; justify-content:space-between; align-items:center; }
    .filter-btn.active { border-color:var(--accent); color:var(--accent); background:var(--accent-soft); }
    .sub-list { display:grid; gap:6px; margin-top:4px; padding-left:6px; } .sub-list .filter-btn { font-size:13px; padding:9px 11px; }
    .main { padding:20px 18px 40px; } .hero { background:linear-gradient(180deg,#ffffff 0%,#f9fbff 100%); border:1px solid var(--line); border-radius:22px; padding:14px 18px; box-shadow:var(--shadow); margin-bottom:16px; }
    .hero-tools { display:flex; gap:10px; flex-wrap:wrap; align-items:center; } .ghost { border:1px solid var(--line); background:#fff; border-radius:12px; padding:10px 12px; font-size:14px; color:var(--text); cursor:pointer; }
    .ghost-label { cursor:pointer; }
    .list { display:grid; gap:12px; } .card { background:#fff; border:1px solid var(--line); border-radius:18px; padding:16px; box-shadow:var(--shadow); } .title { font-size:19px; font-weight:800; margin:0 0 8px; }
    .meta { color:var(--muted); font-size:13px; display:flex; gap:8px 12px; flex-wrap:wrap; margin-bottom:10px; } .summary { font-size:15px; margin-bottom:12px; } .tags { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:12px; }
    .tag { background:var(--tag); color:#314155; border-radius:999px; padding:4px 10px; font-size:12px; } .actions { display:flex; flex-wrap:wrap; gap:8px; margin:8px 0 2px; } .link-btn { display:inline-flex; align-items:center; border:1px solid var(--line); border-radius:10px; padding:8px 12px; text-decoration:none; color:var(--accent); background:#fff; font-size:14px; font-weight:700; }
    details.paper-detail { border-top:1px dashed var(--line); padding-top:10px; margin-top:8px; } details.paper-detail summary { cursor:pointer; color:var(--accent); font-weight:700; list-style:none; } details.paper-detail summary::-webkit-details-marker { display:none; } .empty { color:var(--muted); text-align:center; padding:42px 16px; background:#fff; border:1px dashed var(--line); border-radius:16px; }
    @media (max-width:900px) { .layout { grid-template-columns:1fr; } .sidebar { position:relative; height:auto; border-right:none; border-bottom:1px solid var(--line); } }
  </style>
</head>
<body>
  <div class="layout">
    <aside class="sidebar">
      <input id="searchInput" class="search" placeholder="搜索标题、摘要、作者、标签…" />
      <div class="statbar"><span class="pill" id="paperCount">0 篇</span><span class="pill" id="collectionCount">0 类</span></div>
      <details class="group" open><summary>研究目录</summary><div class="menu-body" id="menuTree"></div></details>
    </aside>
    <main class="main">
      <section class="hero"><div class="hero-tools"><button type="button" class="ghost" id="clearFilterBtn">清空筛选</button><button type="button" class="ghost ghost-label" id="currentFilterLabel">当前：全部</button></div></section>
      <section id="paperList" class="list"></section>
    </main>
  </div>
  <script id="embeddedData" type="application/json">__EMBEDDED_DATA__</script>
  <script>
    const data = JSON.parse(document.getElementById('embeddedData').textContent.trim());
    const menuGroups = data.menu_groups || {};
    const state = { allPapers: Array.isArray(data.papers) ? data.papers : [], keyword:'', selectedFilter:'全部' };
    const el = { searchInput:document.getElementById('searchInput'), paperList:document.getElementById('paperList'), menuTree:document.getElementById('menuTree'), paperCount:document.getElementById('paperCount'), collectionCount:document.getElementById('collectionCount'), clearFilterBtn:document.getElementById('clearFilterBtn'), currentFilterLabel:document.getElementById('currentFilterLabel') };
    const safeText = (v,f='未提供') => v===null||v===undefined||String(v).trim()==='' ? f : String(v).trim();
    const normalizeList = v => !v ? [] : Array.isArray(v) ? v.filter(Boolean) : [String(v)];
    const getCollections = p => normalizeList(p.collections && p.collections.length ? p.collections : [p.category]);
    const countByName = name => state.allPapers.filter(p => getCollections(p).includes(name) || p.category===name).length;
    function matchesKeyword(p, keyword) { if(!keyword) return true; const hay=[p.title,p.authors,p.year,p.category,getCollections(p).join(' '),normalizeList(p.tags).join(' '),p.abstract_original,p.abstract_summary_zh,p.filename].join(' ').toLowerCase(); return hay.includes(keyword.toLowerCase()); }
    function matchesFilter(p) { if(state.selectedFilter==='全部') return true; return p.category===state.selectedFilter || getCollections(p).includes(state.selectedFilter); }
    function filteredPapers() { return state.allPapers.filter(p => matchesFilter(p) && matchesKeyword(p, state.keyword)); }
    function resetFilters() {
      state.keyword='';
      state.selectedFilter='全部';
      el.searchInput.value='';
      renderMenu();
      renderPapers();
    }
    function renderMenu() {
      const topCount = Object.keys(menuGroups).length;
      el.collectionCount.textContent = `${topCount} 类`;
      let html = `<button type="button" class="filter-btn ${state.selectedFilter==='全部'?'active':''}" data-name="全部"><span>全部</span><span>${state.allPapers.length}</span></button>`;
      for (const [top, children] of Object.entries(menuGroups)) {
        const topActive = state.selectedFilter===top ? 'active' : '';
        html += `<details class="group" open><summary>${top}</summary><div class="menu-body"><button type="button" class="filter-btn ${topActive}" data-name="${top}"><span>${top}</span><span>${countByName(top)}</span></button><div class="sub-list">`;
        children.forEach(child => {
          const active = state.selectedFilter===child ? 'active' : '';
          html += `<button type="button" class="filter-btn ${active}" data-name="${child}"><span>${child}</span><span>${countByName(child)}</span></button>`;
        });
        html += `</div></div></details>`;
      }
      el.menuTree.innerHTML = html;
      el.menuTree.querySelectorAll('.filter-btn').forEach(btn => btn.addEventListener('click', () => { state.selectedFilter = btn.dataset.name; renderMenu(); renderPapers(); }));
      el.currentFilterLabel.textContent = `当前：${state.selectedFilter}`;
    }
    function renderPapers() {
      const papers = filteredPapers();
      el.paperCount.textContent = `${papers.length} 篇`;
      if (!papers.length) { el.paperList.innerHTML = '<div class="empty">当前筛选条件下没有文献。</div>'; return; }
      el.paperList.innerHTML = papers.map(p => {
        const authors = Array.isArray(p.authors) ? p.authors.join('、') : safeText(p.authors, '作者未提取');
        const collections = getCollections(p);
        const tags = normalizeList(p.tags).filter(t => !collections.includes(t));
        const href = p.file_url || p.file_path || '';
        return `<article class="card"><h2 class="title">${safeText(p.title, safeText(p.filename, '未命名文献'))}</h2><div class="meta"><span>一级类目：${safeText(p.category, '未分类')}</span><span>作者：${authors}</span><span>年份：${safeText(p.year, '未提取')}</span><span>加入时间：${safeText(p.added_at, '未记录')}</span></div><div class="summary">${safeText(p.abstract_summary_zh, '未生成概括性摘要说明')}</div><div class="tags">${collections.map(t => `<span class="tag">${t}</span>`).join('')}${tags.map(t => `<span class="tag">${t}</span>`).join('')}</div><div class="actions">${href ? `<a class="link-btn" href="${encodeURI(href)}" target="_self">打开原文</a>` : ''}</div><details class="paper-detail"><summary>查看原始摘要</summary><div>${safeText(p.abstract_original, '未提取到摘要')}</div></details><details class="paper-detail"><summary>查看补充信息</summary><div>原始文件名：${safeText(p.filename, '未记录')}</div><div>来源备注：${safeText(p.source_note, '未记录')}</div><div>原文路径：${safeText(p.file_path || p.file_url, '未记录')}</div></details></article>`;
      }).join('');
    }
    el.searchInput.addEventListener('input', e => { state.keyword = e.target.value.trim(); renderPapers(); });
    el.clearFilterBtn.addEventListener('click', resetFilters);
    el.currentFilterLabel.addEventListener('click', resetFilters);
    renderMenu(); renderPapers();
  </script>
</body>
</html>'''

class SimpleHTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
    def handle_data(self, data):
        if data.strip():
            self.parts.append(data.strip())
    def get_text(self):
        return '\n'.join(self.parts)

def ensure_dirs():
    LIB_DIR.mkdir(parents=True, exist_ok=True)
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    if not PAPERS_JSON.exists():
        save_library({'version': 3, 'library_name': 'agent文献库', 'menu_groups': MENU_GROUPS, 'collections': FLAT_COLLECTIONS, 'papers': []})

def load_library():
    ensure_dirs()
    return json.loads(PAPERS_JSON.read_text(encoding='utf-8'))

def save_library(data):
    PAPERS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def clean_text(text):
    text = text.replace('\x00', ' ')
    text = re.sub(r'\r\n?', '\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def read_txt(path):
    for enc in ('utf-8', 'utf-8-sig', 'gb18030', 'latin-1'):
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return ''

def read_html(path):
    raw = read_txt(path)
    parser = SimpleHTMLStripper()
    parser.feed(raw)
    return parser.get_text()

def read_docx(path):
    try:
        from xml.etree import ElementTree as ET
        with zipfile.ZipFile(path) as z:
            xml = z.read('word/document.xml')
        root = ET.fromstring(xml)
        texts = [node.text for node in root.iter() if node.text]
        return '\n'.join(texts)
    except Exception:
        return ''

def read_pdf(path):
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        text = '\n'.join((page.extract_text() or '') for page in reader.pages)
        if text.strip():
            return text
    except Exception:
        pass
    try:
        import fitz
        doc = fitz.open(str(path))
        text = '\n'.join((doc.load_page(i).get_text('text') or '') for i in range(doc.page_count))
        if text.strip():
            return text
    except Exception:
        pass
    try:
        out = subprocess.run(['pdftotext', str(path), '-'], capture_output=True, text=True, check=False)
        return out.stdout or ''
    except Exception:
        return ''

def extract_text(path):
    suffix = path.suffix.lower()
    if suffix in {'.txt', '.md'}:
        return read_txt(path)
    if suffix in {'.html', '.htm'}:
        return read_html(path)
    if suffix == '.docx':
        return read_docx(path)
    if suffix == '.pdf':
        return read_pdf(path)
    return ''

def maybe_unpack_zip(path):
    unpack_dir = INCOMING_DIR / (path.stem + '_unzipped')
    unpack_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(path, 'r') as zf:
        zf.extractall(unpack_dir)
    return [p for p in unpack_dir.rglob('*') if p.is_file()]

def fallback_title_from_filename(filename):
    stem = Path(filename or '').stem
    stem = re.sub(r'---[0-9a-fA-F-]{8,}$', '', stem)
    stem = re.sub(r'(?i)_\d{4}_[A-Za-z]+$', '', stem)
    stem = re.sub(r'(?i)_[A-Za-z]+$', '', stem)
    stem = re.sub(r'_[\u4e00-\u9fff]{2,4}$', '', stem)
    stem = stem.replace('_', ' ').replace('ﬁ', 'fi').replace('ﬃ', 'ffi').replace('ﬀ', 'ff')
    stem = re.sub(r'\s+', ' ', stem).strip(' -—_:：,.;()[]')
    return stem


def normalize_title(title, fallback=''):
    title = clean_text(title)
    title = title.replace('ﬁ', 'fi').replace('ﬃ', 'ffi').replace('ﬀ', 'ff')
    title = re.sub(r'\s+', ' ', title)
    title = re.sub(r'(?i)^contents lists available at\s*', '', title)
    title = re.sub(r'(?i)^available online\b.*$', '', title)
    title = re.sub(r'(?i)^research article\b[:\s-]*', '', title)
    title = re.sub(r'(?i)^article\b[:\s-]*', '', title)
    title = re.sub(r'(?i)^www\.[^\s]+\s*', '', title)
    title = re.sub(r'(?i)^li et al\.,\s*[^\n]*$', '', title)
    title = re.sub(r'(?i)^photoacoustics\s+\d+.*$', '', title)
    title = re.sub(r'(?i)^ieee transactions on [^\n]+$', '', title)
    title = re.sub(r'(?i)^international journal of [^\n]+$', '', title)
    title = re.sub(r'(?i)^school code[:：].*$', '', title)
    title = re.sub(r'(?i)^学校代码[:：].*$', '', title)
    title = re.sub(r'(?i)^长春理工大学学报（自然科学版）.*$', '', title)
    title = re.sub(r'(?i)^journal of [^\n]+$', '', title)
    title = re.sub(r'\b(Vol\.?\s*\d+|No\.?\s*\d+|\d{4})\b', '', title)
    title = re.sub(r'\s+', ' ', title).strip(' -—_:：,.;()[]')
    bad = [
        r'(?i)^(sciencedirect|photoacoustics|journal homepage|issn)',
        r'(?i)^robot\.\s*\d+',
        r'(?i)^available online',
        r'(?i)^contents lists available',
    ]
    if not title or any(re.search(p, title) for p in bad):
        return fallback
    return title


def detect_title(text, fallback):
    lines = [re.sub(r'\s+', ' ', ln.strip()) for ln in text.splitlines() if ln.strip()]
    skip = re.compile(
        r'^(research article|article|www\.|adv\.|doi\b|abstract\b|摘要\b|keywords?\b|关键词\b|table\b|figure\b|contents lists available|available online|journal homepage|school code|学校代码|分类号|密级|学号|收稿日期|基金项目|作者简介|通讯作者|目\s*录|第[一二三四五六七八九十]+章|introduction\b)',
        re.I,
    )
    candidates = []
    for idx, ln in enumerate(lines[:40]):
        compact = normalize_title(ln, '')
        if not compact:
            continue
        if skip.match(ln):
            continue
        if len(compact) <= 8 or len(compact) >= 220:
            continue
        score = 0
        if re.search(r'[\u4e00-\u9fff]{6,}', compact):
            score += 4
        if re.search(r'[A-Za-z]', compact):
            score += 2
        if ':' in compact or '：' in compact:
            score += 1
        if 20 <= len(compact) <= 140:
            score += 2
        if re.search(r'(university|journal|issn|science direct|photoacoustics|ieee transactions|school code|学校代码|分类号|密级|学号)', compact, re.I):
            score -= 5
        if idx < 12:
            score += 2
        if idx < 6:
            score += 1
        candidates.append((score, idx, compact))
        if idx + 1 < len(lines[:40]) and len(compact.split()) <= 10:
            merged = normalize_title(compact + ' ' + lines[idx + 1], '')
            if 12 <= len(merged) <= 220 and not skip.match(merged):
                merged_score = score + 1
                if re.search(r'(university|journal|issn|science direct|photoacoustics|ieee transactions)', merged, re.I):
                    merged_score -= 5
                candidates.append((merged_score, idx, merged))
    if candidates:
        candidates.sort(key=lambda x: (-x[0], x[1], len(x[2])))
        return candidates[0][2]
    return normalize_title(fallback, fallback)

def detect_year(text):
    m = re.search(r'\b(19\d{2}|20\d{2})\b', text)
    return m.group(1) if m else ''

def detect_authors(text):
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines[:12]:
        compact = re.sub(r'\s+', ' ', ln)
        if len(compact) > 240 or len(compact) < 8:
            continue
        if re.search(r'www\.|doi|abstract|摘要|university|journal|department|introduction|research article', compact, re.I):
            continue
        if compact.count(',') >= 2:
            names = [x.strip(' *') for x in re.split(r',|;| and |、|&', compact) if x.strip()]
            alpha_like = [n for n in names if re.search(r'[A-Za-z\u4e00-\u9fff]', n)]
            if 2 <= len(alpha_like) <= 20:
                return alpha_like[:12]
    return []

def extract_abstract(text):
    text = clean_text(text)
    patterns = [
        r'(?is)\babstract\b[:\s]*(.+?)(?=\n\s*\bkeywords?\b|\n\s*1[\.\s]+|\n\s*introduction\b|$)',
        r'(?is)摘要[:：\s]*(.+?)(?=\n\s*关键词|\n\s*1[\.、\s]+|\n\s*引言|$)'
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            abs_text = clean_text(m.group(1))
            if len(abs_text) > 80:
                return abs_text
    paras = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    if paras:
        joined = ' '.join(paras[:2])
        return joined[:1200] if len(joined) > 80 else ''
    return ''

def detect_collections(title, abstract_text, text):
    source = f'{title}\n{abstract_text}\n{text[:2000]}'.lower()
    found = []
    for name, keywords in COLLECTION_RULES:
        if any(k.lower() in source for k in keywords):
            found.append(name)
    return found or ['其他']

def primary_from_collections(collections):
    for top in MENU_GROUPS:
        if top in collections:
            return top
    return collections[0] if collections else '其他'

def attach_top_level(collections):
    result = list(dict.fromkeys(collections))
    for top, children in MENU_GROUPS.items():
        if top in result:
            continue
        if any(child in result for child in children):
            result.insert(0, top)
    return list(dict.fromkeys(result))

def summarize_zh(title, primary, abstract_text):
    if not abstract_text:
        return f'这篇文献围绕“{title}”展开，当前未能稳定抽取到原始摘要。结合标题和正文前部内容，它大致属于“{primary}”相关研究，可先作为待补充条目纳入文献库。'
    return f'这篇文献主要围绕“{primary}”相关问题展开，核心对象是“{title}”所对应的方法、材料或系统。作者重点讨论了该方向中的关键挑战、解决思路以及验证结果，适合用来快速把握这项工作的研究重点和应用价值。'

def detect_tags(text, collections):
    tags = []
    low = text.lower()
    keyword_map = {
        '实验验证': ['experiment', 'evaluation', '实验', '验证'],
        '系统设计': ['system design', 'architecture', '系统', '架构'],
        '算法': ['algorithm', 'optimization', 'policy', '算法', '优化'],
        '应用': ['application', 'deployment', 'clinical', '应用', '临床']
    }
    for tag, kws in keyword_map.items():
        if any(k in low for k in kws):
            tags.append(tag)
    for c in collections:
        if c not in tags:
            tags.append(c)
    return tags[:10]

def build_record(path, text):
    title = detect_title(text, fallback_title_from_filename(path.name))
    abstract_original = extract_abstract(text) or '未提取到摘要'
    collections = attach_top_level(detect_collections(title, '' if abstract_original == '未提取到摘要' else abstract_original, text))
    primary = primary_from_collections(collections)
    library_copy = FILES_DIR / path.name
    if not library_copy.exists():
        shutil.copy2(path, library_copy)
    rel_path = f'files/{path.name}'
    return {
        'id': f'{path.name}-{int(path.stat().st_mtime)}',
        'title': title,
        'authors': detect_authors(text),
        'year': detect_year(text),
        'category': primary,
        'collections': collections,
        'tags': detect_tags(text, collections),
        'abstract_original': abstract_original,
        'abstract_summary_zh': summarize_zh(title, primary, '' if abstract_original == '未提取到摘要' else abstract_original),
        'filename': path.name,
        'source_note': '自动解析导入',
        'added_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'file_path': rel_path,
        'file_url': rel_path
    }

def ensure_structure(data):
    data['version'] = max(int(data.get('version', 1)), 3)
    data['library_name'] = 'agent文献库'
    data['menu_groups'] = MENU_GROUPS
    seen = set()
    for paper in data.get('papers', []):
        cols = paper.get('collections') or []
        if not cols:
            cols = [paper.get('category', '其他')]
        cols = attach_top_level(cols)
        paper['collections'] = cols
        paper['category'] = primary_from_collections(cols)
        fallback_title = fallback_title_from_filename(paper.get('filename', ''))
        paper['title'] = normalize_title(paper.get('title', ''), fallback_title)
        seen.update(cols)
    data['collections'] = sorted(seen | set(FLAT_COLLECTIONS))
    return data

def render_html(data):
    embedded = json.dumps(data, ensure_ascii=False, indent=2)
    return HTML_TEMPLATE.replace('__TITLE__', data.get('library_name', 'agent文献库')).replace('__EMBEDDED_DATA__', embedded)

def load_deploy_config():
    if not DEPLOY_CONFIG.exists():
        return None
    try:
        return json.loads(DEPLOY_CONFIG.read_text(encoding='utf-8'))
    except Exception:
        return None

def auto_sync_to_remote():
    cfg = load_deploy_config()
    if not cfg or not cfg.get('enabled'):
        return {'enabled': False, 'ok': False, 'message': 'auto sync disabled'}
    user = cfg.get('user', 'admin')
    host = cfg.get('host')
    remote_path = cfg.get('remote_path', '/var/www/literature-library/')
    if not host:
        return {'enabled': True, 'ok': False, 'message': 'missing host'}
    sync_cmd = [
        'rsync', '-az', '--delete',
        str(LIB_DIR) + '/',
        f'{user}@{host}:{remote_path}'
    ]
    remote_fix = (
        f"find {remote_path} -type d -exec chmod 755 {{}} \\; && "
        f"find {remote_path} -type f -exec chmod 644 {{}} \\; && "
        f"systemctl reload caddy"
    )
    ssh_cmd = ['ssh', f'{user}@{host}', remote_fix]
    try:
        sync_out = subprocess.run(sync_cmd, capture_output=True, text=True, check=False)
        if sync_out.returncode != 0:
            return {
                'enabled': True,
                'ok': False,
                'message': (sync_out.stdout or sync_out.stderr).strip()[:500],
                'returncode': sync_out.returncode,
                'target': f'{user}@{host}:{remote_path}',
                'stage': 'rsync'
            }
        fix_out = subprocess.run(ssh_cmd, capture_output=True, text=True, check=False)
        ok = fix_out.returncode == 0
        return {
            'enabled': True,
            'ok': ok,
            'message': ((fix_out.stdout or '') + '\n' + (fix_out.stderr or '')).strip()[:500],
            'returncode': fix_out.returncode,
            'target': f'{user}@{host}:{remote_path}',
            'stage': 'post-deploy-fix'
        }
    except Exception as e:
        return {'enabled': True, 'ok': False, 'message': str(e)}

def move_processed(path):
    target = PROCESSED_DIR / path.name
    if path.resolve() != target.resolve() and not target.exists():
        shutil.move(str(path), str(target))

def main():
    ensure_dirs()
    data = ensure_structure(load_library())
    existing = {p.get('filename'): p for p in data.get('papers', [])}
    processed_count = 0
    abstract_ok = 0
    failures = []
    queue = []
    for p in INCOMING_DIR.rglob('*'):
        if p.is_file():
            if p.suffix.lower() == '.zip':
                try:
                    queue.extend(maybe_unpack_zip(p))
                except Exception as e:
                    failures.append({'file': p.name, 'reason': f'解压失败: {e}'})
            else:
                queue.append(p)
    for path in queue:
        if path.name.startswith('.') or path.name in existing:
            continue
        text = extract_text(path)
        if not text.strip():
            failures.append({'file': path.name, 'reason': '未读取到可用文本（可能是扫描件/图片版/不支持格式）'})
            continue
        text = clean_text(text)
        record = build_record(path, text)
        data.setdefault('papers', []).append(record)
        processed_count += 1
        if record['abstract_original'] != '未提取到摘要':
            abstract_ok += 1
        move_processed(path)
    data = ensure_structure(data)
    data['papers'] = sorted(data.get('papers', []), key=lambda x: x.get('added_at', ''), reverse=True)
    save_library(data)
    INDEX_HTML.write_text(render_html(data), encoding='utf-8')
    deploy_result = auto_sync_to_remote()
    report = {
        'processed_count': processed_count,
        'abstract_ok': abstract_ok,
        'top_groups': {k: sum(1 for p in data['papers'] if p.get('category') == k or k in p.get('collections', [])) for k in MENU_GROUPS},
        'papers_json_updated': True,
        'index_html_updated': True,
        'failures': failures,
        'service_url': f'http://127.0.0.1:{SERVER_PORT}/index.html',
        'auto_sync': deploy_result
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
