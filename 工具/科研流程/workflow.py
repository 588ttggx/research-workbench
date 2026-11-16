"""Local, restartable Zotero → Open Notebook accumulation workflow."""
from __future__ import annotations

import argparse
import base64
from collections import defaultdict
from contextlib import contextmanager
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import threading
import time

import requests

from workspace_runtime import (ROOT, HERE, DATA, KB, LIBRARY, STATE, API, ZOTERO,
                               now, digest, read_json, atomic_text, write_json)
LOCK = threading.Lock()


def api(method, path, **kwargs):
    response = requests.request(method, API + path, timeout=180, **kwargs)
    response.raise_for_status()
    return response.json() if response.content else None


def all_sources(notebook=None):
    result, offset = [], 0
    while True:
        batch = api('GET', '/sources', params={'limit':100, 'offset':offset, **({'notebook_id':notebook} if notebook else {})})
        result.extend(batch)
        if len(batch) < 100:
            return result
        offset += 100


def normalize_doi(value):
    return re.sub(r'^https?://(?:dx\.)?doi\.org/', '', (value or '').strip(), flags=re.I).lower()


def clean_markdown(content):
    content = re.sub(r'\A---\r?\n.*?\r?\n---\r?\n', '', content, flags=re.S)
    return re.split(r'\n## Relations\s*\n', content)[0].strip()


class NoteTextParser(HTMLParser):
    """Readable text for notes not registered with Better Notes; HTML is never rendered."""
    def __init__(self):
        super().__init__()
        self.parts=[]
        self.hidden=0

    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):
            self.hidden+=1
        if tag in ('p','div','br','li','h1','h2','h3'):
            self.parts.append('\n')

    def handle_endtag(self,tag):
        if tag in ('script','style'):
            self.hidden=max(0,self.hidden-1)
        if tag in ('p','div','li','h1','h2','h3'):
            self.parts.append('\n')

    def handle_data(self,data):
        if not self.hidden:
            self.parts.append(data)


def export_zotero_notes(items,state):
    import note_reconciliation
    state['better_notes_comparison']={'checked':now(),'records':len(note_reconciliation.compare(items,locked=True)['records']),
                                     'boundary':'Markdown-main; native plugin registrations unchanged'}
    ledger=state.setdefault('zotero_notes',{})
    for item in items:
        if item['itemType']!='note':
            continue
        tags=[tag['tag'] for tag in item.get('tags',[])]
        if any(tag.startswith(('workspace-note:','workspace-provenance:')) for tag in tags):
            continue  # Compared and preserved separately; never overwrite knowledge originals.
        raw=item.get('note') or ''
        parser=NoteTextParser()
        parser.feed(raw)
        text=re.sub(r'\n{3,}','\n\n',''.join(parser.parts)).strip()
        if not text:
            continue
        path=KB/'笔记/Zotero'/(item['key']+'.md')
        import note_management as notes
        if notes.suppressed(path.relative_to(KB).as_posix()):continue
        current_hash=digest(path.read_text('utf-8')) if path.exists() else None
        previous=ledger.get(item['key'],{})
        if previous.get('html_hash')==digest(raw):
            continue
        content=f"# Zotero 笔记 {item['key']}\n\n来源：zotero://select/library/items/{item['key']}；父条目：{item.get('parentItem') or '独立笔记'}\n\n{text}\n"
        if previous and path.exists() and current_hash!=previous.get('file_hash'):
            conflict=KB/'同步冲突'/('zotero-'+item['key']+'-'+digest(raw)[:8]+'.md')
            if not conflict.exists():
                atomic_text(conflict,content)
                event(state,'conflict','Zotero 笔记和导出文件均有修改，保留远端副本：'+item['key'])
            ledger[item['key']]['conflict']=str(conflict.relative_to(KB))
            continue
        if path.exists():
            atomic_text(DATA/'备份/笔记'/('zotero-'+item['key']+'-'+current_hash[:12]+'.md'),path.read_text('utf-8'))
        atomic_text(path,content)
        ledger[item['key']]={'html_hash':digest(raw),'file_hash':digest(content),'exported':now()}
        event(state,'note','Zotero 阅读笔记已导出：'+item['key'])


def note_action(local, remote, previous):
    if local == remote:
        return 'same'
    if not previous or remote != previous.get('remote'):
        return 'conflict'
    return 'push' if local != previous.get('local') else 'same'


def event(state, kind, message, record_id=None):
    item = {'time':now(), 'kind':kind, 'message':message, 'record_id':record_id}
    state.setdefault('events', []).append(item)
    state['events'] = state['events'][-300:]
    log = ROOT / '工具/日志/科研流程.jsonl'
    try:
        import runtime_logs
        runtime_logs.append_jsonl(log, item, log_root=log.parent)
    except (OSError, ValueError) as error:
        import sys
        print('technical_log_error:'+type(error).__name__, file=sys.stderr, flush=True)
    print(json.dumps(item, ensure_ascii=True), flush=True)


def load_state():
    return read_json(STATE, {'papers':{}, 'notes':{}, 'events':[], 'schema':1})


def notebooks():
    existing = {item['name']:item['id'] for item in api('GET', '/notebooks')}
    project_names=['项目：'+p.name for p in (KB/'项目').iterdir() if p.is_dir() and p.name!='山药']
    for name in ('科研共享背景', '山药课题',*project_names):
        if name not in existing:
            existing[name] = api('POST', '/notebooks', json={'name':name, 'description':'科研共享资料积累'})['id']
    return existing


def note_notebook(relative,spaces):
    parts=Path(relative).parts
    if len(parts)>2 and parts[0]=='项目':
        return spaces['山药课题'] if parts[1]=='山药' else spaces['项目：'+parts[1]]
    if relative.startswith(('文献/阅读卡片/','文献/AI阅读记录/')):
        return spaces['山药课题'] if 'YAM' in relative or 'NAKAJIMA' in relative or 'LASSO' in relative else spaces['科研共享背景']
    return spaces['科研共享背景']


def paper_notebook(record, spaces):
    # All original non-group papers were selected for the yam research project.
    project=record.get('project')
    if project == '山药':
        return spaces['山药课题']
    if project and '项目：'+project in spaces:
        return spaces['项目：'+project]
    return spaces['科研共享背景'] if record['id'].startswith(('group-','zotero-','oa-')) else spaces['山药课题']


def zotero_items():
    result, offset = [], 0
    while True:
        response = requests.get(ZOTERO + '/items', params={'limit':100,'start':offset}, timeout=30)
        response.raise_for_status()
        batch = response.json()
        result.extend(item['data'] for item in batch)
        if len(batch) < 100:
            return result
        offset += 100


def merge_zotero(library, state):
    """Read through Zotero's supported local API, never open its live SQLite DB."""
    try:
        items = zotero_items()
    except requests.RequestException as exc:
        state['zotero'] = {'online':False, 'error':type(exc).__name__, 'checked':now()}
        return
    state['zotero'] = {'online':True, 'checked':now(), 'items':len(items)}
    export_zotero_notes(items,state)
    import paper_evidence as evidence
    candidate_snapshot = __import__('radar_inbox').snapshot()
    pending = evidence.candidate_records(candidate_snapshot)
    active_ids = {record['id'] for record in library['records']}
    known = pending + library['records']
    by_id = {r['id']:r for r in known}
    by_doi = {normalize_doi(r.get('doi')):r for r in known if r.get('doi')}
    imported = read_json(ROOT / '工具/日志/zotero-import.json', {})
    by_key = {p['key']:by_id[p['recordID']] for p in imported.get('papers',[]) if p['recordID'] in by_id}
    by_key.update({r['zotero_key']:r for r in known if r.get('zotero_key')})
    legacy_ids = {p['key']:p['recordID'] for p in imported.get('papers',[])}
    attachments = {}
    batch = {}
    for item in items:
        if item['itemType'] == 'attachment' and item.get('parentItem'):
            attachments.setdefault(item['parentItem'], []).append(item)
    for item in items:
        if item['itemType'] in ('attachment','note','annotation'):
            continue
        tags = [t['tag'] for t in item.get('tags', [])]
        identifier = next((t.split(':',1)[1] for t in tags if t.startswith('workspace-id:')), None)
        if identifier and (not re.fullmatch(r'[\w.-]{1,120}',identifier) or identifier in ('.','..')):
            identifier = None
        record = by_id.get(identifier) or by_key.get(item['key']) or by_doi.get(normalize_doi(item.get('DOI')))
        if record is None:
            record = {'id':identifier or legacy_ids.get(item['key']) or 'zotero-' + item['key'], 'title':item.get('title') or item['key'], 'doi':item.get('DOI') or None, 'topic':'; '.join(tags), 'identity_status':'zotero_metadata_unverified', 'availability':'metadata_only', 'reading_status':'unread', 'artifacts':[], 'provenance':[{'source':'Zotero local API','date':now()}]}
            import administrator
            record['project']=administrator.settings()['default_project']
            by_id[record['id']] = record
        by_key[item['key']] = record
        record['zotero_key'] = item['key']
        record['zotero_version'] = item['version']
        record['creators'] = item.get('creators',[])
        record['authors'] = [c.get('name') or ' '.join(filter(None,[c.get('firstName'),c.get('lastName')])) for c in item.get('creators',[]) if c.get('creatorType')=='author']
        record['journal'] = item.get('publicationTitle') or ''
        record['issn'] = item.get('ISSN') or ''
        record['abstract'] = item.get('abstractNote') or ''
        record['url'] = item.get('url') or ''
        if item.get('date'):
            record['publication_date'] = item['date']
        # Explicit edits in Zotero update metadata while identity and old provenance remain stable.
        if item.get('title'):
            record['title'] = item['title']
        if item.get('DOI'):
            record['doi'] = item['DOI']
            by_doi[normalize_doi(item['DOI'])] = record
        for attachment in attachments.get(item['key'], []):
            kind = 'pdf' if attachment.get('contentType') == 'application/pdf' or attachment.get('filename','').lower().endswith('.pdf') else 'jats_xml' if str(attachment.get('path') or attachment.get('filename','')).lower().endswith('.xml') else None
            if not kind:
                continue
            raw = attachment.get('path') or attachment.get('filename') or ''
            if attachment.get('linkMode') in ('imported_file','imported_url'):
                from zotero_bridge import attachment_path
                resolved = attachment_path(attachment['key'])
                file_path = resolved if resolved is not None else Path.home() / 'Zotero/storage' / attachment['key'] / attachment.get('filename',raw.removeprefix('storage:'))
            elif raw.startswith('storage:'):
                file_path = Path.home() / 'Zotero/storage' / attachment['key'] / raw[8:]
            elif attachment.get('linkMode') == 'imported_file':
                file_path = Path.home() / 'Zotero/storage' / attachment['key'] / attachment.get('filename', raw)
            elif raw.startswith('attachments:'):
                # Relative linked files require the user's Zotero base directory; do not guess.
                continue
            else:
                file_path = Path(raw)
            if not file_path.is_absolute() or not file_path.is_file():
                continue
            path = str(file_path.resolve()).replace('\\','/')
            old = next((a for a in record['artifacts'] if Path(a['path']) == file_path), None)
            if old is None:
                old = {'kind':kind, 'path':path}
                record['artifacts'].append(old)
            stamp = file_path.stat()
            if old.get('mtime_ns') != stamp.st_mtime_ns or old.get('bytes') != stamp.st_size:
                old.update(bytes=stamp.st_size, mtime_ns=stamp.st_mtime_ns, sha256=digest(file_path.read_bytes()), zotero_attachment_key=attachment['key'])
        batch[record['id']] = record
    acquisitions=read_json(DATA/'全文获取记录.json',{})
    confirmed=False
    outcomes={}
    for outcome in acquisitions.values():
        record=by_id.get(outcome.get('id'))
        if record and outcome.get('status')=='downloaded' and any(a.get('zotero_attachment_key') and Path(a['path']).is_file() for a in record['artifacts']):
            message='Zotero 书目及全文附件已保存'
            if outcome.get('zotero_status')!=message:
                outcome['zotero_status']=message;outcome['zotero_attachment_key']=next(a['zotero_attachment_key'] for a in record['artifacts'] if a.get('zotero_attachment_key'));confirmed=True
                outcomes[record['id']]=outcome
                batch.setdefault(record['id'],record)
    if confirmed:
        write_json(DATA/'全文获取记录.json',acquisitions)
    admitted=evidence.admit_many(batch.values(),library,outcomes,candidate_snapshot)
    for record in batch.values():
        if record['id'] in admitted and record['id'] not in active_ids:
            __import__('administrator').schedule(record.get('project') or '待归类','新增 Zotero 条目',record['id'])
            event(state, 'paper', '全文进入活动文献库：' + record['title'], record['id'])


def chosen_artifact(record):
    for kind in ('pdf','jats_xml'):
        for artifact in record.get('artifacts', []):
            if artifact['kind'] == kind and Path(artifact['path']).is_file():
                return artifact
    return None


@contextmanager
def process_lock():
    """Prevent CLI and the background service from importing the same item concurrently."""
    import msvcrt
    DATA.mkdir(parents=True,exist_ok=True)
    with (DATA/'.sync.lock').open('a+b') as handle:
        handle.seek(0)
        try:
            if not handle.read(1):
                handle.write(b'0')
                handle.flush()
        except PermissionError:
            # Windows denies reads of a byte held by another sync process too.
            # Treat this as busy so backup/polling can wait and try again.
            yield False
            return
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)


def extract(record, artifact, *, repair=False):
    """Read quality-checked text; existing suspect caches need explicit repair."""
    import fulltext_parser
    source = Path(artifact['path'])
    sha = digest(source.read_bytes())
    cache = DATA / '正文' / (sha + '.json')
    return fulltext_parser.extract(artifact, cache, sha, repair=repair)


def indexed_text(record, extracted):
    import fulltext_parser
    if fulltext_parser.assess_cache(extracted).get('status')!='ready':
        raise ValueError('原文文字质量未通过，请先修复异常页；原文和已有索引保留。')
    header = f"文献 ID：{record['id']}\n题名：{record['title']}\nDOI：{record.get('doi') or '未核实'}\n原文类型：{extracted['kind']}\n"
    chunks = []
    for page in extracted['pages']:
        location = f"PDF 第 {page['page']} 页" if page.get('page') else f"XML {page.get('section','正文')}（无 PDF 页码）"
        chunks.append(f"[文献 {record['id']} · {location} · {page['method']}]\n{page['text']}")
    return header + '\n\n'.join(chunks)


def create_text_source(title, content, notebook):
    return api('POST','/sources', data={'type':'text','title':title,'content':content,'notebooks':json.dumps([notebook]),'embed':'true','async_processing':'true'})


def wait_source(source_id, seconds=180):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        source = api('GET','/sources/' + source_id)
        if source.get('full_text') and source.get('embedded_chunks',0) > 0:
            return source
        if source.get('status') in ('failed','error'):
            raise RuntimeError('来源处理失败：' + source_id)
        time.sleep(1)
    raise TimeoutError('来源索引尚未完成：' + source_id)


def source_matches_paper(source, identifier):
    first_line, _, _ = (source.get('full_text') or '').lstrip('\ufeff').partition('\n')
    return first_line.rstrip('\r') == '文献 ID：'+identifier


def sync_paper(record, state, spaces, existing):
    artifact = chosen_artifact(record)
    entry = state['papers'].setdefault(record['id'], {})
    if artifact is None:
        entry.update(status='metadata_only', title=record['title'])
        return
    extracted = extract(record,artifact)
    if extracted.get('status')!='ready':
        entry.update(status=extracted.get('status','unparsed'), sha256=extracted['sha256'],
                     text_quality=extracted.get('quality_failed_locations',[]))
        return
    content = indexed_text(record,extracted)
    fingerprint = digest(content)
    target = paper_notebook(record,spaces)
    source_id = entry.get('source_id')
    other_claims = {other.get(field) for key, other in state['papers'].items() if key != record['id']
                    for field in ('source_id', 'pending_id')}
    registered_id = record.get('open_notebook_source_id')
    if not source_id and registered_id in existing and registered_id not in other_claims:
        registered = api('GET', '/sources/'+registered_id)
        if source_matches_paper(registered, record['id']):
            source_id = registered_id
            if digest(registered['full_text']) == fingerprint and registered.get('embedded_chunks', 0) > 0:
                api('POST', '/notebooks/'+target+'/sources/'+source_id)
                entry.update(pending_id=source_id, pending_fingerprint=fingerprint, notebook=target,
                             title=record['title'], original=artifact['path'])
                complete_paper(record, entry, state, extracted, detail=registered)
                return
    if entry.get('fingerprint') == fingerprint and source_id in existing and source_id not in other_claims:
        if entry.get('notebook')!=target:
            api('POST','/notebooks/'+target+'/sources/'+source_id)
            entry['notebook']=target
        entry.update(status='indexed', original=artifact['path'])
        entry.pop('error', None)
        record['open_notebook_source_id'] = source_id
        return
    entry.update(title=record['title'], status='indexing', original=artifact['path'])
    write_json(STATE,state)
    payload = create_text_source(record['title'],content,target)
    new_id = payload['id']
    # Persist pending replacement BEFORE waiting. Failed runs resume it, no duplicate creation.
    entry.update(pending_id=new_id,pending_fingerprint=fingerprint,pending_old_id=source_id,notebook=target)
    write_json(STATE,state)
    complete_paper(record, entry, state, extracted)


def complete_paper(record, entry, state, extracted=None, *, detail=None):
    pending = entry['pending_id']
    detail = detail if detail is not None else wait_source(pending)
    if not source_matches_paper(detail, record['id']):
        for key in ('pending_id', 'pending_fingerprint', 'pending_old_id'):
            entry.pop(key, None)
        write_json(STATE, state)
        raise ValueError('待发布检索来源的文献身份不匹配，来源已保留。')
    old_id = entry.get('pending_old_id')
    extracted = extracted or extract(record,chosen_artifact(record))
    if old_id and old_id != pending:
        replaced = entry.setdefault('replaced_source_ids', [])
        if old_id not in replaced:
            replaced.append(old_id)
    entry.update(text_fingerprint=extracted.get('text_fingerprint'),parser_version=extracted.get('parser_version'))
    entry.update(source_id=pending, fingerprint=entry['pending_fingerprint'], status='indexed', indexed_at=now(), sha256=extracted['sha256'], page_count=len(extracted['pages']) if extracted['kind']=='pdf' else 0, ocr_pages=sum(p['method']=='local_ocr' for p in extracted['pages']), embedded_chunks=detail['embedded_chunks'])
    for key in ('pending_id','pending_fingerprint','pending_old_id','error'):
        entry.pop(key,None)
    record['open_notebook_source_id'] = pending
    event(state,'indexed','已保存原文定位并完成索引：'+record['title'],record['id'])
    write_json(STATE,state)


def clean_replaced_sources(state, records):
    """Retire a derivative only after both current mappings have been saved."""
    active_ids = {record.get('open_notebook_source_id') for record in records}
    active_ids.update(entry.get(field) for entry in state['papers'].values()
                      for field in ('source_id', 'pending_id'))
    errors = []
    for identifier, entry in state['papers'].items():
        for source_id in list(entry.get('replaced_source_ids', [])):
            if source_id in active_ids:
                continue
            try:
                source = api('GET', '/sources/'+source_id)
                if source_matches_paper(source, identifier):
                    write_json(DATA/'备份'/(source_id.replace(':','-')+'.json'), source)
                    api('DELETE', '/sources/'+source_id)
                    event(state, 'dedupe', '已备份旧检索索引：'+identifier, identifier)
                else:
                    event(state, 'conflict', '旧检索来源的归属无法确认，已保留：'+source_id, identifier)
            except (requests.RequestException, OSError) as exc:
                if not (isinstance(exc, requests.HTTPError) and exc.response is not None
                        and exc.response.status_code == 404):
                    errors.append({'id': identifier, 'error': type(exc).__name__+': '+str(exc)[:250]})
                    continue
            entry['replaced_source_ids'].remove(source_id)
        if not entry.get('replaced_source_ids'):
            entry.pop('replaced_source_ids', None)
    return errors


def sync_notes(state,spaces):
    remote_notes = api('GET','/notes')
    import note_management as notes
    claims = defaultdict(set)
    for relative, entry in state['notes'].items():
        if entry.get('note_id'):
            claims[entry['note_id']].add(relative)
    for row in notes.active():
        if row.get('remote_note_id'):
            claims[row['remote_note_id']].add(row['path'])
    shared = {identifier for identifier, paths in claims.items() if len(paths) > 1}
    if shared:
        for remote in remote_notes:
            if remote['id'] in shared:
                write_json(DATA/'备份/冲突笔记'/(digest(remote['id']+json.dumps(remote, sort_keys=True))[:24]+'.json'), remote)
        for relative, entry in state['notes'].items():
            if entry.get('note_id') in shared:
                entry['ambiguous_note_id'] = entry.pop('note_id')
                entry.pop('notebook', None)
                event(state, 'conflict', '共用的检索笔记已保留并重新绑定：'+relative)
        write_json(STATE, state)
    notes.sync_remote(state,remote_notes,protected_ids=shared)
    archived = notes.archived_paths()
    removed = notes.sync_archived(state,remote_notes,archived)
    preserved = {entry.get('ambiguous_note_id') for entry in state['notes'].values()}
    excluded = notes.remote_ids() | removed | preserved
    remote_notes=[n for n in remote_notes if n['id'] not in excluded]
    remote_by_id = {n['id']:n for n in remote_notes}
    paths = list((KB/'背景').glob('*.md')) + list((KB/'项目').rglob('*.md')) + list((KB/'文献/阅读卡片').glob('*.md')) + list((KB/'文献/AI阅读记录').glob('*.md')) + list((KB/'更新记录').glob('*.md'))
    # Export notes created directly in Open Notebook to Markdown, then manage them normally.
    managed_ids = {entry.get('note_id') for entry in state['notes'].values()} | notes.remote_ids()
    for note in remote_notes:
        if note['id'] not in managed_ids:
            path = KB / '笔记/OpenNotebook' / (note['id'].replace(':','-') + '.md')
            if not path.exists():
                atomic_text(path, f"# {note.get('title') or '未命名笔记'}\n\n{note.get('content') or ''}\n")
            relative = str(path.relative_to(KB)).replace('\\','/')
            state['notes'][relative] = {'note_id':note['id'],'local':digest(clean_markdown(path.read_text('utf-8'))),'remote':digest(note.get('content') or ''),'notebook':spaces['科研共享背景']}
    paths += list((KB/'笔记').rglob('*.md'))
    for path in paths:
        relative = str(path.relative_to(KB)).replace('\\','/')
        if relative in archived or notes.suppressed(relative):continue
        entry = state['notes'].setdefault(relative,{})
        raw_note=path.read_text('utf-8')
        import knowledge as knowledge_records
        from material_roles import interpret
        metadata=knowledge_records.split(raw_note)[0]
        role=interpret(metadata,'科研知识库/'+relative)
        if role['content_role'] in {'system_record','unclassified'} or role['stage_removed']:
            entry['excluded_content_role']=role['content_role'];continue
        entry.pop('excluded_content_role',None)
        if metadata.get('record_type')=='Stage':
            from project_stages import active_body
            raw_note=active_body(raw_note)
        local = clean_markdown(raw_note)
        local_hash = digest(local)
        remote = remote_by_id.get(entry.get('note_id'))
        notebook = entry.get('notebook') or note_notebook(relative,spaces)
        created = remote is None
        if created:
            remote = api('POST','/notes',json={'title':path.stem,'content':local,'note_type':'ai' if relative.startswith(('文献/AI阅读记录/','更新记录/')) else 'human','notebook_id':notebook})
            event(state,'note','新笔记入库：'+path.stem)
        else:
            remote_content = remote.get('content') or ''
            action = note_action(local_hash,digest(remote_content),entry)
            if action=='conflict':
                conflict = KB/'同步冲突'/(digest(relative+remote_content)[:16] + '.md')
                if not conflict.exists():
                    atomic_text(conflict, f"# 同步冲突：{relative}\n\nOpen Notebook 版本有变更，原文件保留。\n\n## 本地版本\n\n{local}\n\n## Open Notebook 版本\n\n{remote_content}\n")
                    event(state,'conflict','Open Notebook 修改已保留为冲突副本：'+relative)
                entry['conflict'] = str(conflict.relative_to(KB))
                continue
            if action=='push':
                write_json(DATA/'备份'/(remote['id'].replace(':','-')+'-'+digest(remote_content)[:12]+'.json'),remote)
                remote = api('PUT','/notes/'+remote['id'],json={'title':path.stem,'content':local})
                event(state,'note','Markdown 修改已同步到笔记：'+relative)
        entry.update(note_id=remote['id'],local=local_hash,remote=digest(remote.get('content') or ''),notebook=notebook,synced=now())
        entry.pop('conflict',None)
        if created:
            write_json(STATE, state)


def changes_feed(state):
    rows = ['# 科研区更新记录','', '这是处理与来源变更记录；索引成功不代表已精读。','']
    for item in state.get('events', [])[-100:]:
        rows.append(f"- {item['time']} · {item['kind']} · {item['message']}")
    atomic_text(KB/'运行记录.md','\n'.join(rows)+'\n')


def sync():
    with process_lock() as acquired:
        return sync_locked() if acquired else {'busy':True,'status':'waiting','message':'已有同步或备份，待下一轮接续。'}


def sync_locked():
    if not LOCK.acquire(blocking=False):
        return {'busy':True,'status':'waiting','message':'已有同步，待下一轮接续。'}
    state = None
    try:
        state = load_state()
        state.update(running=True,last_started=now())
        write_json(STATE,state)
        library = read_json(LIBRARY)
        from paper_import import import_inbox
        import_inbox(library)
        from zotero_bridge import drain
        drain()
        merge_zotero(library,state)
        from workspace import reconcile_paper_properties
        reconcile_paper_properties(library)
        spaces = notebooks()
        existing = {s['id']:s for s in all_sources()}
        from document_parser import ManagedInferenceUnavailable, sync_inference_retry
        errors = []
        indexed = 0
        with sync_inference_retry(state) as retry:
            for record in library['records']:
                try:
                    entry = state['papers'].get(record['id'],{})
                    if entry.get('pending_id'):
                        complete_paper(record,entry,state)
                    sync_paper(record,state,spaces,existing)
                    entry = state['papers'].get(record['id'],{})
                    if entry.get('source_id'):
                        existing[entry['source_id']] = {'id':entry['source_id'],'title':record['title']}
                    if entry.get('status') == 'indexed':
                        indexed += 1
                    if entry.get('status') in {'unparsed','low_quality_text'}:
                        errors.append({'id':record['id'],'error':'原文文字质量待核查。','category':'text_quality'})
                except Exception as exc:
                    message = type(exc).__name__ + ': ' + str(exc)[:350]
                    entry = state['papers'].setdefault(record['id'],{})
                    if entry.get('error') != message:
                        event(state,'error',record['title'] + '：' + message,record['id'])
                    waiting = isinstance(exc, ManagedInferenceUnavailable)
                    entry.update(status='waiting' if waiting else 'error',error=message)
                    issue = {'id':record['id'],'error':message}
                    if waiting:
                        issue.update(dependency='document_parser',retry_after=retry.get('retry_after'))
                    errors.append(issue)
                    write_json(STATE,state)
        sync_notes(state,spaces)
        library.update(integration_status='zotero_open_notebook_incremental_sync')
        checked = now()
        library['last_sync_attempt'] = checked
        write_json(LIBRARY,library)
        errors.extend(clean_replaced_sources(state,library['records']))
        from workspace import refresh_views
        refresh_views()
        state.pop('last_error',None)
        dependencies = {}
        if state.get('zotero',{}).get('online') is False:
            dependencies['zotero'] = {'status':'waiting','error':state['zotero']['error']}
        blocked = next((item for item in errors if item.get('dependency')=='document_parser'),None)
        if blocked:
            dependencies['document_parser'] = {'status':'waiting','error':blocked['error'],**retry}
        if not (errors or dependencies):
            status = 'completed'
            state['last_completed'] = checked
            library['last_synced'] = checked
            write_json(LIBRARY,library)
        elif indexed or state['notes'] or len(errors) < len(library['records']):
            status = 'partial'
        elif dependencies and all(item.get('dependency') for item in errors):
            status = 'waiting'
        else:
            status = 'failed'
        messages = {'completed':'同步完成。','partial':'同步部分完成，失败或等待的资料留待接续。',
                    'waiting':'同步依赖暂不可用，待下一轮接续。','failed':'本轮同步未完成，请检查资料或运行记录。'}
        result = {'status':status,'message':messages[status],'papers':len(library['records']),
                  'notes':len(state['notes']),'indexed':indexed,'errors':errors,'dependencies':dependencies}
        state.update(errors=errors,last_attempt=result,last_finished=checked)
        changes_feed(state)
        return result
    except Exception as exc:
        if state is not None:
            state['last_error'] = type(exc).__name__ + ': ' + str(exc)[:300]
            state['last_attempt'] = {'status':'failed','message':state['last_error']}
            event(state,'error',state['last_error'])
        raise
    finally:
        try:
            if state is not None:
                state['running'] = False
                write_json(STATE,state)
        finally:
            LOCK.release()


def search(query, include_notes=False, limit=10, *, scope='knowledge', project=None):
    result = api('POST','/search',json={'query':query,'type':'vector','limit':limit,'minimum_score':0.15,'search_sources':True,'search_notes':include_notes})
    if include_notes:
        import note_management as notes
        suppressed = notes.inactive_remote_ids(load_state())
        result['results'] = [row for row in result.get('results',[]) if row.get('id') not in suppressed and row.get('parent_id') not in suppressed]
    from material_scope import filter_search
    return filter_search(result,scope=scope,project=project)


def paper_by_id(identifier):
    records = read_json(LIBRARY)['records']
    return next(record for record in records if record['id']==identifier)


def page_image(identifier, number, scale=1.8):
    import pymupdf as fitz
    record = paper_by_id(identifier)
    artifact = chosen_artifact(record)
    if not artifact or artifact['kind']!='pdf':
        raise ValueError('本条目没有 PDF 原文')
    with fitz.open(artifact['path']) as doc:
        if not 1 <= number <= len(doc):
            raise ValueError('页码超出范围')
        return doc[number-1].get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False).tobytes('png')


def vision_payload(question, identifier, numbers):
    if not isinstance(question,str) or not 1 <= len(question.strip()) <= 8000:
        raise ValueError('请填写问题（最多 8000 字）')
    record = paper_by_id(identifier)
    if not 1 <= len(numbers) <= 4 or any(type(n) is not int for n in numbers):
        raise ValueError('一次选择 1–4 个 PDF 页码')
    content = [{'type':'text','text':f"论文：{record['title']}\n文献 ID：{identifier}；PDF 页码：{numbers}\n问题：{question}\n请区分图片直接可见的信息、正文支持的判断和推断。引用用 [文献 ID · PDF 第 n 页]。数字看不清请明确说明，禁止编造曲线数值。"}]
    for number in numbers:
        content.append({'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(page_image(identifier,number)).decode('ascii'),'detail':'high'}})
    return {'model':'deepseek-flash','messages':[{'role':'user','content':content}],'max_tokens':3500,'thinking':{'type':'disabled'}}


def discover():
    from research_radar import discover as radar_discover
    return radar_discover()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action',nargs='?',default='sync',choices=['sync','discover','serve'])
    args = parser.parse_args()
    if args.action=='serve':
        from dashboard import serve
        serve()
    else:
        print(json.dumps(sync() if args.action=='sync' else discover(),ensure_ascii=True))


if __name__=='__main__':
    main()
