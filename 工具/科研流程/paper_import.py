"""Quick PDF intake with stable identities, duplicate detection and Zotero attachments."""
from pathlib import Path
import re
from urllib.parse import quote
import pymupdf
import requests
from acquisitions import submit_zotero, MAX_BYTES
import paper_evidence as evidence
import workflow as w


def inspect_pdf(filename, raw):
    if not isinstance(filename, str) or not filename.lower().endswith('.pdf') or len(filename) > 180 or re.search(r'[/\\<>:"|?*\x00-\x1f]', filename) or filename in ('.', '..'):
        raise ValueError('请选择名称有效的 PDF 文件。')
    if not isinstance(raw, bytes) or not 5 < len(raw) <= MAX_BYTES or not raw.startswith(b'%PDF-'):
        raise ValueError('仅接收实际 PDF，单份最多 40 MB。')
    try:
        with pymupdf.open(stream=raw, filetype='pdf') as doc:
            if not len(doc) or doc.needs_pass: raise ValueError('PDF 为空或需要密码。')
            text = doc[0].get_text()
            metadata = doc.metadata or {}
            title = metadata.get('title', '').strip()
            if not 5 <= len(title) <= 500 or title.lower() in ('untitled', 'document'): title = Path(filename).stem
            match = re.search(r'(?i)(?:doi\s*:?\s*|https?://(?:dx\.)?doi\.org/)(10\.\d{4,9}/[^\s<>"\x00-\x1f]+)', text)
            doi = w.normalize_doi(match[1].rstrip('.,;)')) if match else None
            return {'title': title, 'doi': doi, 'page_count': len(doc), 'sha256': w.digest(raw)}
    except ValueError: raise
    except Exception: raise ValueError('无法读取这个 PDF，请检查文件是否完整。') from None


def register(library, path, metadata, project, filename):
    existing = next((r for r in library['records'] if any(a.get('sha256') == metadata['sha256'] for a in r.get('artifacts', []))), None)
    if existing and any(a.get('sha256') == metadata['sha256'] and Path(a['path']).is_file() for a in existing['artifacts']): return existing, True
    if not existing and metadata['doi']: existing = next((r for r in library['records'] if w.normalize_doi(r.get('doi')) == metadata['doi']), None)
    if not existing:
        existing = evidence.candidate_record(doi=metadata['doi']) or next((r for r in evidence.candidate_records() if any(a.get('sha256') == metadata['sha256'] for a in r.get('artifacts', []))), None)
        if existing:existing['project']=project
    identifier = existing['id'] if existing else 'pdf-'+metadata['sha256'][:16]
    record = existing or {'id': identifier, 'title': metadata['title'], 'doi': metadata['doi'], 'topic': project, 'project': project, 'identity_status': 'uploaded_metadata_unverified', 'reading_status': 'unread', 'artifacts': [], 'provenance': []}
    artifact = {'kind': 'pdf', 'path': path.resolve().as_posix(), 'bytes': path.stat().st_size, 'sha256': metadata['sha256'], 'file_header_check': True, 'page_count': metadata['page_count'], 'url': 'http://127.0.0.1:8503/api/original?paper='+quote(identifier)}
    record['artifacts'].append(artifact); record['availability'] = 'fulltext_on_disk'
    record.setdefault('provenance', []).append({'source': '用户快捷导入', 'filename': filename, 'date': w.now(), 'scope': '原 PDF 已保存；题名与 DOI 来自文件，元数据待核查，阅读状态不提升'})
    evidence.admit(record,library)
    return record, False


def import_bytes(filename, raw, project=None):
    metadata = inspect_pdf(filename, raw)
    if project is None:
        import administrator
        project=administrator.settings()['default_project']
    if project not in ('共享','待归类') and (not isinstance(project, str) or project not in {p.name for p in (w.KB/'项目').iterdir() if p.is_dir()}): raise ValueError('请选择已有项目。')
    with w.process_lock() as acquired:
        if not acquired: raise ValueError('正在同步，请稍后再导入，当前文件没有丢失。')
        library = w.read_json(w.LIBRARY)
        existing = next((r for r in library['records'] if any(a.get('sha256') == metadata['sha256'] and Path(a['path']).is_file() for a in r.get('artifacts', []))), None)
        if existing:
            from zotero_bridge import enqueue
            enqueue(existing,next(a for a in existing['artifacts'] if a.get('sha256')==metadata['sha256']))
            return {'id': existing['id'], 'title': existing['title'], 'reused': True, 'message': '已有同一份 PDF，沿用原条目和阅读记录；后台核对正式书目收录。'}
        path = w.KB/'文献/导入全文'/('pdf-'+metadata['sha256'][:16])/filename
        if path.exists() and w.digest(path.read_bytes()) != metadata['sha256']: raise ValueError('同名原文已有不同内容，未覆盖。')
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists(): path.write_bytes(raw)
        record, reused = register(library, path, metadata, project, filename)
        w.write_json(w.LIBRARY, library)
        try: zotero = submit_zotero(record, record['artifacts'][-1])
        except (requests.RequestException, ValueError): zotero = 'Zotero 当前未接收附件；原文已保留，可在运行状态中重试。'
        from workspace import refresh_views
        refresh_views()
        if not reused:
            import administrator
            administrator.schedule(record.get('project') or project, '新论文已登记', record['id'])
        return {'id': record['id'], 'title': record['title'], 'reused': reused, 'message': 'PDF 已登记，后台将继续索引。'+zotero}


def import_inbox(library):
    """The caller holds the sync lock; newly dropped files are registered in place."""
    folder = w.KB/'文献/待入库'; folder.mkdir(parents=True, exist_ok=True)
    ledger = w.read_json(w.DATA/'收件箱导入.json', {})
    known = {a.get('sha256') for r in library['records'] for a in r.get('artifacts', [])}
    for path in folder.glob('*.pdf'):
        stat = path.stat(); stamp = str(stat.st_size)+':'+str(stat.st_mtime_ns)
        if ledger.get(path.name, {}).get('stamp') == stamp: continue
        try:
            if stat.st_size > MAX_BYTES: raise ValueError('PDF 超过 40 MB。')
            raw = path.read_bytes(); metadata = inspect_pdf(path.name, raw)
            if metadata['sha256'] in known: ledger[path.name] = {'stamp': stamp, 'status': '已有原文'}; continue
            import administrator
            project=administrator.settings()['default_project']
            if project not in ('共享','待归类') and not (w.KB/'项目'/project).is_dir():project='待归类'
            record, _ = register(library, path, metadata, project, path.name); known.add(metadata['sha256'])
            administrator.schedule(record.get('project') or project, '收件箱发现新论文', record['id'])
            w.write_json(w.LIBRARY, library)
            try: zotero = submit_zotero(record, record['artifacts'][-1])
            except (requests.RequestException, ValueError): zotero = 'Zotero 待接收，原 PDF 已保留'
            ledger[path.name] = {'stamp': stamp, 'status': '已登记', 'id': record['id'], 'zotero': zotero}
        except (ValueError, OSError) as exc: ledger[path.name] = {'stamp': stamp, 'status': '需检查', 'message': str(exc)}
    w.write_json(w.DATA/'收件箱导入.json', ledger)

