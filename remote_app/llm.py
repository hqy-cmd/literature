from __future__ import annotations

import json
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

