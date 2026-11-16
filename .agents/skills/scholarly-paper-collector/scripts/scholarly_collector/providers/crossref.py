from __future__ import annotations

import logging
from typing import Any

from ..schema import make_paper
from ._paging import json_pages


def _first_year(item: dict) -> int | None:
    for key in ("published-print", "published-online", "published", "created"):
        parts = ((item.get(key) or {}).get("date-parts") or [])
        if parts and parts[0]:
            try:
                return int(parts[0][0])
            except (TypeError, ValueError):
                return None
    return None


def search(query: str, from_year: int | None, to_year: int | None, max_results: int, client: Any, logger: logging.Logger, *, contact_email: str = "") -> list[dict]:
    headers = {"User-Agent": "scholarly-paper-collector/1.0"}
    if contact_email:
        headers["User-Agent"] = f"scholarly-paper-collector/1.0 (mailto:{contact_email})"
    filters = []
    if from_year:
        filters.append(f"from-pub-date:{from_year}-01-01")
    if to_year:
        filters.append(f"until-pub-date:{to_year}-12-31")
    items = json_pages(
        client, 'crossref',
        "https://api.crossref.org/works",
        {
            "query.bibliographic": query,
            "filter": ",".join(filters) if filters else None,
            "mailto": contact_email or None,
        },
        max_results,
        headers=headers,
    )
    papers = []
    client.partial_papers['crossref'] = papers
    for item in items:
        title = (item.get("title") or [""])[0]
        year = _first_year(item)
        authors = []
        for author in item.get("author", []) or []:
            name = " ".join(part for part in (author.get("given"), author.get("family")) if part)
            if name:
                authors.append(name)
        papers.append(
            make_paper(
                title=title,
                source="crossref",
                authors=authors,
                year=year,
                venue=(item.get("container-title") or [""])[0],
                abstract=item.get("abstract"),
                doi=item.get("DOI"),
                citation_count=item.get("is-referenced-by-count"),
                raw={"type": item.get("type"), "URL": item.get("URL"),"issn":item.get('ISSN') or []},
            )
        )
    logger.info("crossref results=%s", len(papers))
    return papers
