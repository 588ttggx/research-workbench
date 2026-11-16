"""Cache public bibliographic years for visualizations without editing the formal library."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import threading
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
import xml.etree.ElementTree as ET
from urllib.parse import quote
import requests
from filelock import FileLock
import workflow as w

LOCK = threading.Lock()


def local_metadata(record):
    for artifact in record.get('artifacts',[]):
        path=Path(artifact.get('path',''))
        if artifact.get('kind')!='jats_xml' or not path.is_file() or path.stat().st_size>20*1024*1024:continue
        try:tree=ET.parse(path)
        except (OSError,ET.ParseError):continue
        journal=tree.findtext('./front/journal-meta/journal-title-group/journal-title') or tree.findtext('./front/journal-meta/journal-title')
        codes=[n.text.strip() for n in tree.findall('./front/journal-meta/issn') if n.text]
        year=next((n.text.strip() for n in tree.findall('./front/article-meta/pub-date/year') if n.text and n.text.strip().isdigit() and 1900<=int(n.text.strip())<=2099),None)
        if year or journal or codes:return {'year':year,'journal':journal,'issn':codes,'source':'已保存 JATS 原文题录','source_path':str(path)}
    # Chinese publisher headers often provide the article number even when the
    # DOI agency has no Crossref record. Match that labelled field, never a
    # general year in the body or references.
    import pymupdf
    for artifact in record.get('artifacts',[]):
        path=Path(artifact.get('path',''))
        if artifact.get('kind')!='pdf' or not path.is_file():continue
        try:
            with pymupdf.open(path) as doc:text=doc[0].get_text()[:6000] if len(doc) else ''
        except (OSError,ValueError,RuntimeError):continue
        match=re.search(r'文章编号[：:]\s*(\d{4})[−–-](\d{3}[\dXx])[（(](20\d{2})[）)]',text)
        if not match:continue
        journal=re.search(r'\[J\][.．]\s*([\u4e00-\u9fff]+)[，,]',text)
        return {'year':match[3],'journal':journal[1] if journal else record.get('journal'),
                'issn':[match[1]+'-'+match[2]],'source':'PDF 首页文章编号与题录','source_path':str(path),'pdf_page':1}
    return {}


def enriched(records):
    cached=w.read_json(w.DATA/'书目日期.json',{})
    identities=publication_identities(records)
    result=[]
    for record in records:
        row=dict(record);meta=cached.get(record['id'],{})
        if (meta.get('doi') or '')==(w.normalize_doi(record.get('doi')) or ''):
            for name in ('year','journal','issn','publication_date'):
                if not row.get(name) and meta.get(name):row[name]=meta[name]
            if not record.get('year') and row.get('year'):row['year_source']=meta.get('source')
            if not row.get('doi') and meta.get('resolved_doi'):row['doi']=meta['resolved_doi']
        result.append({**row,**identities.get(record['id'],{})})
    return result


def publication_identities(records):
    """Link independently registered IDs when exact PDF and title support one DOI."""
    groups=defaultdict(dict)
    for row in records:
        title=' '.join(str(row.get('title') or '').casefold().split())
        if not title:
            continue
        for artifact in row.get('artifacts',[]):
            digest=artifact.get('sha256')
            if artifact.get('kind')=='pdf' and isinstance(digest,str) and re.fullmatch('[a-fA-F0-9]{64}',digest):
                groups[title,digest.lower()][row['id']]=w.normalize_doi(row.get('doi'))
    matches=defaultdict(set)
    for members in groups.values():
        known={identifier:doi for identifier,doi in members.items() if doi}
        if len(members)<2 or len(set(known.values()))!=1:
            continue
        for identifier in members:
            matches[identifier].add(tuple(sorted(set(members)-{identifier})))
    return {identifier:{'related_paper_ids':list(related)}
            for identifier, candidates in matches.items() if len(candidates)==1
            for related in candidates}


def title_matches(left,right):
    clean=lambda text:re.sub(r'[^\w]','',str(text or '').casefold())
    a,b=clean(left),clean(right)
    return len(a)>=20 and bool(b) and SequenceMatcher(None,a,b).ratio()>=.94


def pdf_dois(record):
    """Header candidates only; Crossref title verification is still required."""
    import pymupdf
    values=[]
    for artifact in record.get('artifacts',[]):
        path=Path(artifact.get('path',''))
        if artifact.get('kind')!='pdf' or not path.is_file():continue
        try:
            with pymupdf.open(path) as doc:
                if not len(doc):continue
                text=doc[0].get_text()+'\n'+'\n'.join(link.get('uri','') for link in doc[0].get_links())
        except (OSError,ValueError,RuntimeError):continue
        for token in re.findall(r'10\.\d{4,9}/[^\s<>\"]+',text):
            value=w.normalize_doi(token.rstrip('.,;)'))
            if value and value not in values:values.append(value)
    return values[:3]


def refresh_dates(force=False):
    w.DATA.mkdir(parents=True,exist_ok=True)
    with LOCK,FileLock(str(w.DATA/'.bibliography.lock'),timeout=25):
        path = w.DATA/'书目日期.json'
        previous = w.read_json(path, {})
        records = w.read_json(w.KB/'文献/library.json', {'records': []})['records']
        missing = [r for r in records if force or (previous.get(r['id'], {}).get('doi') or '') != (w.normalize_doi(r.get('doi')) or '') or
            (previous.get(r['id'], {}).get('status') != 'saved' or not previous.get(r['id'],{}).get('metadata_checked')) and previous.get(r['id'], {}).get('next_retry', '') < w.now()][:40]
        def fetch(record):
            doi = w.normalize_doi(record.get('doi'))
            local=local_metadata(record)
            if local.get('year') and local.get('issn'):
                return record['id'],{**local,'doi':doi,'status':'saved','metadata_checked':True,'checked':w.now()}
            try:
                headers={'User-Agent':'LocalResearchWorkflow/1.0 (bibliographic metadata lookup)'}
                candidates=[doi] if doi else pdf_dois(record)
                item=None
                for candidate in candidates:
                    response=requests.get('https://api.crossref.org/works/'+quote(candidate,safe=''),headers=headers,timeout=20)
                    if response.status_code==404:continue
                    response.raise_for_status();found=response.json()['message']
                    if doi or title_matches(record.get('title'),next(iter(found.get('title') or []),'')):
                        item=found;break
                if item is None and not doi:
                    response=requests.get('https://api.crossref.org/works',params={'query.title':record.get('title',''),'rows':3},headers=headers,timeout=20)
                    response.raise_for_status()
                    matches=[p for p in response.json()['message']['items'] if title_matches(record.get('title'),next(iter(p.get('title') or []),''))]
                    if len({p.get('DOI') for p in matches})==1:item=matches[0]
                if item is None:raise ValueError('没有通过身份核验的题录')
                date = next((item.get(key, {}).get('date-parts', [[]])[0] for key in ('published', 'published-print', 'published-online', 'issued') if item.get(key, {}).get('date-parts')), [])
                year = date[0] if date and type(date[0]) is int and 1900 <= date[0] <= 2099 else None
                return record['id'], {**local,'doi':doi,'resolved_doi':w.normalize_doi(item.get('DOI')) if not doi else None,'year':str(year) if year else local.get('year'),
                    'journal':next(iter(item.get('container-title') or []),None) or local.get('journal'),'issn':item.get('ISSN') or local.get('issn') or [],
                    'status':'saved' if year or local.get('year') else 'unavailable','metadata_checked':True,
                    'source':'Crossref 题录；文献身份沿用原核查状态','checked':w.now(),'next_retry':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}
            except (requests.RequestException, KeyError, ValueError):
                old=previous.get(record['id'],{})
                if (old.get('doi') or '')!=(doi or ''):old={}
                preserved={**old,**{key:value for key,value in local.items() if value}}
                return record['id'], {**preserved,'doi':doi,'status':'saved' if preserved.get('year') else 'unavailable',
                    'metadata_checked':False,'checked':w.now(),'next_retry':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}
        if missing:
            with ThreadPoolExecutor(max_workers=3) as pool:
                previous.update(pool.map(fetch, missing))
            w.write_json(path, previous)
        return {'known_years': sum(bool(p.get('year')) for p in previous.values()), 'checked': len(missing)}
