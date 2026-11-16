"""Clarivate official APIs only; no browser cookies or internal web endpoints."""
import re

from ..schema import make_paper
from ._paging import record_page


def _list(value):
    return value if isinstance(value, list) else [value] if value is not None else []


def _text(value):
    if isinstance(value, dict):
        return _text(value.get('content', value.get('value', value.get('p', ''))))
    if isinstance(value, list):
        return ' '.join(_text(item) for item in value)
    return str(value or '')


def normalize(item, api):
    if api == 'starter':
        uid = item.get('uid')
        source = item.get('source') or {}
        identifiers = item.get('identifiers') or {}
        names = _list((item.get('names') or {}).get('authors'))
        count = next((row.get('count') for row in item.get('citations', []) if row.get('db') == 'WOS'), None)
        values = dict(title=item.get('title', ''), year=source.get('publishYear'),
                      venue=source.get('sourceTitle'), abstract=item.get('abstract'), doi=identifiers.get('doi'),
                      authors=[row.get('displayName') or row.get('wosStandard') for row in names])
    else:
        uid = item.get('UID')
        static = item.get('static_data') or {}
        summary = static.get('summary') or {}
        dynamic = item.get('dynamic_data') or {}
        titles = _list((summary.get('titles') or {}).get('title'))
        title = next((_text(row) for row in titles if row.get('type') == 'item'), '')
        venue = next((_text(row) for row in titles if row.get('type') == 'source'), '')
        names = _list((summary.get('names') or {}).get('name'))
        identifiers = _list(((dynamic.get('cluster_related') or {}).get('identifiers') or {}).get('identifier'))
        doi = next((row.get('value') for row in identifiers if row.get('type') == 'doi'), None)
        counts = _list(((dynamic.get('citation_related') or {}).get('tc_list') or {}).get('silo_tc'))
        count = next((row.get('local_count') for row in counts if row.get('coll_id') == 'WOS'), None)
        abstracts = _list(((static.get('fullrecord_metadata') or {}).get('abstracts') or {}).get('abstract'))
        abstract = ' '.join(_text(row.get('abstract_text')) for row in abstracts)
        values = dict(title=title, year=(summary.get('pub_info') or {}).get('pubyear'), venue=venue,
                      abstract=abstract, doi=doi, authors=[row.get('full_name') or row.get('display_name') for row in names])
    if not uid or not values['title']:
        raise ValueError('WoS response lacks a stable UID or title')
    count = int(count) if count is not None else None
    return make_paper(source='wos', wos_id=uid, citation_count=count,
                      raw={'uid': uid, 'api': api, 'record': item}, **values)


def search(query, from_year, to_year, max_results, client, logger, *, api_key, api='starter', database='WOS'):
    if not api_key:
        raise ValueError('WoS requires a configured WOS_API_KEY; website login is a separate permission')
    if api not in ('starter', 'expanded'):
        raise ValueError('WOS_API must be starter or expanded')
    if not re.search(r'\b(?:TS|TI|AB|AK|AU|AI|SO|DO|UT|PY|OG)\s*=', query, re.I):
        raise ValueError('Provide an explicit WoS field query through --wos-query, e.g. TS=(terahertz AND starch)')
    if from_year or to_year:
        query = f'({query}) AND PY=({from_year or 1900}-{to_year or 2100})'
    papers = []
    page = 1
    starter_page_size = min(50, max_results)
    while len(papers) < max_results:
        size = starter_page_size if api == 'starter' else min(100, max_results - len(papers))
        if api == 'starter':
            url = 'https://api.clarivate.com/apis/wos-starter/v1/documents'
            params = {'db': database, 'q': query, 'page': page, 'limit': size}
        else:
            url = 'https://api.clarivate.com/api/wos/'
            params = {'databaseId': database, 'usrQuery': query, 'firstRecord': len(papers)+1, 'count': size}
        data = client.get_json(url, params=params, headers={'X-ApiKey': api_key, 'Accept': 'application/json'},
                               cache_namespace='wos_'+api, fail_fast_statuses={401, 403, 429})
        if api == 'starter':
            if 'hits' not in data or 'metadata' not in data:
                raise ValueError('Unexpected WoS Starter response; not recorded as zero results')
            items = _list(data['hits'])
            total = data['metadata'].get('total')
        else:
            if 'QueryResult' not in data:
                raise ValueError('Unexpected WoS Expanded response; not recorded as zero results')
            items = _list((((data.get('Data') or {}).get('Records') or {}).get('records') or {}).get('REC'))
            total = data['QueryResult'].get('RecordsFound')
        papers.extend(normalize(item, api) for item in items)
        exhausted = not items or len(items) < size or (total is not None and len(papers) >= int(total))
        record_page(client, 'wos', papers[:max_results], total, exhausted and len(papers) <= max_results)
        if exhausted:
            break
        page += 1
    logger.info('wos %s results=%s', api, len(papers))
    return papers[:max_results]
