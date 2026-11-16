"""Interpret project membership once; evidence and layout remain separate owners."""
from collections import Counter
from pathlib import Path
import re
import knowledge as k
import project_questions as questions
import workflow as w
import workspace_catalog as catalog
from research_store import Store, encode


LIBRARY_TYPES=('操作卡','方案','采购与样品','背景','记录','其他')
# Copies, AI reading output and canvas notes are reachable elsewhere; a project
# library that mixes them in stops being a place to find the working originals.
LIBRARY_EXCLUDED=('/旧稿归档/','/科研工作区重构/','/文献/AI阅读记录/','/画布笔记/')


def material_history():
    """Collection-level access to project materials outside global knowledge."""
    return [d for d in catalog.rows(reconcile_records=False) if d.get('content_role')!='knowledge']


def library_type(doc):
    path=str(doc.get('path') or '').replace('\\','/');name=Path(path).name
    text=' '.join(str(doc.get(key) or '') for key in ('title','display_title','path'))
    if '操作卡' in text:return '操作卡'
    if name in {'当前课题状态.md','任务.md','研究主线.md','方向选择.md'}:return '记录'
    if '方案' in text or '实验设计' in text:return '方案'
    if doc.get('kind') in ('项目记录','决策日志','会议','研究日志','项目复盘') or doc.get('record_type') in (
            'Decision','Meeting','DailyLog','Issue','Failure','Solution'):
        return '记录'
    if doc.get('content_role')=='project_reference' or '背景' in text:return '背景'
    if any(word in text for word in ('采购','样品','材料','制样','制粉','压片')):return '采购与样品'
    return '其他'


def library(project):
    """Current non-knowledge originals of one project, grouped for the fixed entry."""
    k.line_path(project,w.KB)
    items=[]
    for doc in catalog.rows(project=project):
        if doc.get('project')!=project or doc.get('content_role')=='knowledge':continue
        if doc.get('visibility')=='system' or doc.get('archived'):continue
        if doc.get('record_type')=='Stage':continue
        path=str(doc.get('path') or '').replace('\\','/')
        if any(part in path for part in LIBRARY_EXCLUDED):continue
        items.append({'id':doc['id'],'title':doc.get('display_title') or doc.get('title') or path,
                      'type':library_type(doc),'kind':doc.get('kind') or '','path':path,
                      'kb_path':doc.get('kb_path') or '','excerpt':doc.get('excerpt') or '',
                      'modified':doc.get('file_modified') or 0,'editable':doc.get('editable',True) and path.startswith('科研知识库/项目/'+project+'/'),
                      'content_role':doc.get('content_role') or '','record_type':doc.get('record_type') or ''})
    order={name:index for index,name in enumerate(LIBRARY_TYPES)}
    items.sort(key=lambda row:(order.get(row['type'],len(order)),-(row['modified'] or 0)))
    counts=Counter(row['type'] for row in items)
    return {'project':project,'items':items,'total':len(items),
            'counts':{name:counts[name] for name in LIBRARY_TYPES if counts.get(name)}}


def create(project,data):
    """Create one typed original under the project; the request ID keeps retries idempotent."""
    if not isinstance(data,dict):raise ValueError('资料内容无效。')
    kind=str(data.get('type') or '').strip();title=str(data.get('title') or '').strip()
    body=str(data.get('body') or '')
    if kind not in LIBRARY_TYPES:raise ValueError('请选择资料类型。')
    if not title or len(title)>200:raise ValueError('资料标题不能为空，最多200字。')
    if not body.strip():raise ValueError('资料正文不能为空。')
    if len(body)>100000:raise ValueError('资料正文最多10万字。')
    root=k.line_path(project,w.KB).parent
    request=data.get('request_id')
    if not isinstance(request,str) or not re.fullmatch(r'[\w.-]{1,200}',request):raise ValueError('请提供有效 request_id。')
    from project_profiles import get,lifecycle_lock
    store=Store();key='project-material-create:'+project+':'+request
    signature=w.digest(encode([kind,title,body.rstrip()]))
    with lifecycle_lock(project),k.editing():
        profile=get(project)
        if profile['archived']:raise ValueError('项目已归档，请恢复后新建资料。')
        if data.get('lifecycle_revision',profile['lifecycle_revision'])!=profile['lifecycle_revision']:
            raise ValueError('项目状态已变化，请重新打开项目资料。')
        receipt=store.cursor(key,{})
        if receipt:
            if receipt['payload_hash']!=signature:raise ValueError('同一请求已保存其他内容，请查看原资料。')
            return receipt['result']
        folder=root/'资料'
        identifier='MAT-'+w.digest(encode([project,request]))[:16]
        path=(folder/(identifier+'.md')).resolve()
        legacy=(folder/('MAT-'+w.digest('|'.join((project,kind,title,request)))[:16]+'.md')).resolve()
        if not path.is_relative_to(root) or not legacy.is_relative_to(root):raise ValueError('资料路径超出项目。')
        relative=path.relative_to(w.ROOT.resolve()).as_posix()
        body='# '+title+'\n\n'+body.rstrip()+'\n'
        if path.exists() or legacy.exists():
            path=path if path.exists() else legacy
            relative=path.relative_to(w.ROOT.resolve()).as_posix()
            metadata,current_body,_=k.split(path.read_text('utf-8-sig'))
            if metadata.get('material_request_signature')!=signature and (path!=legacy or current_body.rstrip()!=body.rstrip()):
                raise ValueError('同一请求的资料已存在，请查看原稿。')
        else:
            metadata={'title':title,'type':'personal_note','note_category':kind,'project':project,
                      'content_role':'project_process','canvas_include':False,'created':w.now(),
                      'material_request':identifier,'material_request_signature':signature}
            w.atomic_text(path,k.properties('',metadata)+body)
        result={'document_id':catalog.identify(relative),'path':relative,'title':title,'type':kind}
        store.commit_page(key,[],{'payload_hash':signature,'result':result})
        return result


def reference_documents(project, *, base, members):
    context={'背景/个人与实验条件.md',k.project_background(project)}
    return [d for d in base['documents'].values() if d.get('content_role')=='project_reference'
            and (d['id'] in members['documents'] or d.get('kb_path') in context)
            and not d.get('archived') and d.get('visibility')!='system']


def source_snapshot(project, *, readonly=False, documents=None):
    lines=k.lines(project)['rows']  # Also validates the project directory.
    docs=catalog.rows(reconcile_records=not readonly) if documents is None else documents
    papers={p['id']:p for p in __import__('bibliography').enriched(w.read_json(w.KB/'文献/library.json',{'records':[]})['records']) if not p.get('hidden')}
    result={'project':project,'documents':{d['id']:d for d in docs},'papers':papers,'seeds':{},'groups':{},'questions':{},'process_documents':{}}
    for line in lines:
        path,raw,meta,body,line,state=questions.read(project,line['id'])
        if state.get('deleted'):continue
        identifier=line['id']
        result['questions'][identifier]=(path,raw,line,state)
        result['seeds']['q-'+identifier]={'id':'q-'+identifier,'source':{'kind':'question','question_id':identifier},'kind':'question','group':''}
    for doc in docs:
        if doc['project']!=project or doc['archived'] or doc['visibility']=='system' or doc.get('question_id'):continue
        local=(w.ROOT/doc['path']).resolve().is_relative_to((w.KB/'项目'/project).resolve())
        if local and doc.get('content_role')=='project_process' and not doc.get('stage_removed') and Path(doc['path']).name not in {'当前课题状态.md','研究主线.md','方向选择.md'}:
            result['process_documents'][doc['id']]=doc
        if doc.get('canvas_include') is False or doc.get('record_type')=='Stage':continue
        # A library-wide default project tag is not an explicit project choice.
        # New notes saved inside this project are scoped by their actual path;
        # shared/library materials enter only through the selection action.
        if not (w.ROOT/doc['path']).resolve().is_relative_to((w.KB/'项目'/project).resolve()):continue
        if Path(doc['path']).name in ('当前课题状态.md','研究主线.md','方向选择.md'):continue
        identifier=doc.get('canvas_node') or 'a-'+w.digest('doc:'+doc['id'])[:24]
        result['seeds'][identifier]={'id':identifier,'source':{'kind':'document','document_id':doc['id']},'kind':'note','group':'','origin':'auto-note'}
    return result


def snapshot(project, *, saved=None, base=None):
    base=source_snapshot(project) if base is None else base
    saved=Store().cursor('project-canvas:'+project,{'nodes':{},'papers':[]}) if saved is None else saved
    rows={**base['seeds']}
    for identifier,row in saved.get('nodes',{}).items():
        if row.get('origin')=='project-knowledge':continue
        rows[identifier]={**rows.get(identifier,{}),**row}
    documents={};history={};papers={}
    def add_paper(identifier,reason,document=None):
        if identifier not in base['papers']:return
        item=papers.setdefault(identifier,{'id':identifier,'reasons':[],'document_ids':[]})
        if reason not in item['reasons']:item['reasons'].append(reason)
        if document and document not in item['document_ids']:item['document_ids'].append(document)
    def add_document(doc,reason):
        item=documents.setdefault(doc['id'],{**doc,'content_fingerprint':doc['sha'],'reasons':[]})
        if reason not in item['reasons']:item['reasons'].append(reason)
        citations=set(doc.get('paper_citations',[]))
        for pid in doc.get('paper_ids',[]):
            add_paper(pid,'当前笔记正文引用' if pid in citations else '当前笔记关联论文',doc['id'])
    for identifier in saved.get('papers',[]):add_paper(identifier,'加入项目文献池')
    state_path=(w.KB/'项目'/project/'当前课题状态.md').resolve()
    state_doc=next((d for d in base['documents'].values() if (w.ROOT/d['path']).resolve()==state_path),None)
    if state_doc:
        citations=set(state_doc.get('paper_citations',[]))
        for identifier in state_doc.get('paper_ids',[]):
            add_paper(identifier,'项目状态原稿正文引用' if identifier in citations else '项目状态原稿关联论文')
    for row in rows.values():
        if row.get('deleted'):continue
        source=row.get('source',{});kind=source.get('kind')
        if kind=='paper':add_paper(source.get('paper_id'),'明确选用论文节点')
        elif kind=='document':
            doc=base['documents'].get(source.get('document_id'))
            if not doc or doc.get('visibility')=='system':continue
            if doc.get('archived'):
                if source.get('allow_archived') and '报告' in doc.get('kind',''):history[doc['id']]={**doc,'content_fingerprint':doc['sha'],'reasons':['明确选用历史报告']}
                continue
            add_document(doc,'项目内新笔记' if row.get('origin')=='auto-note' else '明确选用资料节点')
        elif kind in ('question','step'):
            original=base['questions'].get(source.get('question_id'))
            if not original:continue
            _,_,line,state=original
            current=state
            if kind=='step':
                if row.get('origin')!='manual':continue
                current=next((x for x in state.get('steps',[]) if x['id']==source.get('step_id') and not x.get('deleted')),None)
                if current is None:continue
            else:
                for pid in line.get('paper_ids',[]):add_paper(pid,'活动研究问题关联')
            for item in current.get('manual',[]):
                if item in state.get('excluded',[]) or item in current.get('excluded',[]):continue
                if item.startswith('paper:'):add_paper(item[6:],'活动研究节点资料')
                elif item.startswith('doc:'):
                    doc=base['documents'].get(item[4:])
                    if doc and not doc.get('archived') and doc.get('visibility')!='system':
                        add_document(doc,'活动研究节点直接选用')
            for pid in re.findall(r'\[\[文献/条目/([\w.-]+)',current.get('progress','')):add_paper(pid,'活动研究节点引用')
    excluded={row.get('source',{}).get('document_id') for row in saved.get('nodes',{}).values() if row.get('deleted')}
    for identifier,doc in base.get('process_documents',{}).items():
        if identifier not in excluded:add_document(doc,'项目过程原稿')
    signature={'documents':sorted((i,sorted(d.get('paper_ids',[]))) for i,d in documents.items()),
               'papers':sorted((i,sorted(v['reasons']),sorted(v['document_ids'])) for i,v in papers.items()),'history':sorted(history)}
    return {'project':project,'documents':documents,'papers':papers,'history':history,'membership_fingerprint':w.digest(encode(signature))}


def reference_scope(project, *, base=None, members=None):
    """Current knowledge plus the existing project process and historical references."""
    import project_knowledge as knowledge
    base=source_snapshot(project,readonly=True) if base is None else base
    saved=Store().cursor('project-canvas:'+project,{'nodes':{},'papers':[]})
    members=snapshot(project,saved=saved,base=base) if members is None else members
    current,_,paper_ids=knowledge.current_scope(project,base,members,knowledge.state(project),saved.get('papers',[]))
    documents={i:d for i,d in members['documents'].items() if d.get('content_role')!='knowledge'}
    documents.update({d['id']:d for d in current})
    papers={**members['papers']}
    for identifier in paper_ids:
        if identifier in base['papers']:
            papers.setdefault(identifier,{'id':identifier,'reasons':['项目知识引用'],'document_ids':[]})
    version=w.digest(encode([sorted((i,d.get('paper_ids',[])) for i,d in documents.items()),sorted(papers),sorted(members['history'])]))
    return {**members,'documents':documents,'papers':papers,'membership_fingerprint':version}


def selected_document_ids(project, *, saved=None, base=None):
    """Persistent choices survive archive filtering, while removals stay removed.

    This deliberately excludes automatic seeds. The caller can separately route
    a local manuscript change to its source project without scanning all prose.
    """
    saved=Store().cursor('project-canvas:'+project,{'nodes':{}}) if saved is None else saved
    selected={row.get('source',{}).get('document_id') for row in saved.get('nodes',{}).values()
              if not row.get('deleted') and row.get('origin') not in {'auto-note','project-knowledge'} and row.get('source',{}).get('kind')=='document'}
    originals=base['questions'].values() if base is not None else (
        (path,raw,line,state) for path,raw,meta,body,line,state in
        (questions.read(project,line['id']) for line in k.lines(project)['rows']))
    for _,_,line,state in originals:
        if state.get('deleted'):continue
        excluded=set(state.get('excluded',[]))
        question_row=saved.get('nodes',{}).get('q-'+line['id'],{})
        refs={item for item in state.get('manual',[]) if item not in excluded} if not question_row.get('deleted') else set()
        for step in state.get('steps',[]):
            attached=any(row.get('origin')=='manual' and not row.get('deleted') and
                         row.get('source',{})=={'kind':'step','question_id':line['id'],'step_id':step['id']}
                         for row in saved.get('nodes',{}).values())
            if attached and not step.get('deleted'):
                refs.update(item for item in step.get('manual',[]) if item not in excluded and item not in step.get('excluded',[]))
        selected.update(item[4:] for item in refs if isinstance(item,str) and item.startswith('doc:'))
    return selected-{None,''}


def prose(doc):
    path=catalog.bounded(doc['path'])
    raw=catalog.read_source(path)
    if doc.get('record_type')=='Stage':
        from project_stages import active_body
        return active_body(raw)
    return k.split(raw)[1]
