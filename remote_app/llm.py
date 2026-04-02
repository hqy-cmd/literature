from __future__ import annotations

import json
import re
from typing import Any

import requests

from .config import settings


def _chat_completion(messages: list[dict[str, str]], temperature: float = 0.1) -> str:
    if not (settings.llm_enabled and settings.llm_base_url and settings.llm_api_key and settings.llm_model):
        return ""
    endpoint = settings.llm_base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": temperature,
    }
    try:
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return ""
        return str(choices[0].get("message", {}).get("content", "")).strip()
    except Exception:
        return ""


def rewrite_query_with_llm(query: str) -> list[str]:
    prompt = (
        "你是文献检索改写器。请把用户问题改写成关键词列表，"
        "兼顾中英文术语。只返回 JSON 数组字符串。"
    )
    content = _chat_completion(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": query},
        ],
        temperature=0.0,
    )
    if not content:
        return []
    try:
        value: Any = json.loads(content)
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
    except Exception:
        return []
    return []


def rerank_with_llm(query: str, candidates: list[dict]) -> list[str]:
    if not candidates:
        return []
    compact = [
        {"id": x.get("id"), "title": x.get("title"), "category": x.get("category")}
        for x in candidates[:20]
    ]
    prompt = (
        "根据用户查询对候选文献排序，只返回按相关性从高到低的 id JSON 数组。"
    )
    content = _chat_completion(
        [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": json.dumps({"query": query, "candidates": compact}, ensure_ascii=False),
            },
        ],
        temperature=0.0,
    )
    if not content:
        return []
    try:
        value: Any = json.loads(content)
        if isinstance(value, list):
            return [str(x) for x in value]
    except Exception:
        return []
    return []


def explain_with_llm(query: str, title: str, reasons: list[str]) -> str:
    prompt = "根据检索查询和命中原因，生成一句中文结果解释。"
    content = _chat_completion(
        [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {"query": query, "title": title, "reasons": reasons},
                    ensure_ascii=False,
                ),
            },
        ],
        temperature=0.2,
    )
    return content.strip()


ALLOWED_TOP_CATEGORIES = {"灵巧手", "脑肿瘤", "肿瘤消融", "其他"}


def _extract_json_payload(content: str) -> dict[str, Any]:
    raw = (content or "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        if isinstance(value, dict):
            return value
    except Exception:
        pass

    candidates = re.findall(r"\{[\s\S]*\}", raw)
    for candidate in reversed(candidates):
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except Exception:
            continue
    return {}


def _as_str(value: Any, limit: int = 2000) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text[:limit]


def _as_list(value: Any, item_limit: int = 40, text_limit: int = 120) -> list[str]:
    if isinstance(value, str):
        items = re.split(r"[,\n;；、]", value)
    elif isinstance(value, list):
        items = value
    else:
        items = []
    out: list[str] = []
    seen = set()
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        text = text[:text_limit]
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= item_limit:
            break
    return out


def extract_ingest_with_llm(filename: str, text: str) -> dict[str, Any]:
    prompt = (
        "你是文献入库抽取器。请从给定文本抽取结构化信息，并且只返回 JSON 对象。"
        "JSON 字段必须包含："
        "title(string), authors(array[string]), year(string), "
        "abstract_summary_zh(string), list_summary_zh(string,最多两句), "
        "top_category(string,只能是 灵巧手/脑肿瘤/肿瘤消融/其他), "
        "tags(array[string]), evidence(array[string])。"
        "禁止输出额外解释文本。"
    )
    payload = {
        "filename": filename,
        "text": (text or "")[:16000],
    }
    content = _chat_completion(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        temperature=0.0,
    )
    if not content:
        return {}
    value = _extract_json_payload(content)
    if not value:
        return {}

    top = _as_str(value.get("top_category"), 32)
    if top not in ALLOWED_TOP_CATEGORIES:
        top = "其他"

    return {
        "title": _as_str(value.get("title"), 260),
        "authors": _as_list(value.get("authors"), item_limit=20, text_limit=80),
        "year": _as_str(value.get("year"), 8),
        "abstract_summary_zh": _as_str(value.get("abstract_summary_zh"), 2200),
        "list_summary_zh": _as_str(value.get("list_summary_zh"), 260),
        "top_category": top,
        "tags": _as_list(value.get("tags"), item_limit=24, text_limit=60),
        "evidence": _as_list(value.get("evidence"), item_limit=12, text_limit=120),
    }


def classify_top_category_with_llm(title: str, abstract_text: str, full_text: str) -> dict[str, Any]:
    prompt = (
        "你是文献顶层分类器。必须在 灵巧手/脑肿瘤/肿瘤消融/其他 中选一个。"
        "请仅返回 JSON 对象，字段: top_category(string), evidence(array[string],最多3条)。"
    )
    payload = {
        "title": _as_str(title, 260),
        "abstract_summary": _as_str(abstract_text, 2400),
        "text_window": _as_str(full_text, 12000),
    }
    content = _chat_completion(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        temperature=0.0,
    )
    if not content:
        return {}
    value = _extract_json_payload(content)
    if not value:
        return {}
    top = _as_str(value.get("top_category"), 32)
    if top not in ALLOWED_TOP_CATEGORIES:
        top = "其他"
    return {
        "top_category": top,
        "evidence": _as_list(value.get("evidence"), item_limit=3, text_limit=80),
    }
