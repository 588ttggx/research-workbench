"""Typed Markdown records and evidence-preserving provenance, without invented facts."""
import json
from pathlib import Path
import re
import workflow as w
import knowledge as k
from research_store import Store

# Prefix, display name, actual content fields. No example experiment is seeded.
TYPES = {
 'DailyLog':('LOG','研究日志',['日期','今天做了什么','证据与来源','待办']),
 'Project':('THZ-P','项目',['研究问题','目标与范围','里程碑','任务','风险','决策','实验计划','项目记忆']),
 'PaperNote':('PN','文献理解',['Paper ID / Zotero URI','阅读范围与定位','我的理解','关键结论','局限','关联项目与 Gap']),
 'Meeting':('MEET','会议',['时间与参与人','讨论','决定','行动与负责人']),
 'Idea':('IDEA','想法',['问题','想法','依据','待核条件']),
 'Gap':('RG','研究缺口',['已有工作','具体不足','证据与适用范围','需要验证什么']),
 'Question':('RQ','研究问题',['问题','关联 Gap','可检验目标','边界']),
 'Hypothesis':('H','假设',['假设','物理或文献依据','可证伪预测','验证设计']),
 'Decision':('DEC','项目记录',[]),
 'Issue':('ISSUE','问题',['发生了什么','影响范围','关联记录','状态']),
 'Failure':('FAIL','失败尝试',['发生了什么','发生位置','尝试过什么','为什么无效','根因候选','证据','解决方式']),
 'Solution':('SOL','解决方案',['关联问题或失败','采取措施','验证证据','适用条件']),
 'Lesson':('LESSON','教训',['关联项目','失败与解决过程','教训候选','证据','适用边界']),
 'Experience':('EXPER','长期经验',['跨项目证据','反例','经重复验证的经验','适用条件','复用记录']),
 'SOP':('SOP','标准操作',['版本','目标','材料与设备','步骤','QC 与异常处理','适用条件','审核与生效']),
 'Method':('METHOD','方法',['方法依据','物理模型与假设','输入与单位','处理步骤','验证数据','版本与局限']),
 'ExperimentPlan':('PLAN','实验设计',['Gap / Question / Hypothesis','设计与 DoE','独立样品与批次','制样重复与重复扫描','测量日期与随机化','对照与样品参考配对','仪器与校准','环境条件','统计计划','原始数据归档']),
 'StatisticalPlan':('STAT','统计计划',['研究问题与终点','独立统计单位','样本量依据','按样品或批次划分','训练折内拟合预处理与特征选择','基线模型','调参范围与过程','不确定性评估','盲法与排除标准']),
 'ExperimentIndex':('EXP','实验索引',['RSpace External ID / URI','状态','Sample / Batch','Treatment / Environment / Deviation','SOP / Instrument / Calibration','Raw Data ID / URI / checksum','QC']),
 'SampleIndex':('S','样品索引',['RSpace URI','材料批次','独立样品','制样重复','处理','容器与位置']),
 'InstrumentIndex':('INST','仪器索引',['RSpace URI','型号','状态','校准记录']),
 'CalibrationIndex':('CAL','校准索引',['RSpace URI','仪器','日期与有效期','证书','状态']),
 'Result':('R','结果',['RUN ID','输入版本','方法','指标与不确定性','来源与局限']),
 'Claim':('C','论断',['论断','Supports / Contradicts / Inconclusive','证据定位','适用条件','限制']),
 'Concept':('CON','概念',['定义','来源与定位','适用边界','同义词']),
 'Figure':('FIG','图与谱系',['图产物 URI / checksum','多来源 Result / RUN','Claim','Dataset ID / version','代码版本与环境','缺失的来源项']),
 'NextExperiment':('NEXT','下一步实验',['建议','依据','待核条件','风险']),
 'Review':('REVIEW','项目复盘',['最终结果','决策','失败与解决','教训与经验','SOP 更新','关键发现','风险','会议','未解决问题']),
 'Closure':('CLOSE','项目关闭',['项目状态','关闭清单','独立恢复证据','项目总结与未解决 Gap']),
 'Paper':('OUT-P','论文输出',['稿件路径','关联 Claim / Figure / Result','引用核查','版本与发布状态']),
 'Patent':('PAT','专利',['内容路径','关联证据','版本与状态']),
 'DatasetOutput':('OUT-D','数据集输出',['Dataset ID / version','归档位置','校验值','许可与发布状态']),
 'Software':('SOFT','软件输出',['Git URI / tag / commit','环境锁','验证','发布状态']),
 'Protocol':('PROTOCOL','协议输出',['SOP / Method','版本','审核与发布']),
 'Presentation':('PRES','演示输出',['文件位置','来源图与结果','版本']),
 'Report':('REPORT','报告',['文件位置','问题','证据与结论','版本']),
}
TYPES.update({
 'BatchIndex':('B','材料批次索引',['RSpace URI','材料来源与批号','样品关系','处理与环境']),
 'QC':('QC','质量控制',['RUN / EXP / Dataset','批准的方法与阈值','SNR / Reference Drift / Time-zero Shift','Water Vapor / Dynamic Range','温度 / 湿度 / 仪器状态','PASS / WARNING / FAIL','Issue / Failure 候选']),
 'PipelineIndex':('PIPE','流程索引',['Git URI / commit','DVC stage / version','输入与输出','参数','批准的方法与测试']),
 'ModelIndex':('M','模型索引',['RUN ID','数据划分','预处理与特征选择','基线与调参','不确定性','模型产物 URI / checksum']),
 'Milestone':('MS','里程碑',['项目','目标与验收','时间','状态']),
 'Task':('TASK','任务',['项目','任务','负责人','截止时间','状态']),
 'Risk':('RISK','风险',['项目','风险','依据','影响','应对与验证'])
})
JUDGMENTS={'Gap','Hypothesis','Claim','Concept','Failure','Lesson','Experience','SOP','NextExperiment'}
OUTPUT_TYPES={'Paper','Patent','DatasetOutput','Software','Protocol','Presentation','Report'}
CLOSURE=['Raw Data 归档','Dataset 冻结','Git Tag','Environment 冻结','Figure 可复现','Decision 整理','Failure 整理','Lesson 整理','Experience 候选审核','SOP 更新','Paper 关联','Dataset 关联','软件版本记录','未解决 Research Gap 记录','项目总结']


def templates():
    import material_roles
    return [{'kind':kind,'label':v[1],'prefix':v[0],'fields':v[2],'body':template(kind),
             'knowledge':kind in material_roles.KNOWLEDGE_RECORD_TYPES} for kind,v in TYPES.items()]


def template(kind):
    if kind not in TYPES:raise ValueError('未知记录类型')
    result='\n\n'.join('## '+f+'\n\n待填写。' for f in TYPES[kind][2])+'\n'
    if kind=='Closure':
        result+='\n'+'\n'.join('- [ ] '+f for f in CLOSURE)+'\n'
    if kind.endswith('Index'):
        result+='\n正式实验事实在 RSpace 填写；部署前此文件仅为待接入索引，不能充当正式 ELN。\n'
    return result


def create(data):
    import material_roles
    entry=data.get('entry')
    if entry not in {None,'knowledge','project','output'}:raise ValueError('新建入口无效。')
    if entry=='knowledge' and data.get('kind') not in material_roles.KNOWLEDGE_RECORD_TYPES:
        raise ValueError('知识区只能新建知识笔记，项目过程请在项目中记录。')
    if entry=='output' and data.get('kind') not in OUTPUT_TYPES:raise ValueError('产出区请选择产出记录类型。')
    kind=data.get('kind');project=data.get('project') or '山药';k.lines(project)
    if kind=='Decision':
        import uuid
        return decision({**data,'body':data.get('body') or template('Decision'),
                         'request_id':data.get('request_id') or uuid.uuid4().hex})
    if kind not in TYPES:raise ValueError('记录类型不存在')
    title=data.get('title','').strip();body=data.get('body') or template(kind)
    if not title or len(title)>200 or not isinstance(body,str) or len(body)>100000 or k.FRONT.match(body):
        raise ValueError('请填写有效标题和正文')
    paper_ids=data.get('paper_ids',[])
    known={p['id'] for p in w.read_json(w.LIBRARY,{'records':[]})['records']}
    if not isinstance(paper_ids,list) or len(paper_ids)>100 or any(not isinstance(i,str) or i not in known for i in paper_ids):
        raise ValueError('请选择已登记论文')
    store=Store();identifier=store.allocate(TYPES[kind][0])
    path=w.KB/'笔记'/project/TYPES[kind][1]/(identifier+'.md')
    relative=path.relative_to(w.KB).as_posix()
    role=('knowledge' if entry=='knowledge' else 'project_process' if entry=='project' else
          material_roles.interpret({'type':'research_record','record_type':kind},relative)['content_role'])
    text=k.properties('',{'id':identifier,'type':'research_record','record_type':kind,'title':title,'project':project,
        'content_role':role,'global_knowledge':role=='knowledge','review_owner':'SQLite',
        'paper_ids':list(dict.fromkeys(paper_ids))})+'# '+title+'\n\n'+body.rstrip()+'\n'
    with k.editing():
        w.atomic_text(path,text)
        row=store.put_node(identifier,kind,'Markdown',project=project,uri=relative,
                           status='CANDIDATE' if kind in JUDGMENTS else 'DRAFT',
                           data={'title':title,'document_sha256':w.digest(('# '+title+'\n\n'+body.rstrip()+'\n').rstrip()),'source':'human-input'})
    return {**row,'path':relative}


def decision_detail(project, identifier):
    node=Store().node(identifier)
    if not node or node['kind']!='Decision' or node['project']!=project:raise ValueError('决定不存在。')
    path=k.path_for(node['uri']);raw=path.read_text('utf-8-sig');meta,body,_=k.split(raw)
    heading='# '+str(meta.get('title',node['data'].get('title','')))
    if body.startswith(heading+'\n'):body=body[len(heading):].lstrip('\n')
    return {**node,'title':meta.get('title',node['data'].get('title','')),'body':body,
            'fingerprint':w.digest(raw),'path':node['uri']}


def decision_plan(project, identifier):
    """The plan text a decision relied on: current version, a historical one, or unavailable.

    Only reads the stored document row, existing versions and the files themselves; it never
    triggers catalog reconciliation, so opening an old decision cannot change its review state.
    """
    node=Store().node(identifier)
    if not node or node['kind']!='Decision' or node['project']!=project:raise ValueError('决定不存在。')
    context=(node.get('data') or {}).get('context') or {}
    plan=context.get('plan') or {}
    document=plan.get('document_id');sha=plan.get('sha')
    if not document:raise ValueError('这条决定没有登记依据方案。')
    import workspace_catalog as catalog
    row=catalog.stored_document(document)
    base={'document_id':document,'title':row.get('title'),'path':row.get('path')}
    path=(w.ROOT/row['path']).resolve()
    try:
        raw=path.read_text('utf-8-sig');body=k.split(raw)[1]
    except OSError:
        return {**base,'state':'unavailable','body':None}
    if not sha or w.digest(body.rstrip())==sha:
        return {**base,'state':'current','body':body,'version':None}
    for candidate in catalog.versions(document):
        try:value=catalog.version(document,candidate['id'])
        except (ValueError,OSError):continue
        text=value.get('body') or ''
        if w.digest(text.rstrip())==sha:
            return {**base,'state':'historical','body':text,'version':candidate['id'],'created':candidate.get('created')}
    return {**base,'state':'unavailable','body':None}


def _finish_decision(store, key, intent):
    """Each durable stage can be resumed without allocating another identity."""
    path=k.path_for(intent['path']);raw=path.read_text('utf-8-sig')
    if w.digest(raw)!=intent['after']:raise ValueError('决策原稿已变化，保留新稿待核对。')
    meta,body,_=k.split(raw);node=store.node(intent['id'])
    if not node or node['data'].get('operation')!=key:
        payload={'title':meta['title'],'document_sha256':w.digest(body.rstrip()),
                 'source':intent['source'],'operation':key,
                 'confirmed_sha256':w.digest(body.rstrip()) if intent['confirm'] else None}
        if intent.get('context'):payload['context']=intent['context']
        node=store.put_node(intent['id'],'Decision','Markdown',project=intent['project'],uri=intent['path'],
            status='CANDIDATE',expected=intent['revision'],data=payload)
    if intent['confirm'] and node['status']=='CANDIDATE':
        store.review(node['id'],node['revision'],'VERIFIED','本人选择并确认此版本的决定；科学证据另行核查。')
    with store.connection() as db:
        store.log(db,'decision.saved',intent['id'],{'project':intent['project'],'confirmed':intent['confirm']})
        db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)',
                   (key,__import__('research_store').encode({**intent,'state':'completed'}),w.now()))


def recover_decisions(project,store):
    prefix='decision-operation:'+project+':'
    with store.connection() as db:
        pending=[(r[0],json.loads(r[1])) for r in db.execute(
            'SELECT key,value FROM cursors WHERE substr(key,1,?)=?',(len(prefix),prefix))]
    for oldkey,intent in pending:
        if intent.get('state')!='pending':continue
        path=k.path_for(intent['path'],existing=False);raw=path.read_text('utf-8-sig') if path.exists() else ''
        if w.digest(raw)==intent['after']:_finish_decision(store,oldkey,intent)
        elif w.digest(raw)!=intent['before']:raise ValueError('有未完成决定且原稿已变化，请先核对。')


def decision(data):
    import project_profiles as profiles
    from research_store import encode
    project=data.get('project') or '山药';request=data.get('request_id')
    if not isinstance(request,str) or not 1<=len(request)<=200 or any(c in request for c in '\r\n\x00'):
        raise ValueError('请提供有效request_id。')
    title=data.get('title');body=data.get('body')
    if not isinstance(title,str) or not title.strip() or len(title)>200 or any(c in title for c in '\r\n\x00'):
        raise ValueError('请填写200字以内的标题。')
    if not isinstance(body,str) or not body.strip() or len(body)>100000 or k.FRONT.match(body) or '\x00' in body:
        raise ValueError('请填写决策正文。')
    confirm=data.get('confirm',False)
    if type(confirm) is not bool:raise ValueError('确认方式无效。')
    source=data.get('source','human-input')
    if source not in ('human-input','ai'):raise ValueError('来源无效。')
    if source=='ai' and confirm:raise ValueError('AI建议先存草稿，核对后由本人确认。')
    context=data.get('context')
    if context is not None:
        if not isinstance(context,dict) or set(context)-{'scope','question_id','plan','task_ids'}:
            raise ValueError('决定范围无效。')
        scope=context.get('scope','project')
        if scope not in ('project','question'):raise ValueError('决定范围无效。')
        question=context.get('question_id')
        if scope=='question' and not (isinstance(question,str) and question.strip()):raise ValueError('问题层选择需要指定研究问题。')
        if question is not None and (not isinstance(question,str) or len(question)>120 or any(c in question for c in '\r\n\x00')):
            raise ValueError('决定关联问题无效。')
        plan=context.get('plan')
        if plan is not None:
            if not isinstance(plan,dict) or set(plan)-{'document_id','sha'}:raise ValueError('依据方案格式无效。')
            identifier=plan.get('document_id');sha=plan.get('sha')
            if identifier is not None:
                if not isinstance(identifier,str) or not re.fullmatch(r'DOC-[0-9a-f]{20}',identifier):raise ValueError('依据方案编号无效。')
                if sha is not None and (not isinstance(sha,str) or not re.fullmatch(r'[0-9a-f]{64}',sha)):raise ValueError('依据方案版本无效。')
                plan={'document_id':identifier}
                if sha:plan['sha']=sha
            else:plan=None
        context={'scope':scope}
        if question:context['question_id']=question
        if isinstance(context,dict) and context.get('scope')=='project':context.pop('question_id',None)
        if plan:context['plan']=plan
    store=Store();prefix='decision-operation:'+project+':'
    key=prefix+request
    signature=w.digest(encode({n:v for n,v in data.items() if n not in ('request_id','fingerprint','revision')}))
    with profiles.lifecycle_lock(project),k.editing():
        if profiles.get(project)['archived']:raise ValueError('请先恢复项目后记录决定。')
        recover_decisions(project,store)
        import project_tasks as work
        task_path=work.path_for(project)
        work._recover(project,task_path.read_text('utf-8-sig') if task_path.exists() else '',store)
        intent=store.cursor(key,{})
        if intent and intent['payload_hash']!=signature:raise ValueError('同一request_id不能用于不同内容。')
        if intent.get('state')=='completed':
            node=store.node(intent['id']);path=k.path_for(intent['path'])
            return {**node,'path':intent['path'],'fingerprint':w.digest(path.read_text('utf-8-sig')),'reused':True}
        identifier=intent.get('id') or data.get('id') or store.allocate('DEC')
        old=store.node(identifier)
        if data.get('id') and (not old or old['kind']!='Decision' or old['project']!=project):raise ValueError('决定不存在。')
        relative=old['uri'] if old else f'笔记/{project}/决策日志/{identifier}.md'
        path=k.path_for(relative,existing=False);before=path.read_text('utf-8-sig') if path.exists() else ''
        if old and (data.get('revision')!=old['revision'] or data.get('fingerprint')!=w.digest(before)):
            raise ValueError('决定或原稿版本已变化，请核对后重新保存；输入保留。')
        if not old and before and not intent:raise ValueError('原稿已存在，未覆盖。')
        content='# '+title.strip()+'\n\n'+body.rstrip()+'\n'
        fields={'id':identifier,'type':'research_record','record_type':'Decision',
            'title':title.strip(),'project':project,'review_owner':'SQLite',
            'content_role':'project_process','global_knowledge':False}
        if context:fields['context']=context
        after=k.properties(before,fields)
        meta,_,front=k.split(after);after=(after[:front.end()] if front else '')+content
        intent={**intent,'state':'pending','payload_hash':signature,'id':identifier,'project':project,
                'path':relative,'before':w.digest(before),'after':w.digest(after),'revision':old['revision'] if old else None,
                'confirm':confirm,'source':source,'context':context}
        store.commit_page(key,[],intent)
        k.persist(path,before,after,w.KB.resolve())
        _finish_decision(store,key,intent)
        return {**store.node(identifier),'path':relative,'fingerprint':w.digest(after),'reused':False}


def create_relation(data):
    """Resolve visible materials to stable IDs without requiring prior AI analysis."""
    import workspace_catalog as catalog
    from relation_schema import RELATIONS
    if data.get('kind') not in RELATIONS:raise ValueError('请选择已登记的关系类型')
    if any(not isinstance(data.get(key),str) or not data[key].strip() or len(data[key])>200 for key in ('source','target')):
        raise ValueError('请选择有效的关系两端资料')
    evidence=data.get('evidence')
    if not isinstance(evidence,list) or not evidence or any(not isinstance(e,dict) for e in evidence):
        raise ValueError('请提供有效的证据位置与出处')
    if not isinstance(data.get('conditions',''),str) or len(data.get('conditions',''))>10000:
        raise ValueError('适用条件最多 1 万字')
    project=data.get('project') or '山药';k.lines(project)
    docs=catalog.rows(project)
    papers=w.read_json(w.LIBRARY,{'records':[]})['records']
    store=Store()
    aliases={}
    for endpoint in (data.get('source'),data.get('target')):
        existing=store.node(endpoint) if isinstance(endpoint,str) else None
        doc=next((d for d in docs if endpoint in (d['id'],d.get('record_id')) or
                  existing and existing['owner']=='Markdown' and existing.get('uri') in (d.get('kb_path'),d['path'])),None)
        if doc:
            if doc['archived'] or doc['visibility']=='system':raise ValueError('资料已归档或不在日常科研范围，请刷新后选择')
            identifier=doc.get('record_id') or (existing['id'] if existing else doc['id']);old=store.node(identifier)
            if not old:
                store.put_node(identifier,'Document','Markdown',project=doc['project'],uri=doc.get('kb_path') or doc['path'],
                               status='INDEXED',data={'title':doc['title'],'doc_id':doc['id'],'document_sha256':doc['sha']})
            aliases[endpoint]=identifier
            continue
        paper=next((p for p in papers if p['id']==endpoint),None)
        if paper:
            old=store.node(endpoint)
            if not old:
                store.put_node(endpoint,'Paper','Zotero',project=paper.get('project') or '共享',external_id=paper.get('zotero_key'),
                               uri='zotero://select/library/items/'+paper['zotero_key'] if paper.get('zotero_key') else paper.get('url'),
                               status='INDEXED',data={'title':paper['title']})
            aliases[endpoint]=endpoint
            continue
        node=store.node(endpoint) if isinstance(endpoint,str) else None
        if not node or node['project'] not in (project,'共享','') or node['owner']=='Markdown':
            raise ValueError('关系对象不存在或已退出日常资料，请刷新')
        aliases[endpoint]=endpoint
    source,target=aliases[data['source']],aliases[data['target']]
    if source==target:raise ValueError('请选择不同的起点和目标')
    return {'id':store.relation(source,target,data.get('kind'),data.get('evidence'),data.get('conditions',''),expected=data.get('revision'))}


def _section_nodes(project,kinds=None,identifiers=None):
    store=Store();query='SELECT * FROM nodes WHERE 1=1';arguments=[]
    if kinds:
        query+=' AND kind IN ('+','.join('?' for _ in kinds)+')';arguments.extend(kinds)
    if identifiers is not None:
        query+=' AND id IN (SELECT value FROM json_each(?))';arguments.append(json.dumps(list(identifiers)))
    if project:
        query+=' AND project IN (?,?)';arguments.extend([project,'共享'])
    with store.connection() as db:rows=db.execute(query+' ORDER BY created DESC',arguments).fetchall()
    return [store.decode_node(row) for row in rows]


def status_for_prose(node, content_sha):
    if node['owner']=='Markdown' and node['data'].get('document_sha256')!=content_sha:
        if node['kind'] in JUDGMENTS or node['kind']=='Decision' and node['status']=='VERIFIED':
            return 'CANDIDATE'
    return node['status']


def reconcile(project=None, *, kinds=None, identifiers=None):
    store=Store()
    read=lambda:_section_nodes(project,kinds,identifiers) if kinds or identifiers is not None else store.nodes(project)
    for node in read():
        if node['owner']!='Markdown' or not node.get('uri'):continue
        try:
            path=k.path_for(node['uri']);_,body,_=k.split(path.read_text('utf-8-sig'))
        except (OSError,ValueError):continue
        content=w.digest(body.rstrip())
        if node['data'].get('document_sha256')==content:continue
        # Any prose modification invalidates a scientific review; audit retains old review.
        status=status_for_prose(node,content)
        store.put_node(node['id'],node['kind'],node['owner'],project=node['project'],uri=node['uri'],
                       external_id=node['external_id'],status=status,expected=node['revision'],
                       data={**node['data'],'document_sha256':content})
    return read()


def requires_review(node):
    """Human work excludes rebuildable AI indexes and ordinary project records."""
    return (node.get('status')=='CANDIDATE' and node.get('kind') in JUDGMENTS
            and node.get('owner')!='KnowledgeExtraction')


def review_relation(edge):
    return (edge.get('status')=='CANDIDATE'
            and edge.get('kind') not in {'DerivedFrom','About','AssociatedWith','Uses','Addresses'})


def section(project,name):
    """Read the records used by a page without its unrelated graph or audit."""
    if name=='suggestions':return suggestion_index(project)
    kinds={'lab':('ExperimentIndex','SampleIndex','BatchIndex','Container','InstrumentIndex','CalibrationIndex','SOP','QC'),
           'received':('Dataset',),'figures':('Figure','Result'),
           'review':tuple(sorted(JUDGMENTS))}.get(name)
    if not kinds:raise ValueError('未知科研记录范围')
    nodes=reconcile(project,kinds=kinds)
    if name=='review':nodes=[n for n in nodes if requires_review(n)]
    return {'nodes':nodes,'section':name,'project':project}


def suggestion_index(project):
    """Thin optional suggestions; full evidence is loaded only when opened."""
    store=Store()
    with store.connection() as db:
        rows=db.execute("SELECT r.* FROM relations r JOIN nodes s ON s.id=r.source JOIN nodes t ON t.id=r.target "
            "WHERE r.status='CANDIDATE' AND s.owner!='KnowledgeExtraction' AND t.owner!='KnowledgeExtraction' "
            "ORDER BY r.created DESC").fetchall()
        nodes=db.execute("SELECT id,kind,owner,project,uri,json_extract(data,'$.title') AS title FROM nodes "
            "WHERE owner!='KnowledgeExtraction'").fetchall()
    from relation_discovery import current_candidate,managed,stale,inputs
    current=inputs(project) if any(managed({**dict(r),'evidence':json.loads(r['evidence'])}) for r in rows) else None
    owned={n['id'] for n in nodes if n['project'] in (project,'共享')}
    visible=owned|set(current or {})
    edges=[]
    for row in rows:
        edge=dict(row)
        if not review_relation(edge):continue
        evidence=json.loads(edge.pop('evidence'))
        edge.update(evidence_count=len(evidence),evidence=[],evidence_deferred=True)
        full={**edge,'evidence':evidence}
        endpoints={edge['source'],edge['target']}
        if managed(full):
            if not endpoints<=current.keys():continue
            edge['stale']=stale(full,current)
        else:
            if not endpoints&owned:continue
            edge['stale']=not current_candidate(full)
        edges.append(edge)
    return {'nodes':[{**dict(n),'data':{'title':n['title'] or n['id']}} for n in nodes if n['id'] in visible],
            'relations':edges,'section':'suggestions','project':project}


def review_item(project,identifier):
    store=Store()
    with store.connection() as db:
        row=db.execute('SELECT * FROM relations WHERE id=?',(identifier,)).fetchone()
    if not row:raise ValueError('关联建议不存在，请刷新列表。')
    edge=dict(row);edge['evidence']=json.loads(edge['evidence'])
    from relation_discovery import current_candidate,managed,stale,inputs
    if managed(edge):
        current=inputs(project)
        if not {edge['source'],edge['target']}<=current.keys():raise ValueError('关联建议已退出当前知识范围。')
        edge['stale']=stale(edge,current)
    else:
        endpoints=[store.node(edge[key]) for key in ('source','target')]
        if not any(n and n['project'] in (project,'共享') for n in endpoints):
            raise ValueError('关联建议不属于当前项目。')
        edge['stale']=not current_candidate(edge)
    return edge


def import_identities():
    store=Store()
    for p in w.read_json(w.LIBRARY,{'records':[]})['records']:
        store.put_node(p['id'],'Paper','Zotero',external_id=p.get('zotero_key'),
                       uri='zotero://select/library/items/'+p['zotero_key'] if p.get('zotero_key') else p.get('url'),
                       project=p.get('project') or '共享',status='INDEXED',
                       data={key:p.get(key) for key in ('title','doi','reading_status','identity_status')})
    for p in (w.KB/'项目').iterdir():
        if p.is_dir():
            # Existing names/IDs are not renamed; the canonical stable identity is mapped explicitly.
            existing=next((n for n in store.nodes(p.name,'Project') if n['owner']=='Markdown'),None)
            if not existing:
                store.put_node(store.allocate('THZ-P'),'Project','Markdown',project=p.name,
                               uri=f'项目/{p.name}/当前课题状态.md',status='ACTIVE',data={'title':p.name,'legacy_name':p.name})


def trace(identifier,store=None):
    store=store or Store();nodes={n['id']:n for n in store.nodes()}
    if identifier not in nodes:raise ValueError('来源 ID 不存在')
    all_edges=store.relations()
    from relation_discovery import evidence_inputs,stale
    current=evidence_inputs([edge for edge in all_edges if edge['status']=='VERIFIED'])
    obsolete={edge['id'] for edge in all_edges if edge['status']=='VERIFIED' and stale(edge,current)}
    edges=[e for e in all_edges if e['status']=='VERIFIED' and e['id'] not in obsolete and not any(v.get('stale') for v in e['evidence'])]
    allowed_runs=None
    if nodes[identifier]['kind'] in ('Figure','Result','RUN'):
        ancestors={identifier};upstream={identifier}
        while upstream:
            next_ids={e['target'] for e in edges if e['source'] in upstream and e['kind'] in ('DerivedFrom','ProducedBy','Uses')}-ancestors
            if not next_ids:break
            ancestors|=next_ids;upstream=next_ids
        allowed_runs={i for i in ancestors if nodes.get(i,{}).get('kind')=='RUN'}
        # Shared inputs, environments and code do not pull every other run into
        # this output's lineage. Multiple explicitly derived RUN branches remain.
        edges=[e for e in edges if all(nodes.get(i,{}).get('kind')!='RUN' or i in allowed_runs for i in (e['source'],e['target']))]
    selected={identifier};front={identifier}
    while front:
        adjacent={e['source'] for e in edges if e['target'] in front and e['status']=='VERIFIED'} | {e['target'] for e in edges if e['source'] in front and e['status']=='VERIFIED'}
        front=adjacent-selected
        if not front:break
        selected|=front
    chain=[nodes[i] for i in sorted(selected)]
    relations=[e for e in edges if e['source'] in selected and e['target'] in selected]
    pending=[{**e,'stale':e['id'] in obsolete} for e in all_edges if (e['status']=='CANDIDATE' or e['id'] in obsolete) and (e['source'] in selected or e['target'] in selected)]
    documents=__import__('workspace_catalog').rows(do_refresh=False) if any(n['owner']=='Markdown' for n in chain) else []
    for node in chain:
        doc=next((d for d in documents if d.get('record_id')==node['id'] or d['id']==node['data'].get('doc_id') or node['uri'] in (d['path'],d.get('kb_path'))),None)
        node['navigation']={'route':'document','id':doc['id']} if doc else {'route':'paper','id':node['id']} if node['kind']=='Paper' and node['owner']=='Zotero' else None
    expected={'RUN','Dataset','Environment','Code','Result'} if nodes[identifier]['kind']=='Figure' else set()
    return {'root':identifier,'nodes':chain,'relations':relations,'pending_relations':pending,
            'relation_types':__import__('relation_schema').definitions(),
            'views':__import__('provenance_views').views(chain,relations),
            'missing':sorted(expected-{n['kind'] for n in chain}),
            'scope':'仅沿已登记且已核实的关系回溯；六类视图保留实际分支，阶段排列不表示相邻对象之间存在关系。待审核关系单独提示，缺失项不补造。'}


def export_snapshot():
    path=w.KB/'关系谱系/只读快照.json'
    w.write_json(path,Store().snapshot())
    return {'path':path.relative_to(w.KB).as_posix(),'editable':False}


def view(project):
    nodes=reconcile(project)
    ids={n['id'] for n in nodes};store=Store()
    relations=[r for r in store.relations() if r['source'] in ids or r['target'] in ids]
    from relation_discovery import managed, stale, inputs
    if any(managed(r) for r in relations):
        current=inputs(project)
        relations=[{**r,'stale':stale(r,current)} if managed(r) else r for r in relations
                   if not managed(r) or {r['source'],r['target']}<=current.keys()]
    return {'nodes':nodes,'relations':relations,'relation_types':__import__('relation_schema').definitions(),
            'jobs':__import__('automation_controls').user_jobs(),'templates':templates(),'audit':store.audit(),
            'closure_checklist':CLOSURE,'rspace':__import__('rspace_connector').status()}
