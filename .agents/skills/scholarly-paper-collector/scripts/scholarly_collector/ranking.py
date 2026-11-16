from __future__ import annotations

import math
import re
from typing import Any


CONTRIBUTION_TERMS = {
    "benchmark",
    "dataset",
    "framework",
    "architecture",
    "method",
    "planning",
    "tool",
    "agent",
    "evaluation",
    "reasoning",
    "retrieval",
    "memory",
}

STOPWORDS = {
    "about",
    "after",
    "and",
    "are",
    "based",
    "between",
    "for",
    "from",
    "into",
    "over",
    "paper",
    "papers",
    "recent",
    "study",
    "survey",
    "the",
    "their",
    "through",
    "using",
    "with",
}

VENUE_HINTS = {
    "nature": 1.0,
    "science": 1.0,
    "neurips": 0.95,
    "icml": 0.95,
    "iclr": 0.95,
    "acl": 0.9,
    "emnlp": 0.9,
    "naacl": 0.9,
    "aaai": 0.85,
    "ijcai": 0.85,
    "arxiv": 0.55,
}


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-zA-Z0-9]+", (text or "").lower()) if len(t) > 2 and t not in STOPWORDS]


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def score_metadata(paper: dict[str, Any], query: str, from_year: int | None, to_year: int | None) -> dict[str, float]:
    query_tokens = set(tokens(query))
    title_tokens = set(tokens(paper.get("title") or ""))
    abstract_tokens = set(tokens(paper.get("abstract") or ""))
    paper_tokens = title_tokens | abstract_tokens
    title_hits = len(query_tokens & title_tokens)
    abstract_hits = len(query_tokens & abstract_tokens)
    relevance = clamp((0.65 * title_hits + 0.35 * abstract_hits) / max(1, len(query_tokens)))
    year = paper.get("year")
    if year and from_year and to_year and to_year >= from_year:
        recency = clamp((year - from_year + 1) / (to_year - from_year + 1))
    elif year and to_year:
        recency = clamp(1.0 - max(0, to_year - year) / 10.0)
    else:
        recency = 0.35
    citations = paper.get("citation_count")
    citation_score = clamp(math.log10(max(0, citations or 0) + 1) / 4.0)
    influential = paper.get("influential_citation_count")
    influential_score = clamp(math.log10(max(0, influential or 0) + 1) / 3.0)
    venue = (paper.get("venue") or " ".join(r.get("source", "") for r in paper.get("source_records", []))).lower()
    venue_score = max([score for hint, score in VENUE_HINTS.items() if hint in venue] or [0.45])
    contribution_hits = len(CONTRIBUTION_TERMS & paper_tokens)
    contribution_proxy = clamp(contribution_hits / 4.0)
    total = (
        0.36 * relevance
        + 0.16 * recency
        + 0.16 * citation_score
        + 0.10 * influential_score
        + 0.10 * venue_score
        + 0.12 * contribution_proxy
    )
    return {
        "relevance": round(relevance, 4),
        "recency": round(recency, 4),
        "citation_impact": round(citation_score, 4),
        "influential_impact": round(influential_score, 4),
        "venue_quality": round(venue_score, 4),
        "contribution_proxy": round(contribution_proxy, 4),
        "metadata_score": round(total, 4),
    }


def apply_metadata_ranking(papers: list[dict[str, Any]], query: str, from_year: int | None, to_year: int | None) -> None:
    for paper in papers:
        scores = score_metadata(paper, query, from_year, to_year)
        paper.setdefault("ranking", {})["metadata_scores"] = scores
        paper["ranking"]["metadata_score"] = scores["metadata_score"]
    papers.sort(
        key=lambda p: (
            p["ranking"]["metadata_score"],
            p.get("year") or 0,
            p.get("citation_count") or 0,
            (p.get("title") or "").lower(),
        ),
        reverse=True,
    )
    for rank, paper in enumerate(papers, start=1):
        paper["metadata_rank"] = rank
        paper["final_rank"] = paper.get("final_rank") or rank


def apply_analysis_reranking(index: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    analysis_by_id = {item.get("paper_id"): item for item in analysis.get("papers", [])}
    papers = index.get("papers", [])
    for paper in papers:
        item = analysis_by_id.get(paper.get("paper_id"), {})
        raw_score = item.get("contribution_score")
        try:
            contribution_score = clamp((float(raw_score) - 1.0) / 4.0)
        except (TypeError, ValueError):
            contribution_score = 0.5 if item else 0.0
        completeness = 0.0
        for key in ("analysis_zh", "contribution_zh", "method_zh", "limitations_zh", "relation_zh"):
            if item.get(key):
                completeness += 0.2
        analysis_score = clamp(0.75 * contribution_score + 0.25 * completeness)
        metadata_score = float(paper.get("ranking", {}).get("metadata_score", 0.0))
        final_score = 0.70 * metadata_score + 0.30 * analysis_score
        paper.setdefault("ranking", {})["analysis_scores"] = {
            "contribution_score_normalized": round(contribution_score, 4),
            "analysis_completeness": round(completeness, 4),
            "analysis_score": round(analysis_score, 4),
            "final_score": round(final_score, 4),
        }
    by_analysis = sorted(
        papers,
        key=lambda p: (
            p.get("ranking", {}).get("analysis_scores", {}).get("analysis_score", 0),
            p.get("ranking", {}).get("metadata_score", 0),
            p.get("year") or 0,
            (p.get("title") or "").lower(),
        ),
        reverse=True,
    )
    for rank, paper in enumerate(by_analysis, start=1):
        paper["analysis_rank"] = rank
    by_final = sorted(
        papers,
        key=lambda p: (
            p.get("ranking", {}).get("analysis_scores", {}).get("final_score", 0),
            p.get("ranking", {}).get("metadata_score", 0),
            p.get("year") or 0,
            (p.get("title") or "").lower(),
        ),
        reverse=True,
    )
    for rank, paper in enumerate(by_final, start=1):
        paper["final_rank"] = rank
    index["papers"] = by_final
    return index
