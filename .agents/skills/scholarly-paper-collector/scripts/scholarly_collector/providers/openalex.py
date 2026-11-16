from __future__ import annotations

import logging
from typing import Any

from ..schema import make_paper
from ._paging import json_pages


class ProviderConfigError(RuntimeError):
    pass


def abstract_text(index):
    if not isinstance(index,dict):return None
    words={position:word for word,positions in index.items() if isinstance(positions,list)
           for position in positions if type(position) is int and 0<=position<10000}
    return ' '.join(str(words[position]) for position in sorted(words)) or None


def search(
    query: str,
    from_year: int | None,
    to_year: int | None,
    max_results: int,
    client: Any,
    logger: logging.Logger,
    *,
    api_key: str,
    strict: bool = False,
    explicit: bool = False,
) -> list[dict]:
    if not api_key:
        message = "OpenAlex skipped: set OPENALEX_API_KEY to enable OpenAlex API access."
        if strict or explicit:
            raise ProviderConfigError(message)
        logger.warning(message)
        return []
    filters = []
    if from_year:
        filters.append(f"from_publication_date:{from_year}-01-01")
    if to_year:
        filters.append(f"to_publication_date:{to_year}-12-31")
    items = json_pages(
        client, 'openalex',
        "https://api.openalex.org/works",
        {
            "search": query,
            "filter": ",".join(filters) if filters else None,
        },
        max_results,
        headers={"User-Agent": "scholarly-paper-collector/1.0", "Authorization": "Bearer "+api_key},
    )
    papers = []
    client.partial_papers['openalex'] = papers
    for item in items:
        authors = []
        for authorship in item.get("authorships", []) or []:
            author = (authorship.get("author") or {}).get("display_name")
            if author:
                authors.append(author)
        best = item.get("best_oa_location") or {}
        pdf_url = best.get("pdf_url")
        access = None
        if pdf_url:
            access = {
                "status": "oa_pdf_available_not_downloaded",
                "oa_url": pdf_url,
                "oa_source": "openalex",
                "license": best.get("license"),
                "local_pdf_path": None,
                "pdf_sha256": None,
                "notes": [],
            }
        papers.append(
            make_paper(
                title=item.get("title") or "",
                source="openalex",
                authors=authors,
                year=item.get("publication_year"),
                venue=((item.get("primary_location") or {}).get("source") or {}).get("display_name"),
                abstract=abstract_text(item.get('abstract_inverted_index')),
                doi=item.get("doi"),
                openalex_id=item.get("id"),
                citation_count=item.get("cited_by_count"),
                access=access,
                raw={"openalex_id": item.get("id"),"issn":((item.get('primary_location') or {}).get('source') or {}).get('issn') or []},
            )
        )
    logger.info("openalex results=%s", len(papers))
    return papers
