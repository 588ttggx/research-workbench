"""Editable topic navigation; classifications do not assert scientific evidence."""
import copy
import json
import re
import uuid
import workflow as w
import knowledge as k
import workspace_catalog as catalog
from research_store import Store, encode
from project_questions import step_rows, step_details, step_hits

KEY = 'workspace-taxonomy:v1'
USES = [('use-background','基础与背景'),('use-reading','文献与阅读'),('use-method','方法与方案'),
        ('use-analysis','实验与分析'),('use-project','项目与决策'),('use-output','成果与总结')]
ROOTS = [('topic-yam','山药与薯蓣'),('topic-thz','太赫兹光谱'),('topic-ml','机器学习与统计'),('topic-starch','淀粉与加工')]


def stored():
    return Store().cursor(KEY, {'nodes':{},'hidden':[],'assignments':{},'reviews':{}})


def fingerprint(value):
    return w.digest(encode(value))


def commit(before, after, event):
    store = Store()
    with store.connection() as db:
        row = db.execute('SELECT value FROM cursors WHERE key=?', (KEY,)).fetchone()
        current = json.loads(row['value']) if row else {'nodes':{},'hidden':[],'assignments':{},'reviews':{}}
        if current != before: raise ValueError('分类已在其他窗口修改，请刷新后重试。')
        db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)', (KEY,encode(after),w.now()))
        store.log(db, 'navigation.'+event, KEY, {'classification_only':True})


def usage(kind):
    if any(t in kind for t in ['阅读','文献','论文批注']): return 'use-reading'
    if any(t in kind for t in ['方法','方案','标准操作','实验设计','统计计划']): return 'use-method'
    if any(t in kind for t in ['分析','实验','样品','仪器','校准','结果']): return 'use-analysis'
    if any(t in kind for t in ['成果','论文输出','图与谱系','复盘','关闭']): return 'use-output'
    if kind == '背景': return 'use-background'
    return 'use-project'


def topic_parent(text):
    if 'THz' in text or '太赫兹' in text or '组内' in text: return 'topic-thz'
    if any(t in text for t in ['山药','薯蓣']): return 'topic-yam'
    if any(t in text for t in ['学习','统计','模型']): return 'topic-ml'
    if any(t in text for t in ['淀粉','加工']): return 'topic-starch'
    return 'topic-unassigned'


def stages_for(text):
    found = {stage for stage, count in step_hits(text).items() if count}
    return found or {'planning'}


def base(project, workspace=None):
    docs = workspace['documents'] if workspace else catalog.rows()
    papers = workspace['papers'] if workspace else w.read_json(w.LIBRARY, {'records':[]})['records']
    lines = (workspace['mainlines']['rows'] if workspace else k.lines(project)['rows']) if project is not None else []
    nodes = {identifier:{'id':identifier,'title':title,'parent':'','dimension':dimension,'order':i}
             for dimension,values in [('usage',USES),('topic',ROOTS)] for i,(identifier,title) in enumerate(values)}
    for dimension in ['topic','usage']:
        identifier = dimension+'-unassigned'
        nodes[identifier] = {'id':identifier,'title':'待归类','parent':'','dimension':dimension,'order':999}
    assignments = {}
    for paper in papers:
        text = str(paper.get('topic') or '')
        topics = []
        if text:
            identifier = 'topic-'+w.digest(text)[:16]
            nodes[identifier] = {'id':identifier,'title':text,'parent':topic_parent(text),'dimension':'topic','order':30}
            topics.append(identifier)
        combined = ' '.join(str(paper.get(f) or '') for f in ['title','display_title','topic'])
        if re.search('SVM|CNN|LASSO|机器学习|神经网络|特征选择|回归',combined,re.I): topics.append('topic-ml')
        if '淀粉' in combined: topics.append('topic-starch')
        assignments['paper:'+paper['id']] = {'usage':'use-reading','topics':list(dict.fromkeys(topics or ['topic-unassigned']))}
    for doc in docs:
        topics = set()
        for paper_id in doc.get('paper_ids',[]): topics.update(assignments.get('paper:'+paper_id,{}).get('topics',[]))
        if not topics:
            text = ' '.join([doc.get('title',''),doc.get('excerpt','')])
            parent = topic_parent(text)
            topics.add(parent)
        assignments['doc:'+doc['id']] = {'usage':usage(doc['kind']),'topics':sorted(topics)}
    # Questions are the same stable entities as project mainlines, rather than another copy.
    for line in lines:
        if line['status']=='不采用': continue
        identifier = 'question:'+project+':'+line['id']
        nodes[identifier] = {'id':identifier,'title':line['title'],'parent':'topic-yam' if project=='山药' else '',
                             'dimension':'topic','kind':'question','question_id':line['id'],'project':project,'order':-20}
        linked = set(line.get('paper_ids',[]))
        from project_questions import read as read_question, materials
        try: problem_state=read_question(project,line['id'])[-1]
        except ValueError: problem_state={}
        related=materials(project,line,problem_state,docs)
        step_refs={}
        for i,row in enumerate(step_details(project,line,problem_state,related,docs)):
            sid=identifier+':'+row['id']
            nodes[sid]={'id':sid,'title':row['title'],'parent':identifier,'dimension':'topic','kind':'step','step_id':row['id'],
                        'question_id':line['id'],'project':project,'order':i}
            step_refs[sid]={r['id'] for r in row['references']}
        linked.update(r['paper_id'] for r in related if r.get('paper_id'))
        related_docs={r['doc_id'] for r in related if r.get('doc_id')}
        for material,assignment in assignments.items():
            if material.startswith('paper:'):
                row = next((p for p in papers if 'paper:'+p['id']==material),{})
                relevant = row.get('id') in linked
            else:
                row = next((d for d in docs if 'doc:'+d['id']==material),{})
                relevant = row.get('id') in related_docs or row.get('question_id')==line['id']
            if relevant:
                assignment['topics'].extend(sid for sid,refs in step_refs.items() if material in refs)
    return nodes,assignments


def view(project, workspace=None):
    k.line_path(project,w.KB)
    state = stored()
    nodes, assignments = base(project,workspace)
    nodes.update({i:copy.deepcopy(n) for i,n in state['nodes'].items() if nodes.get(i,{}).get('kind')!='step'})
    for identifier in list(nodes):
        if identifier.startswith('question:') and identifier.count(':')>=3 and ':'.join(identifier.split(':')[:3]) not in nodes:
            nodes.pop(identifier)
    hidden = set(state['hidden'])
    nodes = {i:n for i,n in nodes.items() if i not in hidden}
    for n in nodes.values():
        if n['parent'] not in nodes: n['parent']=''
    for identifier,override in state['assignments'].items():
        if identifier in assignments:
            steps=[t for t in assignments[identifier]['topics'] if nodes.get(t,{}).get('kind')=='step']
            assignments[identifier]=copy.deepcopy(override)
            assignments[identifier]['topics']=[t for t in assignments[identifier]['topics'] if nodes.get(t,{}).get('kind')!='step']+steps
    docs=workspace['documents'] if workspace else catalog.rows()
    for doc in docs:
        identifier='doc:'+doc['id']
        if identifier not in state['assignments'] and doc.get('paper_ids'):
            inherited=[t for p in doc['paper_ids'] for t in assignments.get('paper:'+p,{}).get('topics',[]) if nodes.get(t,{}).get('kind')!='step']
            stages=[t for t in assignments[identifier]['topics'] if t.startswith('question:')]
            assignments[identifier]['topics']=list(dict.fromkeys(inherited+stages)) or ['topic-unassigned']
    for assignment in assignments.values():
        assignment['topics'] = list(dict.fromkeys(i for i in assignment['topics'] if i in nodes and nodes[i]['dimension']=='topic')) or ['topic-unassigned']
        if assignment['usage'] not in nodes: assignment['usage']='usage-unassigned'
    return {'nodes':sorted(nodes.values(),key=lambda n:(n.get('order',0),n['title'])),
            'assignments':assignments,'fingerprint':navigation_revision(project,state)}


def navigation_revision(project,state):
    from project_questions import read,revision
    rows=k.lines(project)
    questions=[]
    for line in rows['rows']:
        _,raw,_,_,saved,_=read(project,line['id'])
        questions.append((line['id'],revision(raw,saved)))
    return fingerprint({'taxonomy':state,'mainlines':rows['fingerprint'],'questions':questions})


def project_category(identifier, node=None):
    return identifier.startswith('question:') or (node or {}).get('kind') in ('question','step')


def global_view(workspace=None):
    """Project steps remain stored associations, outside the global taxonomy."""
    if workspace is None:
        workspace=__import__('knowledge_catalog').catalog(include_classification=False)
    state=stored();nodes,assignments=base(None,workspace)
    for identifier,original in state['nodes'].items():
        if project_category(identifier,original):continue
        node=copy.deepcopy(original)
        if project_category(node.get('parent',''),state['nodes'].get(node.get('parent'))):
            node['legacy_parent']=node['parent']
            node['legacy_path']=node['parent']
            node['parent']=node.get('global_parent','')
        nodes[identifier]=node
    nodes={i:n for i,n in nodes.items() if i not in state['hidden']}
    for node in nodes.values():
        if node.get('parent') not in nodes:node['parent']=''
    for identifier,override in state['assignments'].items():
        if identifier in assignments:assignments[identifier]=copy.deepcopy(override)
    for doc in workspace['documents']:
        identifier='doc:'+doc['id']
        if identifier not in state['assignments'] and doc.get('paper_ids'):
            inherited=[t for pid in doc['paper_ids'] for t in assignments.get('paper:'+pid,{}).get('topics',[]) if t in nodes]
            assignments[identifier]['topics']=list(dict.fromkeys(inherited)) or ['topic-unassigned']
    for identifier,assignment in assignments.items():
        assignment['topics']=list(dict.fromkeys(t for t in assignment.get('topics',[]) if t in nodes and nodes[t]['dimension']=='topic')) or ['topic-unassigned']
        if assignment.get('usage') not in nodes:assignment['usage']='usage-unassigned'
    documents={doc['id']:doc for doc in workspace['documents']}
    reviews={}
    for topic_id,document_id in (state.get('reviews') or {}).items():
        if topic_id not in nodes or nodes[topic_id]['dimension']!='topic':continue
        doc=documents.get(document_id)
        if not doc or doc.get('archived') or doc.get('visibility')=='system':continue
        if doc.get('content_role')!='knowledge' or not doc.get('global_knowledge'):continue
        reviews[topic_id]={'document_id':document_id,'title':doc.get('display_title') or doc.get('title',''),
                           'excerpt':doc.get('excerpt',''),'updated':doc.get('file_modified')}
    return {'nodes':sorted(nodes.values(),key=lambda n:(n.get('order',0),n['title'])),
            'assignments':assignments,'reviews':reviews,'fingerprint':fingerprint(state)}


def preserve_project_assignment(before, identifier, assignment):
    original=before.get('assignments',{}).get(identifier,{})
    hidden=[t for t in original.get('topics',[]) if project_category(t,before.get('nodes',{}).get(t))]
    return {**copy.deepcopy(original),**assignment,'topics':list(dict.fromkeys(assignment['topics']+hidden))}


def persist_node(before, node, global_scope):
    if not global_scope:return node
    original=before['nodes'].get(node['id'],{})
    saved={**original,**{f:v for f,v in node.items() if f not in ('legacy_parent','legacy_path')}}
    if project_category(original.get('parent',''),before['nodes'].get(original.get('parent'))):
        saved.update(parent=original['parent'],global_parent=node['parent'])
    return saved


def global_change(data):
    return change(data,global_scope=True)


def global_assign(data):
    return assign(data,global_scope=True)


def assign_step_links(project,ids,topics,nodes,current):
    """The question Markdown is authoritative for step links in both screens."""
    from project_questions import read,write,place_material
    by_question={};plans=[];docs={d['id']:d for d in catalog.rows()}
    for node in nodes.values():
        if node.get('kind')=='step':by_question.setdefault(node['question_id'],[]).append(node)
    for question,steps in by_question.items():
        selected=[n for n in steps if n['id'] in topics]
        if len(selected)>1:raise ValueError('同一研究问题请选择一个主要步骤；其他关联可保留为主题。')
        selected=selected[0] if selected else None
        step_ids={n['id'] for n in steps}
        relevant=[i for i in ids if selected or step_ids.intersection(current['assignments'][i]['topics'])]
        if not relevant:continue
        if selected and any(m.startswith('doc:') and docs.get(m[4:],{}).get('question_id')==question for m in relevant):raise ValueError('问题摘要不能关联为自身资料。')
        plans.append((read(project,question),steps,selected,relevant))
    for (_,raw,meta,body,line,state),steps,selected,relevant in plans:
        for material in relevant:
            if selected:place_material(state,selected['step_id'],material,'add')
            else:
                for row in steps:place_material(state,row['step_id'],material,'remove')
        write(project,line['id'],raw,meta,body,line,state,'step_reference_from_knowledge')


def change(data, *, global_scope=False):
    project = data.get('project','山药')
    with k.editing():
        current = global_view() if global_scope else view(project); before = stored(); after = copy.deepcopy(before)
        if data.get('fingerprint') != current['fingerprint']: raise ValueError('分类已更新，请刷新后再修改。')
        nodes = {n['id']:n for n in current['nodes']}
        op = data.get('op'); identifier = data.get('id')
        if op == 'create':
            if len(nodes)>1000: raise ValueError('分类过多，请先合并重复分类。')
            identifier = 'category-'+uuid.uuid4().hex[:16]
            node = {'id':identifier,'dimension':data.get('dimension'),'order':len(nodes)}
        else:
            if not isinstance(identifier,str):raise ValueError('分类编号无效。')
            if identifier not in nodes or identifier.endswith('-unassigned'): raise ValueError('请选择可修改的分类。')
            node = copy.deepcopy(nodes[identifier])
            if node.get('kind') in ('question','step'): raise ValueError('请从项目页修改这个研究问题，两个入口会同步。')
        if op=='review':
            if node.get('dimension')!='topic': raise ValueError('主题综述只能绑定到研究主题。')
            document_id=data.get('document_id')
            if document_id in (None,''):
                after.setdefault('reviews',{}).pop(identifier,None)
            else:
                documents={d['id']:d for d in catalog.rows(reconcile_records=False)}
                document=documents.get(document_id)
                if (not document or document.get('archived') or document.get('content_role')!='knowledge'
                        or not document.get('global_knowledge') or document.get('visibility')=='system'):
                    raise ValueError('请选择仍在使用的全局知识稿作为主题综述。')
                after.setdefault('reviews',{})[identifier]=document_id
        elif op in ('create','update'):
            title = data.get('title'); parent = data.get('parent','')
            if not isinstance(title,str) or not title.strip() or len(title)>100: raise ValueError('分类名称为 1–100 字。')
            if node['dimension'] not in ('topic','usage'): raise ValueError('分类类型无效。')
            if not isinstance(parent,str) or parent and (parent not in nodes or nodes[parent]['dimension']!=node['dimension']): raise ValueError('请选择同类型的上级分类。')
            seen = {identifier}; cursor = parent
            while cursor:
                if cursor in seen: raise ValueError('不能把分类移到自身或其子分类中。')
                seen.add(cursor); cursor=nodes[cursor]['parent']
            if any(n['id']!=identifier and n['parent']==parent and n['dimension']==node['dimension'] and n['title']==title.strip() for n in nodes.values()):
                raise ValueError('同一层已有这个名称。')
            node.update(title=title.strip(),parent=parent)
            after['nodes'][identifier]=persist_node(before,node,global_scope)
        elif op in ('delete','merge'):
            target = data.get('target') if op=='merge' else node['dimension']+'-unassigned'
            if not isinstance(target,str) or target not in nodes or nodes[target]['dimension']!=node['dimension'] or target==identifier: raise ValueError('合并目标无效。')
            cursor=target
            while cursor:
                if cursor==identifier: raise ValueError('不能合并到自己的子分类。')
                cursor=nodes[cursor]['parent']
            after['hidden']=list(dict.fromkeys(after['hidden']+[identifier]))
            after['nodes'].pop(identifier,None)
            review=(after.get('reviews') or {}).pop(identifier,None)
            if review and op=='merge' and not after.get('reviews',{}).get(target):after.setdefault('reviews',{})[target]=review
            for n in nodes.values():
                if n['parent']==identifier:
                    after['nodes'][n['id']]=persist_node(before,{**n,'parent':node['parent'] if op=='delete' else target},global_scope)
            for material,assignment in current['assignments'].items():
                if identifier in assignment['topics'] or assignment['usage']==identifier:
                    a=copy.deepcopy(assignment)
                    a['topics']=list(dict.fromkeys(target if t==identifier else t for t in a['topics']))
                    if a['usage']==identifier:a['usage']=target
                    after['assignments'][material]=preserve_project_assignment(before,material,a) if global_scope else a
        elif op=='reorder':
            order=data.get('order')
            if type(order) is not int or abs(order)>10000:raise ValueError('排序位置无效。')
            after['nodes'][identifier]=persist_node(before,{**node,'order':order},global_scope)
        else: raise ValueError('分类操作无效。')
        commit(before,after,op)
    return global_view() if global_scope else view(project)


def assign(data, *, global_scope=False):
    project=data.get('project','山药')
    with k.editing():
        current=global_view() if global_scope else view(project);before=stored();after=copy.deepcopy(before)
        if data.get('fingerprint')!=current['fingerprint']:raise ValueError('分类已变化，请刷新后再分配。')
        nodes={n['id']:n for n in current['nodes']};ids=data.get('ids');topics=data.get('topics');use=data.get('usage')
        if not isinstance(ids,list) or not 1<=len(ids)<=500 or any(not isinstance(i,str) or i not in current['assignments'] for i in ids):raise ValueError('请选择有效资料。')
        if topics is not None and (not isinstance(topics,list) or len(topics)>100 or any(not isinstance(t,str) or t not in nodes or nodes[t]['dimension']!='topic' for t in topics)):raise ValueError('请选择有效主题。')
        if use is not None and (not isinstance(use,str) or use not in nodes or nodes[use]['dimension']!='usage'):raise ValueError('请选择有效用途。')
        if topics is not None and not global_scope:assign_step_links(project,ids,topics,nodes,current)
        for identifier in ids:
            assignment=copy.deepcopy(current['assignments'][identifier])
            if use is not None:assignment['usage']=use
            if topics is not None:assignment['topics']=list(dict.fromkeys(topics)) or ['topic-unassigned']
            after['assignments'][identifier]=preserve_project_assignment(before,identifier,assignment) if global_scope else assignment
        commit(before,after,'assign')
    return global_view() if global_scope else view(project)
