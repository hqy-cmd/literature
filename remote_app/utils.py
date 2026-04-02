from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path


TOKEN_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9\-]{1,}|[\u4e00-\u9fff]{2,}")
TEXT_CLEAN = re.compile(r"\s+")


STOP_WORDS = {
    "找一下",
    "相关文章",
    "关于",
    "哪些",
    "有关",
    "方面",
    "研究",
    "一下",
    "相关",
    "文献",
    "文章",
    "创新点",
    "the",
    "and",
    "for",
    "with",
}

TOP_LEVEL_CATEGORIES = {"灵巧手", "脑肿瘤", "肿瘤消融", "其他"}
SUB_CATEGORY_TO_TOP = {
    "机器人抓取": "灵巧手",
    "视觉触觉融合": "灵巧手",
    "多智能体强化学习": "灵巧手",
    "脑组织": "脑肿瘤",
    "电免疫治疗": "脑肿瘤",
    "可注射水凝胶": "脑肿瘤",
    "生物可吸收材料": "脑肿瘤",
    "温度成像": "肿瘤消融",
    "荧光纳米温度计": "肿瘤消融",
}


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def normalize_text(value: str) -> str:
    return TEXT_CLEAN.sub(" ", (value or "").strip()).lower()


def tokenize(value: str) -> list[str]:
    base = [tok.lower() for tok in TOKEN_PATTERN.findall(value or "")]
    return [tok for tok in base if tok not in STOP_WORDS]


def hash_vector(tokens: list[str], dim: int = 128) -> list[float]:
    vec = [0.0] * dim
    if not tokens:
        return vec
    for token in tokens:
        vec[hash(token) % dim] += 1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def cosine_sim(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    size = min(len(left), len(right))
    return sum(left[i] * right[i] for i in range(size))


def chunk_text(value: str, chunk_size: int = 800) -> list[str]:
    text = (value or "").strip()
    if not text:
        return []
    parts: list[str] = []
    idx = 0
    while idx < len(text):
        parts.append(text[idx : idx + chunk_size].strip())
        idx += chunk_size
    return [x for x in parts if x]


def ensure_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        return [x.strip() for x in re.split(r"[,\n]", value) if x.strip()]
    return [str(value).strip()] if str(value).strip() else []


def split_sentences_zh(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r"(?<=[。！？!?])\s+|(?<=[。！？!?])", text.strip())
    cleaned = [re.sub(r"\s+", " ", x).strip() for x in parts if x and x.strip()]
    return cleaned


def compact_to_two_sentences(text: str, fallback: str = "暂无摘要。") -> str:
    lines = split_sentences_zh(text)
    if not lines:
        value = re.sub(r"\s+", " ", (text or "").strip())
        if not value:
            return fallback
        if len(value) > 120:
            value = value[:120].rstrip("，,；;。.!?！？")
        if value and value[-1] not in "。.!?！？":
            value = value + "。"
        return value
    chosen = lines[:2]
    value = " ".join(chosen).strip()
    if len(value) > 180:
        value = value[:180].rstrip("，,；;。.!?！？") + "。"
    return value


def build_list_summary(title: str, category: str, abstract_text: str) -> str:
    clean_title = re.sub(r"\s+", " ", (title or "").strip())
    clean_title = clean_title[:42] if clean_title else "该研究"
    first = f"研究对象：{clean_title}（{category or '其他'}）。"
    detail = compact_to_two_sentences(abstract_text, fallback="")
    detail_lines = split_sentences_zh(detail)
    second_seed = detail_lines[0] if detail_lines else ""
    if second_seed:
        second_seed = second_seed.rstrip("。.!?！？")
        second_seed = second_seed[:68]
        second = f"主要贡献：{second_seed}。"
    else:
        second = "主要贡献：给出了可复用的方法与实验结论。"
    return f"{first} {second}"


def normalize_top_category(category: str | None, collections: list[str] | None = None) -> str:
    names: list[str] = []
    if category:
        names.append(str(category).strip())
    for item in collections or []:
        value = str(item).strip()
        if value:
            names.append(value)

    for name in names:
        if name in TOP_LEVEL_CATEGORIES:
            return name
        mapped = SUB_CATEGORY_TO_TOP.get(name)
        if mapped:
            return mapped
    return "其他"


def normalize_file_url(file_url: str | None, file_path: str | None = None, filename: str | None = None) -> str:
    for raw in (file_url, file_path):
        value = (raw or "").strip()
        if not value:
            continue
        if re.match(r"^https?://", value, re.I):
            return value
        norm = value.replace("\\", "/")
        if norm.startswith("/files/"):
            return norm
        if norm.startswith("files/"):
            return f"/{norm}"
        if "/files/" in norm:
            tail = norm.split("/files/", 1)[1].lstrip("/")
            if tail:
                return f"/files/{tail}"
        if norm.startswith("/"):
            return norm
        if "/" not in norm:
            return f"/files/{norm}"
        return f"/{norm.lstrip('/')}"

    fallback = (filename or "").strip()
    if fallback:
        return f"/files/{Path(fallback).name}"
    return ""
