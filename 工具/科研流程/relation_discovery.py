"""Incremental cross-document suggestions, independent of folders and classifications.

Markdown/Zotero remain authoritative. SQLite stores only indexes, source-bound
AI suggestions and successful input signatures. No generated report is created.
"""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import threading
from time import monotonic
import requests

import knowledge as k
import workflow as w
from research_store import Store, encode
from relation_requests import PROTOCOL, prepare
from structured_response import ResponseValidationError, request_released, resume_request

VERSION = 'relations-v1'
GLOBAL_SCOPE = '共享'
LOCK = threading.RLock()
_NEXT_PROBE = {}
KINDS = {'RelatedTo', 'MethodSimilar', 'Uses', 'Addresses', 'Supports', 'Contradicts', 'Inconclusive'}
SCIENCE = {'Supports', 'Contradicts', 'Inconclusive'}
LABELS = {'RelatedTo': '内容相关', 'MethodSimilar': '方法相近', 'Uses': '方法参考',
          'Addresses': '回应问题', 'Supports': '支持', 'Contradicts': '反驳', 'Inconclusive': '证据未定'}


def _describe(error):
    """保留具体原因（代理拒连、超时、返回格式错误等），不要只写“暂未完成”。"""
    if isinstance(error, ValueError):
        return str(error)
    text = ' '.join(str(error).split())[:160]
    return '关联分析暂未完成：' + type(error).__name__ + ('：' + text if text else '')


def database():
    store = Store()
    with store.connection() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS relation_inputs(
            project TEXT NOT NULL,id TEXT NOT NULL,signature TEXT NOT NULL,
            summary TEXT NOT NULL,updated TEXT NOT NULL,PRIMARY KEY(project,id))''')
        db.execute('''CREATE TABLE IF NOT EXISTS relation_vectors(
            fingerprint TEXT PRIMARY KEY,model TEXT NOT NULL,vector TEXT NOT NULL,updated TEXT NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS relation_failures(
            project TEXT NOT NULL,id TEXT NOT NULL,signature TEXT NOT NULL,protocol TEXT NOT NULL,
            retry_round INTEGER NOT NULL,error TEXT NOT NULL,updated TEXT NOT NULL,PRIMARY KEY(project,id))''')
        db.execute('''CREATE TABLE IF NOT EXISTS relation_pair_inputs(signature TEXT PRIMARY KEY)''')
    return store


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def document_input(doc, body):
    """Build the existing version-bound excerpts from a canonical body snapshot."""
    if not body.strip():return None
    lines=body.splitlines(keepends=True);chunks=[];start=0
    while start<len(lines) and len(chunks)<3:
        end=start;length=0
        while end<len(lines) and (length<1600 or end==start):
            length+=len(lines[end]);end+=1
        chunks.append({'ref':'body-'+str(len(chunks)),'kind':'document_excerpt',
                       'location':doc['path']+' · 正文第 '+str(start+1)+'–'+str(end)+' 行（节选）',
                       'text':''.join(lines[start:end])[:2200]})
        start=end
    identifier=doc.get('record_id') or doc['id']
    item={'id':identifier,'kind':'Document','title':doc['display_title'],'project':doc['project'],
          'owner':'Markdown','uri':doc.get('kb_path') or doc['path'],'doc_id':doc['id'],
          'document_sha256':doc['sha'],'sources':chunks,'paper_ids':doc['paper_ids'],
          'scope':doc.get('reading_scope') or ('AI 草稿，未替代原文核查' if doc['kind'] in {'分析报告','阅读笔记','阅读记录'} else '用户资料节选')}
    item['fingerprint']=digest({'title':item['title'],'sha':doc['sha'],'sources':chunks})
    return item


def paper_input(paper, state):
    """Read one already registered paper's current cached excerpts, without a model."""
    metadata='题名：'+paper.get('title',paper['id'])+'\nDOI：'+str(paper.get('doi') or '未提供')
    if paper.get('abstract'):metadata+='\n摘要（书目元数据）：'+str(paper['abstract'])[:2500]
    sources=[{'ref':'metadata','kind':'metadata','location':'Zotero / 已登记题录','text':metadata}]
    sha=state.get('papers',{}).get(paper['id'],{}).get('sha256','')
    from organization import current_artifact_sha
    try:actual_sha=current_artifact_sha(w.chosen_artifact(paper))
    except OSError:actual_sha=None
    if re.fullmatch(r'[a-f0-9]{64}',str(sha)) and actual_sha==sha:
        import fulltext_parser
        cached=fulltext_parser.read_cache(w.DATA/'正文'/(sha+'.json'),usable_only=True)
        if cached.get('sha256')!=sha:cached={}
        for index,page in enumerate(cached.get('pages',[])[:3]):
            text=str(page.get('text') or '').strip()[:1800]
            if not text:continue
            location='PDF 第 '+str(page['page'])+' 页' if page.get('page') else 'XML '+str(page.get('section') or '正文节选')
            sources.append({'ref':'excerpt-'+str(index),'kind':'fulltext_excerpt','location':location,'text':text})
    item={'id':paper['id'],'kind':'Paper','title':paper.get('title') or paper['id'],
          'project':paper.get('project') or '共享','owner':'Zotero','uri':paper.get('url'),
          'external_id':paper.get('zotero_key'),'sources':sources,'paper_ids':[paper['id']]}
    item['fingerprint']=digest({'title':item['title'],'sources':sources})
    return item


def scope_materials(project):
    """Reuse the scope used by the two knowledge entry points."""
    import knowledge_catalog
    if project==GLOBAL_SCOPE:
        snapshot=knowledge_catalog.source_catalog()
        return snapshot['documents'],snapshot['papers']
    from project_knowledge import view
    current=view(project)
    papers={p['id'] for p in current['papers']}
    return current['documents'],[p for p in knowledge_catalog._registered_papers() if p['id'] in papers]


def _knowledge_docs(docs):
    from material_roles import knowledge
    return [d for d in docs if knowledge(d) and not (d.get('kb_path') or '').startswith('文献/条目/')]


def _stamp(path):
    try:
        info=path.stat()
        return info.st_size,info.st_mtime_ns
    except OSError:
        return None


def input_epoch(project,materials=None):
    """A cheap version/membership check before dispatching an analysis job."""
    docs,papers=scope_materials(project) if materials is None else materials
    state=w.read_json(w.DATA/'state.json',{}).get('papers',{})
    rows=[(d.get('record_id') or d['id'],d['sha']) for d in _knowledge_docs(docs)]
    from pathlib import Path
    for paper in papers:
        sha=state.get(paper['id'],{}).get('sha256') or ''
        artifact=w.chosen_artifact(paper) or {}
        rows.append((paper['id'],paper.get('title'),paper.get('doi'),paper.get('abstract'),
                     _stamp(Path(artifact['path'])) if artifact.get('path') else None,
                     sha,_stamp(w.DATA/'正文'/(sha+'.json')) if re.fullmatch(r'[a-f0-9]{64}',sha) else None))
    return digest(sorted(rows))


def _documents(docs):
    import workspace_catalog as catalog
    for doc in _knowledge_docs(docs):
        try:
            body = k.split(catalog.bounded(doc['path']).read_text('utf-8-sig'))[1]
        except (OSError, ValueError, UnicodeError):
            continue
        item=document_input(doc,body)
        if item:yield item


def inputs(project,materials=None):
    docs,papers=scope_materials(project) if materials is None else materials
    state=w.read_json(w.DATA/'state.json',{})
    result={p['id']:paper_input(p,state) for p in papers}
    result.update((i['id'],i) for i in _documents(docs))
    return result


def local_vectors(items, store):
    """Reuse the installed Qwen 4B model; cache derived vectors, never download one."""
    base = 'http://127.0.0.1:11434'
    try:
        response = requests.get(base+'/api/tags', timeout=3); response.raise_for_status()
        model = next((m for m in response.json().get('models', []) if m.get('name') == 'qwen3-embedding:4b'), None)
        if not model:
            return None
        model_id = model['name']+'@'+model['digest']
        keys = {i: digest(['embedding-v1', model_id, item['fingerprint']]) for i,item in items.items()}
        with store.connection() as db:
            cached = {r['fingerprint']: json.loads(r['vector']) for r in db.execute('SELECT fingerprint,vector FROM relation_vectors WHERE model=?', (model_id,))}
        missing = [i for i in items if keys[i] not in cached]
        # Bound the initial catch-up; new material usually requires only one vector.
        for start in range(0,min(len(missing),12),4):
            batch = missing[start:min(start+4,12)]
            texts = [(items[i]['title']+'\n'+'\n'.join(s['text'] for s in items[i]['sources']))[:3500] for i in batch]
            response = requests.post(base+'/api/embed', json={'model':model['name'],'input':texts,'truncate':True,'keep_alive':'10m'}, timeout=90)
            response.raise_for_status(); vectors = response.json().get('embeddings')
            import numpy as np
            matrix = np.asarray(vectors,dtype=float)
            if matrix.ndim != 2 or matrix.shape[0] != len(batch) or matrix.shape[1] < 32 or not np.isfinite(matrix).all():
                return None
            with store.connection() as db:
                for i,vector in zip(batch,vectors):
                    db.execute('INSERT OR REPLACE INTO relation_vectors VALUES(?,?,?,?)',(keys[i],model_id,encode(vector),w.now()))
                    cached[keys[i]] = vector
        remaining = max(0,len(missing)-12)
        if remaining:
            return {'remaining':remaining}
        return [cached[keys[i]] for i in items]
    except (requests.RequestException, ValueError, KeyError, TypeError):
        # Local retrieval can degrade gracefully; it never creates scientific edges.
        return None


def shortlist(items, vectors=None):
    """Mature local retrieval only selects passages; it never declares a relation."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    ids = list(items)
    if len(ids) < 2:
        return {i: [] for i in ids}
    texts = [items[i]['title']+'\n'+'\n'.join(s['text'] for s in items[i]['sources']) for i in ids]
    try:
        matrix = vectors if vectors is not None else TfidfVectorizer(analyzer='char', ngram_range=(2, 4), max_features=30000).fit_transform(texts)
        similarity = cosine_similarity(matrix)
    except ValueError:
        return {i: [] for i in ids}
    result = {}
    for n, identifier in enumerate(ids):
        ordered = sorted(range(len(ids)), key=lambda m: (-similarity[n, m], ids[m]))
        result[identifier] = [ids[m] for m in ordered if m != n and similarity[n, m] >= (.45 if vectors is not None else .06)
                             and not (items[identifier]['kind'] == 'Paper' and identifier in items[ids[m]]['paper_ids'])
                             and not (items[ids[m]]['kind'] == 'Paper' and ids[m] in items[identifier]['paper_ids'])][:5]
    return result


def signatures(items):
    return {i: digest([VERSION, item.get('document_sha256') or item['fingerprint']])
            for i, item in items.items()}


def _pair_signature(a,b,hashes):
    return digest([VERSION,sorted(((a,hashes[a]),(b,hashes[b])))])


def _reuse_legacy_success(store,project,items,hashes,previous):
    """Keep existing successful analyses when their observed source is still current."""
    with store.connection() as db:
        successes=db.execute('SELECT project,id,signature,updated FROM relation_inputs').fetchall()
    observations={}
    for saved in successes:
        identifier=saved['id']
        if identifier not in items or saved['project']!=project and project!=GLOBAL_SCOPE:continue
        if identifier in previous and previous[identifier]==hashes[identifier]:continue
        source_project=saved['project']
        if source_project not in observations:
            observations[source_project]=store.cursor('relation-discovery:observed:'+source_project,{}) or {}
        seen=observations[source_project].get(identifier,{})
        if (seen.get('fingerprint')==items[identifier]['fingerprint'] and seen.get('changed')
                and datetime.fromisoformat(seen['changed'])<=datetime.fromisoformat(saved['updated'])):
            previous[identifier]=hashes[identifier]


def clean_quote(text):
    return re.sub(r'\s+', '', text)


def evidence_units(item):
    """Let the model select a fixed original span instead of retyping a quote."""
    units=[]
    for source in item['sources']:
        text=source['text']
        for offset in range(0,len(text),320):
            passage=text[offset:offset+320]
            if len(passage.strip())<6:
                continue
            units.append({**source,'ref':source['ref']+'@'+str(offset),'text':passage,
                          'location':source['location']+' · 节选字符 '+str(offset+1)+'–'+str(offset+len(passage))})
    return units


def validate(plan, batch, items, neighbors, *, provided=None, ordinary_only=False):
    rows = plan.get('items') if isinstance(plan, dict) else None
    if not isinstance(rows, list) or len(rows) != len(batch):
        raise ValueError('关联分析没有完整返回本批资料，成功进度未推进。')
    seen = set(); result = []
    if provided is None:
        provided=set(batch)|{target for identifier in batch for target in neighbors[identifier]}
    for row in rows:
        identifier = row.get('id') if isinstance(row, dict) else None
        if identifier not in batch or identifier in seen:
            raise ValueError('关联分析返回了未知或重复资料 ID。')
        seen.add(identifier)
        summary = row.get('summary')
        relations = row.get('relations')
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 700 or not isinstance(relations, list) or len(relations) > 5:
            raise ValueError('关联摘要或关系格式无效。')
        edges = []
        for edge in relations:
            if not isinstance(edge, dict):
                raise ValueError('关系条目格式无效。')
            if not isinstance(edge.get('target'),str) or edge['target'] not in provided:
                raise ValueError('AI 返回了未提供的关联目标「'+str(edge.get('target'))[:80]+'」。')
            if edge['target']==identifier:
                # 自反关系没有意义：忽略这一条，不让整篇资料因此永久失败。
                continue
            if ordinary_only and edge['target'] not in neighbors[identifier]:
                raise ValueError('关联目标不在当前资料的候选列表中。')
            if not isinstance(edge.get('kind'),str) or edge['kind'] not in KINDS:
                raise ValueError('AI 返回的关系类型「'+str(edge.get('kind'))[:80]+'」不受支持；可选 '+', '.join(sorted(KINDS))+'。')
            target = edge['target']; reason = edge.get('reason'); conditions = edge.get('conditions', '')
            evidence = edge.get('evidence')
            if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000 or not isinstance(conditions, str) or len(conditions) > 1000:
                raise ValueError('每条关联需要说明具体原因与适用条件。')
            if not isinstance(evidence, list) or not 2 <= len(evidence) <= 6:
                raise ValueError('关联必须附上两端资料的真实原文片段。')
            verified = []; endpoints = set()
            for entry in evidence:
                if not isinstance(entry, dict) or entry.get('id') not in {identifier, target}:
                    raise ValueError('关联证据不能借用其他资料。')
                source_id = entry['id']; units=evidence_units(items[source_id])
                source = next((s for s in units+items[source_id]['sources'] if s['ref'] == entry.get('ref')), None)
                quote = entry.get('quote')
                if quote is None and source and source in units:
                    quote=source['text']
                if source is None or not isinstance(quote, str) or not 6 <= len(quote) <= 400 or not clean_quote(quote) or clean_quote(quote) not in clean_quote(source['text']):
                    raise ValueError('关联引用的文字或位置不在本次实际提供的材料中。')
                endpoints.add(source_id)
                verified.append({'id': source_id, 'ref': source['ref'], 'location': source['location'], 'quote': quote,
                                 'scope': '仅题录' if source['kind'] == 'metadata' else items[source_id].get('scope') or '原文节选，未核查全文',
                                  'source_kind': source['kind'], 'fingerprint': items[source_id]['fingerprint'], 'generator': VERSION,
                                  **({'document_sha256':items[source_id]['document_sha256']} if items[source_id].get('document_sha256') else {})})
            if endpoints != {identifier, target}:
                raise ValueError('关系两端都必须有实际依据。')
            kind = edge['kind']; note = ''
            if kind in SCIENCE and ordinary_only:
                continue
            elif kind in SCIENCE and any(item.get('source_kind') != 'fulltext_excerpt' for item in verified):
                # 题录、AI 笔记和报告只能提出内容关联：降级而不是整批失败，避免同一资料无限重试。
                note = '\n原判「'+LABELS[kind]+'」缺少两端论文原文，已降为内容相关；核查原文后可另行建立科研关系。'
                kind = 'RelatedTo'
            edges.append({'source': identifier, 'target': target, 'kind': kind, 'evidence': verified,
                          'conditions': reason.strip()+('\n适用条件：'+conditions.strip() if conditions.strip() else '')+note})
        result.append({'id': identifier, 'summary': summary.strip(), 'relations': edges})
    return result


def partition_response(value, active, items, neighbors, decode, *, ordinary_only=False):
    """Keep independently valid documents; ambiguous batch identities fail closed."""
    identities = decode(value, identities_only=True)
    # Enforce the complete, unique batch before salvaging any document.
    identifiers = [row['id'] for row in identities['items']]
    if len(identifiers) != len(active) or set(identifiers) != set(active):
        raise ValueError('关联分析没有完整返回本批资料，或返回了未知或重复资料 ID。')
    provided = set(active) | {j for i in active for j in neighbors[i]}
    plans = []; failures = {}
    for row, identity in zip(value['items'], identities['items']):
        identifier = identity['id']
        try:
            decoded = decode({'items': [row]})
            plans += validate(decoded, [identifier], items, neighbors, provided=provided, ordinary_only=ordinary_only)
        except ValueError as error:
            message = str(error)
            prefix = '「'+items[identifier]['title'][:70]+'」'
            failures[identifier] = message if message.startswith(prefix) else prefix+'：'+message
    return plans, failures


def managed(edge):
    return any(isinstance(e, dict) and e.get('generator') == VERSION for e in edge.get('evidence', []))


def _same_source(evidence,item):
    if evidence.get('document_sha256'):
        return evidence['document_sha256']==item.get('document_sha256')
    if evidence.get('fingerprint')==item['fingerprint']:return True
    # Older edges used the display title and path in their source fingerprint.
    # Retain them when the stored excerpt is still at the same source reference.
    quote=clean_quote(evidence.get('quote') or '')
    return bool(item.get('document_sha256') and evidence.get('source_kind')=='document_excerpt' and quote
                and any(span['ref']==evidence.get('ref') and quote in clean_quote(span['text'])
                        for span in evidence_units(item)+item['sources']))


def stale(edge, items):
    return managed(edge) and ((edge['status'] != 'REJECTED' and not current_candidate(edge)) or any(
        e.get('id') not in items or not _same_source(e,items[e['id']])
        for e in edge['evidence'] if e.get('generator') == VERSION))


def current_candidate(edge):
    """Keep historical suggestions stored, outside current evidence and daily review."""
    if edge['status'] == 'REJECTED' or any(e.get('stale') for e in edge.get('evidence', [])):
        return False
    if managed(edge) and edge['kind'] in SCIENCE:
        return bool(edge['evidence']) and all(e.get('source_kind') == 'fulltext_excerpt'
            or not e.get('source_kind') and str(e.get('ref', '')).startswith('excerpt-') for e in edge['evidence'])
    return True


def evidence_inputs(edges):
    """Evidence freshness uses stable source identities independently of membership."""
    required={e['id'] for edge in edges for e in edge['evidence'] if e.get('generator')==VERSION}
    if not required:return {}
    import workspace_catalog
    import knowledge_catalog
    docs=[d for d in workspace_catalog.rows() if (d.get('record_id') or d['id']) in required]
    state=w.read_json(w.DATA/'state.json',{})
    current={p['id']:paper_input(p,state) for p in knowledge_catalog._registered_papers() if p['id'] in required}
    current.update((i['id'],i) for i in _documents(docs))
    return current


def assert_review_current(edge, store):
    if managed(edge) and stale(edge,evidence_inputs([edge])):
        raise ValueError('关联依据已经变化或资料已归档，请等待重新分析后核查。')


def register(items, store):
    for item in items.values():
        old = store.node(item['id'])
        # A typed research object keeps its own authority, status and review.
        if old and item.get('doc_id') and old['kind'] != 'Document':
            continue
        data = {**(old['data'] if old else {}), 'title': item['title'], 'doc_id': item.get('doc_id'),
                'document_sha256': item.get('document_sha256'), 'scope': item.get('scope', '题录与原文节选')}
        uri = ('zotero://select/library/items/'+item['external_id'] if item.get('external_id') else item.get('uri')) or (old or {}).get('uri')
        store.put_node(item['id'], item['kind'], item['owner'], project=item['project'], uri=uri,
                       external_id=item.get('external_id'), status=old['status'] if old else 'INDEXED', data=data)
    identifiers=set(items)
    for edge in store.relations():
        if not managed(edge) or edge['status'] == 'REJECTED' or not ({edge['source'],edge['target']} & identifiers):
            continue
        if any(e.get('generator')==VERSION and e.get('id') in items and not _same_source(e,items[e['id']])
               for e in edge['evidence']) and not any(e.get('stale') for e in edge['evidence']):
            with store.connection() as db:
                evidence = [{**e, 'stale': True} for e in edge['evidence']]
                changed = db.execute("UPDATE relations SET status='CANDIDATE',evidence=?,revision=revision+1,updated=? WHERE id=? AND revision=?",
                                     (encode(evidence), w.now(), edge['id'], edge['revision'])).rowcount
                if changed:
                    store.log(db, 'relation.source_changed', edge['id'])


def summary(project):
    store = database()
    value = store.cursor('relation-discovery:'+project, {}) or {}
    edges = [r for r in store.relations() if managed(r)]
    ids=set(value['material_ids']) if 'material_ids' in value else {n['id'] for n in store.nodes(project)}
    scoped=[r for r in edges if r['status']=='CANDIDATE' and {r['source'],r['target']}<=ids]
    return {**value,'candidates':sum(current_candidate(r) for r in scoped),
            'historical_candidates':sum(not current_candidate(r) for r in scoped)}


def project_links(nodes,documents,papers,saved):
    """Project organization can show ordinary relations on its current selections."""
    from knowledge_catalog import _relation_inputs
    from relation_schema import RELATIONS
    doc_ids={d['id']:d.get('record_id') or d['id'] for d in documents}
    visible={}
    for node in nodes:
        source=node['source']
        material=(doc_ids.get(source.get('document_id')) if source['kind']=='document'
                  else source.get('paper_id'))
        if material:visible[material]=node['id']
    store=Store()
    hidden=set(saved.get('hidden_auto_edges',[]))
    edges=[e for e in store.relations()
           if managed(e) and e['kind'] not in SCIENCE and e['id'] not in hidden
           and {e['source'],e['target']}<=visible.keys() and current_candidate(e)]
    current=_relation_inputs(edges,documents,papers,store)
    return [{'id':e['id'],'source':visible[e['source']],'target':visible[e['target']],
             'kind':'ai-content','label':RELATIONS[e['kind']]['label'],'reason':e['conditions'],
             'organization':True,'evidence':e['evidence']}
            for e in edges if not stale(e,current)]


def discover(data):
    with LOCK:
        return _run_discovery(data)


def _run_discovery(data):
    project = data.get('project') or '山药'
    store=database()
    previous=store.cursor('relation-discovery:'+project,{}) or {}
    try:
        result=_discover(data)
        store.commit_page('relation-discovery:'+project,[],result)
        return result
    except Exception as error:
        current=store.cursor('relation-discovery:'+project,{}) or {}
        attempts=previous.get('attempts',0)+1 if previous.get('error')==_describe(error) else 1
        store.commit_page('relation-discovery:'+project,[],{**current,
            'status':'needs_attention' if isinstance(error,ResponseValidationError) else 'waiting',
            'request_id':getattr(error,'request_id',None),'replay_mismatch':getattr(error,'replay_mismatch',False),
            'checked':w.now(),'attempts':attempts,'error':_describe(error)})
        raise


def _discover(data):
    project=data.get('project') or '山药'
    with LOCK:
        import project_profiles
        store=database()
        current_key='relation-discovery:'+project
        prior=store.cursor(current_key,{}) or {}
        revision=None if project==GLOBAL_SCOPE else project_profiles.capture_automatic(project)
        request_id=prior.get('request_id')
        if request_id and (prior.get('replay_mismatch') or not request_released(store,request_id)):
            return prior
        materials=scope_materials(project)
        epoch=input_epoch(project,materials)
        items=inputs(project,materials);register(items,store)
        baseline={'input_epoch':epoch,'material_ids':sorted(items),'last_success':prior.get('last_success')}
        observed_key='relation-discovery:observed:'+project
        observed=store.cursor(observed_key,{}) or {}; observed_changed=False; stamp=w.now()
        for identifier,item in items.items():
            if observed.get(identifier,{}).get('fingerprint')!=item['fingerprint']:
                observed[identifier]={'fingerprint':item['fingerprint'],'changed':stamp};observed_changed=True
        if observed_changed:
            # Observation is independent of the successful-analysis cursor.
            store.commit_page(observed_key,[],observed)
        hashes=signatures(items)
        with store.connection() as db:
            previous = {r['id']: r['signature'] for r in db.execute('SELECT id,signature FROM relation_inputs WHERE project=?', (project,))}
            saved_failures = {r['id']: dict(r) for r in db.execute('SELECT * FROM relation_failures WHERE project=?', (project,))}
            existing_pairs={r['signature'] for r in db.execute('SELECT signature FROM relation_pair_inputs')}
            failed = {i: r for i, r in saved_failures.items()
                      if i in hashes and r['signature']==hashes[i] and r['protocol']==PROTOCOL}
        _reuse_legacy_success(store,project,items,hashes,previous)
        changed = [i for i in items if previous.get(i) != hashes[i]]
        # New material is handled before the initial historical backlog.
        changed.sort(key=lambda i: (-datetime.fromisoformat(observed[i]['changed']).timestamp(),i))
        retry_failed = data.get('retry_failed') is True
        eligible = [i for i in changed if i in saved_failures] if retry_failed else [i for i in changed if i not in failed]
        batch = eligible[:3]
        failures = lambda: [{'id':i,'title':items[i]['title'],'doc_id':items[i].get('doc_id'),'error':failed[i]['error']}
                            for i in changed if i in failed]
        if not batch:
            return {**baseline,'status':'needs_attention' if failed else 'unchanged','analyzed':0,
                    'remaining':len(changed),'relations':0,'checked':w.now(),'retrieval':prior.get('retrieval'),
                    'failures':failures(),'error':next(iter(failed.values()))['error'] if failed else ''}
        vectors=local_vectors(items,store) if len(items)>1 else None
        if isinstance(vectors,dict):
            return {**baseline,'status':'indexing','analyzed':0,'relations':0,'remaining':vectors['remaining'],
                    'retrieval':'Qwen3 Embedding 4B','checked':w.now()}
        retrieval='Qwen3 Embedding 4B' if vectors is not None else '词面检索（本地语义服务暂不可用）'
        neighbors=shortlist(items,vectors)
        for i in batch:
            neighbors[i]=[j for j in neighbors[i] if _pair_signature(i,j,hashes) not in existing_pairs]
        isolated = [i for i in batch if not neighbors[i]]
        active = [i for i in batch if neighbors[i]]
        store.commit_page(current_key,[],{**prior,**baseline,'status':'running',
            'remaining':len(changed),'checked':w.now(),'error':''})
        plans = [{'id': i, 'summary': '暂未发现值得核查的内容关联；资料保留，可随新增内容重新分析。', 'relations': []} for i in isolated]
        if active:
            from model_gateway import model_status
            if not model_status()['configured']:
                raise ValueError('自动关联等待本机 DeepSeek 配置；资料和成功进度已保留。')
            import structured_response
            retry_round=max((failed[i]['retry_round']+1 for i in active if i in failed),default=0)
            payload,decode=prepare(project,active,items,neighbors,KINDS-SCIENCE,evidence_units,retry_round)
            try:
                with resume_request(store,request_id):
                    plan=structured_response.request(payload,'跨资料关联',
                        lambda value:validate(decode(value),active,items,neighbors,ordinary_only=True))
            except ResponseValidationError as error:
                # Known invalid answers need a new explicit retry, not an endless cache replay.
                # Unknown provider outcomes never enter this table or get a fresh retry round.
                try:
                    valid_plans, invalid=partition_response(error.value,active,items,neighbors,decode,ordinary_only=True)
                except ValueError:
                    valid_plans, invalid = [], {i: str(error) for i in active}
                with store.connection() as db:
                    for i, reason in invalid.items():
                        record=(project,i,hashes[i],PROTOCOL,retry_round,reason,w.now())
                        db.execute('INSERT OR REPLACE INTO relation_failures VALUES(?,?,?,?,?,?,?)',record)
                        failed[i]={'error':reason,'retry_round':retry_round}
                plans += valid_plans
                if not plans:
                    store.commit_page(current_key,[],{**baseline,'analyzed':0,'relations':0,
                        'remaining':len(changed),'status':'needs_attention','error':str(error),'failures':failures(),'checked':w.now()})
                    raise
            else:
                plans+=validate(decode(plan),active,items,neighbors,ordinary_only=True)
        # Do not publish an AI result produced against an older user manuscript.
        import workspace_catalog as catalog
        lifecycle=nullcontext() if revision is None else project_profiles.lifecycle_lock(project)
        with lifecycle,k.editing(),catalog.LOCK:
            if revision is not None:
                profile=project_profiles.get(project)
                if profile['archived'] or profile['lifecycle_revision']!=revision:
                    raise project_profiles.AutomaticStopped('项目状态已变化，本次旧关联不发布。')
            current = inputs(project)
            involved = set(batch) | {e['target'] for p in plans for e in p['relations']}
            if any(i not in current or current[i]['fingerprint'] != items[i]['fingerprint'] for i in involved):
                raise ValueError('资料在分析期间已修改，本批候选未发布，稍后会重新分析。')
            existing = {(r['source'],r['target'],r['kind']): r for r in store.relations()}
            count = 0
            for plan in plans:
                for edge in plan['relations']:
                    if edge['kind'] in {'RelatedTo','MethodSimilar'}:
                        edge['source'],edge['target'] = sorted([edge['source'],edge['target']])
                        edge['evidence'].sort(key=lambda e:(e['id'],e['ref']))
                    old = existing.get((edge['source'], edge['target'], edge['kind']))
                    if old and (old['status'] == 'REJECTED' or not managed(old) or not stale(old, items)):
                        continue
                    store.relation(edge['source'], edge['target'], edge['kind'], edge['evidence'], edge['conditions'])
                    existing[(edge['source'],edge['target'],edge['kind'])] = {**edge, 'status': 'CANDIDATE'}
                    count += 1
            with store.connection() as db:
                for plan in plans:
                    db.execute('INSERT OR REPLACE INTO relation_inputs VALUES(?,?,?,?,?)', (project, plan['id'], hashes[plan['id']], plan['summary'], w.now()))
                    db.executemany('INSERT OR IGNORE INTO relation_pair_inputs VALUES(?)',
                                   [(_pair_signature(plan['id'],target,hashes),) for target in neighbors[plan['id']]])
                    db.execute('DELETE FROM relation_failures WHERE project=? AND id=?',(project,plan['id']))
                    failed.pop(plan['id'],None)
        result = {**baseline,'status': 'partial' if failed else 'completed', 'analyzed': len(plans), 'remaining': len(changed)-len(plans),
                  'relations': count, 'checked': w.now(), 'last_success': w.now(), 'retrieval':retrieval,
                  'failures':failures(),'error':next(iter(failed.values()))['error'] if failed else ''}
        return result


def pending_project():
    import administrator
    import administrator_state
    from knowledge_extraction import CONTROL, PROVIDER_BLOCK
    projects=[]
    for project in dict.fromkeys([administrator.settings()['project'],*administrator_state.configured_projects()]):
        cfg=administrator.settings(project)
        if not cfg['enabled'] or not cfg.get('auto_relations',True):continue
        if project!=GLOBAL_SCOPE:
            try:k.line_path(project,w.KB)
            except ValueError:continue
        projects.append(project)
    store=database();candidates=[]
    global_settings=store.cursor(CONTROL,{}) or {}
    if (global_settings.get('enabled',bool(projects)) and not global_settings.get('paused')
            and not (store.cursor(PROVIDER_BLOCK,{}) or {}).get('blocked')):
        projects.append(GLOBAL_SCOPE)
    else:
        projects=[p for p in projects if p!=GLOBAL_SCOPE]
    for project in dict.fromkeys(projects):
        progress=store.cursor('relation-discovery:'+project,{}) or {}
        value=progress.get('next_check')
        try:ready=not value or datetime.fromisoformat(value)<=datetime.now(timezone.utc)
        except (ValueError,TypeError):ready=True
        if not ready:continue
        request_id=progress.get('request_id')
        if request_id:
            if not progress.get('replay_mismatch') and request_released(store,request_id):
                candidates.append((progress.get('checked',''),project))
            continue
        remaining=progress.get('remaining',0)-len(progress.get('failures') or [])
        if progress.get('status') in ('indexing','running') or remaining>0 and progress.get('status')!='waiting':
            candidates.append((progress.get('checked',''),project));continue
        if progress.get('status')=='waiting' and progress.get('attempts',0)<3:
            candidates.append((progress.get('checked',''),project));continue
        probe=(store.path,project);now=monotonic()
        if now<_NEXT_PROBE.get(probe,0):continue
        if progress.get('input_epoch')==input_epoch(project):
            _NEXT_PROBE[probe]=now+60
            continue
        candidates.append((progress.get('checked',''),project))
    return min(candidates)[1] if candidates else None


def due():
    return pending_project() is not None


def tick():
    import administrator
    project=pending_project()
    if project is None:
        return {'status':'disabled'}
    store = database(); previous=store.cursor('relation-discovery:'+project,{}) or {}
    if previous.get('next_check'):
        try:
            if datetime.fromisoformat(previous['next_check']) > datetime.now(timezone.utc):
                return {'status':'not_due'}
        except ValueError:
            pass
    try:
        result = discover({'project': project})
        minutes = 15 if result.get('status')=='needs_attention' else 1 if result.get('remaining') else 3
    except Exception as error:
        result=store.cursor('relation-discovery:'+project,{}) or {}
        minutes = 1 if isinstance(error,ResponseValidationError) else 15
    result['next_check'] = (datetime.now(timezone.utc)+timedelta(minutes=minutes)).isoformat()
    store.commit_page('relation-discovery:'+project, [], result)
    return result
