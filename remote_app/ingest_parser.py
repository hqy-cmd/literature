from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from html.parser import HTMLParser
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from .utils import build_list_summary, ensure_list, normalize_top_category, now_text


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".html", ".htm", ".zip"}

COLLECTION_RULES = [
    ("脑组织", ["brain tissue", "brain", "脑组织", "脑部"]),
    ("脑肿瘤", ["glioblastoma", "brain tumor", "glioma", "脑肿瘤"]),
    ("肿瘤消融", ["tumor ablation", "thermal ablation", "肿瘤消融", "消融"]),
    ("温度成像", ["temperature imaging", "thermometry", "温度成像", "测温"]),
    ("荧光纳米温度计", ["nanothermometer", "荧光纳米温度计", "荧光温度计"]),
    ("灵巧手", ["dexterous hand", "multi-fingered hand", "灵巧手"]),
    ("机器人抓取", ["grasp", "grasping", "robotic hand", "机器人抓取", "抓取"]),
    ("视觉触觉融合", ["visuo-tactile", "visual and tactile", "tactile", "视觉触觉"]),
    ("多智能体强化学习", ["multi-agent", "reinforcement learning", "多智能体强化学习"]),
    ("可注射水凝胶", ["injectable hydrogel", "可注射水凝胶", "导电水凝胶"]),
    ("生物可吸收材料", ["bioresorbable", "biodegradable", "生物可吸收"]),
    ("电免疫治疗", ["electroimmunotherapy", "electrotherapy", "电免疫治疗"]),
]


class SimpleHTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())

    def get_text(self) -> str:
        return "\n".join(self.parts)


def clean_text(text: str) -> str:
    text = (text or "").replace("\x00", " ")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def read_txt(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return ""


def read_html(path: Path) -> str:
    raw = read_txt(path)
    parser = SimpleHTMLStripper()
    parser.feed(raw)
    return parser.get_text()


def read_docx(path: Path) -> str:
    try:
        from xml.etree import ElementTree as ET

        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
        root = ET.fromstring(xml)
        texts = [node.text for node in root.iter() if node.text]
        return "\n".join(texts)
    except Exception:
        return ""


def read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        if text.strip():
            return text
    except Exception:
        pass
    try:
        import fitz

        doc = fitz.open(str(path))
        text = "\n".join((doc.load_page(i).get_text("text") or "") for i in range(doc.page_count))
        if text.strip():
            return text
    except Exception:
        pass
    try:
        out = subprocess.run(["pdftotext", str(path), "-"], capture_output=True, text=True, check=False)
        return out.stdout or ""
    except Exception:
        return ""


def extract_text_from_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return clean_text(read_txt(path))
    if suffix in {".html", ".htm"}:
        return clean_text(read_html(path))
    if suffix == ".docx":
        return clean_text(read_docx(path))
    if suffix == ".pdf":
        return clean_text(read_pdf(path))
    return ""


def extract_texts_from_zip(path: Path) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="litzip_") as td:
        target = Path(td)
        with zipfile.ZipFile(path, "r") as archive:
            archive.extractall(target)
        for p in target.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in SUPPORTED_EXTENSIONS or p.suffix.lower() == ".zip":
                continue
            text = extract_text_from_file(p)
            if text:
                items.append((p.name, text))
    return items


def fetch_url_text(url: str) -> tuple[str, str]:
    resp = requests.get(url, timeout=20, headers={"User-Agent": "literature-bot/1.0"})
    resp.raise_for_status()
    html = resp.text
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.text if soup.title else "").strip()
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    text = clean_text(soup.get_text("\n"))
    return title, text


def fallback_title_from_filename(filename: str) -> str:
    stem = Path(filename or "").stem
    stem = stem.replace("_", " ")
    stem = re.sub(r"\s+", " ", stem).strip(" -_")
    return stem or "未命名文献"


def detect_title(text: str, fallback: str) -> str:
    lines = [re.sub(r"\s+", " ", x.strip()) for x in (text or "").splitlines() if x.strip()]
    for ln in lines[:30]:
        if len(ln) < 8 or len(ln) > 220:
            continue
        if re.search(r"(abstract|摘要|keywords|doi|www\.|issn)", ln, re.I):
            continue
        if re.search(r"[\u4e00-\u9fff]{4,}", ln) or re.search(r"[A-Za-z]{4,}", ln):
            return ln
    return fallback_title_from_filename(fallback)


def detect_year(text: str) -> str:
    m = re.search(r"\b(19\d{2}|20\d{2})\b", text or "")
    return m.group(1) if m else ""


def detect_authors(text: str) -> list[str]:
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
    for ln in lines[:12]:
        if len(ln) < 6 or len(ln) > 220:
            continue
        if "," in ln and not re.search(r"(abstract|摘要|keywords)", ln, re.I):
            items = [x.strip(" *") for x in re.split(r",|;| and |、|&", ln)]
            items = [x for x in items if re.search(r"[A-Za-z\u4e00-\u9fff]", x)]
            if 1 < len(items) <= 20:
                return items[:12]
    return []


def detect_collections(title: str, abstract_text: str, full_text: str) -> list[str]:
    hay = f"{title}\n{abstract_text}\n{full_text}".lower()
    found = []
    for name, keys in COLLECTION_RULES:
        if any(k.lower() in hay for k in keys):
            found.append(name)
    return found or ["其他"]


def primary_from_collections(collections: list[str]) -> str:
    return normalize_top_category("", collections)


def detect_tags(title: str, full_text: str, collections: list[str]) -> list[str]:
    text = f"{title}\n{full_text}".lower()
    tags = list(collections)
    if "review" in text or "综述" in text:
        tags.append("综述")
    if "experiment" in text or "实验" in text or "in vivo" in text:
        tags.append("实验验证")
    if "algorithm" in text or "模型" in text or "network" in text:
        tags.append("算法")
    if "application" in text or "应用" in text:
        tags.append("应用")
    return sorted(set(tags))


def extract_abstract(text: str) -> str:
    text = clean_text(text)
    if not text:
        return ""
    patterns = [
        r"(?is)(?:abstract|摘要)\s*[:：]?\s*(.{120,2200})",
        r"(?is)(?:introduction|引言)\s*[:：]?\s*(.{120,1600})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            value = clean_text(m.group(1))
            if value:
                return value[:2200]
    return text[:1200]


def summarize_zh(title: str, category: str, abstract_text: str) -> str:
    abs_text = clean_text(abstract_text)[:180]
    if not abs_text:
        return f"这篇文献聚焦于“{category}”方向，标题为“{title}”。"
    return f"这篇文献聚焦于“{category}”方向，标题为“{title}”。核心内容：{abs_text}"


def summarize_list_zh(title: str, category: str, abstract_text: str) -> str:
    return build_list_summary(title, category, abstract_text)


def estimate_confidence(title: str, year: str, authors: list[str], collections: list[str], abstract_original: str) -> float:
    score = 0.0
    if title and len(title) >= 8:
        score += 0.3
    if year:
        score += 0.15
    if authors:
        score += 0.2
    if collections and collections != ["其他"]:
        score += 0.2
    if abstract_original and len(abstract_original) >= 120:
        score += 0.15
    return round(min(score, 1.0), 2)


def decide_publish_status(confidence: float) -> str:
    if confidence >= 0.75:
        return "published"
    if confidence >= 0.45:
        return "pending_review"
    return "pending_review"


def build_paper_payload(filename: str, text: str) -> dict:
    abstract_original = extract_abstract(text)
    title = detect_title(text, filename)
    year = detect_year(text)
    authors = ensure_list(detect_authors(text))
    collections = detect_collections(title, abstract_original, text)
    category = primary_from_collections(collections)
    tags = detect_tags(title, text, collections)
    summary = summarize_zh(title, category, abstract_original)
    list_summary = summarize_list_zh(title, category, abstract_original)
    confidence = estimate_confidence(title, year, authors, collections, abstract_original)
    publish_status = decide_publish_status(confidence)
    file_id = f"{filename}-{int(time.time())}"
    return {
        "id": file_id,
        "title": title,
        "authors": authors,
        "year": year,
        "category": category,
        "collections": collections,
        "tags": tags,
        "abstract_original": abstract_original,
        "abstract_summary_zh": summary,
        "list_summary_zh": list_summary,
        "filename": filename,
        "source_note": "远端上传自动解析",
        "added_at": now_text(),
        "analysis_confidence": confidence,
        "publish_status": publish_status,
    }


def persist_uploaded_file(src: Path, dest_dir: Path) -> tuple[Path, str]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = src.stem
    suffix = src.suffix
    candidate = dest_dir / src.name
    idx = 1
    while candidate.exists():
        candidate = dest_dir / f"{stem}-{idx}{suffix}"
        idx += 1
    shutil.move(str(src), str(candidate))
    relative = f"files/{candidate.name}"
    return candidate, relative
