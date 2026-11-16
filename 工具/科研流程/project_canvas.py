"""Free project organization, with durable layout and links to canonical sources."""
import copy
import json
import math
import re
import uuid
from filelock import FileLock

import canvas_sources as sources
import knowledge as k
import workflow as w
from research_store import Store, encode


def key(project):
    k.line_path(project,w.KB)
    return 'project-canvas:'+project


def state(project):
    return Store().cursor(key(project),{'nodes':{},'groups':{},'edges':[],'papers':[],'receipts':{},'revision':0})


def fingerprint(value):return w.digest(encode(value))


def document_summary(doc):
    """Small canonical-source pointer; editor saves still fetch fresh detail."""
    if not doc:return None
    path=__import__('workspace_catalog').bounded(doc['path'])
    return {'document_id':doc['id'],'title':doc['display_title'],'path':doc['path'],
            'kb_path':doc.get('kb_path'),'sha':doc['sha'],'fingerprint':w.digest(path.read_text('utf-8-sig')),
            'modified':doc.get('file_modified'),'archived':doc['archived'],'project':doc['project']}


def project_overview(project, snap, members, profile):
    """Project orientation from existing records, with no inference or writes."""
    from project_questions import revision,plan_payload
    folder=k.line_path(project,w.KB).parent
    docs_by_path={(w.ROOT/d['path']).resolve():d for d in snap['documents'].values()}
    question_docs=list(snap['documents'].values())
    questions=[]
    for identifier,(path,raw,line,current) in snap['questions'].items():
        plan_id=current.get('plan_document_id')
        questions.append({**line,'phase':current.get('phase',line.get('status','')),
                          'progress':current.get('progress',''),'next_step':current.get('next_step',''),
                          'solution':current.get('solution',''),
                          'progress_records':copy.deepcopy(current.get('progress_records',[])),
                          'fingerprint':revision(raw,line),'source_fingerprint':revision(raw,line),
                          'plan_document_id':plan_id or None,'plan_document':plan_payload(plan_id,question_docs),
                          'has_saved_steps':bool(current.get('steps')),
                          'document_id':__import__('workspace_catalog').identify(path.relative_to(w.ROOT.resolve()).as_posix()) if path.is_file() else None,
                          'path':path.relative_to(w.ROOT.resolve()).as_posix(),
                          'modified':path.stat().st_mtime if path.is_file() else None})
    state_doc=document_summary(docs_by_path.get((folder/'当前课题状态.md').resolve()))
    task_doc=document_summary(docs_by_path.get((folder/'任务.md').resolve()))
    if task_doc:
        raw=(folder/'任务.md').read_text('utf-8-sig')
        task_doc['count']=len(re.findall(r'(?m)^\s*[-*] \[[ xX]\]',raw))
        task_doc['status_note']='任务勾选保留原记录，不代表实验已经完成；科研状态以有来源的项目主稿为准。'
    identifier=profile.get('plan_document_id');doc=snap['documents'].get(identifier)
    plan={'document_id':identifier,'state':'unspecified' if not identifier else 'missing'}
    if doc:
        plan={**document_summary(doc),'state':'archived' if doc['archived'] else 'active' if identifier in members['documents'] else 'out_of_scope'}
    return {'questions':questions,'state_document':state_doc,'plan_document':plan,'task_document':task_doc,
            'mainlines_fingerprint':k.lines(project)['fingerprint']}


def view(project, *, saved=None, snap=None, knowledge_scope=False):
    saved=state(project) if saved is None else saved
    if snap is None:
        if knowledge_scope:
            from project_materials import source_snapshot
            snap=source_snapshot(project,readonly=True)
        else:snap=sources.snapshot(project)
    groups={**snap['groups'],**saved['groups']}
    groups={i:g for i,g in groups.items() if not g.get('deleted')}
    merged=copy.deepcopy(snap['seeds'])
    for identifier,row in saved['nodes'].items():
        if row.get('origin')=='project-knowledge' and not knowledge_scope:continue
        if row.get('source',{}).get('kind')=='step' and row.get('origin')!='manual':continue
        if row.get('origin')=='auto-note' and identifier not in snap['seeds']:continue
        merged[identifier]={**merged.get(identifier,{}),**row}
    from project_materials import snapshot as membership
    members=membership(project,base=snap,saved=saved)
    if knowledge_scope:
        import project_knowledge as knowledge
        documents,_,paper_ids=knowledge.current_scope(project,snap,members,knowledge.state(project),saved['papers'])
        existing={}
        for row in sorted(merged.values(),key=lambda row:bool(row.get('deleted'))):
            source=row['source']
            key=(source['kind'],source.get('document_id') or source.get('paper_id'))
            existing.setdefault(key,row)
        merged={}
        sources_in_scope=[('document',doc['id']) for doc in documents]+[('paper',pid) for pid in sorted(paper_ids) if pid in snap['papers']]
        for kind,identifier in sources_in_scope:
            row=existing.get((kind,identifier))
            if row is None:
                material=('doc:' if kind=='document' else 'paper:')+identifier
                node_id='a-'+w.digest(material)[:24]
                row={'id':node_id,'source':{'kind':kind,kind+'_id':identifier},'kind':'note' if kind=='document' else 'paper','origin':'project-knowledge'}
            merged[row['id']]={**row,'deleted':False}
    nodes=[];deleted=[]
    for index,(identifier,row) in enumerate(merged.items()):
        node=sources.resolve(row,snap)
        if node is None:continue
        node.setdefault('position',{'x':(index%4)*330,'y':(index//4)*240})
        if node.get('group') not in groups:node['group']=''
        (deleted if row.get('deleted') else nodes).append(node)
    live={n['id'] for n in nodes}
    papers=sources.pool(project,snap,nodes,saved['papers'],saved=saved,scope=members)
    automatic=__import__('canvas_organization').graph(project,nodes,saved)
    if knowledge_scope:
        ordinary=__import__('relation_discovery').project_links(nodes,documents,[snap['papers'][pid] for pid in sorted(paper_ids) if pid in snap['papers']],saved)
        automatic['auto_edges'].extend(ordinary)
    live.update('direction:'+d['id'] for d in automatic['directions'])
    edges=[e for e in saved['edges'] if not e.get('deleted') and e['source'] in live and e['target'] in live]
    structure_edges=edges+automatic['auto_edges'] if knowledge_scope else edges
    automatic['structure_signature']=fingerprint([automatic['structure_signature'],[(e['source'],e['target']) for e in structure_edges]])
    profile=__import__('project_profiles').get(project)
    return {'project':project,'project_profile':profile,'project_overview':project_overview(project,snap,members,profile),
            'project_materials':{'documents':list(members['documents'].values()),'history':list(members['history'].values())},
            'fingerprint':fingerprint(saved),'creation_receipts':{name[4:]:value for name,value in saved.get('receipts',{}).items() if name.startswith('add:')},'nodes':nodes,'deleted':deleted,'edges':edges,**automatic,
            'groups':list(groups.values()),'papers':papers,'viewport':saved.get('viewport'),
            'display':saved.get('display','cards'),'kinds':sources.KINDS,'statuses':sources.STATUSES,
            'has_layout':any('position' in row for row in saved['nodes'].values()),'layout_signature':saved.get('layout_signature'),
            'show_frames':saved.get('show_frames',False),
            'hidden_node_ids':sorted(set(saved.get('knowledge_hidden_node_ids' if knowledge_scope else 'hidden_node_ids',saved.get('hidden_node_ids',[])))&{n['id'] for n in nodes}),
            'source_signature':source_signature(snap,merged)}


def source_signature(snap,merged):
    scoped={r.get('source',{}).get('document_id') for r in merged.values() if not r.get('deleted')}
    docs=[(d['id'],d['sha']) for d in snap['documents'].values()
          if not d['archived'] and d['visibility']!='system' and
          d['id'] in scoped]
    native=[(i,w.digest(raw),line) for i,(_,raw,line,_) in snap['questions'].items()]
    papers=[(r['source']['paper_id'],{key:snap['papers'].get(r['source']['paper_id'],{}).get(key) for key in ('title','doi','abstract')}) for r in merged.values() if r.get('source',{}).get('kind')=='paper' and not r.get('deleted')]
    # Include explicitly scoped document content; unrelated projects do not affect drafts.
    return fingerprint([sorted(docs),native,papers])


def text(value, limit, label, *, blank=False):
    if not isinstance(value,str) or len(value)>limit or '\x00' in value or (not blank and not value.strip()):
        raise ValueError(label+'格式或长度无效。')
    return value.strip() if not blank else value


def point(value):
    if not isinstance(value,dict) or set(value)!={'x','y'}:raise ValueError('节点位置格式无效。')
    if any(isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or abs(n)>1000000 for n in value.values()):
        raise ValueError('节点位置超出范围。')
    return value


def group_id(value, current):
    if value and value not in {g['id'] for g in current['groups']}:raise ValueError('这个分组不存在。')
    return value or ''


def request_id(data):
    value=data.get('request_id') or uuid.uuid4().hex
    if not isinstance(value,str) or not re.fullmatch(r'[\w.-]{1,100}',value):raise ValueError('创建请求编号无效。')
    return value


def add_note(project, saved, current, data, *, ai=False, paper_ids=()):
    request=request_id(data);identifier='c-'+w.digest(project+':'+request)[:24]
    if identifier in saved['nodes']:
        return identifier
    if len(current['nodes'])>=1000:raise ValueError('画布已有 1000 个活动节点，请先分组整理。')
    kind=data.get('kind','note')
    if kind not in sources.KINDS or kind=='paper':raise ValueError('请选择有效的笔记节点类型。')
    title=text(data.get('title'),200,'节点标题');body=text(data.get('body',''),100000,'笔记正文',blank=True)
    group=group_id(data.get('group',''),current);position=point(data.get('position',{'x':0,'y':0}))
    source=sources.create_note(project,identifier,title,body,paper_ids,ai=ai)
    saved['nodes'][identifier]={'id':identifier,'source':source,'kind':kind,'group':group,'position':position,
                                'status':'待核查' if ai else '未开始','origin':'ai-draft' if ai else 'manual'}
    saved['receipts']['add:'+request]=identifier
    return identifier


def attach(project, saved, current, data, snap):
    material=data.get('material')
    if not isinstance(material,str):raise ValueError('请选择已登记的文献或笔记。')
    if material.startswith('paper:') and material[6:] in snap['papers']:
        source={'kind':'paper','paper_id':material[6:]};kind='paper'
        saved['papers']=sorted(set(saved['papers'])|{material[6:]})
    elif material.startswith('doc:'):
        doc=snap['documents'].get(material[4:])
        if not doc or doc['archived'] and not (data.get('include_archived') is True and '报告' in doc['kind']) or doc['visibility']=='system':
            raise ValueError('请选择有效原稿；跨项目选用仍保留原来源。')
        source={'kind':'document','document_id':doc['id']};kind='note'
        if doc['archived']:source['allow_archived']=True
    else:raise ValueError('这份来源不存在或已退出活动资料。')
    identifier='a-'+w.digest(material)[:24]
    existing=next((n for n in current['nodes']+current['deleted'] if n['source']==source),None)
    if existing:identifier=existing['id']
    old=saved['nodes'].get(identifier,{})
    saved['nodes'][identifier]={**old,'id':identifier,'source':source,'kind':old.get('kind',kind),
        'group':group_id(data.get('group',old.get('group','')),current),
        'position':point(data.get('position',old.get('position',{'x':0,'y':0}))),'deleted':False,'origin':'manual'}
    return identifier


def edge(saved, current, data):
    live={n['id'] for n in current['nodes']}|{'direction:'+d['id'] for d in current.get('directions',[])};source=data.get('source');target=data.get('target')
    if source not in live or target not in live or source==target:raise ValueError('请连接两个不同的现有节点。')
    label=text(data.get('label','关联'),80,'连线名称')
    if len(saved['edges'])>=3000:raise ValueError('画布连线过多，请先整理。')
    old=next((e for e in saved['edges'] if e['source']==source and e['target']==target and e['label']==label),None)
    if old:old['deleted']=False;return old['id']
    identifier='e-'+uuid.uuid4().hex[:20]
    saved['edges'].append({'id':identifier,'source':source,'target':target,'label':label})
    return identifier


def persist(project, saved, before, op):
    store=Store()
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        found=db.execute('SELECT value FROM cursors WHERE key=?',(key(project),)).fetchone()
        actual=json.loads(found['value']) if found else state_default()
        if fingerprint(actual)!=before:raise ValueError('画布已在其他窗口修改，请刷新后合并。')
        saved['revision']+=1
        db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)',(key(project),encode(saved),w.now()))
        Store.log(db,'canvas.'+op,project,{'revision':saved['revision']})


def state_default():return {'nodes':{},'groups':{},'edges':[],'papers':[],'receipts':{},'revision':0}


def select_papers(saved, identifiers, mode, available):
    """Change the canonical paper pool without touching nodes or their layout."""
    if not isinstance(identifiers,list) or not 1<=len(identifiers)<=100 or any(not isinstance(i,str) or i not in available for i in identifiers):
        raise ValueError('请选择已登记的有效文献。')
    chosen=set(saved.get('papers',[]))
    if mode=='add':chosen.update(identifiers)
    elif mode=='remove':chosen.difference_update(identifiers)
    else:raise ValueError('请选择加入或移除。')
    saved['papers']=sorted(chosen)


def change(data):
    project=data.get('project','山药');key(project)
    import project_profiles as profiles
    knowledge_scope=data.get('scope')=='knowledge'
    with profiles.lifecycle_lock(project),FileLock(str(w.DATA/'.project-canvas.lock'),timeout=20):
        if profiles.get(project)['archived']:raise ValueError('项目已归档，关系图只读。')
        saved=state(project);before=fingerprint(saved);op=data.get('op')
        if knowledge_scope and op not in {'move','visibility','display','direction','update','edge','remove_edge','remove_auto_edge'}:
            raise ValueError('请从项目知识目录调整选用范围。')
        # Deliberate creation retries reuse the same source even after a timeout.
        if op=='add' and data.get('request_id') and 'add:'+data['request_id'] in saved['receipts']:return view(project,saved=saved)
        if op=='apply':
            receipt='draft:'+str(data.get('draft_id'))
            if receipt in saved['receipts']:
                if sorted(data.get('selected',[]))!=saved['receipts'][receipt]:raise ValueError('该草稿已采纳，请重新生成后再调整。')
                return view(project,saved=saved)
        if data.get('fingerprint')!=before:raise ValueError('画布已在其他窗口修改，请重新读取后合并；内容仍保留。')
        snap=sources.snapshot(project);snap['project']=project
        current=view(project,saved=saved,snap=snap,knowledge_scope=knowledge_scope)
        # Classification can finish while ELK is working. Its old virtual hubs
        # are an obsolete layout, not a user error or permission to move new hubs.
        if op=='move' and data.get('layout_signature') and data['layout_signature']!=current['structure_signature']:
            return current
        nodes={n['id']:n for n in current['nodes']+current['deleted']}
        identifier=data.get('node_id');node=nodes.get(identifier)
        if op=='add':add_note(project,saved,current,data)
        elif op=='attach':attach(project,saved,current,data,snap)
        elif op=='expand':
            materials=data.get('materials')
            if not isinstance(materials,list) or not 1<=len(materials)<=60 or any(not isinstance(m,str) for m in materials):raise ValueError('每次请选择 1–60 份资料。')
            origin=point(data.get('position',{'x':0,'y':0}))
            existing={('paper:'+n['source']['paper_id']) if n['source']['kind']=='paper' else ('doc:'+n['document_id']) for n in current['nodes'] if n['source']['kind'] in ('document','paper')}
            for index,material in enumerate(dict.fromkeys(materials)):
                if material in existing:continue
                attach(project,saved,current,{'material':material,'include_archived':data.get('include_archived',False),'group':data.get('group',''),
                       'position':{'x':origin['x']+index%3*330,'y':origin['y']+index//3*240}},snap)
        elif op=='move':
            positions=data.get('positions',{})
            if not isinstance(positions,dict) or len(positions)>1000:raise ValueError('位置列表无效。')
            validated={}
            for nid,position in positions.items():
                if nid not in nodes:raise ValueError('移动的节点已不存在。')
                validated[nid]=point(position)
            viewport=data.get('viewport')
            if viewport is not None:
                if not isinstance(viewport,dict) or set(viewport)!={'x','y','zoom'}:raise ValueError('画布视口无效。')
                point({n:viewport[n] for n in ('x','y')})
                zoom=viewport['zoom']
                if isinstance(zoom,bool) or not isinstance(zoom,(int,float)) or not math.isfinite(zoom) or not .05<=zoom<=4:raise ValueError('缩放比例无效。')
                saved['viewport']=viewport
            for nid,position in validated.items():
                old=saved['nodes'].get(nid,nodes[nid])
                if data.get('preserve_manual') and old.get('manual_position'):position=old['position']
                saved['nodes'][nid]={**old,'position':position,'manual_position':old.get('manual_position',False) if data.get('preserve_manual') else data.get('manual',True)}
            direction_positions=data.get('direction_positions',{})
            allowed_directions={d['id'] for d in current['directions']}
            if not isinstance(direction_positions,dict) or len(direction_positions)>100 or set(direction_positions)-allowed_directions:raise ValueError('方向位置无效。')
            for did,position in direction_positions.items():
                if data.get('preserve_manual') and saved.get('direction_manual',{}).get(did):position=saved['direction_positions'][did]
                saved.setdefault('direction_positions',{})[did]=point(position)
                saved.setdefault('direction_manual',{})[did]=saved.get('direction_manual',{}).get(did,False) if data.get('preserve_manual') else data.get('manual',True)
            if data.get('layout_signature')==current['structure_signature']:saved['layout_signature']=data['layout_signature']
        elif op=='visibility':
            hidden=data.get('hidden_node_ids')
            if not isinstance(hidden,list) or len(hidden)>1000 or any(not isinstance(i,str) or i not in {n['id'] for n in current['nodes']} for i in hidden):raise ValueError('请选择当前项目内有效的资料。')
            hidden_key='knowledge_hidden_node_ids' if knowledge_scope else 'hidden_node_ids'
            if not knowledge_scope:saved.setdefault('knowledge_hidden_node_ids',saved.get('hidden_node_ids',[]))
            inactive=set(saved.get(hidden_key,saved.get('hidden_node_ids',[])))-{n['id'] for n in current['nodes']}
            saved[hidden_key]=sorted(set(hidden)|inactive)
        elif op=='display':
            if data.get('display') not in ('cards','compact'):raise ValueError('显示方式无效。')
            saved['display']=data['display']
        elif op=='frames':
            if not isinstance(data.get('show_frames'),bool):raise ValueError('分组边框设置无效。')
            saved['show_frames']=data['show_frames']
        elif op=='direction':
            title=text(data.get('title'),48,'研究方向');did=data.get('direction_id') or 'd-'+w.digest(title)[:16]
            if data.get('direction_id') and did not in {d['id'] for d in current['directions']}:raise ValueError('研究方向已不存在。')
            summary=text(data.get('summary',''),250,'方向说明',blank=True)
            saved.setdefault('directions',{})[did]={'title':title,'summary':summary}
        elif op=='group':
            title=text(data.get('title'),120,'分组名称');gid=data.get('group_id') or 'g-'+uuid.uuid4().hex[:16]
            if data.get('group_id') and gid not in {g['id'] for g in current['groups']}:raise ValueError('分组不存在。')
            if not isinstance(gid,str) or not re.fullmatch(r'[\w.-]{1,100}',gid):raise ValueError('分组编号无效。')
            color=data.get('color','#7666b8')
            if not isinstance(color,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',color):raise ValueError('分组颜色无效。')
            saved['groups'][gid]={'id':gid,'title':title,'color':color}
        elif op=='remove_group':
            gid=group_id(data.get('group_id'),current)
            if not gid:raise ValueError('请选择要解散的分组。')
            saved['groups'][gid]={**next(g for g in current['groups'] if g['id']==gid),'deleted':True}
            for nid,n in nodes.items():
                if n.get('group')==gid:saved['nodes'][nid]={**saved['nodes'].get(nid,n),'group':''}
        elif op=='update':
            if not node or node.get('deleted'):raise ValueError('请选择一个有效节点。')
            fields=data.get('fields')
            if node['source'].get('task_id') and isinstance(fields,dict) and set(fields)&{'title','body','next_step','status','kind'}:
                raise ValueError('此节点指向同一条项目工作，请打开任务原稿或工作详情修改。')
            if not isinstance(fields,dict) or set(fields)-{'title','body','next_step','group','kind','status','direction'}:raise ValueError('节点字段无效。')
            if 'kind' in fields and (fields['kind'] not in sources.KINDS or (fields['kind']=='paper')!=(node['source']['kind']=='paper')):raise ValueError('节点类型无效。')
            if 'title' in fields:text(fields['title'],200,'节点标题')
            if 'group' in fields:group_id(fields['group'],current)
            if 'direction' in fields and fields['direction'] not in {d['id'] for d in current['directions']}:raise ValueError('请选择已有的研究方向。')
            if 'status' in fields and fields['status'] not in sources.STATUSES:raise ValueError('节点状态无效。')
            prose={n:v for n,v in fields.items() if n in ('title','body','next_step')}
            if prose:sources.save_source(project,node,prose,data.get('source_fingerprint'))
            saved['nodes'][identifier]={**saved['nodes'].get(identifier,node),**{n:v for n,v in fields.items() if n in ('group','kind','status')}}
            if 'direction' in fields:saved['nodes'][identifier]['direction_override']=fields['direction']
        elif op in ('remove','restore'):
            # A selected original can have just been archived or gone missing;
            # its persistent selection must still be explicitly removable.
            node=node or saved['nodes'].get(identifier)
            if not node:raise ValueError('节点已不存在，请重新读取。')
            saved['nodes'][identifier]={**saved['nodes'].get(identifier,node),'deleted':op=='remove'}
            if node['source'].get('kind')=='paper':
                pid=node['source']['paper_id'];chosen=set(saved['papers'])
                chosen.discard(pid) if op=='remove' else chosen.add(pid)
                saved['papers']=sorted(chosen)
        elif op=='edge':edge(saved,current,data)
        elif op=='remove_edge':
            found=next((e for e in saved['edges'] if e['id']==data.get('edge_id')),None)
            if not found:raise ValueError('连线不存在。')
            found['deleted']=True
        elif op=='remove_auto_edge':
            eid=data.get('edge_id')
            if eid not in {e['id'] for e in current['auto_edges']}:raise ValueError('这条自动关联已变化。')
            saved['hidden_auto_edges']=sorted(set(saved.get('hidden_auto_edges',[]))|{eid})
        elif op=='paper':
            pid=data.get('paper_id')
            select_papers(saved,[pid],data.get('mode'),snap['papers'])
            if data.get('mode')=='add':
                attach(project,saved,current,{'material':'paper:'+pid},snap)
            elif data.get('mode')=='remove':
                for n in current['nodes']:
                    if n['source'].get('paper_id')==pid:saved['nodes'][n['id']]={**saved['nodes'].get(n['id'],n),'deleted':True}
        elif op=='apply':
            from canvas_drafts import apply
            apply(project,saved,current,data,snap)
        else:raise ValueError('画布操作无效。')
        # Persist only identity, organization and layout; never a duplicate prose snapshot.
        allowed={'id','source','kind','group','position','status','deleted','origin','direction_override','manual_position'}
        saved['nodes']={nid:{n:v for n,v in row.items() if n in allowed} for nid,row in saved['nodes'].items()}
        persist(project,saved,before,op)
    return view(project,knowledge_scope=knowledge_scope)


def propose(data):
    from canvas_drafts import propose as generate
    return generate(data)


def node_detail(project, identifier):
    snap=sources.snapshot(project);saved=state(project)
    row={**snap['seeds'].get(identifier,{}),**saved['nodes'].get(identifier,{})}
    if not row or row.get('deleted'):raise ValueError('这个节点不存在或已移出画布。')
    result=sources.resolve(row,snap,full=True)
    if not result:raise ValueError('节点来源已不在活动资料中，请核对原入口。')
    return result


def inventory(project):
    snap=sources.snapshot(project)
    docs=[{'id':'doc:'+d['id'],'title':d['display_title'],'kind':d['kind'],'project':d['project'],'paper_ids':d['paper_ids']}
          for d in snap['documents'].values() if not d['archived'] and d['visibility']!='system' and not d.get('question_id')]
    papers=[{'id':'paper:'+p['id'],'title':p.get('display_title') or p['title'],'kind':'文献','project':p.get('project') or '共享'} for p in snap['papers'].values()]
    reports=[{'id':'doc:'+d['id'],'title':d['display_title'],'kind':d['kind'],'project':d['project'],'archived':d['archived']}
             for d in snap['documents'].values() if d['visibility']!='system' and '报告' in d['kind']]
    return {'documents':docs,'papers':papers,'reports':reports}
