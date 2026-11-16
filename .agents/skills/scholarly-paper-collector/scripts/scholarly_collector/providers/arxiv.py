from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Any

from ..schema import make_paper
from ._paging import record_page


ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"


def _text(node: ET.Element | None) -> str:
    return "".join(node.itertext()).strip() if node is not None else ""


def _normalize(entries, from_year, to_year):
    papers = []
    for entry in entries:
        title = _text(entry.find(f"{ATOM}title"))
        summary = _text(entry.find(f"{ATOM}summary"))
        published = _text(entry.find(f"{ATOM}published"))
        year = int(published[:4]) if published[:4].isdigit() else None
        if from_year and year and year < from_year:
            continue
        if to_year and year and year > to_year:
            continue
        arxiv_id = _text(entry.find(f"{ATOM}id")).rsplit("/", 1)[-1]
        authors = [_text(author.find(f"{ATOM}name")) for author in entry.findall(f"{ATOM}author")]
        doi = _text(entry.find(f"{ARXIV}doi")) or None
        access = {
            "status": "oa_pdf_available_not_downloaded",
            "oa_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            "oa_source": "arxiv",
            "license": None,
            "local_pdf_path": None,
            "pdf_sha256": None,
            "notes": [],
        }
        papers.append(
            make_paper(
                title=title,
                source="arxiv",
                authors=authors,
                year=year,
                venue="arXiv",
                abstract=summary,
                doi=doi,
                arxiv_id=arxiv_id,
                access=access,
                raw={"published": published},
            )
        )
    return papers


def query_expression(query):
    if re.search(r'\b(?:all|ti|au|abs|cat|id|doi|submittedDate)\s*:',query,re.I):return query
    parts=[];previous=None;depth=0
    for word in re.findall(r'"[^"]+"|[()]|[^\s()]+',query):
        operator=word.upper() in ('AND','OR','ANDNOT','NOT')
        kind='operator' if operator else 'open' if word=='(' else 'close' if word==')' else 'term'
        if kind in ('term','open') and previous in ('term','close'):parts.append('AND')
        if kind in ('operator','close') and previous not in ('term','close'):raise ValueError('arXiv query has misplaced operators or parentheses')
        if kind=='open':depth+=1
        if kind=='close':depth-=1
        if depth<0:raise ValueError('arXiv query has unbalanced parentheses')
        parts.append(('ANDNOT' if word.upper()=='NOT' else word.upper()) if operator else word if kind!='term' else 'all:'+word)
        previous=kind
    if depth or previous not in ('term','close'):raise ValueError('arXiv query is incomplete')
    return ' '.join(parts)


def search(query: str, from_year: int | None, to_year: int | None, max_results: int, client: Any, logger: logging.Logger) -> list[dict]:
    expression = query_expression(query)
    if from_year or to_year:
        expression = '('+expression+') AND submittedDate:['+str(from_year or 1900)+'01010000 TO '+str(to_year or 2100)+'12312359]'
    papers = []
    client.partial_papers['arxiv'] = papers
    size, start = min(max_results,100), 0
    while len(papers) < max_results:
        text = client.get_text('https://export.arxiv.org/api/query',params={
            'search_query':expression,'start':start,'max_results':size,
            'sortBy':'relevance','sortOrder':'descending'},
            headers={'User-Agent':'scholarly-paper-collector/1.0'},cache_namespace='arxiv',
            retry_delays=(3.0,6.0),fail_fast_statuses={400,401,403,429})
        root = ET.fromstring(text)
        entries = root.findall(f'{ATOM}entry')
        if any('/api/errors' in _text(entry.find(f'{ATOM}id')) for entry in entries):
            raise RuntimeError('arXiv returned a query error, not a zero-result search')
        total_text = root.findtext('{http://a9.com/-/spec/opensearch/1.1/}totalResults')
        total = int(total_text) if total_text and total_text.isdigit() else None
        page = _normalize(entries,from_year,to_year)
        papers.extend(page[:max_results-len(papers)])
        start += len(entries)
        exhausted = len(entries) < size or (total is not None and start >= total)
        record_page(client,'arxiv',papers,total,exhausted)
        if exhausted or not entries:break
    logger.info('arxiv results=%s',len(papers))
    return papers
