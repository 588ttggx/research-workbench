"""Legal open-access acquisition, explicit failure states and stable paper identities."""
from __future__ import annotations
import ipaddress
import json
from pathlib import Path
import re
import socket
import uuid
import xml.etree.ElementTree as ET
from urllib.parse import urlparse,quote,urljoin
import requests
import paper_evidence as evidence
import workflow as w

MAX_BYTES=40*1024*1024


def submit_zotero(record,artifact=None):
    from zotero_bridge import submit
    return submit(record,artifact)


def validate_public_url(url):
    parsed=urlparse(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError('全文链接不是公共 HTTPS 地址')
    addresses=socket.getaddrinfo(parsed.hostname,443,type=socket.SOCK_STREAM)
    if any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('全文地址不能指向内网或本机')


def download_pdf(url,destination):
    for _ in range(5):
        validate_public_url(url)
        response=requests.get(url,stream=True,allow_redirects=False,timeout=(12,45),headers={'User-Agent':'LocalResearchWorkspace/2.0'})
        if response.is_redirect:
            next_url=urljoin(url,response.headers['Location']);response.close();url=next_url;continue
        response.raise_for_status()
        if int(response.headers.get('Content-Length','0'))>MAX_BYTES:
            response.close();raise ValueError('全文文件超过 40 MB')
        chunks=[];total=0
        try:
            for chunk in response.iter_content(65536):
                total+=len(chunk)
                if total>MAX_BYTES:raise ValueError('全文文件超过 40 MB')
                chunks.append(chunk)
        finally:response.close()
        raw=b''.join(chunks)
        if not raw.startswith(b'%PDF-'):raise ValueError('来源没有返回实际 PDF')
        import pymupdf
        with pymupdf.open(stream=raw,filetype='pdf') as doc:
            if not len(doc):raise ValueError('PDF 没有正文页')
        from original_files import save_pdf
        saved=save_pdf(destination,raw)
        return {'url':url,'path':saved.resolve().as_posix(),'bytes':total,'sha256':w.digest(raw)}
    raise ValueError('全文来源重定向过多')


def acquire(doi, project=None, *, candidate_snapshot=None):
    doi=w.normalize_doi(doi)
    if not re.fullmatch(r'10\.\d{4,9}/[^\s<>"\x00-\x1f]{1,180}',doi):raise ValueError('请填写有效 DOI')
    if project is not None and project not in ('共享','待归类'):
        __import__('knowledge').lines(project)
    with w.process_lock() as owned:
        if not owned:raise ValueError('同步正在运行，请稍后获取全文')
        library=w.read_json(w.LIBRARY)
        active=next((r for r in library['records'] if w.normalize_doi(r.get('doi'))==doi),None)
        candidates=candidate_snapshot if candidate_snapshot is not None else __import__('radar_inbox').snapshot()
        existing=active or evidence.candidate_record(doi=doi,candidates=candidates)
        candidate=next((r for r in candidates['records'] if w.normalize_doi(r.get('doi'))==doi),None)
        if existing and active is None and project is not None:existing['project']=project
        saved=w.chosen_artifact(existing) if existing else None
        saved_xml=saved if saved and saved['kind']=='jats_xml' else None
        if saved and saved['kind']=='pdf':
            from zotero_bridge import enqueue
            outcome={'status':'already_saved','id':existing['id'],'has_pdf':True,'message':'PDF 已保存，沿用原条目。','zotero_status':'沿用原文；后台核对正式书目与附件'}
            if active is None:
                evidence.admit(existing,library,outcome,candidates=candidates)
                w.write_json(w.LIBRARY,library)
                __import__('administrator').schedule(existing.get('project') or '待归类','获取开放全文',existing['id'])
            enqueue(existing,w.chosen_artifact(existing))
            return outcome
        title=candidate['title'] if candidate else doi
        errors=[];urls=[];metadata={}
        try:
            r=requests.get('https://api.openalex.org/works/https://doi.org/'+quote(doi,safe='/'),timeout=25);r.raise_for_status();item=r.json()
            title=item.get('title') or title
            from research_radar import normalize
            metadata=normalize(item,'OpenAlex',{'id':'selected-intake','type':'paper'}) or {}
            for location in [item.get('best_oa_location'),*item.get('locations',[])]:
                if location and location.get('is_oa') and location.get('pdf_url'):urls.append(location['pdf_url'])
        except requests.RequestException:errors.append('OpenAlex 未返回可用开放全文')
        if not urls:
            try:
                r=requests.get('https://api.crossref.org/works/'+quote(doi,safe=''),timeout=25);r.raise_for_status();item=r.json()['message'];title=' '.join(item.get('title',[])) or title
                from research_radar import normalize
                crossref=normalize(item,'Crossref',{'id':'selected-intake','type':'paper'}) or {}
                for key,value in crossref.items():
                    if value and not metadata.get(key):metadata[key]=value
                if any('creativecommons.org/licenses/' in v.get('URL','') for v in item.get('license',[])):
                    urls.extend(v['URL'] for v in item.get('link',[]) if v.get('content-type')=='application/pdf')
            except requests.RequestException:errors.append('Crossref 未返回可用许可与全文')
        identifier=existing['id'] if existing else (candidate or {}).get('workspace_id') or 'oa-'+w.digest(doi)[:14]
        folder=w.KB/'文献/开放全文'/identifier
        artifact=None
        for url in dict.fromkeys(urls):
            try:
                downloaded=download_pdf(url,folder/'original.pdf')
                artifact={'kind':'pdf','path':str((folder/'original.pdf').resolve()).replace('\\','/'),**downloaded};break
            except (requests.RequestException,ValueError,OSError):errors.append('开放 PDF 未下载或未通过文件验证')
        if artifact is None and saved_xml is not None:
            # The official PMC Cloud now exposes publisher-permitted PDFs directly.
            # Supplement the original XML under the same identity, never replace it.
            try:
                from pmc_fulltext import pdf_candidates
                for candidate_pdf in pdf_candidates(existing):
                    try:
                        downloaded=download_pdf(candidate_pdf['url'],folder/'original.pdf')
                        artifact={'kind':'pdf','path':str((folder/'original.pdf').resolve()).replace('\\','/'),**candidate_pdf,**downloaded};break
                    except (requests.RequestException,ValueError,OSError):errors.append('PMC 开放 PDF 未下载或未通过文件验证')
            except (requests.RequestException,ValueError,ET.ParseError,OSError):errors.append('PMC Cloud 未返回与 DOI 对应的可用 PDF')
        # Europe PMC offers OA full text as JATS, which must not be mislabelled PDF.
        if artifact is None and saved_xml is None:
            try:
                response=requests.get('https://www.ebi.ac.uk/europepmc/webservices/rest/search',params={'query':'DOI:"'+doi+'"','format':'json'},timeout=25);response.raise_for_status()
                result=next((r for r in response.json().get('resultList',{}).get('result',[]) if r.get('isOpenAccess')=='Y' and r.get('pmcid')),None)
                if result:
                    response=requests.get('https://www.ebi.ac.uk/europepmc/webservices/rest/'+result['pmcid']+'/fullTextXML',timeout=30);response.raise_for_status()
                    tree=ET.fromstring(response.content)
                    if tree.tag!='article' or tree.find('body') is None:raise ValueError('未获取完整 XML 正文')
                    folder.mkdir(parents=True,exist_ok=True);path=folder/'original.xml';path.write_bytes(response.content)
                    artifact={'kind':'jats_xml','path':str(path.resolve()).replace('\\','/'),'url':response.url,'bytes':len(response.content),'sha256':w.digest(response.content)}
                    title=result.get('title') or title
            except (requests.RequestException,ValueError,ET.ParseError):errors.append('Europe PMC 未返回可用开放正文')
        status='downloaded' if artifact else 'pdf_unavailable' if saved_xml else 'no_open_fulltext'
        record=existing or {'id':identifier,'title':title,'doi':doi,'topic':'待归类','identity_status':'oa_metadata_unverified','reading_status':'unread','artifacts':[],'provenance':[]}
        for key in ('journal','issn','creators','publication_date','year','abstract','url','openalex_id'):
            if not record.get(key):record[key]=metadata.get(key) or (candidate or {}).get(key)
        if artifact:
            record['artifacts'].append(artifact);record['availability']='fulltext_on_disk';record['provenance'].append({'source':'合法开放全文获取','url':artifact['url'],'date':w.now(),'scope':'全文已保存，相关性与结论尚未核查'})
        else:record.setdefault('availability','metadata_only')
        if active is None:
            import administrator
            record['project']=project or record.get('project') or (candidate or {}).get('project') or administrator.settings()['default_project']
        has_pdf=bool(artifact and artifact['kind']=='pdf')
        message='PDF 已保存，可在原文页查看。' if has_pdf else '当前只保存了 XML 全文，PDF 尚未获取；原附件保留，可重试补齐 PDF。' if artifact or saved_xml else '尚未获得可用全文，请检查来源或导入 PDF。'
        outcome={'doi':doi,'status':status,'id':identifier,'has_pdf':has_pdf,'message':message,'checked':w.now(),'messages':errors,
                 'zotero_status':'Zotero 书目/附件待核查；已在本地保留'}
        try:
            outcome['zotero_status']=submit_zotero(record,artifact or saved_xml)
        except (requests.RequestException,ValueError):
            pass
        finally:
            # One durable local admission survives a failed/interrupted Zotero
            # submission, without rewriting the large candidate inbox twice.
            admitted=evidence.admit(record,library,outcome,candidates=candidates)
            w.write_json(w.LIBRARY,library)
            ledger=w.read_json(w.DATA/'全文获取记录.json',{})
            ledger[doi]=outcome;w.write_json(w.DATA/'全文获取记录.json',ledger)
            if admitted and active is None:
                __import__('administrator').schedule(record['project'],'获取开放全文',record['id'])
        return outcome


def acquire_candidates():
    # A candidate is never saved automatically before a human selects collection.
    candidates=__import__('radar_inbox').snapshot()
    records=candidates['records']
    chosen=[r for r in records if r.get('selected') and not r.get('acquisition')][:3]
    return {'attempted':len(chosen),'results':[collect_selected(r.get('doi') or r.get('openalex_id') or r.get('external_id'),candidate_snapshot=candidates) for r in chosen]}


def collect_selected(identifier, project=None, *, candidate_snapshot=None):
    candidates=candidate_snapshot if candidate_snapshot is not None else __import__('radar_inbox').snapshot()
    candidate=next((r for r in candidates['records'] if identifier in (r.get('doi'),r.get('openalex_id'),r.get('external_id'),r.get('wos_id'))),None)
    if not candidate or not candidate.get('selected'):raise ValueError('请先选择需要收录的候选')
    if candidate.get('doi'):return acquire(candidate['doi'],project=project or candidate.get('project'),candidate_snapshot=candidates)
    if project is not None and project not in ('共享','待归类'):
        __import__('knowledge').lines(project)
    with w.process_lock() as owned:
        if not owned:raise ValueError('同步正在运行，收录选择已保留')
        library=w.read_json(w.LIBRARY)
        stable=candidate.get('openalex_id') or candidate['external_id']
        paper_id=candidate.get('workspace_id') or 'radar-'+w.digest(stable)[:16]
        record=next((r for r in library['records'] if r['id']==paper_id),None)
        active=record is not None
        record=record or evidence.candidate_record(identifier=paper_id,candidates=candidates)
        if record is None:
            record={'id':paper_id,'title':candidate['title'],'doi':None,'openalex_id':candidate.get('openalex_id'),'wos_id':candidate.get('wos_id'),
                    'source':candidate.get('source'),'external_id':candidate.get('external_id'),
                    'url':candidate.get('url'),'publication_date':candidate.get('publication_date'),
                    'project':project or candidate.get('project') or '待归类','topic':'待归类','reading_status':'unread',
                    'identity_status':'radar_metadata_unverified','availability':'metadata_only','artifacts':[],
                    'provenance':[{'source':candidate.get('source'),'date':w.now(),'scope':'用户选择收录，尚未核查正文'}]}
            record.update({key:candidate.get(key) for key in ('journal','issn','creators','year','abstract','wos_id') if candidate.get(key)})
        elif not active and project is not None:record['project']=project
        outcome={'status':'metadata_saved','id':paper_id,'checked':w.now(),'zotero_status':'Zotero 书目待核查；已在本地保留',
                 'message':'题录已保留在候选；实际全文到位后进入活动文献库。' if not evidence.eligible(record) else '沿用原全文条目。'}
        try:
            outcome['zotero_status']=submit_zotero(record)
        except (requests.RequestException,ValueError):
            pass
        finally:
            admitted=evidence.admit(record,library,outcome,candidates=candidates)
            w.write_json(w.LIBRARY,library)
            if admitted and not active:
                __import__('administrator').schedule(record.get('project') or '待归类','获取开放全文',record['id'])
        return outcome
