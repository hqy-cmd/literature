from __future__ import annotations

import math
import re
from datetime import datetime


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

