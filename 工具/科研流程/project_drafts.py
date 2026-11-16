"""User-triggered project drafts; paid-call ledger is owned by the existing bridge."""
import json
import re
import knowledge as k
import workflow as w
import project_profiles as profiles
import research_prompts
from research_store import Store,encode


def _inputs(project,data,purpose):
    import project_stages as stages
    import project_knowledge as knowledge
    import project_materials as materials
    token=profiles.capture_automatic(project)
    if purpose=='stages':
        progress=stages.progress(project);overview=stages.overview(project)
        inputs=[{'id':'project-overview','title':'项目总览','body':overview['body'][:10000],'kind':'本人项目记录'}]
        if data.get('stage_id'):
            stage=stages.detail(project,data['stage_id'])
            inputs.append({'id':stage['document_id'],'title':stage['title'],'body':stages.active_body(stage['raw'])[:16000],'kind':'阶段过程'})
        context={'stages':[{'id':s['id'],'title':s['title'],'stage_status':s['stage_status']} for s in progress['stages']]}
    else:
        current=knowledge.view(project);context={};inputs=[]
        if purpose=='extract':
            source=knowledge._source(project,data)
            if not source:raise ValueError('请先选择来源记录。')
            doc=__import__('workspace_catalog').detail(source['document_id'])
            raw=__import__('workspace_catalog').bounded(doc['path']).read_text('utf-8-sig')
            text=k.split(raw)[1]
            if source.get('block_id'):text=next(e['body'] for e in stages.parse(raw)[2] if e['id']==source['block_id'])
            inputs=[{'id':doc['id'],'title':doc['title'],'body':text[:16000],'kind':'选中的过程记录'}]
        else:
            module=next((m for m in current['modules'] if m['id']==data.get('module_id')),None)
            if not module:raise ValueError('请选择本项目模块。')
            context={'module':module['title']}
            for doc in current['documents']:
                if module['id'] in current['assignments'].get(doc['id'],[]) and doc['id']!=module.get('review_document_id'):
                    inputs.append({'id':doc['id'],'title':doc['title'],'body':materials.prose(doc)[:6000],'kind':'已存知识笔记，不代表重新核查原文'})
            if not inputs:raise ValueError('模块还没有详细知识笔记，可以先手写综述或加入资料。')
    truncated=len(inputs)>12
    inputs=inputs[:12]
    signature=w.digest(encode([token,purpose,inputs,context,data.get('instruction','')]))
    return inputs,context,token,signature,truncated


def _target(data,purpose):
    if purpose=='stages':return [data.get('stage_id') or '']
    if purpose=='extract':return [data.get('source_document_id') or '',data.get('block_id') or '']
    return [data.get('module_id') or '']


def _key(project,purpose,identifier):
    return 'project-draft:'+project+':'+purpose+':'+identifier


def draft(data,purpose=None):
    project=data.get('project') or '山药';purpose=purpose or data.get('purpose','overview')
    if purpose not in {'stages','overview','extract'}:raise ValueError('起草用途无效。')
    user_instruction=data.get('instruction','')
    if not isinstance(user_instruction,str) or len(user_instruction)>4000:raise ValueError('起草要求无效或超过长度限制。')
    inputs,context,token,input_signature,truncated=_inputs(project,data,purpose)
    rules=research_prompts.bundle('project' if purpose=='stages' else 'knowledge')
    target=_target(data,purpose)
    signature=w.digest(encode([project,purpose,target,input_signature,rules['versions']]))
    identifier='DRAFT-'+signature[:24]
    key=_key(project,purpose,identifier)
    old=Store().cursor(key,{})
    if old.get('signature')==signature:return old
    from model_gateway import call_deepseek
    instruction=('只输出JSON {"candidates":[{"title":"阶段名","goal":"阶段目标","reason":"建议理由","sources":["来源ID"]}]}，最多6项，只建议后续研究阶段，不生成计划清单、执行记录、完成状态。'
                 if purpose=='stages' else '只输出JSON {"title":"标题","body":"可编辑Markdown正文","sources":["来源ID"]}。'+('提炼选中记录中的可复用知识，明确适用条件，保留失败和待核边界。' if purpose=='extract' else '根据模块已存笔记起草综述，先概括再梳理主题和详细笔记入口。'))
    system=rules['text']+'\n'+instruction+'来源只能使用所提供ID。'
    response=call_deepseek({'model':'deepseek-flash','_interactive':True,'max_tokens':5500,'messages':[{'role':'system','content':system},
        {'role':'user','content':json.dumps({'context':context,'instruction':user_instruction,'sources':inputs},ensure_ascii=False)}]})
    if response.get('error'):raise ValueError(response['error'])
    try:value=json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',response.get('answer','').strip()))
    except (ValueError,TypeError):raise ValueError('模型返回格式无效，已有原稿保持。') from None
    if not isinstance(value,dict):raise ValueError('模型返回格式无效，已有原稿保持。')
    allowed={s['id'] for s in inputs}
    rows=value.get('candidates') if purpose=='stages' else [value]
    if not isinstance(rows,list) or not 1<=len(rows)<=6:raise ValueError('候选数量或格式无效。')
    checked=[]
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get('title'),str) or not 1<=len(row['title'])<=200:raise ValueError('候选标题格式无效。')
        sources=row.get('sources',[])
        if not isinstance(sources,list) or any(not isinstance(i,str) or i not in allowed for i in sources):raise ValueError('草稿引用了未提供来源。')
        names=('goal','reason') if purpose=='stages' else ('body',)
        if any(not isinstance(row.get(n,''),str) or len(row.get(n,''))>100000 for n in names):raise ValueError('候选正文格式无效。')
        checked.append({name:row.get(name,'') for name in ('title',*names)}|{'sources':sources})
    result={'id':identifier,'project':project,'purpose':purpose,'signature':signature,'input_signature':input_signature,
            'target':target,'instruction':user_instruction,'lifecycle_revision':token,'rule_versions':rules['versions'],
            'candidates':checked if purpose=='stages' else [],'sources':[{n:v for n,v in s.items() if n!='body'} for s in inputs],
            'coverage_truncated':truncated,'created':w.now(),**(checked[0] if purpose!='stages' else {})}
    with profiles.automatic_commit(project,token):
        if _inputs(project,data,purpose)[3]!=input_signature:raise ValueError('生成期间项目或来源已变化，请重新核对后起草。')
        store=Store();current=store.cursor(key,{})
        if current.get('signature')==signature:return current
        store.commit_page(key,[],result)
        return result


def check_draft(data,purpose=None):
    project=data.get('project') or '山药';purpose=purpose or data.get('draft_purpose','overview')
    if purpose not in {'stages','overview','extract'}:raise ValueError('草稿用途无效。')
    identifier=data.get('draft_id')
    message='草稿或来源已变化，请重新起草或核对后手写。'
    if not isinstance(identifier,str) or not re.fullmatch(r'DRAFT-[a-f0-9]{24}',identifier):raise ValueError(message)
    store=Store()
    saved=store.cursor(_key(project,purpose,identifier),{})
    if not saved:
        # Previously delivered drafts remain usable while their original inputs match.
        saved=store.cursor('project-draft:'+project+':'+purpose,{})
    target=_target(data,purpose)
    if saved.get('id')!=identifier or saved.get('target',target)!=target:
        raise ValueError(message)
    current=_inputs(project,{**data,'instruction':saved.get('instruction',data.get('instruction',''))},purpose)[3]
    if current!=saved.get('input_signature',saved.get('signature')):
        raise ValueError(message)
