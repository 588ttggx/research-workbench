"""Project-scoped knowledge organization; all prose remains in originals."""
import copy
import json
import re
from urllib.parse import urlencode

import knowledge as k
import workflow as w
import workspace_catalog as catalog
import project_profiles as profiles
import material_roles
from research_store import Store,encode


def state(project):
    k.line_path(project,w.KB)
    return Store().cursor('project-knowledge:'+project,{'modules':{},'assignments':{}})


def owned(project,document):
    return (document.get('path') or '').startswith('科研知识库/项目/'+project+'/')


def current_scope(project,base,members,saved,selected_paper_ids=()):
    """Admit actual research references, not every old graph selection or project tag."""
    import project_tasks
    import project_stages
    included=set(saved.get('included_documents',[]));excluded=set(saved.get('excluded_documents',[]))
    candidates={i:d for i,d in base['documents'].items() if material_roles.knowledge(d) and
                (d.get('global_knowledge',True) or i in members['documents'] or i in included or owned(project,d))}
    reasons={i:'本人选入项目知识库' for i in included if i in candidates}
    papers=set(selected_paper_ids);seeds=[]
    path=k.line_path(project,w.KB).parent/'当前课题状态.md'
    state_id=catalog.identify(path.relative_to(w.ROOT.resolve()).as_posix())
    seeds.append(state_id)
    plan=profiles.get(project).get('plan_document_id')
    if plan:seeds.append(plan)
    for row in project_tasks.read(project)['items']:
        if row.get('removed') or row.get('replacement'):continue
        for ref in row.get('references',[]):
            kind,_,identifier=ref.get('material_id','').partition(':')
            if kind=='doc':seeds.append(identifier)
            elif kind=='paper':papers.add(identifier)
    for source in project_stages.folder(project).glob('STG-*.md'):
        try:meta,_,_=project_stages.parse(source.read_text('utf-8-sig'))
        except (ValueError,OSError):continue
        if meta.get('stage_removed') or meta.get('project')!=project:continue
        for ref in meta.get('stage_references',[]):
            kind,_,identifier=ref.get('material_id','').partition(':')
            if kind=='doc':seeds.append(identifier)
            elif kind=='paper':papers.add(identifier)
    # Follow process links from the current state/plan to their actual knowledge citations.
    # Stop at knowledge: its historical bibliography is not a request to import a project.
    seen=set()
    while seeds:
        identifier=seeds.pop()
        if identifier in seen:continue
        seen.add(identifier)
        doc=candidates.get(identifier) or members['documents'].get(identifier) or (base['documents'].get(identifier) if identifier==state_id else None)
        if not doc:continue
        papers.update(doc.get('paper_ids',[]))
        if identifier in candidates:
            reasons.setdefault(identifier,'当前方案、工作或节点引用')
        else:
            seeds.extend(ref['id'] for ref in doc.get('references',[]) if ref.get('link_type') not in {'navigation','history'})
    for identifier,doc in candidates.items():
        if '/知识笔记/' in doc['path'] and owned(project,doc):
            reasons.setdefault(identifier,'本项目新建或提炼的知识')
    for identifier in excluded:reasons.pop(identifier,None)
    for i in reasons:papers.update(candidates[i].get('paper_ids',[]))
    # A selected paper's reading card is the same evidence, with its reading range retained.
    for i,doc in candidates.items():
        reading_card=doc.get('kb_path','').startswith('文献/阅读卡片/')
        if reading_card and i not in reasons and i not in excluded and set(doc.get('paper_ids',[]))&papers:
            reasons[i]='当前研究引用文献的阅读笔记'
    documents=[{**doc,'knowledge_scope_reason':reasons[i],'project_owned':owned(project,doc)}
               for i,doc in candidates.items() if i in reasons]
    return documents,list(candidates.values()),papers


def view(project):
    import project_materials as materials
    import project_canvas as canvas
    base=materials.source_snapshot(project,readonly=True);members=materials.snapshot(project,base=base)
    saved=state(project)
    canvas_state=canvas.state(project)
    selected_paper_ids=canvas_state.get('papers',[])
    documents,candidates,paper_ids=current_scope(project,base,members,saved,selected_paper_ids)
    known={d['id'] for d in documents}
    modules=sorted((dict(m) for m in saved['modules'].values()),key=lambda m:(m.get('order',0),m['id']))
    for module in modules:
        current_sources=_review_sources(saved,module['id'],documents)
        module['review_stale']=bool(module.get('review_document_id') and module.get('review_sources',{})!=current_sources)
        module['source_signature']=w.digest(encode(current_sources))
    assignments={identifier:[m for m in ms if m in saved['modules']] for identifier,ms in saved['assignments'].items() if identifier in known}
    selected={identifier for identifier,ms in assignments.items() if ms}
    records=[d for d in base['documents'].values() if d.get('source_project')==project or d.get('project')==project and d['path'].startswith('科研知识库/项目/'+project+'/')]
    records=[d for d in records if d.get('content_role') in {'project_process','unclassified'} and not d.get('stage_removed')]
    picker_fields=('id','title','display_title','source_project','global_knowledge')
    return {'project':project,'modules':modules,'assignments':assignments,'documents':documents,
            'candidates':[{field:d.get(field) for field in picker_fields} for d in candidates],
            'uncategorized':[d['id'] for d in documents if d['id'] not in selected],
            'records':records,'references':materials.reference_documents(project,base=base,members=members),
            'history':list(members['history'].values()),'papers':[{**base['papers'][pid],**members['papers'].get(pid,{'reasons':['项目知识引用']})}
                for pid in sorted(paper_ids) if pid in base['papers']],
            'paper_candidates':[{key:p.get(key) for key in ('id','title','display_title','authors','year','doi','availability')} for p in base['papers'].values()],'selected_paper_ids':selected_paper_ids,
            'paper_fingerprint':canvas.fingerprint(canvas_state),
            'fingerprint':w.digest(encode(saved)),'lifecycle_revision':profiles.get(project)['lifecycle_revision']}


def _review_sources(saved,identifier,documents):
    review=saved['modules'][identifier].get('review_document_id')
    return {d['id']:d['sha'] for d in documents if d['id']!=review and identifier in saved['assignments'].get(d['id'],[])}


def _request(data):
    request=data.get('request_id')
    if not isinstance(request,str) or not re.fullmatch(r'[\w.-]{1,200}',request):raise ValueError('请提供有效request_id。')
    return request


def _modules(saved,ids):
    if not isinstance(ids,list) or len(ids)>100 or any(not isinstance(i,str) or i not in saved['modules'] for i in ids):raise ValueError('请选择本项目已有模块。')
    return list(dict.fromkeys(ids))


def change(data):
    project=data.get('project') or '山药';request=_request(data);store=Store();key='knowledge-operation:'+project+':'+request
    signature=w.digest(encode({n:v for n,v in data.items() if n not in {'fingerprint','paper_fingerprint','lifecycle_revision'}}))
    with profiles.lifecycle_lock(project),k.editing():
        profile=profiles.get(project)
        if profile['archived']:raise ValueError('项目已归档，知识组织只读。')
        if data.get('lifecycle_revision',profile['lifecycle_revision'])!=profile['lifecycle_revision']:raise ValueError('项目状态已变化。')
        receipt=store.cursor(key,{})
        if receipt:
            if receipt['payload_hash']!=signature:raise ValueError('同一request_id不能用于不同内容。')
            return {**view(project),'result_id':receipt.get('result_id')}
        before=state(project)
        if data.get('fingerprint')!=w.digest(encode(before)):raise ValueError('知识模块已变化，请重新读取；输入保留。')
        saved=copy.deepcopy(before);modules=saved['modules'];op=data.get('op');identifier=data.get('id');result_id=identifier;canvas_update=None
        if op in {'add_papers','remove_papers'}:
            import project_canvas as canvas
            import project_materials as materials
            canvas_before=canvas.state(project)
            if data.get('paper_fingerprint')!=canvas.fingerprint(canvas_before):raise ValueError('项目文献或图已变化，请重新读取；选择保留。')
            canvas_update=copy.deepcopy(canvas_before)
            available=materials.source_snapshot(project,readonly=True)['papers']
            canvas.select_papers(canvas_update,data.get('paper_ids'),'add' if op=='add_papers' else 'remove',available)
            canvas_update['revision']=canvas_update.get('revision',0)+1
        elif op in {'select','set_selection','change_selection'}:
            current=view(project);known={d['id'] for d in current['candidates']}
            included=set(saved.get('included_documents',[]));excluded=set(saved.get('excluded_documents',[]))
            def selected_ids(value):
                if not isinstance(value,list) or any(not isinstance(i,str) or i not in known for i in value):raise ValueError('请选择本项目可用知识。')
                return set(value)
            if op=='change_selection':
                added=selected_ids(data.get('add_ids'));removed=selected_ids(data.get('remove_ids'))
                if added&removed:raise ValueError('同一份知识不能同时选入和移出。')
            else:
                chosen=selected_ids(data.get('document_ids'));selected=data.get('selected')
                if op=='set_selection':added=chosen;removed=known-chosen
                elif not chosen or type(selected) is not bool:raise ValueError('请选择本项目可用知识。')
                elif selected:added=chosen;removed=set()
                else:added=set();removed=chosen
            saved['included_documents']=sorted((included|added)-removed)
            saved['excluded_documents']=sorted((excluded|removed)-added)
        elif op=='share':
            document=next((d for d in view(project)['documents'] if d['id']==identifier),None)
            if not document or not owned(project,document):raise ValueError('请从原稿所属项目调整全局可见性。')
            catalog.update_metadata({'id':identifier,'fingerprint':data.get('document_fingerprint'),
                'global_knowledge':data.get('global_knowledge'),'lifecycle_revision':profile['lifecycle_revision']})
        elif op in {'create_module','update_module'}:
            title=data.get('title')
            if not isinstance(title,str) or not title.strip() or len(title)>200 or any(c in title for c in '\n\r\x00'):raise ValueError('请填写200字以内的模块名称。')
            parent=data.get('parent_id','')
            if parent and parent not in modules:raise ValueError('上级模块不存在。')
            if op=='create_module':identifier='MOD-'+w.digest(project+':'+request)[:24];result_id=identifier
            elif identifier not in modules:raise ValueError('模块不存在。')
            if any(m['id']!=identifier and m['title']==title.strip() and m.get('parent_id','')==parent for m in modules.values()):raise ValueError('同级模块名称已存在。')
            order=data.get('order',modules.get(identifier,{}).get('order',len(modules)))
            if type(order) is not int or order<0:raise ValueError('模块顺序无效。')
            modules[identifier]={**modules.get(identifier,{}),'id':identifier,'title':title.strip(),'parent_id':parent,'order':order}
            for current in modules:
                seen=set()
                while current:
                    if current in seen:raise ValueError('模块层级不能形成循环。')
                    seen.add(current);current=modules[current].get('parent_id','')
        elif op=='remove_module':
            if identifier not in modules:raise ValueError('模块不存在。')
            parent=modules[identifier].get('parent_id','')
            for module in modules.values():
                if module.get('parent_id')==identifier:module['parent_id']=parent
            del modules[identifier]
            saved['assignments']={doc:[m for m in ms if m!=identifier] for doc,ms in saved['assignments'].items()}
        elif op in {'assign','bind_summary'}:
            current=view(project);known={d['id'] for d in current['documents']}
            if op=='assign':
                selected=data.get('document_ids');chosen=_modules(saved,data.get('module_ids',[]))
                if not isinstance(selected,list) or any(i not in known for i in selected):raise ValueError('请选择本项目知识笔记。')
                for doc in selected:saved['assignments'][doc]=chosen
            else:
                if identifier not in modules:raise ValueError('模块不存在。')
                doc=data.get('document_id')
                if doc is not None and doc not in known:raise ValueError('请选择本项目知识稿作为综述。')
                modules[identifier]['review_document_id']=doc
                modules[identifier]['review_sources']=_review_sources(saved,identifier,current['documents'])
        elif op=='acknowledge_summary':
            if identifier not in modules:raise ValueError('模块不存在。')
            modules[identifier]['review_sources']=_review_sources(saved,identifier,view(project)['documents'])
        else:raise ValueError('知识组织操作无效。')
        with store.connection() as db:
            if canvas_update is not None:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT value FROM cursors WHERE key=?',(canvas.key(project),)).fetchone()
                actual=json.loads(row['value']) if row else canvas.state_default()
                if canvas.fingerprint(actual)!=data.get('paper_fingerprint'):raise ValueError('项目文献或图已变化，请重新读取；选择保留。')
                db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)',(canvas.key(project),encode(canvas_update),w.now()))
            db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)',('project-knowledge:'+project,encode(saved),w.now()))
            db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)',(key,encode({'payload_hash':signature,'result_id':result_id}),w.now()))
            store.log(db,'project.knowledge_'+op,project,{'module_id':result_id})
    return {**view(project),'result_id':result_id}


def _source(project,data):
    identifier=data.get('source_document_id')
    if not identifier:return None
    from project_materials import snapshot,source_snapshot
    members=snapshot(project,base=source_snapshot(project,readonly=True))
    doc=members['documents'].get(identifier) or members['history'].get(identifier)
    if not doc:raise ValueError('知识来源未选入本项目。')
    raw=catalog.bounded(doc['path']).read_text('utf-8-sig');meta,body,_=k.split(raw)
    source={'document_id':identifier,'document_sha':w.digest(body.rstrip()),'stage_id':meta.get('id') if meta.get('record_type')=='Stage' else None,
            'block_id':data.get('block_id'),'title':doc['title']}
    if meta.get('record_type')=='Stage':
        import project_stages as stages
        _,_,entries=stages.parse(raw);entry=next((e for e in stages.active_entries(entries) if e['id']==data.get('block_id')),None)
        if entry is None:raise ValueError('来源记录已移除或不存在，请重新选择。')
        if data.get('block_sha')!=entry['sha']:raise ValueError('来源记录已变化，请刷新提炼预览；输入保留。')
        source['block_sha']=entry['sha']
    else:
        if data.get('block_sha',source['document_sha'])!=source['document_sha']:raise ValueError('来源正文已变化，请重新核对。')
        source['block_id']=None;source['block_sha']=source['document_sha']
    with catalog.database().connection() as db:
        db.execute('INSERT OR IGNORE INTO document_source_snapshots VALUES(?,?,?,?)',(identifier,source['document_sha'],body,w.now()))
    return source


def extract(data):
    project=data.get('project') or '山药';request=_request(data);store=Store();key='knowledge-write:'+project+':'+request
    signature=w.digest(encode({n:v for n,v in data.items() if n not in {'fingerprint','lifecycle_revision'}}))
    with profiles.lifecycle_lock(project),k.editing():
        profile=profiles.get(project)
        if profile['archived']:raise ValueError('项目已归档，不能新增知识。')
        if data.get('lifecycle_revision',profile['lifecycle_revision'])!=profile['lifecycle_revision']:raise ValueError('项目状态已变化。')
        old=store.cursor(key,{})
        if old and old['payload_hash']!=signature:raise ValueError('同一request_id不能用于不同内容。')
        note_id='KN-'+w.digest(project+':'+request)[:24]
        path=k.line_path(project,w.KB).parent/'知识笔记'/(note_id+'.md')
        doc_id=catalog.identify(path.relative_to(w.ROOT.resolve()).as_posix())
        if old.get('state')=='completed':return catalog.detail(doc_id)
        saved=state(project);chosen=_modules(saved,data.get('module_ids',[]))
        if data.get('summary_module_id') and data['summary_module_id'] not in saved['modules']:raise ValueError('综述模块不存在。')
        if old.get('state')=='pending' and path.exists():
            if w.digest(path.read_text('utf-8-sig'))!=old['after']:raise ValueError('知识原稿在中断后又被修改，未覆盖。')
            chosen=old['module_ids']
        else:
            if data.get('draft_id'):
                from project_drafts import check_draft
                if data.get('summary_module_id'):
                    check_draft({**data,'module_id':data['summary_module_id']},'overview')
                else:
                    check_draft(data,'extract')
            if data.get('summary_module_id') and data.get('source_signature'):
                actual=w.digest(encode(_review_sources(saved,data['summary_module_id'],view(project)['documents'])))
                if actual!=data['source_signature']:raise ValueError('模块资料已变化，请刷新后核对综述预览。')
            title=data.get('title');body=data.get('body')
            if not isinstance(title,str) or not 1<=len(title.strip())<=200 or '\n' in title:raise ValueError('请填写有效知识标题。')
            if not isinstance(body,str) or not body.strip() or len(body)>100000 or k.FRONT.match(body):raise ValueError('请填写10万字以内的知识正文。')
            published=data.get('global_knowledge',False)
            if type(published) is not bool:raise ValueError('全局关联选择无效。')
            source=_source(project,data);sources=[source] if source else []
            if source:
                query=urlencode({'project':project,'view':'progress','stage':source['stage_id'],'entry':source['block_id']}) if source['stage_id'] else None
                target='#projects?'+query if query else '#document?'+urlencode({'id':source['document_id']})
                body=body.rstrip()+'\n\n## 来源记录\n\n['+source['title'].replace('[','').replace(']','')+']('+target+')\n'
            raw=k.properties('# '+title.strip()+'\n\n'+body.rstrip()+'\n',{'id':note_id,'type':'personal_note','title':title.strip(),'project':project,'source_project':project,
                'content_role':'knowledge','global_knowledge':published,'knowledge_sources':sources,'created_at':w.now(),'creation_request_id':request})
            old={'payload_hash':signature,'state':'pending','after':w.digest(raw),'module_ids':chosen,'document_id':doc_id}
            store.commit_page(key,[],old)
            if path.exists():raise ValueError('知识原稿已存在但没有匹配回执，未覆盖。')
            k.persist(path,'',raw,w.KB.resolve())
        saved['assignments'][doc_id]=chosen
        if data.get('summary_module_id'):
            module=data['summary_module_id']
            if module not in saved['modules']:raise ValueError('综述模块不存在。')
            saved['modules'][module]['review_document_id']=doc_id
            saved['modules'][module]['review_sources']=_review_sources(saved,module,view(project)['documents'])
        with store.connection() as db:
            db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)',('project-knowledge:'+project,encode(saved),w.now()))
            db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)',(key,encode({**old,'state':'completed'}),w.now()))
            store.log(db,'project.knowledge_extract',project,{'document_id':doc_id})
        catalog.refresh();doc=catalog.detail(doc_id);catalog.notify_change(doc)
        return doc


def source_status(identifier):
    doc=catalog.detail(identifier);result=[]
    for source in doc.get('knowledge_sources',[]):
        row={**source,'changed':False,'missing':False}
        try:
            original=catalog.detail(source['document_id']);raw=catalog.bounded(original['path']).read_text('utf-8-sig')
            if source.get('block_id'):
                from project_stages import parse,active_entries
                meta,_,entries=parse(raw)
                entry=None if meta.get('stage_removed') else next((e for e in active_entries(entries) if e['id']==source['block_id']),None)
                row.update(missing=entry is None,changed=entry is None or entry['sha']!=source['block_sha'])
            else:row['changed']=w.digest(k.split(raw)[1].rstrip())!=source['document_sha']
        except (ValueError,OSError):row.update(changed=True,missing=True)
        result.append(row)
    return result


def source_version(identifier,sha):
    if not isinstance(sha,str) or not re.fullmatch(r'[a-f0-9]{64}',sha):raise ValueError('来源版本无效。')
    with catalog.database().connection() as db:
        row=db.execute('SELECT body FROM document_source_snapshots WHERE document=? AND sha=?',(identifier,sha)).fetchone()
    if not row:raise ValueError('当时来源版本暂不可读，不能以当前稿代替。')
    return {'id':identifier,'sha':sha,'body':row['body']}


def save_summary(data):
    project=data.get('project') or '山药';request=_request(data);store=Store();key='knowledge-summary:'+project+':'+request
    signature=w.digest(encode({n:v for n,v in data.items() if n not in {'fingerprint','lifecycle_revision'}}))
    with profiles.lifecycle_lock(project):
        if profiles.get(project)['archived']:raise ValueError('项目已归档。')
        receipt=store.cursor(key,{})
        if receipt and receipt['payload_hash']!=signature:raise ValueError('同一request_id不能用于不同内容。')
        if receipt.get('state')=='completed':return catalog.detail(data['id'])
        saved=state(project);module=saved['modules'].get(data.get('module_id'))
        if not module or module.get('review_document_id')!=data.get('id'):raise ValueError('模块综述绑定已变化，请重新读取。')
        observed_sources=_review_sources(saved,module['id'],view(project)['documents'])
        expected=w.digest(encode(observed_sources))
        if data.get('source_signature')!=expected:raise ValueError('模块资料已变化，输入保留，请重新核对。')
        if data.get('draft_id'):
            from project_drafts import check_draft
            check_draft(data,'overview')
        doc=catalog.detail(data['id'])
        if not owned(project,doc):raise ValueError('这是引用的外来综述，请回来源原稿编辑，或建立本项目综述。')
        if not isinstance(data.get('title'),str) or not data['title'].strip() or not isinstance(data.get('body'),str) or not data['body'].strip():raise ValueError('请填写综述标题与正文。')
        raw=catalog.bounded(doc['path']).read_text('utf-8-sig')
        if receipt.get('state')=='pending' and w.digest(raw)==receipt['after']:
            result=doc
        else:
            if receipt.get('state')=='pending' and w.digest(raw)!=receipt['before']:raise ValueError('综述在中断后已被修改，未覆盖。')
            title=data['title'].strip();body=data['body']
            body=re.sub(r'(?m)^# [^\n]*',lambda _:'# '+title,body,count=1) if re.search(r'(?m)^# ',body) else '# '+title+'\n\n'+body
            meta,_,front=k.split(raw)
            after=k.properties((raw[:front.end()] if front else '')+body.rstrip()+'\n',{'title':title})
            if meta.get('standard_template') is True:after=k.properties(after,{'standard_template':False})
            receipt={'state':'pending','payload_hash':signature,'before':w.digest(raw),'after':w.digest(after)}
            store.commit_page(key,[],receipt)
            result=catalog.save(data)
        with k.editing():
            current=state(project)
            if current['modules'].get(module['id'],{}).get('review_document_id')!=data['id']:raise ValueError('正文已保存，综述绑定又有变化，请重新查看。')
            current['modules'][module['id']]['review_sources']=observed_sources
            Store().commit_page('project-knowledge:'+project,[],current)
            store.commit_page(key,[],{**receipt,'state':'completed'})
        return result
