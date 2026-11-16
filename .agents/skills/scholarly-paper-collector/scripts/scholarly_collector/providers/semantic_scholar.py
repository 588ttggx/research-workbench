from __future__ import annotations

import logging
from typing import Any

from ..schema import make_paper
from ._paging import json_pages


def search(query: str, from_year: int | None, to_year: int | None, max_results: int, client: Any, logger: logging.Logger, *, api_key: str = "") -> list[dict]:
    headers = {"User-Agent": "scholarly-paper-collector/1.0"}
    retry_delays = (1.0, 2.0, 4.0)
    fail_fast_statuses: set[int] = set()
    if api_key:
        headers["x-api-key"] = api_key
    else:
        client.throttle("semantic_scholar_public", 3.0)
        retry_delays = ()
        fail_fast_statuses = {429}
    year_filter = None
    if from_year or to_year:
        year_filter = f"{from_year or ''}-{to_year or ''}"
    items = json_pages(
        client, 'semantic_scholar',
        "https://api.semanticscholar.org/graph/v1/paper/search",
        {
            "query": query,
            "year": year_filter,
            "fields": "title,authors,year,venue,abstract,externalIds,citationCount,influentialCitationCount,openAccessPdf",
        },
        max_results,
        headers=headers,
        retry_delays=retry_delays,
        fail_fast_statuses=fail_fast_statuses,
    )
    papers = []
    client.partial_papers['semantic_scholar'] = papers
    for item in items:
        external = item.get("externalIds") or {}
        pdf = item.get("openAccessPdf") or {}
        access = None
        if pdf.get("url"):
            access = {
                "status": "oa_pdf_available_not_downloaded",
                "oa_url": pdf.get("url"),
                "oa_source": "semantic_scholar",
                "license": None,
                "local_pdf_path": None,
                "pdf_sha256": None,
                "notes": [],
            }
        papers.append(
            make_paper(
                title=item.get("title") or "",
                source="semantic_scholar",
                authors=[a.get("name") for a in item.get("authors", []) if a.get("name")],
                year=item.get("year"),
                venue=item.get("venue"),
                abstract=item.get("abstract"),
                doi=external.get("DOI"),
                arxiv_id=external.get("ArXiv"),
                semantic_scholar_id=item.get("paperId"),
                citation_count=item.get("citationCount"),
                influential_citation_count=item.get("influentialCitationCount"),
                access=access,
                raw={"paperId": item.get("paperId")},
            )
        )
    logger.info("semantic_scholar results=%s", len(papers))
    return papers
