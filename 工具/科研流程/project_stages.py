"""Project stages: one Markdown original, shared work, recoverable organization."""
import copy
import json
import math
import re
from pathlib import Path

import knowledge as k
import workflow as w
import project_profiles as profiles
from research_store import Store, encode

STATES=('未开始','进行中','受阻','暂缓','已完成')
PROBLEM_STATES=('未处理','处理中','已解决','暂缓')
KINDS={'goal','work','idea','problem','attempt','problem_summary','stage_summary'}
BLOCK=re.compile(r'(?m)^<!-- stage:block:start (\{[^\n]*\}) -->\r?\n([\s\S]*?)^<!-- stage:block:end ([\w.-]+) -->[ \t]*(?:\r?\n|$)')
ID=re.compile(r'STG-[a-f0-9]{24}')


def folder(project):
    return k.line_path(project,w.KB).parent/'进展节点'


def path_for(project,identifier):
    if not isinstance(identifier,str) or not ID.fullmatch(identifier):raise ValueError('阶段身份无效。')
    return folder(project)/(identifier+'.md')


def parse(raw):
    meta,body,_=k.split(raw)
    if meta.get('record_type')!='Stage' or meta.get('stage_schema')!=1:raise ValueError('阶段原稿版本或格式无效，请核对原稿。')
    entries=[];seen=set()
    for match in BLOCK.finditer(body):
        try:entry=json.loads(match[1])
        except (ValueError,TypeError):raise ValueError('阶段记录标记损坏，原稿未覆盖。')
        identifier=entry.get('id')
        if not isinstance(identifier,str) or not re.fullmatch(r'[\w.-]+',identifier) or identifier!=match[3] or identifier in seen or entry.get('kind') not in KINDS:
            raise ValueError('阶段记录标记重复或错配，原稿未覆盖。')
        seen.add(identifier);text=match[2].rstrip('\r\n')
        entries.append({**entry,'body':text,'sha':w.digest(text.rstrip()),'_start':match.start(),'_end':match.end()})
    if body.count('<!-- stage:block:start ')!=len(entries) or body.count('<!-- stage:block:end ')!=len(entries):
        raise ValueError('阶段记录标记不完整，原稿未覆盖。')
    by_id={e['id']:e for e in entries}
    if not {'goal','stage-summary'}<=seen:raise ValueError('阶段固定区块缺失，原稿未覆盖。')
    for entry in entries:
        parent=entry.get('parent_id')
        if entry['kind'] in {'attempt','problem_summary'} and (parent not in by_id or by_id[parent]['kind']!='problem'):
            raise ValueError('尝试或总结缺少所属问题。')
        if entry['kind']=='problem' and entry.get('status','未处理') not in PROBLEM_STATES:raise ValueError('问题状态无效。')
    if meta.get('stage_status','未开始') not in STATES:raise ValueError('阶段状态无效。')
    return meta,body,entries


def active_entries(entries):
    removed={e['id'] for e in entries if e.get('removed')}
    return [e for e in entries if not e.get('removed') and e.get('parent_id') not in removed]


def active_body(raw):
    meta,body,entries=parse(raw);active={e['id'] for e in active_entries(entries)}
    for entry in reversed(entries):
        replacement=entry['body']+'\n' if entry['id'] in active else ''
        body=body[:entry['_start']]+replacement+body[entry['_end']:]
    return '' if meta.get('stage_removed') else body


def _block(entry):
    metadata={key:value for key,value in entry.items() if key not in {'body','sha'} and not key.startswith('_')}
    return '<!-- stage:block:start '+json.dumps(metadata,ensure_ascii=False,separators=(',',':'))+' -->\n'+entry.get('body','').rstrip()+'\n<!-- stage:block:end '+entry['id']+' -->\n'


def _entry(entries,identifier):
    value=next((e for e in entries if e['id']==identifier),None)
    if value is None:raise ValueError('这条阶段记录不存在，请重新读取。')
    return value


def detail(project,identifier,*,work=None):
    path=path_for(project,identifier)
    if not path.is_file():raise ValueError('阶段原稿不存在。')
    raw=path.read_text('utf-8-sig');meta,body,entries=parse(raw)
    if meta.get('id')!=identifier or meta.get('project')!=project:raise ValueError('阶段所属项目不一致。')
    import workspace_catalog as catalog
    import project_tasks
    visible=active_entries(entries)
    rows=project_tasks.read(project)['items'] if work is None else work
    linked=[r for r in rows if identifier in r.get('stage_ids',[]) and not r.get('removed') and not r.get('replacement')]
    return {'id':identifier,'project':project,'title':meta.get('title',identifier),'stage_status':meta.get('stage_status','未开始'),
            'removed':bool(meta.get('stage_removed')),'goal':_entry(entries,'goal')['body'],
            'summary':_entry(entries,'stage-summary')['body'],'path':path.relative_to(w.KB.resolve()).as_posix(),
            'document_id':catalog.identify(path.relative_to(w.ROOT.resolve()).as_posix()),'fingerprint':w.digest(raw),
            'raw':raw,'entries':[{key:value for key,value in e.items() if not key.startswith('_')} for e in entries],
            'tasks':[r for r in linked if r['item_type']=='plan'],
            'work_items':[r for r in linked if r['item_type']=='work'],
            'references':meta.get('stage_references',[]),'updated':meta.get('updated_at',''),
            'open_problems':sum(e['kind']=='problem' and e.get('status')!='已解决' for e in visible),
            'lifecycle_revision':profiles.get(project)['lifecycle_revision']}


def _state(project):
    return Store().cursor('project-progress:'+project,{'mainline':[],'branches':[],'links':[],'positions':{}})


def progress(project,include_removed=False):
    path=folder(project);stages=[];errors=[]
    import project_tasks
    work=project_tasks.read(project)['items']
    for source in sorted(path.glob('STG-*.md')) if path.exists() else []:
        try:
            d=detail(project,source.stem,work=work)
            stages.append({key:value for key,value in d.items() if key not in {'raw','entries','tasks','work_items','references'}}|
                          {'task_count':len(d['tasks']),'done_count':sum(x['done'] for x in d['tasks']),
                           'work_count':len(d['work_items']),'current_work_count':sum(not x['done'] for x in d['work_items'])})
        except (ValueError,OSError,UnicodeError) as error:errors.append({'path':source.name,'error':str(error)})
    state=_state(project);known={s['id'] for s in stages};placed=set(state.get('mainline',[]))
    for branch in state.get('branches',[]):placed.update(branch['stage_ids'])
    mainline=[x for x in state.get('mainline',[]) if x in known]+[s['id'] for s in stages if s['id'] not in placed]
    visible=[s for s in stages if include_removed or not s['removed']]
    return {**state,'mainline':mainline,'project':project,'stages':visible,'history':[s for s in stages if s['removed']],
            'errors':errors,'fingerprint':w.digest(encode(state)),'lifecycle_revision':profiles.get(project)['lifecycle_revision']}


def _finish(store,key,intent):
    project=intent['project'];identifier=intent['id'];path=path_for(project,identifier)
    raw=path.read_text('utf-8-sig');meta,body,_=parse(raw)
    node=store.node(identifier)
    data={'title':meta['title'],'document_sha256':w.digest(body.rstrip()),'stage_status':meta['stage_status'],'removed':bool(meta.get('stage_removed'))}
    if not node or node.get('data')!=data:
        store.put_node(identifier,'Stage','Markdown',project=project,uri=path.relative_to(w.KB.resolve()).as_posix(),status='DRAFT',data=data)
    if intent['op']=='create':
        state=_state(project);placed=set(state.get('mainline',[]))
        for branch in state.get('branches',[]):placed.update(branch['stage_ids'])
        if identifier not in placed:
            state.setdefault('mainline',[]).append(identifier);store.commit_page('project-progress:'+project,[],state)
    store.commit_page(key,[],{**intent,'state':'completed'})
    with store.connection() as db:store.log(db,'project.stage_'+intent['op'],project,{'stage_id':identifier,'entry_id':intent.get('result_id')})
    import workspace_catalog as catalog
    try:catalog.notify_change(path)
    except (OSError,ValueError):
        # The original is committed. The same durable receipt records pending notification.
        store.commit_page(key,[],{**intent,'state':'completed','notification_pending':True})


def _recover(project,store):
    prefix='stage-write:'+project+':'
    with store.connection() as db:
        pending=[(row[0],json.loads(row[1])) for row in db.execute('SELECT key,value FROM cursors WHERE substr(key,1,?)=?',(len(prefix),prefix))]
    for key,intent in pending:
        if intent.get('state')=='completed' and intent.get('notification_pending'):
            import workspace_catalog as catalog
            try:
                catalog.notify_change(path_for(project,intent['id']))
                store.commit_page(key,[],{**intent,'notification_pending':False})
            except (OSError,ValueError):pass
            continue
        if intent.get('state')!='pending':continue
        path=path_for(project,intent['id']);raw=path.read_text('utf-8-sig') if path.exists() else ''
        if w.digest(raw)==intent['after']:_finish(store,key,intent)
        elif w.digest(raw)==intent['before']:store.commit_page(key,[],{**intent,'state':'retryable'})
        else:raise ValueError('有阶段操作尚未完成且原稿已再次变化，请核对历史，未覆盖新稿。')


def _text(value,label,limit=100000,empty=True):
    if not isinstance(value,str) or len(value)>limit or '\x00' in value or '<!-- stage:block:' in value or not empty and not value.strip():
        raise ValueError(label+'无效或超过长度限制。')
    return value


def change(data):
    project=data.get('project') or '山药';op=data.get('op');request=data.get('request_id')
    if not isinstance(request,str) or not re.fullmatch(r'[\w.-]{1,200}',request):raise ValueError('请提供有效request_id。')
    signature=w.digest(encode({key:value for key,value in data.items() if key not in {'fingerprint','lifecycle_revision'}}))
    key='stage-write:'+project+':'+request;store=Store()
    with profiles.lifecycle_lock(project),k.editing():
        profile=profiles.get(project)
        if profile['archived']:raise ValueError('项目已归档，阶段只读。')
        if data.get('lifecycle_revision',profile['lifecycle_revision'])!=profile['lifecycle_revision']:raise ValueError('项目状态已变化，请刷新。')
        _recover(project,store);old=store.cursor(key,{})
        if old and old.get('payload_hash')!=signature:raise ValueError('同一request_id不能用于不同内容。')
        if old.get('state')=='completed':return {**detail(project,old['id']),'result_id':old.get('result_id'),'reused':True}
        stamp=old.get('stamp') or w.now()
        identifier=data.get('id') if op!='create' else 'STG-'+w.digest(project+':'+request)[:24]
        path=path_for(project,identifier);before=path.read_text('utf-8-sig') if path.exists() else '';result_id=None
        if op=='create':
            if data.get('draft_id'):
                from project_drafts import check_draft
                check_draft({'project':project,'draft_id':data['draft_id'],'stage_id':data.get('draft_stage_id')},'stages')
            if before:raise ValueError('阶段已存在，请核对操作回执。')
            if data.get('fingerprint')!=progress(project)['fingerprint']:raise ValueError('阶段组织已变化，请重新读取后创建。')
            title=_text(data.get('title'),'阶段名称',200,False).strip()
            if '\n' in title:raise ValueError('阶段名称须为单行。')
            goal=_text(data.get('goal',''),'阶段目标')
            body='# '+title+'\n\n## 阶段目标\n\n'+_block({'id':'goal','kind':'goal','body':goal})
            body+='\n## 工作记录\n\n## 想法\n\n## 问题与尝试\n\n## 阶段总结\n\n'+_block({'id':'stage-summary','kind':'stage_summary','body':''})+'\n## 引用资料\n'
            after=k.properties(body,{'id':identifier,'type':'research_record','record_type':'Stage','stage_schema':1,'project':project,
                'title':title,'stage_status':'未开始','content_role':'project_process','global_knowledge':False,'created_at':stamp,'updated_at':stamp})
        else:
            if not before:raise ValueError('阶段不存在。')
            if data.get('fingerprint')!=w.digest(before):raise ValueError('阶段已在其他窗口更新，请重新读取后合并；输入未覆盖原稿。')
            meta,body,entries=parse(before);fields=data.get('fields',{})
            if not isinstance(fields,dict):raise ValueError('阶段字段无效。')
            if meta.get('stage_removed') and op!='restore':raise ValueError('阶段已移除，请先恢复。')
            after=before
            if op=='update':
                allowed={'title','goal','summary','stage_status','references'}
                if set(fields)-allowed:raise ValueError('阶段字段无效。')
                updates={}
                if 'title' in fields:
                    title=_text(fields['title'],'阶段名称',200,False).strip()
                    if '\n' in title:raise ValueError('阶段名称须为单行。')
                    updates['title']=title;body=re.sub(r'(?m)^# [^\n]*',lambda _:'# '+title,body,count=1)
                    _,_,entries=parse(k.properties(body,meta))
                for name,block_id in [('goal','goal'),('summary','stage-summary')]:
                    if name in fields:
                        e=_entry(entries,block_id);e={**e,'body':_text(fields[name],name)}
                        body=body[:e['_start']]+_block(e)+body[e['_end']:]
                        _,_,entries=parse(k.properties(body,meta))
                if 'stage_status' in fields:
                    if fields['stage_status'] not in STATES:raise ValueError('阶段状态无效。')
                    updates['stage_status']=fields['stage_status']
                if 'references' in fields:
                    from project_tasks import _apply_fields
                    _apply_fields({}, {'references':meta.get('stage_references',[])}, {'references':fields['references']}, project)
                    updates['stage_references']=fields['references']
                    updates['paper_ids']=[r['material_id'][6:] for r in fields['references'] if r['material_id'].startswith('paper:')]
                after=k.properties(body,{**meta,**updates})
            elif op=='save_problem':
                if set(fields)-{'title','body','solution'}:raise ValueError('问题字段无效。')
                problem=copy.deepcopy(_entry(entries,data['entry_id'])) if data.get('entry_id') else None
                if problem and (problem['kind']!='problem' or problem.get('removed')):raise ValueError('请选择活动问题。')
                result_id=problem['id'] if problem else 'ENTRY-'+w.digest(project+':'+request)[:24]
                current=problem or {'id':result_id,'kind':'problem','parent_id':None,'created_at':stamp,'removed':False,'status':'未处理'}
                current={**current,'title':_text(fields.get('title',current.get('title','')),'问题标题',200),
                         'body':_text(fields.get('body',current.get('body','')),'问题描述'),'updated_at':stamp}
                current.setdefault('status','未处理')
                solution=next((e for e in entries if e['kind']=='problem_summary' and e.get('parent_id')==result_id and not e.get('removed')),None)
                text=_text(fields.get('solution',solution['body'] if solution else ''),'解决办法')
                solution_block=None
                if solution or text:
                    solution_block=_block({**(solution or {'id':'ENTRY-'+w.digest(project+':'+request+':solution')[:24],
                        'kind':'problem_summary','parent_id':result_id,'title':'解决办法','created_at':stamp,'removed':False}),
                        'body':text,'updated_at':stamp})
                if problem:
                    replacements=[(problem['_start'],problem['_end'],_block(current)+(solution_block if solution_block and not solution else ''))]
                    if solution:replacements.append((solution['_start'],solution['_end'],solution_block))
                    for start,end,replacement in sorted(replacements,reverse=True):body=body[:start]+replacement+body[end:]
                else:
                    heading='## 问题与尝试\n';position=body.find(heading)
                    if position<0:raise ValueError('阶段分区缺失，请核对原稿。')
                    next_heading=body.find('\n## ',position+len(heading));position=len(body) if next_heading<0 else next_heading+1
                    body=body[:position]+_block(current)+(solution_block or '')+'\n'+body[position:]
                after=k.properties(body,meta)
            elif op=='add_entry':
                kind=fields.get('kind')
                if kind not in {'work','idea','problem','attempt','problem_summary'}:raise ValueError('记录类型无效。')
                parent=fields.get('parent_id')
                if kind in {'attempt','problem_summary'}:
                    p=_entry(entries,parent)
                    if p['kind']!='problem' or p.get('removed'):raise ValueError('请选择活动问题。')
                    if kind=='problem_summary' and any(e['kind']==kind and e.get('parent_id')==parent and not e.get('removed') for e in entries):raise ValueError('问题已有总结，请编辑现有总结。')
                result_id='ENTRY-'+w.digest(project+':'+request)[:24]
                entry={'id':result_id,'kind':kind,'parent_id':parent,'title':_text(fields.get('title',''),'记录标题',200),
                       'body':_text(fields.get('body',''),'记录正文'),'created_at':stamp,'updated_at':stamp,'removed':False}
                if kind=='problem':entry['status']='未处理'
                section={'work':'工作记录','idea':'想法'}.get(kind,'问题与尝试')
                heading='## '+section+'\n';position=body.find(heading)
                if position<0:raise ValueError('阶段分区缺失，请核对原稿。')
                next_heading=body.find('\n## ',position+len(heading));position=len(body) if next_heading<0 else next_heading+1
                body=body[:position]+_block(entry)+'\n'+body[position:];after=k.properties(body,meta)
            elif op in {'update_entry','remove_entry','restore_entry'}:
                entry=copy.deepcopy(_entry(entries,data.get('entry_id')));result_id=entry['id']
                if entry['id'] in {'goal','stage-summary'} and op!='update_entry':raise ValueError('固定分区保留，请编辑内容。')
                if op=='update_entry':
                    if set(fields)-{'title','body','status'}:raise ValueError('记录字段无效。')
                    for name in ('title','body'):
                        if name in fields:entry[name]=_text(fields[name],name,200 if name=='title' else 100000)
                    if 'status' in fields:
                        if entry['kind']!='problem' or fields['status'] not in PROBLEM_STATES:raise ValueError('问题状态无效。')
                        entry['status']=fields['status']
                else:
                    if op=='restore_entry' and entry['kind']=='problem_summary' and any(e['kind']=='problem_summary' and e['id']!=entry['id'] and e.get('parent_id')==entry.get('parent_id') and not e.get('removed') for e in entries):
                        raise ValueError('已有活动解决总结；请先移除或合并当前总结，再恢复旧总结。')
                    entry['removed']=op=='remove_entry'
                entry['updated_at']=stamp;body=body[:entry['_start']]+_block(entry)+body[entry['_end']:];after=k.properties(body,meta)
            elif op in {'remove','restore'}:after=k.properties(before,{'stage_removed':op=='remove'})
            else:raise ValueError('阶段操作无效。')
            after=k.properties(after,{'updated_at':stamp})
        parse(after)
        if len(after)>500000:raise ValueError('阶段内容过长，请拆分阶段。')
        intent={'project':project,'id':identifier,'op':op,'payload_hash':signature,'before':w.digest(before),'after':w.digest(after),
                'result_id':result_id,'stamp':stamp,'state':'pending'}
        store.commit_page(key,[],intent);k.persist(path,before,after,w.KB.resolve());_finish(store,key,intent)
        return {**detail(project,identifier),'result_id':result_id}


def organize(data):
    project=data.get('project') or '山药';request=data.get('request_id')
    if not isinstance(request,str) or not re.fullmatch(r'[\w.-]{1,200}',request):raise ValueError('请提供有效request_id。')
    key='progress-operation:'+project+':'+request;store=Store();signature=w.digest(encode({k0:v for k0,v in data.items() if k0 not in {'fingerprint','lifecycle_revision'}}))
    with profiles.lifecycle_lock(project),k.editing():
        profile=profiles.get(project)
        if profile['archived']:raise ValueError('项目已归档，进展图只读。')
        if data.get('lifecycle_revision',profile['lifecycle_revision'])!=profile['lifecycle_revision']:raise ValueError('项目状态已变化。')
        old=store.cursor(key,{})
        if old:
            if old['payload_hash']!=signature:raise ValueError('同一request_id不能用于不同内容。')
            return progress(project)
        current=progress(project,True)
        if data.get('fingerprint')!=current['fingerprint']:raise ValueError('阶段组织已更新，请刷新后调整。')
        state=copy.deepcopy(_state(project));known={s['id'] for s in current['stages']};active={s['id'] for s in current['stages'] if not s['removed']}
        state['mainline']=current['mainline'];op=data.get('op')
        def ids(value):
            if not isinstance(value,list) or len(value)!=len(set(value)) or any(x not in active for x in value):raise ValueError('请选择本项目有效阶段。')
            return value
        if op=='set_current':
            identifier=data.get('stage_id')
            if identifier is not None and identifier not in active:raise ValueError('请选择本项目活动阶段。')
            state['current_stage_id']=identifier
        elif op in {'branch','move_mainline'}:
            chosen=ids(data.get('stage_ids',[]))
            if not chosen:raise ValueError('请选择阶段。')
            state['mainline']=[x for x in state['mainline'] if x not in chosen]
            for b in state['branches']:b['stage_ids']=[x for x in b['stage_ids'] if x not in chosen]
            state['branches']=[b for b in state['branches'] if b['stage_ids']]
            if op=='move_mainline':state['mainline'].extend(chosen)
            else:
                anchor=data.get('anchor_stage_id')
                if anchor not in active or anchor in chosen:raise ValueError('支线锚点无效。')
                state['branches'].append({'id':'BR-'+w.digest(project+request)[:20],'anchor_stage_id':anchor,'stage_ids':chosen})
        elif op=='reorder':
            ordered=data.get('stage_ids');lane=data.get('branch_id')
            target=state['mainline'] if not lane else next((b['stage_ids'] for b in state['branches'] if b['id']==lane),None)
            if target is None or not isinstance(ordered,list) or len(ordered)!=len(target) or set(ordered)!=set(target):raise ValueError('排序须保留原阶段集合。')
            target[:]=ordered
        elif op=='link':
            source,target=data.get('source'),data.get('target')
            if source not in active or target not in active or source==target:raise ValueError('请选择两个不同的本项目阶段。')
            state['links'].append({'id':'LINK-'+w.digest(project+request)[:20],'source':source,'target':target,'label':_text(data.get('label','关联'),'连接说明',200)})
        elif op=='unlink':state['links']=[e for e in state['links'] if e['id']!=data.get('id')]
        elif op=='layout':
            positions=data.get('positions')
            if not isinstance(positions,dict):raise ValueError('布局无效。')
            for identifier,position in positions.items():
                if identifier not in known or not isinstance(position,dict) or any(type(position.get(a)) not in (int,float) or not math.isfinite(position[a]) or abs(position[a])>1000000 for a in ('x','y')):raise ValueError('布局坐标无效。')
            state.setdefault('positions',{}).update(positions)
        else:raise ValueError('进展组织操作无效。')
        parents={identifier:b['anchor_stage_id'] for b in state['branches'] for identifier in b['stage_ids']}
        for identifier in parents:
            seen=set();current_id=identifier
            while current_id in parents:
                if current_id in seen:raise ValueError('支线归属不能形成循环。')
                seen.add(current_id);current_id=parents[current_id]
        placed=state['mainline']+[x for b in state['branches'] for x in b['stage_ids']]
        if len(placed)!=len(set(placed)) or set(placed)!=known:raise ValueError('阶段组织不完整或重复。')
        with store.connection() as db:
            db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)',('project-progress:'+project,encode(state),w.now()))
            db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)',(key,encode({'payload_hash':signature}),w.now()))
            store.log(db,'project.progress_'+op,project,{})
        if op=='set_current' and state['current_stage_id']!=current.get('current_stage_id'):
            __import__('administrator').schedule(project,'项目当前节点已变化')
    return progress(project)


def overview(project):
    path=k.line_path(project,w.KB).parent/'当前课题状态.md';raw=path.read_text('utf-8-sig') if path.exists() else '';_,body,_=k.split(raw)
    sections={}
    matches=list(re.finditer(r'(?m)^## (.+)\s*$',body))
    for i,m in enumerate(matches):sections[m[1].strip()]=body[m.end():matches[i+1].start() if i+1<len(matches) else len(body)].strip()
    return {'project':project,'fingerprint':w.digest(raw),'sections':sections,'body':body,'path':path.relative_to(w.KB.resolve()).as_posix()}


def save_overview(data):
    project=data.get('project') or '山药';path=k.line_path(project,w.KB).parent/'当前课题状态.md'
    with profiles.lifecycle_lock(project),k.editing():
        if profiles.get(project)['archived']:raise ValueError('项目已归档。')
        before=k.validate_fingerprint(path,data.get('fingerprint'));meta,body,_=k.split(before)
        fields=data.get('sections',{})
        if not isinstance(fields,dict) or set(fields)-{'总想法','研究目标'}:raise ValueError('总览字段无效。')
        for title,text in fields.items():
            _text(text,title);pattern=re.compile(r'(?ms)^## '+re.escape(title)+r'\s*\n.*?(?=^## |\Z)')
            section='## '+title+'\n\n'+text.rstrip()+'\n\n'
            body=pattern.sub(lambda _:section,body,count=1) if pattern.search(body) else body.rstrip()+'\n\n'+section
        after=(before[:k.split(before)[2].end()] if k.split(before)[2] else '')+body
        k.persist(path,before,after,w.KB.resolve())
    import workspace_catalog as catalog
    catalog.notify_change(path)
    return overview(project)


def project_listing():
    records=[]
    for profile in profiles.listing():
        current=progress(profile['project']);summary=overview(profile['project'])
        active=[s for s in current['stages'] if s['stage_status'] in {'进行中','受阻'}]
        chosen=next((s for s in [*current['stages'],*current['history']] if s['id']==current.get('current_stage_id')),None)
        records.append({**profile,'description':summary['sections'].get('总想法','')[:240],
            'current_stage':{key:chosen[key] for key in ('id','title','stage_status','removed')} if chosen else None,
            'stage_count':len(current['stages']),'current_stages':[{'id':s['id'],'title':s['title'],'stage_status':s['stage_status']} for s in active],
            'recent_update':max((s['updated'] for s in current['stages']),default=profile.get('updated',''))})
    return records
