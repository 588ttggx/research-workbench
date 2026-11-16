from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_title(title: str) -> str:
    title = clean_text(title).lower()
    title = re.sub(r"[^\w\s]", "", title)
    return re.sub(r"\s+", " ", title).strip()


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = doi.strip().lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    return doi or None


def base_access() -> dict[str, Any]:
    return {
        "status": "metadata_only_no_legal_pdf",
        "oa_url": None,
        "oa_source": None,
        "license": None,
        "local_pdf_path": None,
        "pdf_sha256": None,
        "notes": [],
    }


def make_paper(
    *,
    title: str,
    source: str,
    authors: list[str] | None = None,
    year: int | None = None,
    venue: str | None = None,
    abstract: str | None = None,
    doi: str | None = None,
    arxiv_id: str | None = None,
    semantic_scholar_id: str | None = None,
    openalex_id: str | None = None,
    wos_id: str | None = None,
    citation_count: int | None = None,
    influential_citation_count: int | None = None,
    access: dict[str, Any] | None = None,
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "paper_id": None,
        "title": clean_text(title),
        "authors": [clean_text(a) for a in authors or [] if clean_text(a)],
        "year": int(year) if year else None,
        "venue": clean_text(venue),
        "abstract": clean_text(abstract),
        "doi": normalize_doi(doi),
        "arxiv_id": clean_text(arxiv_id) or None,
        "semantic_scholar_id": clean_text(semantic_scholar_id) or None,
        "openalex_id": clean_text(openalex_id) or None,
        "wos_id": clean_text(wos_id) or None,
        "citation_count": citation_count,
        "citation_count_source": source if citation_count is not None else None,
        "citation_counts": {source: citation_count} if citation_count is not None else {},
        "influential_citation_count": influential_citation_count,
        "source_records": [{"source": source, "raw": raw or {}}],
        "access": access or base_access(),
        "ranking": {},
        "metadata_rank": None,
        "analysis_rank": None,
        "final_rank": None,
    }


def merge_papers(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(left)
    for key in ("doi", "arxiv_id", "semantic_scholar_id", "openalex_id", "wos_id"):
        merged[key] = merged.get(key) or right.get(key)
    if len(right.get("abstract") or "") > len(merged.get("abstract") or ""):
        merged["abstract"] = right.get("abstract") or ""
    if not merged.get("venue") and right.get("venue"):
        merged["venue"] = right["venue"]
    if not merged.get("year") and right.get("year"):
        merged["year"] = right["year"]
    merged["authors"] = list(dict.fromkeys([*(merged.get("authors") or []), *(right.get("authors") or [])]))
    if merged.get('citation_count') is None and right.get('citation_count') is not None:
        merged['citation_count'] = right['citation_count']
        merged['citation_count_source'] = right.get('citation_count_source')
    merged['citation_counts'] = {**merged.get('citation_counts', {}), **right.get('citation_counts', {})}
    if merged.get('influential_citation_count') is None:
        merged['influential_citation_count'] = right.get('influential_citation_count')
    merged["source_records"] = [*(merged.get("source_records") or []), *(right.get("source_records") or [])]
    left_access = merged.get("access") or base_access()
    right_access = right.get("access") or base_access()
    if left_access.get("status") == "metadata_only_no_legal_pdf" and right_access.get("oa_url"):
        merged["access"] = right_access
    return merged


def dedupe_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    title_dois = {}
    for paper in papers:
        title = (normalize_title(paper.get('title') or ''), paper.get('year') or '')
        if paper.get('doi'):title_dois.setdefault(title,set()).add(paper['doi'])
    by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for paper in papers:
        keys = []
        if paper.get("doi"):
            keys.append(f"doi:{paper['doi']}")
        if paper.get("arxiv_id"):
            keys.append(f"arxiv:{paper['arxiv_id'].lower()}")
        if paper.get("semantic_scholar_id"):
            keys.append(f"s2:{paper['semantic_scholar_id']}")
        if paper.get("openalex_id"):
            keys.append(f"openalex:{paper['openalex_id']}")
        if paper.get("wos_id"):
            keys.append(f"wos:{paper['wos_id']}")
        title_key = normalize_title(paper.get("title") or "")
        if title_key and len(title_dois.get((title_key,paper.get('year') or ''),set())) <= 1:
            keys.append(f"title:{title_key}:{paper.get('year') or ''}")
        existing_key = next((key for key in keys if key in by_key and not (
            key.startswith('title:') and paper.get('doi') and by_key[key].get('doi')
            and paper['doi'] != by_key[key]['doi'])), None)
        if existing_key:
            previous = by_key[existing_key]
            merged = merge_papers(previous, paper)
            for alias in list(by_key):
                if by_key[alias] is previous:
                    by_key[alias] = merged
            for key in keys:
                by_key[key] = merged
        else:
            primary = keys[0] if keys else f"idx:{len(order)}"
            by_key[primary] = paper
            order.append(primary)
            for key in keys[1:]:
                by_key[key] = paper
    unique = []
    seen = set()
    for key in order:
        paper = by_key[key]
        marker = id(paper)
        if marker not in seen:
            unique.append(paper)
            seen.add(marker)
    assign_ids(unique)
    return unique


def assign_ids(papers: list[dict[str, Any]]) -> None:
    for idx, paper in enumerate(papers, start=1):
        paper["paper_id"] = paper.get("paper_id") or f"p{idx:03d}"


def sort_for_output(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(papers, key=lambda p: (p.get("final_rank") or p.get("metadata_rank") or 9999, p.get("title") or ""))


def write_index(path: Path, *, query: str, sources_requested: list[str], warnings: list[str], papers: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": "1.1",
        "query": query,
        "generated_at": now_iso(),
        "sources_requested": sources_requested,
        "warnings": warnings,
        "papers": sort_for_output(papers),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_index(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
