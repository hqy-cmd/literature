from __future__ import annotations

from collections import Counter

from sqlalchemy.orm import Session

from . import llm
from .models import Paper
from .utils import cosine_sim, hash_vector, normalize_file_url, normalize_text, resolve_category, tokenize


REWRITE_MAP = [
    (["机器人识别", "机器人抓取", "灵巧手", "抓取"], ["robotic hand", "grasp", "grasping", "dexterous hand"]),
    (["识别", "视觉", "触觉"], ["visual", "tactile", "visuo-tactile"]),
    (["光声显微", "光声"], ["photoacoustic microscopy", "photoacoustic"]),
    (["纳米温度计", "温度成像", "测温"], ["nanothermometer", "temperature imaging", "thermometry"]),
    (["脑肿瘤", "胶质瘤"], ["glioma", "glioblastoma", "brain tumor"]),
    (["消融", "热疗"], ["tumor ablation", "thermal ablation", "microwave ablation"]),
    (["血流动力学"], ["hemodynamic", "hemodynamics", "blood flow"]),
]


def normalize_query(query: str) -> str:
    return normalize_text(query or "")


def heuristic_rewrite(query: str) -> list[str]:
    raw = normalize_query(query)
    terms = tokenize(raw)
    expanded = list(terms)
    for keys, adds in REWRITE_MAP:
        if any(k in raw for k in keys):
            expanded.extend(adds)
            expanded.extend(keys)
    dedup: list[str] = []
    seen = set()
    for x in expanded:
        if x and x not in seen:
            seen.add(x)
            dedup.append(x)
    return dedup


def rewrite_query(query: str) -> list[str]:
    rewritten = heuristic_rewrite(query)
    llm_terms = llm.rewrite_query_with_llm(query)
    for term in llm_terms:
        if term not in rewritten:
            rewritten.append(term)
    return rewritten


def _fields_text(paper: Paper) -> dict[str, str]:
    top_category = resolve_category(paper.category, paper.collections or [], bool(paper.manual_edit))
    return {
        "title": normalize_text(paper.title),
        "authors": normalize_text(" ".join(paper.authors or [])),
        "category": normalize_text(top_category),
        "collections": normalize_text(" ".join(paper.collections or [])),
        "tags": normalize_text(" ".join(paper.tags or [])),
        "abstract": normalize_text(f"{paper.abstract_summary_zh} {paper.abstract_original}"),
        "filename": normalize_text(paper.filename),
    }


def _lexical_score(terms: list[str], field_texts: dict[str, str]) -> tuple[float, list[str], list[str]]:
    score = 0.0
    reasons: list[str] = []
    matched_fields: set[str] = set()
    for term in terms:
        if not term:
            continue
        if term in field_texts["title"]:
            score += 10
            matched_fields.add("title")
            reasons.append(f"标题命中“{term}”")
        if term in field_texts["tags"]:
            score += 7
            matched_fields.add("tags")
            reasons.append(f"标签命中“{term}”")
        if term in field_texts["category"] or term in field_texts["collections"]:
            score += 6
            matched_fields.add("category_or_collections")
            reasons.append(f"分类命中“{term}”")
        if term in field_texts["authors"]:
            score += 3
            matched_fields.add("authors")
        if term in field_texts["abstract"]:
            score += 2
            matched_fields.add("abstract")
        if term in field_texts["filename"]:
            score += 1
            matched_fields.add("filename")
    return score, reasons[:5], sorted(matched_fields)


def _semantic_score(terms: list[str], paper: Paper) -> float:
    query_vec = hash_vector(terms)
    paper_vec = paper.token_vector or []
    if not paper_vec:
        paper_vec = hash_vector(tokenize(paper.search_text or ""))
    return cosine_sim(query_vec, paper_vec)


def rerank_candidates(query: str, ranked: list[dict]) -> list[dict]:
    ordered_ids = llm.rerank_with_llm(query, ranked)
    if not ordered_ids:
        return ranked
    mapping = {item["id"]: item for item in ranked}
    sorted_with_llm = [mapping[x] for x in ordered_ids if x in mapping]
    remain = [item for item in ranked if item["id"] not in ordered_ids]
    return sorted_with_llm + remain


def summarize_results(query: str, results: list[dict]) -> str:
    if not results:
        return f"关于“{query}”没有找到明显相关文献。"
    top = results[:5]
    category_counter = Counter((x.get("category") or "其他") for x in top)
    top_cats = [name for name, _ in category_counter.most_common(3)]
    if top_cats:
        return f"关于“{query}”共找到 {len(results)} 篇候选，最相关方向集中在：{'、'.join(top_cats)}。"
    return f"关于“{query}”共找到 {len(results)} 篇候选文献。"


def search_papers(db: Session, query: str, limit: int = 20) -> dict:
    normalized = normalize_query(query)
    if not normalized:
        return {
            "query": query,
            "normalized_query": normalized,
            "rewritten_terms": [],
            "summary": "请输入检索问题。",
            "results": [],
        }

    terms = rewrite_query(normalized)
    candidates = db.query(Paper).filter(Paper.publish_status == "published").all()
    ranked: list[dict] = []

    for paper in candidates:
        top_category = resolve_category(paper.category, paper.collections or [], bool(paper.manual_edit))
        file_url = normalize_file_url(paper.file_url, paper.file_path, paper.filename)
        fields = _fields_text(paper)
        lexical_score, reasons, matched_fields = _lexical_score(terms, fields)
        semantic_score = _semantic_score(terms, paper)
        score = lexical_score * 0.75 + semantic_score * 25
        if score <= 0:
            continue
        if not reasons:
            reasons = ["语义相似度命中"]
        explain = llm.explain_with_llm(query, paper.title, reasons)
        if explain:
            reasons = [explain]
        ranked.append(
            {
                "id": paper.id,
                "title": paper.title,
                "authors": paper.authors or [],
                "year": paper.year or "",
                "category": top_category,
                "collections": paper.collections or [],
                "tags": paper.tags or [],
                "abstract_original": paper.abstract_original or "",
                "abstract_summary_zh": paper.abstract_summary_zh or "",
                "filename": paper.filename or "",
                "source_note": paper.source_note or "",
                "added_at": paper.added_at or "",
                "file_path": paper.file_path or "",
                "file_url": file_url,
                "manual_edit": bool(paper.manual_edit),
                "locked_fields": paper.locked_fields or [],
                "publish_status": paper.publish_status or "published",
                "analysis_confidence": float(paper.analysis_confidence or 0.0),
                "analysis_confidence_breakdown": paper.analysis_confidence_breakdown or {},
                "analysis_warnings": paper.analysis_warnings or [],
                "classification_evidence": paper.classification_evidence or [],
                "search_score": round(score, 4),
                "hit_reasons": reasons,
                "matched_fields": matched_fields,
            }
        )

    ranked.sort(key=lambda x: x["search_score"], reverse=True)
    ranked = rerank_candidates(query, ranked)[:limit]
    return {
        "query": query,
        "normalized_query": normalized,
        "rewritten_terms": terms,
        "summary": summarize_results(query, ranked),
        "results": ranked,
    }
