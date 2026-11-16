"""Keep partial pages and honest bounded-search receipts across providers."""


def record_page(client, source, papers, total, exhausted):
    client.partial_papers[source] = list(papers)
    client.observations[source] = {
        "status": "completed" if exhausted else "bounded",
        "retrieved": len(papers),
        "upstream_total": int(total) if str(total).isdigit() else None,
        "exhausted": bool(exhausted),
    }


def json_pages(client, source, url, params, max_results, **options):
    """Bounded cursor/offset paging; page size stays fixed for offset consistency."""
    params = dict(params)
    size = min(max_results, 100)
    page_key = 'limit' if source == 'semantic_scholar' else 'rows' if source == 'crossref' else 'per-page'
    params[page_key] = size
    params['offset' if source == 'semantic_scholar' else 'cursor'] = 0 if source == 'semantic_scholar' else '*'
    retrieved, seen = 0, set()
    while retrieved < max_results:
        data = client.get_json(url, params=dict(params), cache_namespace=source, **options)
        if source == 'crossref':
            body = data['message']; items = body['items']; total = body.get('total-results'); cursor = body.get('next-cursor')
        elif source == 'openalex':
            items = data['results']; body = data.get('meta', {}); total = body.get('count'); cursor = body.get('next_cursor')
        else:
            items = data['data']; total = data.get('total'); cursor = data.get('next')
        selected = items[:max_results-retrieved]
        retrieved += len(selected)
        exhausted = not items or (len(items) < size and len(selected) == len(items)) or (total is not None and retrieved >= int(total))
        if source != 'crossref' and cursor is None and len(selected) == len(items):
            exhausted = True
        client.observations[source] = {'status': 'completed' if exhausted else 'bounded', 'retrieved': retrieved,
                                       'upstream_total': total, 'exhausted': exhausted}
        yield from selected
        if exhausted or not cursor or cursor in seen or retrieved >= max_results:
            break
        seen.add(cursor)
        params['offset' if source == 'semantic_scholar' else 'cursor'] = cursor
