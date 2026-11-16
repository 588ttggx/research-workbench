"""One address and editor for existing research documents, including old reports.

This is an index of Markdown originals, not another copy of their prose. Literal
links are navigation dependencies; they are never promoted to scientific evidence.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlparse
import html
import difflib
import json
import re
import threading
import uuid

import knowledge as k
import workflow as w
import material_roles
import project_profiles
import maintenance_policy
from research_store import Store

LOCK = threading.RLock()
TECHNICAL = re.compile(r'验收|部署|维护|诊断|实施|电脑整理|网上方案|成熟方案|运行记录|核查管理员|资料管理要求')
ALLOWED_KB = ('背景/', '项目/', '笔记/', '文献/阅读卡片/', '文献/AI阅读记录/', '更新记录/')
LINK = re.compile(r'\[[^\]\n]*\]\(([^\n)]+)\)|\[\[([^\]\n]+)\]\]|href=["\']([^"\']+)["\']')
WORK_STATES = ['草稿', '整理中', '待补资料', '可用', '不再更新']
# Bump whenever the projected document fields or link classification change shape:
# refresh() includes this value in the catalog signature and rebuilds once.
INDEX_VERSION = '10'
SCAN_ISSUE_KEY = 'catalog_scan_issues'
CITED_PAPER = re.compile(r'(?:^|/)(?:文献/)?条目/([\w.-]+?)(?:\.md)?$')
SCAN_IGNORED = {'修改前', '修改后', '_临时', '编辑备份', '垃圾箱', '.git', 'node_modules'}
NAVIGATION_LABELS = {'目录', '索引', '导航', '返回', '上一页', '下一页', '相关阅读', '首页'}
CONTENT_LABELS = re.compile(r'依据|来源|证据|数据|结果|方法|条件|参数|实验|测量|数值|单位|第\s*\d+\s*页|pdf|xml', re.I)


def _link_meta(body):
    rows=[]
    for match in LINK.finditer(body):
        text=match.group(0)
        if text.startswith('[['):
            target=match.group(2); label=target.split('|')[-1]
        elif text.startswith('['):
            target=match.group(1); label=text[1:text.find(']')]
        else:
            target=match.group(3); label=''
        rows.append({'target':target.strip(),'label':label.strip()})
    return rows


def _link_type(source, target, label):
    folded=label.casefold().strip()
    target_lower=target.casefold()
    if folded in NAVIGATION_LABELS or Path(target).stem.casefold() in {'index','toc','目录','索引'}:
        return 'navigation'
    if any(part in f'/{target_lower}/' for part in ('更新记录','历史','archive','retired')):
        return 'history'
    if CONTENT_LABELS.search(label):
        return 'content'
    return 'unknown'


def database():
    store = Store()
    with store.connection() as db:
        db.executescript('''
          CREATE TABLE IF NOT EXISTS documents(
            id TEXT PRIMARY KEY,path TEXT NOT NULL UNIQUE,title TEXT NOT NULL,
            kind TEXT NOT NULL,project TEXT NOT NULL,sha TEXT NOT NULL,
            data TEXT NOT NULL,visibility TEXT NOT NULL,archived INTEGER NOT NULL DEFAULT 0,
            present INTEGER NOT NULL DEFAULT 1,updated TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS document_links(
            source TEXT NOT NULL REFERENCES documents(id),
            target TEXT NOT NULL REFERENCES documents(id),
            expected_sha TEXT NOT NULL,label TEXT NOT NULL,
            PRIMARY KEY(source,target));
          CREATE TABLE IF NOT EXISTS document_versions(
            id TEXT PRIMARY KEY,document TEXT NOT NULL REFERENCES documents(id),
            path TEXT NOT NULL,sha TEXT NOT NULL,created TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS document_source_snapshots(
            document TEXT NOT NULL REFERENCES documents(id),sha TEXT NOT NULL,
            body TEXT NOT NULL,created TEXT NOT NULL,PRIMARY KEY(document,sha));
          CREATE TABLE IF NOT EXISTS document_content_reviews(
            document TEXT NOT NULL REFERENCES documents(id),sha TEXT NOT NULL,
            sources_sha TEXT NOT NULL,created TEXT NOT NULL,
            PRIMARY KEY(document,sha,sources_sha));
        ''')
        columns={row['name'] for row in db.execute('PRAGMA table_info(document_links)')}
        if 'link_type' not in columns:
            db.execute("ALTER TABLE document_links ADD COLUMN link_type TEXT NOT NULL DEFAULT 'unknown'")
    return store


def bounded(relative):
    if not isinstance(relative, str) or not relative or len(relative) > 1200 or '\x00' in relative:
        raise ValueError('资料地址无效')
    root = w.ROOT.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() != '.md':
        raise ValueError('只允许访问已登记的科研正文')
    rel = path.relative_to(root).as_posix()
    if rel.startswith('科研知识库/'):
        name = rel.removeprefix('科研知识库/')
        if not name.startswith(ALLOWED_KB):
            raise ValueError('该文件不是科研正文')
    elif not rel.startswith(('output/', 'research/')):
        raise ValueError('该文件不是科研正文')
    if any(part in {'垃圾箱', '编辑备份', '.git', '_临时', 'node_modules'} for part in Path(rel).parts):
        # Historical IDs already given to the user remain readable. New copies
        # in these folders never acquire an everyday catalog identity.
        with database().connection() as db:
            registered=db.execute('SELECT id FROM documents WHERE path=?',(rel,)).fetchone()
        if not registered:raise ValueError('该文件不在资料索引范围')
    if path.name in {'AGENTS.md', 'SKILL.md'}:
        raise ValueError('该文件不是科研正文')
    return path


def paper_link_ids(body):
    """Return only explicit body-linked paper identities, not frontmatter associations."""
    result=set(re.findall(r'\[\[文献/条目/([\w.-]+)',body))
    for match in LINK.finditer(body):
        target=next(value for value in match.groups() if value is not None).strip()
        target=html.unescape(unquote(target.strip().strip('<>'))).replace('\\','/').split('#',1)[0]
        found=CITED_PAPER.search(target)
        if found:result.add(found.group(1))
    return result


def read_source(path):
    """Decode existing Markdown without requiring a lossy conversion first."""
    raw=path.read_bytes()
    if raw.startswith((b'\xff\xfe',b'\xfe\xff')):return raw.decode('utf-16')
    return raw.decode('utf-8-sig')


def scan_issues():
    """Return the latest scan diagnostics without reading original prose."""
    with database().connection() as db:
        row=db.execute("SELECT value FROM meta WHERE key=?",(SCAN_ISSUE_KEY,)).fetchone()
    try:return json.loads(row['value']) if row else []
    except (TypeError,ValueError):return []


def identify(relative):
    return 'DOC-' + w.digest(relative)[:20]


def _maintenance_owner(meta,ai_generated,body_digest):
    """Project who maintains the prose; never infer machine write rights from a label.

    An AI draft is only called AI-maintained when its managed hash still matches
    the current body. Legacy drafts without that proof stay mixed/review-pending.
    """
    explicit=str(meta.get('maintenance_owner') or '').strip()
    if explicit in ('human','ai','mixed'):return explicit,'explicit'
    managed=str(meta.get('managed_hash') or '').strip()
    if ai_generated and managed:
        return ('ai' if managed==body_digest else 'mixed'),'managed_hash'
    if ai_generated:return 'mixed','ai_draft'
    return 'human','human'


def describe(path, raw):
    meta, body, _ = k.split(raw)
    rel = path.relative_to(w.ROOT.resolve()).as_posix()
    kbrel = rel.removeprefix('科研知识库/') if rel.startswith('科研知识库/') else None
    title = str(meta.get('title') or next((line[2:].strip() for line in body.splitlines() if line.startswith('# ')), path.stem))
    category = str(meta.get('type') or '')
    weekly=category=='weekly_brief' or bool(kbrel and kbrel.startswith('笔记/共享/每周研究简报/') and title.startswith('Weekly Research Brief'))
    kind = '报告' if kbrel is None else '项目记录' if kbrel.startswith('项目/') else '背景' if kbrel.startswith('背景/') else '阅读笔记' if kbrel.startswith('文献/阅读卡片/') else '候选修改' if kbrel.startswith('更新记录/') else '笔记'
    if kind=='项目记录' and category in material_roles.KNOWLEDGE_TYPES:kind='笔记'
    kind = {'ai_paper_note': '阅读笔记', 'ai_reading_record': '阅读记录', 'ai_analysis': '分析报告',
            'data_analysis': '分析记录', 'ai_change_proposal': '候选修改', 'direction_candidate': '方向候选',
            'organization_candidate': '整理草稿', 'background_candidate': '背景候选', 'ai_administrator_chat': '历史讨论',
            'personal_note': meta.get('note_category') or '笔记'}.get(category, kind)
    if weekly:kind='报告'
    display_title = title
    created = None
    if category == 'ai_analysis':
        # Old AI reports used the same prompt as their title. Show the actual
        # authored heading and generation time without renaming the original.
        request = re.search(r'^要求：[ \t]*(.+)$', body, re.M)
        if request and len(title.split(' · ')) >= 3 and request[1].strip().startswith(title.rsplit(' · ', 1)[-1]):
            headings = re.findall(r'^# (.+)$', body, re.M)
            display_title = next((heading.strip() for heading in headings if heading.strip() != title), title)
        stamp = re.search(r'^日期：[ \t]*(\d{4}-\d{2}-\d{2}T[0-9:.]+(?:Z|[+-]\d{2}:\d{2}))', body, re.M)
        if stamp:
            created = stamp[1]
    record_kind = meta.get('record_type')
    if record_kind:
        import research_records
        kind = research_records.TYPES.get(record_kind, ('', kind, []))[1]
    project = str(meta.get('project') or (kbrel.split('/')[1] if kbrel and kbrel.startswith('项目/') else '共享'))
    source_project = str(meta.get('source_project') or '').strip()
    if not source_project and meta.get('project') not in (None,'','共享','待归类'):
        source_project=str(meta['project'])
    if not source_project and kbrel:
        parts=Path(kbrel).parts
        if len(parts)>2 and parts[0] in ('项目','笔记') and (w.KB/'项目'/parts[1]).is_dir():
            source_project=parts[1]
    if project == '共享' and (not kbrel) and ('山药' in title or 'yam' in rel.lower()):
        project = '山药'
    visibility = 'system' if TECHNICAL.search(rel) or kind in {'候选修改', '方向候选', '整理草稿', '背景候选'} or path.name in {'研究主线.md', '方向选择.md'} or (kbrel and '脉络' in path.stem and kbrel.startswith('背景/')) else 'reference' if kbrel is None or kind == '阅读记录' else 'active'
    if category == 'ai_administrator_chat':
        visibility = 'system'
    if re.search(r'功能验收|界面.*验收|隔离.*验收|核查管理员', title):
        visibility = 'system'
    paper_ids = set(meta.get('paper_ids') or []) if isinstance(meta.get('paper_ids'), list) else set()
    if meta.get('paper_id'):
        paper_ids.add(meta['paper_id'])
    paper_citations=paper_link_ids(body)
    paper_ids.update(paper_citations)
    for paper in w.read_json(w.LIBRARY, {'records': []})['records']:
        card = paper.get('reading_card')
        if card and (Path(card) if Path(card).is_absolute() else w.KB/card).resolve() == path:
            paper_ids.add(paper['id'])
    role=material_roles.interpret(meta,rel,visibility)
    # A folder-derived display name must not turn a legacy knowledge note into
    # a record; explicit record metadata still wins in the central interpreter.
    if kind=='项目记录' and role['content_role']=='knowledge':kind='笔记'
    ai_generated=bool(meta.get('ai_generated')) or weekly or bool(meta.get('ai_canvas_draft')) or category in {'ai_paper_note', 'ai_reading_record', 'ai_analysis'} or bool(re.search(r'AI\s*整理.*待(?:更新|核查)', str(meta.get('status') or '')))
    body_digest=w.digest(body.rstrip())
    work_items=meta.get('work_items') if path.name=='任务.md' and kbrel and kbrel.startswith('项目/') else None
    work_version=w.digest(json.dumps(work_items,ensure_ascii=False,sort_keys=True,default=str)) if work_items else None
    stage_state=({'status':str(meta.get('stage_status') or '未开始'),'removed':bool(meta.get('stage_removed'))}
                 if meta.get('record_type')=='Stage' else None)
    maintenance_owner,maintenance_owner_basis=_maintenance_owner(meta,ai_generated,body_digest)
    return {**role, 'id': identify(rel), 'path': rel, 'kb_path': kbrel, 'title': title[:500], 'display_title': display_title[:500], 'created': created, 'kind': kind,
            'project': project, 'source_project':source_project, 'sha': body_digest, 'work_version':work_version,
            'stage_state':stage_state,'visibility': visibility,
            'status': str(meta.get('status') or '已保存'), 'paper_ids': sorted(paper_ids),
            'paper_citations': sorted(paper_citations),
            'work_status': str(meta.get('work_status') or ''), 'work_status_options': WORK_STATES,
            'ai_generated':ai_generated,'maintenance_owner':maintenance_owner,
            'maintenance_owner_basis':maintenance_owner_basis,
            'maintenance_regions':meta.get('maintenance_regions') if isinstance(meta.get('maintenance_regions'),list) else [],
            'proposal_id': meta.get('proposal_id'), 'record_id': meta.get('id'),
            'question_id': meta.get('question_id'),
            'canvas_node': meta.get('canvas_node'),
            'canvas_include': meta.get('canvas_include',True),
            'question_deleted': bool(meta.get('problem_fields', {}).get('deleted')) if isinstance(meta.get('problem_fields'), dict) else False,
            'zotero_note_key': meta.get('$itemKey'), 'aliases': meta.get('aliases') if isinstance(meta.get('aliases'), list) else [],
            'reading_scope': str(meta.get('reading_scope') or ''), 'excerpt': re.sub(r'[#*\[\]`]', '', re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', re.sub(r'(?s)<!--.*?-->','',body))).strip()[:160],
            'editable': not bool(meta.get('proposal_id')) and path.name not in {'研究主线.md', '方向选择.md'},
            'links': [next(v for v in match.groups() if v is not None).strip() for match in LINK.finditer(body)],
            'link_meta': _link_meta(body),
            'file_modified': path.stat().st_mtime}


def resolve_target(target, source, by_path, by_name):
    target = html.unescape(unquote(target.strip().strip('<>'))).split('|')[0]
    target = re.split(r'\s+["\']', target)[0].split('#')[0]
    parsed = urlparse(target)
    if not target or target.startswith('//') or (parsed.scheme and not re.match(r'^[A-Za-z]:[/\\]', target)):
        return None
    if target in by_path:
        return by_path[target]
    possibilities = []
    for candidate in [(w.ROOT/source).parent/target, w.KB/target]:
        try:
            path = candidate.resolve()
            if not path.suffix:
                path = path.with_suffix('.md')
            if path.is_relative_to(w.ROOT.resolve()):
                possibilities.append(path.relative_to(w.ROOT.resolve()).as_posix())
        except (ValueError, OSError):
            continue
    for relative in possibilities:
        if relative in by_path:
            return by_path[relative]
    matches = by_name.get(Path(target).stem.casefold(), [])
    if not matches:
        native = re.search(r'-([A-Z0-9]{8})$', Path(target).stem)
        if native:
            matches = by_name.get(native[1].casefold(), [])
    return matches[0] if len(matches) == 1 else None


def refresh(*, acknowledged_source=None, decision_source=None, deliver_notifications=True):
    with LOCK:
        store = database()
        paths = []
        for prefix in ALLOWED_KB:
            folder=w.KB/prefix
            paths.extend(path for path in folder.rglob('*.md') if not SCAN_IGNORED.intersection(path.relative_to(folder).parts))
        for folder in ('output', 'research'):
            directory=w.ROOT/folder
            paths.extend(path for path in directory.rglob('*.md') if not SCAN_IGNORED.intersection(path.relative_to(directory).parts))
        paths=sorted(set(paths))
        stamps=[]
        for path in [*paths,w.LIBRARY]:
            try:
                info=path.stat();stamps.append((str(path.resolve()),info.st_mtime_ns,info.st_ctime_ns,info.st_size))
            except OSError:stamps.append((str(path),'unavailable'))
        signature=w.digest(json.dumps([material_roles.RULES_VERSION,INDEX_VERSION,stamps],ensure_ascii=False))
        with store.connection() as db:
            previous=db.execute("SELECT value FROM meta WHERE key='catalog_files_signature'").fetchone()
        if not acknowledged_source and previous and previous['value']==signature:
            if decision_source:
                with store.connection() as db:
                    db.execute("""UPDATE cursors SET value=json_set(value,'$.change_type','decision_result')
                        WHERE key=? AND json_extract(value,'$.status')='pending'
                        AND json_extract(value,'$.document.sha')=?""",
                               ('document-notification:'+decision_source[0],decision_source[1]))
            if deliver_notifications:
                _drain_notifications(store)
            return store
        docs = []; bodies = {}; issues=[]
        for path in paths:
            relative=None
            try:
                relative=path.resolve().relative_to(w.ROOT.resolve()).as_posix()
                if any(part in SCAN_IGNORED for part in Path(relative).parts):
                    continue
                path=bounded(relative)
                if not path.is_file():continue
                size=path.stat().st_size
                if size>1200000:
                    issues.append({'path':relative,'reason':'too_large','size':size})
                    continue
                raw=read_source(path)
            except UnicodeError:
                if relative:issues.append({'path':relative,'reason':'decode_error','size':path.stat().st_size if path.exists() else 0})
                continue
            except OSError:
                if relative:issues.append({'path':relative,'reason':'unreadable','size':path.stat().st_size if path.exists() else 0})
                continue
            except ValueError:
                # Backup/tmp/dot paths are intentionally outside the catalog;
                # they are not broken source documents.
                continue
            try:
                doc=describe(path,raw)
                body=k.split(raw)[1]
            except (ValueError,TypeError,KeyError):
                if relative:issues.append({'path':relative,'reason':'parse_error','size':path.stat().st_size if path.exists() else 0})
                continue
            docs.append(doc);bodies[doc['id']]=body
        issues=sorted(issues,key=lambda item:item['path'])
        by_path = {doc['path']: doc['id'] for doc in docs}
        by_name = {}
        by_id = {doc['id']: doc for doc in docs}
        for doc in docs:
            names = {Path(doc['path']).stem.casefold(), doc['title'].casefold(), *[str(alias).casefold() for alias in doc['aliases']]}
            if doc['zotero_note_key']:
                names.add(doc['zotero_note_key'].casefold())
            for name in names:
                by_name.setdefault(name, []).append(doc['id'])
        with store.connection() as db:
            initial_baseline = db.execute("SELECT value FROM meta WHERE key='catalog_prose_hash'").fetchone() is None
            prior_docs={row['id']:json.loads(row['data']) for row in db.execute('SELECT id,data FROM documents WHERE present=1')}
            db.execute('UPDATE documents SET present=0')
            for doc in docs:
                old=prior_docs.get(doc['id'])
                if old and doc.get('stage_state') and 'stage_state' not in old and old.get('file_modified')==doc['file_modified']:
                    old={**old,'stage_state':doc['stage_state']}
                if (not initial_baseline and doc.get('visibility')!='system' and doc.get('kind')!='候选修改'
                        and (old is None or document_version(old)!=document_version(doc))):
                    change_type=('content' if old is None or any(old.get(key)!=doc.get(key) for key in ('sha','work_version','stage_state')) else
                                 'references' if old.get('paper_ids')!=doc.get('paper_ids') else
                                 'knowledge_visibility' if any(old.get(f)!=doc.get(f) for f in ('content_role','global_knowledge')) else 'display')
                    if decision_source==(doc['id'],doc['sha']):change_type='decision_result'
                    receipt={'document':doc,'version':document_version(doc),'change_type':change_type,'status':'pending','updated':w.now()}
                    db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)',
                               ('document-notification:'+doc['id'],json.dumps(receipt,ensure_ascii=False),w.now()))
                db.execute('''INSERT INTO documents(id,path,title,kind,project,sha,data,visibility,updated)
                    VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,
                    kind=excluded.kind,project=excluded.project,sha=excluded.sha,data=excluded.data,
                    visibility=excluded.visibility,present=1,updated=excluded.updated''',
                    (doc['id'], doc['path'], doc['title'], doc['kind'], doc['project'], doc['sha'], json.dumps(doc, ensure_ascii=False), doc['visibility'], w.now()))
                # Immutable, read-only comparison history; Markdown remains the editable source.
                db.execute('INSERT OR IGNORE INTO document_source_snapshots VALUES(?,?,?,?)',
                           (doc['id'], doc['sha'], bodies[doc['id']], w.now()))
            for issue in issues:
                row=db.execute('SELECT id,data FROM documents WHERE path=?',(issue['path'],)).fetchone()
                if not row:continue
                data=json.loads(row['data'])
                data['scan_issue']=issue['reason']
                data['scan_issue_detail']=issue
                db.execute('UPDATE documents SET present=1,data=?,updated=? WHERE id=?',
                           (json.dumps(data,ensure_ascii=False),w.now(),row['id']))
            for doc in docs:
                targets = {}
                for link in doc.get('link_meta', [{'target':value,'label':''} for value in doc['links']]):
                    target = resolve_target(link['target'], doc['path'], by_path, by_name)
                    if target and target != doc['id']:
                        candidate=(link['label'],_link_type(doc['path'],by_id[target]['path'],link['label']))
                        previous=targets.get(target)
                        rank={'navigation':0,'history':1,'unknown':2,'content':3}
                        if previous is None or rank[candidate[1]]>rank[previous[1]]:targets[target]=candidate
                for target, (label, link_type) in targets.items():
                    db.execute('''INSERT OR IGNORE INTO document_links(source,target,expected_sha,label,link_type)
                        VALUES(?,?,?,?,?)''', (doc['id'], target, by_id[target]['sha'], label, link_type))
                    db.execute('UPDATE document_links SET label=?,link_type=? WHERE source=? AND target=?',
                               (label,link_type,doc['id'],target))
                    if acknowledged_source == doc['id']:
                        db.execute('UPDATE document_links SET expected_sha=? WHERE source=? AND target=?',
                                   (by_id[target]['sha'],doc['id'],target))
                prior = db.execute('SELECT target FROM document_links WHERE source=?', (doc['id'],)).fetchall()
                for row in prior:
                    if row['target'] not in targets:
                        db.execute('DELETE FROM document_links WHERE source=? AND target=?', (doc['id'], row['target']))
            if initial_baseline:
                # This index is newly deployed. Synchronization metadata is not
                # research prose and must not create a permanent review storm.
                db.execute('UPDATE document_links SET expected_sha=(SELECT sha FROM documents WHERE documents.id=document_links.target)')
                db.execute("INSERT INTO meta(key,value) VALUES('catalog_prose_hash','1')")
            db.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (SCAN_ISSUE_KEY,json.dumps(issues,ensure_ascii=False)))
            db.execute("INSERT INTO meta(key,value) VALUES('catalog_files_signature',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(signature,))
        if deliver_notifications:
            _drain_notifications(store)
        return store


def _drain_notifications(store):
    """Deliver committed source versions; an interrupted delivery remains retryable."""
    with store.connection() as db:
        pending=db.execute("SELECT key,value FROM cursors WHERE key LIKE 'document-notification:%' AND json_extract(value,'$.status')='pending' ORDER BY updated LIMIT 50").fetchall()
    for row in pending:
        receipt=json.loads(row['value'])
        try:
            doc=receipt['document']
            __import__('administrator').schedule(doc.get('project') or '共享','资料原稿已变化',
                document_id=doc['id'],version=receipt['version'],change_type=receipt.get('change_type','content'))
        except Exception:
            continue
        with store.connection() as db:
            current=db.execute('SELECT value FROM cursors WHERE key=?',(row['key'],)).fetchone()
            if current and json.loads(current['value']).get('version')==receipt['version']:
                receipt.update(status='delivered',updated=w.now())
                db.execute('UPDATE cursors SET value=?,updated=? WHERE key=?',(json.dumps(receipt,ensure_ascii=False),w.now(),row['key']))


def reconcile_sources():
    """Deliver catalog events and reconcile record versions on the maintenance clock."""
    from research_records import reconcile
    store=refresh()
    with store.connection() as db:
        identifiers=[row[0] for row in db.execute("""SELECT DISTINCT n.id FROM nodes n
            JOIN documents d ON n.id=json_extract(d.data,'$.record_id')
            WHERE d.present=1 AND n.owner='Markdown'""")]
    if identifiers:
        reconcile(identifiers=identifiers)


def rows(project=None, *, do_refresh=True, reconcile_records=True, browse=False):
    store = (refresh(deliver_notifications=False) if browse else refresh()) if do_refresh else database()
    from research_records import reconcile, status_for_prose
    with store.connection() as db:
        documents = [dict(row) for row in db.execute('SELECT * FROM documents WHERE present=1')]
        links = [dict(row) for row in db.execute('SELECT * FROM document_links')]
        content_reviews = {tuple(row) for row in db.execute('SELECT document,sha,sources_sha FROM document_content_reviews')}
        archive_info={row['object_id']:json.loads(row['detail']) for row in db.execute("SELECT object_id,detail FROM audit WHERE event='document_archive' ORDER BY id")}
        record_rows=db.execute("SELECT DISTINCT n.* FROM nodes n JOIN documents d ON n.id=json_extract(d.data,'$.record_id') WHERE d.present=1").fetchall()
    record_nodes=[store.decode_node(row) for row in record_rows]
    records={node['id']:node for node in (reconcile(identifiers=[n['id'] for n in record_nodes]) if reconcile_records and not browse else record_nodes)}
    docs = {row['id']: {**json.loads(row['data']), 'archived': bool(row['archived'])} for row in documents}
    for doc in docs.values():
        archived=archive_info.get(doc['id'],{}) if doc['archived'] else {}
        doc['archive_reason']=archived.get('reason','')
        replacement=docs.get(archived.get('replacement'))
        doc['archive_replacement']={'id':replacement['id'],'title':replacement['display_title']} if replacement else None
        record = records.get(doc.get('record_id'))
        if record:
            status=status_for_prose(record,doc['sha']) if browse and doc.get('kb_path') else record['status']
            doc['review_status'] = status
            doc['status'] = {'CANDIDATE':'待审核','VERIFIED':'已审核','DRAFT':'草稿','REJECTED':'未采纳'}.get(status,status)
            doc['record_revision'] = record['revision']
        outgoing = [link for link in links if link['source'] == doc['id'] and link['target'] in docs]
        incoming = [link for link in links if link['target'] == doc['id'] and link['source'] in docs]
        doc['references'] = [{'id': link['target'], 'title': docs[link['target']]['display_title'], 'kind': docs[link['target']]['kind'], 'sha': docs[link['target']]['sha'],
                              'link_type': link.get('link_type','unknown'),
                              'changed': link['expected_sha'] != docs[link['target']]['sha']} for link in outgoing]
        doc['backlinks'] = [{'id': link['source'], 'title': docs[link['source']]['display_title'], 'kind': docs[link['source']]['kind'],
                            'changed': link['expected_sha'] != doc['sha']} for link in incoming]
        doc['needs_review'] = any(link['changed'] and document_dependency(link) for link in doc['references'])
        legacy_sources={link['target']:docs[link['target']]['sha'] if document_dependency(link) else link['expected_sha']
                        for link in outgoing if link.get('link_type','unknown') in ('content','unknown')}
        legacy_signature=w.digest(json.dumps(legacy_sources,sort_keys=True))
        doc['ai_review_pending'] = bool(doc['ai_generated'] and not doc.get('record_id') and
            (doc['id'], doc['sha'], source_signature(doc)) not in content_reviews and
            (doc['id'], doc['sha'], legacy_signature) not in content_reviews)
        doc['needs_action'] = doc['needs_review'] or doc['ai_review_pending']
        doc['update_state'] = {'kind': 'sources_changed' if doc['needs_review'] else 'ai_review' if doc['ai_review_pending'] else 'current',
            'label': '引用待处理' if doc['needs_review'] else 'AI 内容待核对' if doc['ai_review_pending'] else '内容已核对' if doc['ai_generated'] and not doc.get('record_id') else doc['status'],
            'source_count': sum(ref['changed'] and document_dependency(ref) for ref in doc['references'])}
        doc['upstream_changed'] = False
        doc.pop('links', None)
    # Literal navigation links are not all research dependencies. Preserve
    # indirect impact separately; acknowledging unchanged direct sources must
    # not leave a permanent review demand around a circular reference.
    for _ in range(len(docs)):
        changed = False
        for doc in docs.values():
            if not doc['upstream_changed'] and any(document_dependency(ref) and
                (docs[ref['id']]['needs_review'] or docs[ref['id']]['upstream_changed']) for ref in doc['references']):
                doc['upstream_changed'] = True
                changed = True
        if not changed:
            break
    return [doc for doc in docs.values() if project is None or doc['project'] in (project, '共享')]


def detail(identifier, *, browse=False):
    doc = next((row for row in (rows(browse=True) if browse else rows()) if row['id'] == identifier), None)
    if doc is None:
        raise ValueError('该资料不存在，请刷新列表')
    path = bounded(doc['path'])
    raw = read_source(path)
    doc.update(body=k.split(raw)[1], fingerprint=w.digest(raw))
    if doc.get('content_role')=='system_record' or doc.get('question_id'):doc['editable']=False
    doc['versions'] = versions(identifier)
    return doc


def stored_document(identifier):
    """Read-only row lookup; unlike detail()/rows() it never runs catalog reconciliation."""
    with database().connection() as db:
        row = db.execute('SELECT id,path,title,project,sha FROM documents WHERE id=?', (identifier,)).fetchone()
    if row is None:
        raise ValueError('该资料不存在')
    return dict(row)


def source_signature(doc):
    """Content references only; navigation and history links do not reopen prose review."""
    return w.digest(json.dumps({ref['id']:ref['sha'] for ref in doc['references']
                                if document_dependency(ref)}, sort_keys=True))


def source_changes(identifier):
    """Compare the exact old version used by this draft with each current source."""
    doc = detail(identifier); changes = []
    with database().connection() as db:
        links = {r['target']:r['expected_sha'] for r in db.execute('SELECT target,expected_sha FROM document_links WHERE source=?', (doc['id'],))}
        snapshots = {ref['id']:db.execute('SELECT body FROM document_source_snapshots WHERE document=? AND sha=?',
                     (ref['id'],links[ref['id']])).fetchone() for ref in doc['references'] if ref['changed']}
    for ref in doc['references']:
        if not ref['changed']: continue
        old_sha = links[ref['id']]; snapshot = snapshots[ref['id']]
        before = snapshot['body'] if snapshot else None
        if before is None:
            # Existing manual-edit history can predate comparison snapshots.
            for previous in versions(ref['id']):
                body = k.split(version(ref['id'], previous['id'])['body'])[1]
                if w.digest(body.rstrip()) == old_sha:
                    before = body; break
        current = stored_document(ref['id'])
        current['body'] = k.split(read_source(bounded(current['path'])))[1]
        if w.digest(current['body'].rstrip()) != ref['sha']:
            raise ValueError('引用来源在比较时又有变化，请重新打开核对')
        diff = list(difflib.unified_diff(before.splitlines(),current['body'].splitlines(),n=3,lineterm=''))[2:] if before is not None else []
        changes.append({**ref, 'before_available':before is not None,
            'diff':[{'kind':'added' if line.startswith('+') else 'removed' if line.startswith('-') else 'same','text':line} for line in diff[:400]],
            'truncated':len(diff)>400, 'current_body':current['body'], 'old_sha':old_sha})
    return {'id':doc['id'],'fingerprint':doc['fingerprint'],'sources':{r['id']:r['sha'] for r in doc['references']},'changes':changes,'document':doc}


def versions(identifier):
    store = database()
    with store.connection() as db:
        doc = db.execute('SELECT path FROM documents WHERE id=? AND present=1', (identifier,)).fetchone()
        if doc is None:
            raise ValueError('资料不存在')
        values = [dict(row) for row in db.execute('SELECT id,sha,created FROM document_versions WHERE document=? ORDER BY created DESC LIMIT 20', (identifier,))]
    kbpath = doc['path'].removeprefix('科研知识库/')
    if doc['path'].startswith('科研知识库/'):
        for path in sorted((p for folder in legacy_folders(kbpath) for p in folder.glob('*.json')), reverse=True)[:20]:
            metadata = w.read_json(path, {})
            if metadata.get('path') == kbpath and path.with_suffix('.md').is_file():
                values.append({'id': 'legacy:'+path.stem, 'created': metadata.get('time'), 'sha': metadata.get('before')})
    return sorted(values, key=lambda value: value.get('created') or '', reverse=True)[:20]


def legacy_folders(kbpath):
    # The original writer hashed native Windows separators; the catalog uses '/'.
    return [w.DATA/'编辑备份'/token for token in dict.fromkeys(w.digest(value)[:16] for value in (kbpath,str(Path(kbpath))))]


def versions_page(identifier,cursor='',limit=20):
    """Keyset pagination over both native versions and original editor backups."""
    import base64
    if type(limit) is not int or not 1<=limit<=100:raise ValueError('历史分页大小须为1至100。')
    with database().connection() as db:
        doc=db.execute('SELECT path FROM documents WHERE id=?',(identifier,)).fetchone()
        if not doc:raise ValueError('资料不存在。')
        values=[dict(row) for row in db.execute('SELECT id,sha,created FROM document_versions WHERE document=?',(identifier,))]
    if doc['path'].startswith('科研知识库/'):
        kbpath=doc['path'].removeprefix('科研知识库/')
        for folder in legacy_folders(kbpath):
            for path in folder.glob('*.json'):
                metadata=w.read_json(path,{})
                if metadata.get('path')==kbpath and path.with_suffix('.md').is_file():
                    values.append({'id':'legacy:'+path.stem,'created':metadata.get('time') or '', 'sha':metadata.get('before')})
    values=sorted({v['id']:v for v in values}.values(),key=lambda v:(v.get('created') or '',v['id']),reverse=True)
    upper=(values[0].get('created') or '',values[0]['id']) if values else ('','')
    last=None
    if cursor:
        try:
            state=json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
            if state['document']!=identifier:raise ValueError()
            upper=tuple(state['upper']);last=tuple(state['last'])
        except (ValueError,KeyError,TypeError,UnicodeError):raise ValueError('历史分页游标无效。')
    filtered=[v for v in values if (v.get('created') or '',v['id'])<=upper and (last is None or (v.get('created') or '',v['id'])<last)]
    page=filtered[:limit];next_cursor=''
    if len(filtered)>limit:
        value={'document':identifier,'upper':upper,'last':(page[-1].get('created') or '',page[-1]['id'])}
        next_cursor=base64.urlsafe_b64encode(json.dumps(value,ensure_ascii=False).encode()).decode()
    return {'records':page,'next_cursor':next_cursor}


def version(identifier, version_id):
    store = database()
    with store.connection() as db:
        row = db.execute('SELECT path FROM documents WHERE id=?', (identifier,)).fetchone()
        previous = db.execute('SELECT path FROM document_versions WHERE id=? AND document=?', (version_id, identifier)).fetchone()
    if row is None:
        raise ValueError('资料不存在')
    if isinstance(version_id, str) and re.fullmatch(r'legacy:[\w-]{1,80}', version_id) and row['path'].startswith('科研知识库/'):
        candidates=[folder/(version_id.removeprefix('legacy:')+'.md') for folder in legacy_folders(row['path'].removeprefix('科研知识库/'))]
        path=next((p for p in candidates if p.is_file()),candidates[0])
    elif previous:
        path = (w.DATA/previous['path']).resolve()
        if not path.is_relative_to((w.DATA/'正文历史').resolve()):
            raise ValueError('历史版本不存在')
    else:
        raise ValueError('历史版本不存在')
    raw = read_source(path)
    return {'id': version_id, 'body': k.split(raw)[1], 'fingerprint': w.digest(raw)}


def document_version(document):
    """The same content/metadata identity for event publication and consumption."""
    identity={key:document.get(key) for key in
        ('sha','title','paper_ids','archived','visibility','work_status','content_role','global_knowledge','knowledge_sources')}
    identity['archived']=bool(document.get('archived'))
    if document.get('work_version'):identity['work_version']=document['work_version']
    if document.get('stage_state'):identity['stage_state']=document['stage_state']
    return w.digest(json.dumps(identity,ensure_ascii=False,sort_keys=True))


def document_dependency(reference):
    return reference.get('link_type')=='content'


def notify_change(document,change_type='content', *, changed_work_ids=()):
    """One source-bound event; recipients interpret their existing selections."""
    if isinstance(document,Path):
        relative=document.resolve().relative_to(w.ROOT.resolve()).as_posix()
        if change_type=='decision_result':
            body=k.split(read_source(document))[1]
            refresh(decision_source=(identify(relative),w.digest(body.rstrip())))
        document=next((doc for doc in rows() if doc['path']==relative),None)
        if document is None:return
    version=document_version(document)
    owner=document['project']
    if not document.get('kb_path') and not document.get('source_project'):owner='共享'
    import administrator
    return administrator.schedule(owner,'资料原稿已变化',document_id=document['id'],version=version,change_type=change_type,
                                  **({'changed_work_ids':changed_work_ids} if changed_work_ids else {}))


@project_profiles.original_edit
def save(data, *, decision_id=None):
    doc = detail(data.get('id'))
    if not doc['editable']:
        raise ValueError('请在候选审核或主线设置中维护这份系统记录')
    body, title = data.get('body'), data.get('title')
    if not isinstance(body, str) or not body.strip() or len(body) > 100000:
        raise ValueError('正文不能为空，最多 10 万字')
    if not isinstance(title, str) or not title.strip() or len(title) > 500:
        raise ValueError('请填写标题，最多 500 字')
    reviewed = data.get('reviewed_sources') is True
    reviewed_ai = data.get('reviewed_ai') is True
    if reviewed_ai and (not doc['ai_generated'] or doc.get('record_id')):
        raise ValueError('这份资料不通过 AI 内容核对确认科研判断')
    observed = {ref['id']: ref['sha'] for ref in doc['references']}
    required = {ref['id']: ref['sha'] for ref in doc['references']
                if document_dependency(ref)}
    provided=data.get('sources')
    if reviewed or reviewed_ai:
        supplied={key:value for key,value in provided.items() if key in required} if isinstance(provided,dict) else None
        if supplied != required:
            raise ValueError('引用来源又有更新，请重新核对后保存；原稿未覆盖')
    reviewed_ids = data.get('reviewed_source_ids', list(required))
    if not isinstance(reviewed_ids, list) or any(not isinstance(identifier, str) or identifier not in required for identifier in reviewed_ids):
        raise ValueError('本批核对来源无效；原稿和未提供来源的核查状态保留')
    if doc['kb_path']:
        k.save(doc['kb_path'], body, data.get('fingerprint'), title=title,notify=False)
    else:
        path = bounded(doc['path'])
        with k.editing():
            before = k.validate_fingerprint(path, data.get('fingerprint'))
            meta, _, front = k.split(before)
            body = re.sub(r'(?m)^# [^\n]*', lambda _: '# '+title.strip(), body, count=1) if re.search(r'(?m)^# ', body) else '# '+title.strip()+'\n\n'+body
            after = k.properties((before[:front.end()] if front else '')+body.rstrip()+'\n', {'title': title.strip()})
            token = uuid.uuid4().hex
            backup = w.DATA/'正文历史'/doc['id']/(token+'.md')
            w.atomic_text(backup, before)
            with database().connection() as db:
                db.execute('INSERT INTO document_versions VALUES(?,?,?,?,?)', (token, doc['id'], backup.relative_to(w.DATA).as_posix(), w.digest(before), w.now()))
            w.atomic_text(path, after)
    # Literal references update their titles/links immediately. Changed source prose
    # prompts review of dependants; no scientific conclusion is silently rewritten.
    change_type='decision_result' if decision_id else 'content'
    if decision_id:
        written_body=k.split(read_source(bounded(doc['path'])))[1]
        refresh(decision_source=(doc['id'],w.digest(written_body.rstrip())))
    else:refresh()
    if reviewed:
        with database().connection() as db:
            for identifier in set(reviewed_ids):
                sha = observed[identifier]
                db.execute('UPDATE document_links SET expected_sha=? WHERE source=? AND target=?', (sha, doc['id'], identifier))
            Store.log(db, 'document_sources_reviewed', doc['id'], {'reason': '用户修订正文时确认已核对这些来源版本'})
    saved=detail(doc['id'])
    concurrent=any(document_dependency(ref) and
                   ref['id'] in required and ref['sha'] != required[ref['id']]
                   for ref in saved['references'])
    if reviewed_ai and not concurrent:
        with database().connection() as db:
            # Bind the receipt to the saved body and its current references; a
            # body edit that adds/removes a link must still close the review.
            db.execute('INSERT OR IGNORE INTO document_content_reviews VALUES(?,?,?,?)',
                       (saved['id'], saved['sha'], source_signature(saved), w.now()))
            Store.log(db, 'document_content_reviewed', saved['id'], {'reason':'用户修订正文并完成内容核对','body_sha':saved['sha']})
        saved=detail(saved['id'])
    if saved['fingerprint']!=doc['fingerprint']:notify_change(saved,change_type)
    return saved


def acknowledge(data):
    doc = detail(data.get('id'))
    if data.get('fingerprint') != doc['fingerprint']:
        raise ValueError('资料已变化，请重新打开后核对')
    sources = data.get('sources')
    required = {ref['id']: ref['sha'] for ref in doc['references']
                if document_dependency(ref)}
    supplied={key:value for key,value in sources.items() if key in required} if isinstance(sources,dict) else None
    if supplied != required:
        raise ValueError('引用的来源又有更新，请重新打开后核对')
    reviewed_ids=data.get('reviewed_source_ids',list(required))
    if (not isinstance(reviewed_ids,list) or
            any(not isinstance(identifier,str) or identifier not in required for identifier in reviewed_ids)):
        raise ValueError('本批核对来源无效；原稿和未提供来源的核查状态保留')
    review_ai = data.get('review_ai') is True
    if review_ai and (not doc['ai_generated'] or doc.get('record_id')):
        raise ValueError('科研判断请通过候选审核确认')
    with database().connection() as db:
        # Acknowledge only the exact source versions shown to the reviewer.
        # A later refresh must still reveal edits arriving during this operation.
        for identifier in reviewed_ids:
            sha=sources[identifier]
            db.execute('UPDATE document_links SET expected_sha=? WHERE source=? AND target=?', (sha, doc['id'], identifier))
        Store.log(db, 'document_sources_reviewed', doc['id'], {'reason': data.get('reason', '')[:2000]})
        if review_ai:
            db.execute('INSERT OR IGNORE INTO document_content_reviews VALUES(?,?,?,?)',
                       (doc['id'], doc['sha'], source_signature(doc), w.now()))
            Store.log(db, 'document_content_reviewed', doc['id'], {'reason':data.get('reason','')[:2000],'body_sha':doc['sha']})
    return detail(doc['id'])


def archive(data):
    doc = detail(data.get('id'))
    if data.get('fingerprint') != doc['fingerprint']:
        raise ValueError('资料已变化，请重新打开')
    if type(data.get('archived')) is not bool:
        raise ValueError('归档状态无效')
    reason=data.get('reason','');replacement=data.get('replacement')
    if not isinstance(reason,str) or len(reason)>1000:raise ValueError('归档说明最多 1000 字。')
    if replacement is not None:
        if not isinstance(replacement,str) or replacement==doc['id']:raise ValueError('归档主稿无效。')
        with database().connection() as db:
            if not db.execute('SELECT id FROM documents WHERE id=? AND present=1 AND archived=0',(replacement,)).fetchone():raise ValueError('请关联尚在使用的主稿。')
    with database().connection() as db:
        db.execute('UPDATE documents SET archived=? WHERE id=?', (int(data['archived']), doc['id']))
        Store.log(db, 'document_archive', doc['id'], {'archived': data['archived'],'reason':reason,'replacement':replacement})
    saved=detail(doc['id'])
    if doc['archived']!=saved['archived']:notify_change(saved,'archive' if saved['archived'] else 'restore')
    return saved


def maintenance_document(path):
    """Find a document by KB-relative or root-relative path for write policy."""
    value=str(path or '').replace('\\','/').strip().lstrip('/')
    if value.startswith('科研知识库/'):value=value[len('科研知识库/'):]
    for doc in rows(reconcile_records=False):
        if doc.get('kb_path')==value or doc.get('path')==value or doc.get('path')=='科研知识库/'+value:
            return detail(doc['id'])
    raise ValueError('资料不在当前目录索引中')


def update_after_automatic_write(identifier,body=None):
    """Refresh the receipt that makes the next authorized write possible."""
    doc=detail(identifier);path=bounded(doc['path']);raw=read_source(path)
    meta,current_body,_=k.split(raw);after_body=current_body if body is None else body
    updates={}
    if doc.get('maintenance_owner')=='ai':
        updates['managed_hash']=w.digest(after_body.rstrip())
    elif doc.get('maintenance_owner')=='mixed':
        updates['maintenance_regions']=maintenance_policy.update_regions(after_body,doc.get('maintenance_regions'))
    if not updates:return doc
    after=k.properties(raw,updates)
    if after==raw:return doc
    if doc.get('kb_path'):
        k.persist(path,raw,after,w.KB.resolve())
    else:
        with k.editing():
            token=uuid.uuid4().hex
            backup=w.DATA/'正文历史'/doc['id']/(token+'.md')
            w.atomic_text(backup,raw)
            w.atomic_text(path,after)
    refresh()
    return detail(identifier)


def maintenance_blocks(identifier):
    """Heading blocks for the maintenance-region selector; read-only."""
    doc=detail(identifier)
    return {'id':doc['id'],'owner':doc.get('maintenance_owner'),'basis':doc.get('maintenance_owner_basis'),
            'managed_hash':bool(doc.get('managed_hash')),
            'regions':doc.get('maintenance_regions') or [],
            'blocks':maintenance_policy.block_list(doc['body'],doc.get('maintenance_regions'))}


@project_profiles.original_edit
def update_metadata(data):
    """Edit mechanical organization once, preserving prose and scientific reviews."""
    doc = detail(data.get('id'))
    if not doc['editable']:
        raise ValueError('请通过这份记录的专用入口维护')
    updates = {}
    if 'content_role' in data:
        if data['content_role'] not in material_roles.ROLES:raise ValueError('资料角色无效。')
        if doc.get('record_type')=='Stage' and data['content_role']!='project_process':raise ValueError('阶段必须保留为项目过程，请用提炼知识建立知识稿。')
        updates['content_role']=data['content_role']
    if 'global_knowledge' in data:
        if type(data['global_knowledge']) is not bool:raise ValueError('全局知识选择须为布尔值。')
        updates['global_knowledge']=data['global_knowledge']
    if updates.get('global_knowledge',doc.get('global_knowledge',True)) and updates.get('content_role',doc.get('content_role'))!='knowledge':
        if data.get('global_knowledge') is True:raise ValueError('项目记录、背景和其他参考资料不能发布到全局知识。')
        updates['global_knowledge']=False
    if 'work_status' in data:
        if data['work_status'] not in WORK_STATES:
            raise ValueError('请选择有效的整理状态')
        updates['work_status'] = data['work_status']
    if 'maintenance_owner' in data:
        if data['maintenance_owner'] not in ('human','ai','mixed'):
            raise ValueError('请选择人工、AI 或混合维护')
        updates['maintenance_owner'] = data['maintenance_owner']
    if 'maintenance_regions' in data:
        updates['maintenance_regions'] = maintenance_policy.region_entries(doc['body'],data['maintenance_regions'])
    if updates.get('maintenance_owner',doc.get('maintenance_owner'))=='human' and 'maintenance_regions' not in data:
        # Switching back to human stops automatic writes; the selector can add
        # regions again if the user later chooses mixed.
        updates['maintenance_regions'] = []
    if 'paper_ids' in data:
        ids = data['paper_ids']
        known = {p['id'] for p in w.read_json(w.LIBRARY, {'records': []})['records']}
        if not isinstance(ids, list) or len(ids) > 100 or any(not isinstance(i, str) or i not in known for i in ids):
            raise ValueError('请选择已登记论文')
        updates['paper_ids'] = list(dict.fromkeys(ids))
        # Older notes used a singular property; replacing the selection must
        # replace that identity too, otherwise an unlinked paper reappears.
        updates['paper_id'] = None
    if not updates:
        raise ValueError('没有可保存的更改')
    path = bounded(doc['path'])
    with k.editing():
        before = k.validate_fingerprint(path, data.get('fingerprint'))
        meta,_,_=k.split(before)
        role=material_roles.interpret({**meta,**updates},doc['path'],doc['visibility'])['content_role']
        if (data.get('content_role')=='knowledge' or data.get('global_knowledge') is True) and role!='knowledge':
            raise ValueError('这类记录或参考资料不能改为知识，请在项目内提炼为独立知识稿。')
        after = k.properties(before, updates)
        if doc['kb_path']:
            k.persist(path, before, after, w.KB.resolve())
        elif before != after:
            token = uuid.uuid4().hex
            backup = w.DATA/'正文历史'/doc['id']/(token+'.md')
            w.atomic_text(backup, before)
            with database().connection() as db:
                db.execute('INSERT INTO document_versions VALUES(?,?,?,?,?)',
                           (token, doc['id'], backup.relative_to(w.DATA).as_posix(), w.digest(before), w.now()))
            w.atomic_text(path, after)
    refresh()
    saved=detail(doc['id'])
    if before!=after:notify_change(saved,'references' if 'paper_ids' in updates else 'knowledge_visibility' if {'content_role','global_knowledge'}&updates.keys() else 'display')
    return saved


def resolve(data):
    docs = rows()
    target = html.unescape(unquote(str(data.get('target') or ''))).strip().strip('<>').replace('\\','/')
    target, _, anchor = target.partition('#')
    if target.lower().startswith('file:'):
        parsed = urlparse(target)
        if parsed.netloc and parsed.netloc.lower()!='localhost':
            raise ValueError('不打开未登记的网络文件地址')
        target=parsed.path
        if re.match(r'^/[A-Za-z]:/',target):target=target[1:]
    papers=w.read_json(w.LIBRARY, {'records': []})['records']
    for paper in papers:
        if target in (paper['id'],'文献/条目/'+paper['id'],'文献/条目/'+paper['id']+'.md') or (paper.get('doi') and w.normalize_doi(target)==w.normalize_doi(paper['doi'])):
            return {'paper_id':paper['id'],'anchor':anchor}
    direct=next((d for d in docs if target in (d['id'],d.get('record_id'))),None)
    if direct:return {'id':direct['id'],'anchor':anchor}
    by_path = {doc['path']: doc['id'] for doc in docs}
    by_name = {}
    for doc in docs:
        names = {Path(doc['path']).stem.casefold(), doc['title'].casefold(), *[str(alias).casefold() for alias in doc.get('aliases', [])]}
        if doc.get('zotero_note_key'):
            names.add(doc['zotero_note_key'].casefold())
        for name in names:
            by_name.setdefault(name, []).append(doc['id'])
    base = next((doc['path'] for doc in docs if doc['id'] == data.get('base')), '科研知识库/背景/个人与实验条件.md')
    identifier = resolve_target(target, base, by_path, by_name)
    if identifier:
        return {'id': identifier,'anchor':anchor}
    # Match saved attachments by registered absolute/relative path first.
    possible={target.casefold()}
    for parent in [(w.ROOT/base).parent,w.KB,w.ROOT]:
        try:possible.add((parent/target).resolve().as_posix().casefold())
        except (ValueError,OSError):pass
    exact=[];names=[]
    for paper in papers:
        for artifact in paper.get('artifacts', []):
            path=str(artifact.get('path') or '').replace('\\','/')
            if path and path.casefold() in possible:exact.append(paper['id'])
            if path and Path(target).name.casefold()==Path(path).name.casefold():names.append(paper['id'])
    matches=set(exact or names)
    if len(matches)==1:return {'paper_id':matches.pop(),'tab':'original' if target.lower().endswith(('.pdf','.xml')) else 'notes','anchor':anchor}
    if len(matches)>1:raise ValueError('同名文件对应多篇论文，请使用论文 ID 或完整链接，避免跳错资料')
    raise ValueError('链接未对应到已登记资料，请检查标题或在统一搜索中查找；原文和路径没有被改动')


def review_summary(docs, pending, papers, project):
    from research_records import requires_review,review_relation
    active=[d for d in docs if not d['archived'] and d['visibility']!='system']
    available={v for d in active for v in (d['id'],d.get('record_id')) if v}
    available.update(p['id'] for p in papers)
    paths={v for d in active for v in (d['path'],d.get('kb_path')) if v}
    store=Store()
    with store.connection() as db:
        node_rows=db.execute("SELECT * FROM nodes WHERE owner!='KnowledgeExtraction' AND project IN (?,?)",(project,'共享')).fetchall()
    nodes=[store.decode_node(row) for row in node_rows]
    from relation_discovery import current_candidate,managed,stale,inputs
    available.update(n['id'] for n in nodes if n['owner']!='Markdown' or n.get('uri') in paths)
    import note_reconciliation
    sync=[r for r in note_reconciliation.entries()['records'] if r['local_path'] in paths and r['status'] in ('needs_review','needs_refresh')]
    with store.connection() as db:
        edge_rows=db.execute("SELECT source,target,kind,status,CASE WHEN kind IN ('Supports','Contradicts','Inconclusive') THEN evidence ELSE '[]' END AS evidence "
            "FROM relations WHERE status='CANDIDATE' AND kind NOT IN ('DerivedFrom','About','AssociatedWith','Uses','Addresses') "
            "AND NOT EXISTS (SELECT 1 FROM json_each(relations.evidence) e WHERE json_extract(e.value,'$.stale')=1)").fetchall()
    edges=[{**dict(row),'evidence':json.loads(row['evidence'])} for row in edge_rows]
    scoped=[r for r in edges if review_relation(r) and r['source'] in available and r['target'] in available]
    current=inputs(project) if any(managed(r) for r in scoped) else None
    suggestions=[r for r in scoped if not (stale(r,current) if managed(r) else not current_candidate(r))]
    result={'source_updates':sum(d['needs_review'] for d in active),'drafts':len(pending),
            'ai_content':sum(d.get('ai_review_pending',False) and not d['needs_review'] for d in active),
            'scientific_records':sum(requires_review(n) and n['id'] in available for n in nodes),
            'relations':len(suggestions),
            'note_sync':len(sync)}
    # Notifications count distinct material, not every suggested edge.
    # Source changes, independently generated AI content and background previews
    # are observations. A user-initiated draft or a real conflict still needs a
    # decision.
    source_observations={d['id'] for d in active if d.get('needs_review')}
    source_observations.update(d['id'] for d in active if d.get('ai_review_pending'))
    material=set()
    by_path={v:d['id'] for d in active for v in (d['path'],d.get('kb_path')) if v}
    by_record={d.get('record_id'):d['id'] for d in active if d.get('record_id')}
    by_record.update({n['id']:by_path[n['uri']] for n in nodes if n['owner']=='Markdown' and n.get('uri') in by_path})
    material.update(by_path[r['local_path']] for r in sync)
    for proposal in pending:
        target=proposal.get('target') or {}
        if proposal.get('automatic'):
            source_observations.add(by_path.get(target.get('path'), 'draft:'+str(proposal.get('id'))))
        else:
            material.add(by_path.get(target.get('path'), 'draft:'+str(proposal.get('id'))))
    material.update(by_record.get(n['id'],n['id']) for n in nodes if requires_review(n) and n['id'] in available)
    # The decision set must come from the same projection as the review panel;
    # otherwise the home badge, the panel count and per-material actions disagree.
    decisions=[]
    if (w.KB/'项目'/project).is_dir():
        try:decisions=__import__('change_impacts').decision_targets(project,documents=docs)
        except (ValueError,OSError):decisions=[]
    material.update('decision:'+target['decision_id'] if target.get('decision_id') else
                    target['id'] if target.get('kind')=='document' else str(target.get('kind') or '')+':'+str(target['id'])
                    for target in decisions)
    # A source decision must not hide an independent sync conflict or judgment.
    material.update(by_path[r['local_path']] for r in sync)
    material.update(by_record.get(n['id'],n['id']) for n in nodes if requires_review(n) and n['id'] in available)
    return {**result,'total':len(material),'attention':len(material),
            'source_observations':len(source_observations),
            'relation_groups':len({by_record.get(r['source'],r['source']) for r in suggestions})}


def automation(project,view='full'):
    """Return the review queue together with one catalog snapshot, or full settings."""
    import administrator, ai_updates, automation_controls, project_profiles
    all_documents=rows(reconcile_records=False)
    fields={'id','record_id','title','display_title','kind','path','kb_path','project','content_role',
            'archived','visibility','editable','status','needs_action','needs_review','ai_review_pending','file_modified'}
    documents=[{key:value for key,value in d.items() if key in fields}
               for d in all_documents if d['project'] in (project,'共享')]
    papers=[{'id':p['id'],'title':p['title'],'display_title':p.get('display_title') or p['title']}
            for p in w.read_json(w.LIBRARY,{'records':[]})['records'] if not p.get('hidden')]
    pending=ai_updates.pending(project)
    relation_status=Store().cursor('relation-discovery:'+project,{}) or {}
    if view=='review':
        import change_impacts
        impacts=change_impacts.review_listing(project,documents=all_documents)
        target_documents={t['id'] for t in impacts['targets'] if t.get('kind')=='document'}
        pending_paths={(p.get('target') or {}).get('path') for p in pending}
        documents=[doc for doc in documents if doc.get('needs_action') or doc['id'] in target_documents
                   or doc.get('path') in pending_paths or doc.get('kb_path') in pending_paths]
        return {'project':project,'documents':documents,'papers':papers,'pending':pending,
                'relation_status':relation_status,'impacts':impacts,'review_only':True}
    profile=project_profiles.get(project)
    return {'project':project,'documents':documents,'papers':papers,'pending':pending,
            'settings':administrator.settings(project),'jobs':automation_controls.user_jobs()[:60],
            'profile':profile,'relation_status':relation_status,'review_only':False}


def workspace(project, *, browse=False):
    all_documents=rows(browse=True) if browse else rows()
    docs=[doc for doc in all_documents if doc['project'] in (project,'共享')]
    records = __import__('bibliography').enriched(w.read_json(w.LIBRARY, {'records': []})['records'])
    dates = w.read_json(w.DATA/'书目日期.json', {})
    from knowledge_graph import paper_display
    ranks = __import__('journal_ranks').resolve_many(records)
    papers = []
    for record in records:
        if record.get('hidden'):  # 仅有题录/摘要、无全文的线索不在文献列表出现
            continue
        related = [doc for doc in docs if record['id'] in doc['paper_ids']]
        cached = dates.get(record['id'], {})
        year = cached.get('year') if cached.get('status') == 'saved' and cached.get('doi') == w.normalize_doi(record.get('doi') or '') else None
        papers.append({key: record.get(key) for key in ('id', 'title', 'doi', 'pmcid', 'url', 'topic', 'project', 'reading_status', 'year', 'publication_date', 'zotero_key', 'open_notebook_source_id', 'journal', 'issn', 'related_paper_ids')} |
                      {'display_title': paper_display(record)['label'], 'year': record.get('year') or year,
                       'year_source': record.get('year_source') or ('正式书目' if record.get('year') else cached.get('source') if year else None),
                       'documents': [{'id': doc['id'], 'title': doc['title'], 'kind': doc['kind']} for doc in related if not doc['archived'] and doc['visibility'] != 'system'],
                       'has_original': bool(w.chosen_artifact(record)), 'original_kind': (w.chosen_artifact(record) or {}).get('kind'),
                       'availability': __import__('paper_evidence').original_availability(record),
                       'journal_ranks': ranks.get(record['id'])})
    import overview
    import administrator
    import automation_controls
    import ai_updates
    from research_records import templates
    from daily_workspace import fingerprint as library_fingerprint
    by_kb_path = {doc['kb_path']:doc['id'] for doc in docs if doc['kb_path']}
    retrieval_map = {value['note_id']:by_kb_path[path] for path,value in w.load_state().get('notes',{}).items()
                     if path in by_kb_path and value.get('note_id')}
    pending = ai_updates.pending(project)
    from administrator_chat import project_document_ids
    return {'project': project, 'projects': [path.name for path in (w.KB/'项目').iterdir() if path.is_dir()],
            'assistant_document_ids':sorted(project_document_ids(project,documents=all_documents)),
            'project_profiles':__import__('project_profiles').listing(),
            'documents': docs, 'papers': papers, 'library_fingerprint': library_fingerprint({'records': records}),
            'retrieval_documents': retrieval_map,
            'mainlines': k.lines(project), 'tasks': overview.tasks(project),
            'settings': administrator.settings(project), 'flow_settings': automation_controls.cached(),
            'pending': pending,
            'relation_status': Store().cursor('relation-discovery:'+project,{}) or {},
            'review_counts': review_summary(docs,pending,papers,project),
             'jobs': automation_controls.user_jobs()[:30], 'templates': templates(),'relation_types':__import__('relation_schema').definitions(),
            'counts': dict(Counter(doc['kind'] for doc in docs if doc['visibility'] == 'active' and not doc['archived']))}


def propose(data):
    """Return a draft in the task ledger; do not create another report file."""
    doc = detail(data.get('id'))
    if not doc['editable']:
        raise ValueError('这份系统记录请通过对应的审核或主线设置维护')
    if data.get('fingerprint') != doc['fingerprint']:
        raise ValueError('正文已经变化，请重新打开后生成草稿')
    instruction = data.get('instruction')
    if not isinstance(instruction, str) or not 1 <= len(instruction.strip()) <= 8000:
        raise ValueError('请说明希望怎样修改')
    from model_gateway import call_deepseek
    from research_prompts import common
    related = [detail(ref['id']) for ref in doc['references'][:5]]
    material = {'title': doc['title'], 'body': doc['body'][:30000], 'instruction': instruction,
                'sources': [{'title': source['title'], 'path': source['path'], 'body': source['body'][:4000]} for source in related]}
    result = call_deepseek({'model': 'deepseek-flash', '_interactive': True, 'max_tokens': 7500,
        'messages': [{'role': 'system', 'content': common()+'\n你是科研正文编辑助手。只输出可供用户编辑的 Markdown 正文，保留原有来源链接。用户将审核草稿后保存，本次没有修改正式文件。'},
                     {'role': 'user', 'content': json.dumps(material, ensure_ascii=False)}]})
    if result.get('error'):
        raise ValueError(result['error'])
    return {'id': doc['id'], 'fingerprint': doc['fingerprint'], 'body': result['answer'], 'status': 'candidate', 'instruction': instruction}
