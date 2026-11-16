"""Reviewable, replayable metadata migration; originals never move or disappear."""
import copy
from pathlib import PurePosixPath
import knowledge as k
import workflow as w
import workspace_catalog as catalog
import material_roles
import project_profiles as profiles
from research_store import Store,encode

SCHEMA='project-stages-knowledge-v1'


def classification(doc,meta):
    role=doc['content_role'];reason='沿用明确内容角色或已知知识类型'
    if role=='system_record':return role,False,'维护记录、备份或系统资料'
    if meta.get('content_role') in material_roles.ROLES:return role,doc['global_knowledge'],'沿用人工角色及关联选择'
    if role=='project_process':return role,False,'原始类型、记录身份或项目状态明确为过程'
    explicit=meta.get('type') in {'personal_note','ai_paper_note','ai_reading_record'} or doc.get('record_type') in {'Concept','Method','LiteratureNote','Evidence'}
    if doc['path'].startswith('科研知识库/项目/') and not explicit:
        return 'unclassified',False,'项目内未明确区分的旧稿，保留至项目待整理'
    if doc['path'].startswith('科研知识库/更新记录/'):
        return 'unclassified',False,'背景候选保留原审核入口，待核对后归类'
    return 'knowledge',meta.get('global_knowledge',True) if type(meta.get('global_knowledge',True)) is bool else False,reason


def _organization(project,docs):
    store=Store();before=store.cursor('project-knowledge:'+project,{'modules':{},'assignments':{}})
    saved=store.cursor('project-canvas:'+project,{})
    auto=store.cursor('canvas-organization:'+project,{})
    after=copy.deepcopy(before)
    directions={**auto.get('directions',{}),**saved.get('directions',{})}
    mapping={}
    for index,(identifier,direction) in enumerate(sorted(directions.items())):
        mid='MOD-'+w.digest(project+':legacy-direction:'+identifier)[:24];mapping[identifier]=mid
        if mid not in after['modules']:
            after['modules'][mid]={'id':mid,'title':direction.get('title') or '旧知识模块','parent_id':'','order':len(after['modules']),
                                   'legacy_direction_id':identifier}
    for doc in docs:
        if doc['role']!='knowledge':continue
        selected=next((nid for nid,node in saved.get('nodes',{}).items() if node.get('source',{}).get('document_id')==doc['id'] and not node.get('deleted')),None)
        if doc['project']!=project and not selected:continue
        nid=selected or doc.get('canvas_node') or 'a-'+w.digest('doc:'+doc['id'])[:24]
        node=saved.get('nodes',{}).get(nid,{})
        if node.get('deleted'):continue
        direction=node.get('direction_override') or auto.get('assignments',{}).get(nid,{}).get('direction')
        if direction in mapping and doc['id'] not in after['assignments']:
            after['assignments'][doc['id']]=[mapping[direction]]
    return {'project':project,'before':before,'after':after,'fingerprint':w.digest(encode(before)),
            'layout_sha':w.digest(encode(saved)),'auto_sha':w.digest(encode(auto)),
            'lifecycle_revision':profiles.get(project)['lifecycle_revision']}


def inventory():
    documents=[]
    for doc in catalog.rows(reconcile_records=False):
        path=catalog.bounded(doc['path']);raw=path.read_text('utf-8-sig');meta,body,_=k.split(raw)
        role,published,reason=classification(doc,meta)
        parts=PurePosixPath(doc['path']).parts
        owner=parts[2] if len(parts)>3 and parts[:2]==('科研知识库','项目') else doc.get('source_project')
        updates={'content_role':role,'global_knowledge':published}
        after=k.properties(raw,updates)
        documents.append({'id':doc['id'],'path':doc['path'],'title':doc['title'],'project':owner,
            'role':role,'global_knowledge':published,'reason':reason,'before_sha':w.digest(raw),'after_sha':w.digest(after),
            'body_sha':w.digest(body),'previous_metadata':{name:meta.get(name) for name in updates},
            'canvas_node':doc.get('canvas_node'),'selected_project':doc.get('project'),
            'archived':doc.get('archived'), 'needs_change':raw!=after})
    organizations=[_organization(p['project'],documents) for p in profiles.listing()]
    plan={'schema':SCHEMA,'created':w.now(),'documents':documents,'organizations':organizations}
    plan['id']=w.digest(encode({key:plan[key] for key in ('schema','documents','organizations')}))
    return plan


def _key(plan,identifier):return 'project-restructure:'+plan['id']+':'+identifier


def apply(plan):
    if plan.get('schema')!=SCHEMA:raise ValueError('归位清单版本不匹配。')
    store=Store();result={'completed':[],'conflicts':[],'organizations':[]}
    for row in plan['documents']:
        if not row['needs_change']:continue
        key=_key(plan,row['id']);receipt=store.cursor(key,{})
        if receipt.get('state')=='completed':result['completed'].append(row['id']);continue
        # Lifecycle and edit locks precede short SQLite receipt transactions.
        from contextlib import nullcontext
        lock=profiles.lifecycle_lock(row['project']) if row.get('project') and (w.KB/'项目'/row['project']).is_dir() else nullcontext()
        with lock,k.editing():
            path=catalog.bounded(row['path']);raw=path.read_text('utf-8-sig');sha=w.digest(raw)
            if sha==row['after_sha'] and receipt.get('state')=='pending':pass
            elif sha!=row['before_sha']:
                result['conflicts'].append({'id':row['id'],'reason':'原稿在清单生成后发生变化'});continue
            else:
                after=k.properties(raw,{'content_role':row['role'],'global_knowledge':row['global_knowledge']})
                if w.digest(after)!=row['after_sha'] or w.digest(k.split(after)[1])!=row['body_sha']:raise ValueError('归位差异超出元数据范围。')
                store.commit_page(key,[],{'state':'pending','before':row['before_sha'],'after':row['after_sha']})
                # Existing immutable version storage also supplies selective rollback.
                if row['path'].startswith('科研知识库/'):
                    k.persist(path,raw,after,w.KB.resolve())
                else:
                    backup=w.DATA/'正文历史'/row['id']/('restructure-'+plan['id'][:20]+'.md')
                    if not backup.exists():w.atomic_text(backup,raw)
                    with catalog.database().connection() as db:
                        db.execute('INSERT OR IGNORE INTO document_versions VALUES(?,?,?,?,?)',('restructure-'+plan['id'][:20]+'-'+row['id'],row['id'],backup.relative_to(w.DATA).as_posix(),row['before_sha'],w.now()))
                    w.atomic_text(path,after)
            store.commit_page(key,[],{'state':'completed','before':row['before_sha'],'after':row['after_sha']})
            result['completed'].append(row['id'])
    for org in plan['organizations']:
        project=org['project'];key=_key(plan,'organization:'+project)
        if store.cursor(key,{}).get('state')=='completed':continue
        with profiles.lifecycle_lock(project),k.editing():
            if store.cursor(key,{}).get('state')=='completed':continue
            before=store.cursor('project-knowledge:'+project,{'modules':{},'assignments':{}})
            if profiles.get(project)['lifecycle_revision']!=org['lifecycle_revision'] or w.digest(encode(before))!=org['fingerprint']:
                result['conflicts'].append({'id':project,'reason':'模块或项目生命周期已变化'});continue
            if w.digest(encode(store.cursor('project-canvas:'+project,{})))!=org['layout_sha'] or w.digest(encode(store.cursor('canvas-organization:'+project,{})))!=org['auto_sha']:
                result['conflicts'].append({'id':project,'reason':'旧知识图组织已变化，请重算模块'});continue
            with store.connection() as db:
                db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)',('project-knowledge:'+project,encode(org['after']),w.now()))
                db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)',(key,encode({'state':'completed'}),w.now()))
                store.log(db,'project.restructure',project,{'plan':plan['id']})
            result['organizations'].append(project)
    catalog.refresh()
    return result


def rollback(plan):
    """Revert only this receipt's unchanged result, never an entire database."""
    store=Store();restored=[];conflicts=[]
    with k.editing():
        for row in plan['documents']:
            key=_key(plan,row['id']);receipt=store.cursor(key,{})
            if receipt.get('state')!='completed':continue
            path=catalog.bounded(row['path']);raw=path.read_text('utf-8-sig')
            if w.digest(raw)!=row['after_sha']:conflicts.append(row['id']);continue
            # Restore exact old raw via the version copied by the existing writer.
            candidates=[]
            for base in (w.DATA/'正文历史'/row['id'],w.DATA/'编辑备份'):
                if base.exists():candidates.extend(base.rglob('*.md'))
            original=next((p.read_text('utf-8-sig') for p in candidates if w.digest(p.read_text('utf-8-sig'))==row['before_sha']),None)
            if original is None:conflicts.append(row['id']);continue
            w.atomic_text(path,original);store.commit_page(key,[],{**receipt,'state':'rolled_back'});restored.append(row['id'])
        for org in plan['organizations']:
            key=_key(plan,'organization:'+org['project'])
            if store.cursor(key,{}).get('state')!='completed':continue
            current=store.cursor('project-knowledge:'+org['project'],{})
            if current!=org['after']:conflicts.append(org['project']);continue
            store.commit_page('project-knowledge:'+org['project'],[],org['before']);store.commit_page(key,[],{'state':'rolled_back'})
    catalog.refresh()
    return {'restored':restored,'conflicts':conflicts}
