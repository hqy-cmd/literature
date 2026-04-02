from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from . import llm
from .utils import (
    TOP_LEVEL_CATEGORIES,
    build_list_summary,
    compact_to_two_sentences,
    ensure_list,
    normalize_top_category,
    now_text,
)


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".html", ".htm", ".zip"}

CATEGORY_KEYWORDS = {
    "灵巧手": [
        ("视触觉", 3.0),
        ("视觉触觉", 3.0),
        ("触觉", 2.2),
        ("robotic hand", 2.5),
        ("dexterous", 2.2),
        ("grasp", 2.0),
        ("manipulation", 1.8),
        ("机器人抓取", 2.3),
        ("灵巧手", 2.6),
        ("visuo-tactile", 2.8),
        ("tactile sensing", 2.2),
    ],
    "脑肿瘤": [
        ("脑肿瘤", 3.0),
        ("胶质瘤", 2.8),
        ("glioma", 2.7),
        ("glioblastoma", 2.9),
        ("brain tumor", 2.8),
        ("脑癌", 2.7),
    ],
    "肿瘤消融": [
        ("肿瘤消融", 3.0),
        ("消融", 2.6),
        ("射频消融", 3.0),
        ("微波消融", 3.0),
        ("热疗", 2.6),
        ("温度成像", 2.6),
        ("测温", 2.3),
        ("temperature imaging", 2.4),
        ("thermometry", 2.3),
        ("tumor ablation", 3.0),
        ("thermal ablation", 2.9),
        ("hyperthermia", 2.0),
        ("nanothermometer", 2.2),
    ],
}

SUBTOPIC_RULES = [
    ("视觉触觉融合", ["视触觉", "视觉触觉", "visuo-tactile", "tactile"]),
    ("机器人抓取", ["抓取", "grasp", "robotic hand"]),
    ("脑肿瘤", ["脑肿瘤", "胶质瘤", "glioma", "glioblastoma", "brain tumor"]),
    ("肿瘤消融", ["消融", "ablation"]),
    ("温度成像", ["温度成像", "测温", "temperature imaging", "thermometry"]),
    ("荧光纳米温度计", ["纳米温度计", "nanothermometer"]),
]

TITLE_NOISE_PATTERNS = [
    r"\bjournal\b",
    r"\bvol(?:ume)?\b",
    r"\bissue\b",
    r"\bissn\b",
    r"\bdoi\b",
    r"\bproceedings?\b",
    r"\bconference\b",
    r"\babstract\b",
    r"\bkeywords?\b",
    r"^\s*(19|20)\d{2}\s*年?\s*\d{1,2}\s*月",
]

AUTHOR_NOISE_PATTERNS = [
    r"\bjournal\b",
    r"\buniversity\b",
    r"\bdepartment\b",
    r"\binstitute\b",
    r"\bcollege\b",
    r"\babstract\b",
    r"\bkeywords?\b",
    r"摘要",
    r"关键词",
    r"引言",
]

GENERIC_SUBCATEGORY_NAMES = {"其他", "未细分", "未分类"}


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


def _looks_like_title_noise(line: str) -> bool:
    check = (line or "").strip().lower()
    if not check:
        return True
    if len(check) < 8 or len(check) > 240:
        return True
    if "http://" in check or "https://" in check:
        return True
    if sum(ch.isdigit() for ch in check) > max(10, len(check) // 3):
        return True
    return any(re.search(pat, check, re.I) for pat in TITLE_NOISE_PATTERNS)


def _sanitize_title(line: str) -> str:
    value = re.sub(r"\s+", " ", (line or "").strip())
    value = re.sub(r"^\s*(19|20)\d{2}\s*年?\s*\d{1,2}\s*月\s*", "", value)
    value = value.strip(" -_：:;；,.，")
    return value[:240]


def _valid_custom_category(name: str) -> bool:
    value = str(name or "").strip()
    if not value:
        return False
    if len(value) < 2 or len(value) > 14:
        return False
    if re.search(r"[\d/\\|:;,.，。！？!?\[\]{}()<>]", value):
        return False
    if value in {"其他", "未分类"}:
        return False
    return bool(re.search(r"[A-Za-z\u4e00-\u9fff]", value))


def detect_title(text: str, fallback: str) -> str:
    lines = [re.sub(r"\s+", " ", x.strip()) for x in (text or "").splitlines() if x.strip()]
    candidates: list[tuple[float, str]] = []
    for idx, ln in enumerate(lines[:80]):
        if _looks_like_title_noise(ln):
            continue
        score = 0.0
        if 10 <= len(ln) <= 120:
            score += 1.2
        if re.search(r"[\u4e00-\u9fff]{4,}", ln):
            score += 1.0
        if re.search(r"[A-Za-z]{4,}", ln):
            score += 0.8
        if not re.search(r"[,:;|/\\\[\]{}]", ln):
            score += 0.3
        if idx <= 8:
            score += 0.8
        if re.search(r"\b(journal|volume|issue|doi|issn)\b", ln, re.I):
            score -= 2.0
        candidates.append((score, ln))

    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        best = _sanitize_title(candidates[0][1])
        if best and not _looks_like_title_noise(best):
            return best
    return fallback_title_from_filename(fallback)


def detect_year(text: str, title: str = "") -> str:
    title_match = re.search(r"\b(19\d{2}|20\d{2})\b", title or "")
    if title_match:
        return title_match.group(1)

    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
    head = "\n".join(lines[:80])
    match = re.search(r"\b(19\d{2}|20\d{2})\b", head)
    if match:
        return match.group(1)

    m = re.search(r"\b(19\d{2}|20\d{2})\b", text or "")
    return m.group(1) if m else ""


def _looks_like_author_line(line: str) -> bool:
    value = (line or "").strip()
    if len(value) < 3 or len(value) > 140:
        return False
    if any(re.search(pat, value, re.I) for pat in AUTHOR_NOISE_PATTERNS):
        return False
    if re.search(r"\d{3,}", value):
        return False
    return bool(re.search(r"[A-Za-z\u4e00-\u9fff]", value))


def _is_name_like(token: str) -> bool:
    value = token.strip(" *-·.")
    if not value:
        return False
    if any(re.search(pat, value, re.I) for pat in AUTHOR_NOISE_PATTERNS):
        return False
    if re.search(r"\d", value):
        return False
    if re.search(r"[\u4e00-\u9fff]", value):
        return 2 <= len(value) <= 12
    parts = [x for x in re.split(r"\s+", value) if x]
    if not (1 <= len(parts) <= 4):
        return False
    if sum(len(x) for x in parts) > 36:
        return False
    return bool(re.search(r"[A-Za-z]", value))


def detect_authors(text: str) -> list[str]:
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
    for ln in lines[:32]:
        if not _looks_like_author_line(ln):
            continue
        items = [x.strip() for x in re.split(r",|;| and |、|&|\|", ln) if x.strip()]
        if len(items) < 2 or len(items) > 20:
            continue
        names = [x for x in items if _is_name_like(x)]
        if len(names) >= 2:
            return names[:12]

    for ln in lines[:20]:
        if not _looks_like_author_line(ln):
            continue
        items = [x for x in re.split(r"\s+", ln) if x]
        if 2 <= len(items) <= 8 and all(_is_name_like(x) for x in items):
            return items[:8]
    return []


def classify_top_category(title: str, abstract_text: str) -> tuple[str, list[str]]:
    hay = clean_text(f"{title}\n{abstract_text}").lower()
    scores: dict[str, float] = defaultdict(float)
    evidence: dict[str, list[str]] = defaultdict(list)
    for cat, rules in CATEGORY_KEYWORDS.items():
        for term, weight in rules:
            if term.lower() in hay:
                scores[cat] += weight
                evidence[cat].append(term)
    if not scores:
        return "其他", []
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_cat, top_score = ranked[0]
    if top_score < 2.2:
        return "其他", []
    return top_cat, evidence.get(top_cat, [])[:5]


def detect_collections(title: str, abstract_text: str, category: str) -> list[str]:
    hay = clean_text(f"{title}\n{abstract_text}").lower()
    found: list[str] = []
    for name, keys in SUBTOPIC_RULES:
        if any(k.lower() in hay for k in keys):
            found.append(name)
    if not found:
        if category in TOP_LEVEL_CATEGORIES and category != "其他":
            return [category]
        return ["其他"]
    dedup: list[str] = []
    seen = set()
    for item in found:
        if item in seen:
            continue
        seen.add(item)
        dedup.append(item)
    return dedup


def merge_subcategories(base: list[str], llm_subs: list[str]) -> list[str]:
    merged: list[str] = []
    seen = set()
    for raw in (base or []) + (llm_subs or []):
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        if len(value) > 24:
            continue
        seen.add(value)
        merged.append(value)
    return merged[:12]


def pick_promoted_top_from_subcategories(subs: list[str]) -> str:
    for raw in subs or []:
        name = str(raw or "").strip()
        if not name or name in GENERIC_SUBCATEGORY_NAMES:
            continue
        mapped = normalize_top_category("", [name])
        if mapped != "其他":
            return mapped
    for raw in subs or []:
        name = str(raw or "").strip()
        if not name or name in GENERIC_SUBCATEGORY_NAMES:
            continue
        if _valid_custom_category(name):
            return f"自定义:{name}"
    return ""


def sanitize_subcategories_for_top(top_category: str, subs: list[str]) -> list[str]:
    display_top = str(top_category or "").strip()
    if display_top.startswith("自定义:"):
        display_top = display_top.split(":", 1)[1].strip() or "其他"
    if display_top == "其他":
        return ["其他"]
    out: list[str] = []
    seen = set()
    for raw in subs or []:
        name = str(raw or "").strip()
        if not name:
            continue
        if name in GENERIC_SUBCATEGORY_NAMES:
            continue
        if name == display_top:
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    if not out:
        return [display_top]
    return out[:12]


def detect_tags(title: str, full_text: str, collections: list[str], llm_tags: list[str] | None = None) -> list[str]:
    text = clean_text(f"{title}\n{full_text}").lower()
    tags = list(collections)
    for tag in llm_tags or []:
        if tag:
            tags.append(tag)
    if "review" in text or "综述" in text:
        tags.append("综述")
    if "experiment" in text or "实验" in text or "in vivo" in text:
        tags.append("实验验证")
    if "algorithm" in text or "模型" in text or "network" in text:
        tags.append("算法")
    if "application" in text or "应用" in text:
        tags.append("应用")
    if "vision" in text or "视觉" in text:
        tags.append("视觉")
    if "tactile" in text or "触觉" in text:
        tags.append("触觉")
    out = sorted(set(x.strip() for x in tags if str(x).strip()))
    return out[:24]


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


def validate_payload(payload: dict) -> list[str]:
    warnings: list[str] = []
    title = str(payload.get("title") or "").strip()
    authors = ensure_list(payload.get("authors"))
    year = str(payload.get("year") or "").strip()
    abstract_summary = clean_text(str(payload.get("abstract_summary_zh") or ""))
    category = str(payload.get("category") or "").strip()
    evidence = ensure_list(payload.get("classification_evidence"))

    if not title or len(title) < 8 or _looks_like_title_noise(title):
        warnings.append("标题疑似异常")
    if not authors:
        warnings.append("作者提取不足")
    if not re.fullmatch(r"(19\d{2}|20\d{2})", year):
        warnings.append("年份缺失或异常")
    if len(abstract_summary) < 60:
        warnings.append("摘要过短")
    if category == "其他" and len(evidence) < 1:
        warnings.append("分类证据弱")
    return warnings


def estimate_confidence(payload: dict, llm_used: bool) -> tuple[float, dict]:
    breakdown = {
        "title": 0.0,
        "authors": 0.0,
        "year": 0.0,
        "summary": 0.0,
        "classification": 0.0,
        "llm": 0.0,
        "warning_penalty": 0.0,
    }

    title = str(payload.get("title") or "").strip()
    if title and len(title) >= 8 and not _looks_like_title_noise(title):
        breakdown["title"] = 0.22
    elif title:
        breakdown["title"] = 0.1

    authors = ensure_list(payload.get("authors"))
    if authors:
        breakdown["authors"] = 0.16

    year = str(payload.get("year") or "").strip()
    if re.fullmatch(r"(19\d{2}|20\d{2})", year):
        breakdown["year"] = 0.12

    summary = clean_text(str(payload.get("abstract_summary_zh") or ""))
    if len(summary) >= 90:
        breakdown["summary"] = 0.2
    elif len(summary) >= 60:
        breakdown["summary"] = 0.12

    category = str(payload.get("category") or "").strip()
    evidence = ensure_list(payload.get("classification_evidence"))
    if category != "其他" and evidence:
        breakdown["classification"] = 0.2
    elif evidence:
        breakdown["classification"] = 0.1
    else:
        breakdown["classification"] = 0.05

    if llm_used:
        breakdown["llm"] = 0.1

    warnings = ensure_list(payload.get("analysis_warnings"))
    if warnings:
        breakdown["warning_penalty"] = min(0.2, 0.05 * len(warnings))

    score = (
        breakdown["title"]
        + breakdown["authors"]
        + breakdown["year"]
        + breakdown["summary"]
        + breakdown["classification"]
        + breakdown["llm"]
        - breakdown["warning_penalty"]
    )
    score = max(0.0, min(1.0, score))
    return round(score, 4), breakdown


def decide_publish_status(confidence: float, warnings: list[str]) -> str:
    blocking = {"标题疑似异常", "摘要过短", "分类证据弱"}
    if confidence >= 0.88 and not any(item in blocking for item in warnings):
        return "published"
    return "pending_review"


def build_paper_payload(filename: str, text: str) -> dict:
    clean_full_text = clean_text(text)
    abstract_original = extract_abstract(clean_full_text)

    local_title = detect_title(clean_full_text, filename)
    local_year = detect_year(clean_full_text, local_title)
    local_authors = ensure_list(detect_authors(clean_full_text))
    local_category, local_evidence = classify_top_category(local_title, abstract_original)
    local_collections = detect_collections(local_title, abstract_original, local_category)
    local_summary = summarize_zh(local_title, local_category, abstract_original)
    local_list_summary = summarize_list_zh(local_title, local_category, abstract_original)

    llm_data = llm.extract_ingest_with_llm(filename, clean_full_text)
    llm_used = bool(llm_data)

    llm_title = str(llm_data.get("title") or "").strip()
    title = llm_title if llm_title and not _looks_like_title_noise(llm_title) else local_title

    llm_year = str(llm_data.get("year") or "").strip()
    year = llm_year if re.fullmatch(r"(19\d{2}|20\d{2})", llm_year) else local_year
    authors = ensure_list(llm_data.get("authors") or local_authors)

    candidate_category = str(llm_data.get("top_category") or "").strip()
    raw_category = str(llm_data.get("top_category_raw") or "").strip()
    if candidate_category not in TOP_LEVEL_CATEGORIES:
        candidate_category = local_category
    if candidate_category not in TOP_LEVEL_CATEGORIES:
        candidate_category = "其他"
    category = candidate_category

    custom_top = ""
    if raw_category and raw_category not in TOP_LEVEL_CATEGORIES and _valid_custom_category(raw_category):
        custom_top = f"自定义:{raw_category}"

    llm_subs = ensure_list(llm_data.get("sub_categories"))
    collections = detect_collections(title, abstract_original, category)
    collections = merge_subcategories(collections, llm_subs)
    llm_evidence = ensure_list(llm_data.get("evidence"))
    evidence = llm_evidence or local_evidence
    evidence = [x for x in evidence if x][:8]

    # Second-pass classification for "其他": ask LLM to force a top-level choice among 4 classes.
    if category == "其他" and not custom_top:
        second = llm.classify_top_category_with_llm(title, abstract_original, clean_full_text)
        second_cat = str(second.get("top_category") or "").strip()
        second_evidence = ensure_list(second.get("evidence"))
        if second_cat in TOP_LEVEL_CATEGORIES and second_cat != "其他":
            category = second_cat
            collections = detect_collections(title, abstract_original, category)
            collections = merge_subcategories(collections, llm_subs)
            if second_evidence:
                evidence = second_evidence[:8]

    # Try to reduce "其他" by lifting from subcategories:
    # 1) map known subtopic -> fixed top category
    # 2) if still unclear, promote a valid subtopic into a custom top category.
    if category == "其他" and not custom_top:
        promoted = pick_promoted_top_from_subcategories(collections or llm_subs)
        if promoted:
            if promoted.startswith("自定义:"):
                custom_top = promoted
            else:
                category = promoted
            evidence = (evidence + [f"子类提升: {promoted.replace('自定义:', '')}"])[:8]

    final_category = custom_top or category
    if custom_top:
        custom_label = custom_top.split(":", 1)[1].strip() if custom_top.startswith("自定义:") else custom_top
        if raw_category:
            evidence = (evidence + [f"LLM自定义大类: {raw_category}"])[:8]
        else:
            evidence = (evidence + [f"规则提升大类: {custom_label}"])[:8]

    collections = sanitize_subcategories_for_top(final_category, collections)

    summary = str(llm_data.get("abstract_summary_zh") or local_summary).strip()
    if not summary:
        summary = local_summary
    list_summary = str(llm_data.get("list_summary_zh") or local_list_summary).strip()
    list_summary = compact_to_two_sentences(list_summary or local_list_summary, fallback="")
    if not list_summary:
        list_summary = local_list_summary

    tags = detect_tags(title, clean_full_text, collections, llm_tags=ensure_list(llm_data.get("tags")))

    payload_for_validation = {
        "title": title,
        "authors": authors,
        "year": year,
        "category": final_category,
        "abstract_summary_zh": summary,
        "classification_evidence": evidence,
    }
    warnings = validate_payload(payload_for_validation)
    payload_for_validation["analysis_warnings"] = warnings
    confidence, breakdown = estimate_confidence(payload_for_validation, llm_used=llm_used)
    publish_status = decide_publish_status(confidence, warnings)

    file_id = f"{filename}-{int(time.time())}"
    return {
        "id": file_id,
        "title": title,
        "authors": authors,
        "year": year,
        "category": final_category,
        "collections": collections or ["其他"],
        "tags": tags,
        "abstract_original": abstract_original,
        "abstract_summary_zh": summary,
        "list_summary_zh": list_summary,
        "filename": filename,
        "source_note": "远端上传自动解析",
        "added_at": now_text(),
        "analysis_confidence": confidence,
        "analysis_confidence_breakdown": breakdown,
        "analysis_warnings": warnings,
        "classification_evidence": evidence,
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
