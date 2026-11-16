import project_profiles as lifecycle
"""One auditable closure checklist, tied to current evidence rather than loose reports."""
from pathlib import Path
from filelock import FileLock
import workflow as w
import knowledge as k
import workspace_catalog as catalog
import research_records as records
from research_store import Store,encode

LABELS=[*records.CLOSURE,'数据、代码、环境、图与谱系独立恢复']


def _lock():
    w.DATA.mkdir(parents=True,exist_ok=True)
    return FileLock(str(w.DATA/'项目关闭.lock'),timeout=15)


def overview(project):
    k.lines(project);records.reconcile();store=Store()
    nodes=store.nodes(project)
    projects=[n for n in nodes if n['kind']=='Project' and n['project']==project]
    project_node=next((n for n in projects if n['data'].get('legacy_name')==project),projects[0] if projects else None)
    docs=[d for d in catalog.rows(project) if not d['archived'] and d['visibility']!='system' and d.get('review_status') not in ('RETIRED','REJECTED')]
    sources={}
    for d in docs:
        sources[d.get('record_id') or d['id']]={'id':d.get('record_id') or d['id'],'doc_id':d['id'],'title':d['display_title'],'kind':d['kind'],'fingerprint':d['sha'],'project':d['project'],'status':d['review_status'] if 'review_status' in d else '见原稿'}
    for n in nodes:
        if n['id'] in sources or n['owner'] in ('Markdown','KnowledgeExtraction') or n['status'] in ('RETIRED','REJECTED') or n['data'].get('formal') is False:continue
        sources[n['id']]={'id':n['id'],'doc_id':None,'title':n['data'].get('title',n['id']),'kind':n['kind'],'project':n['project'],'status':n['status'],'fingerprint':w.digest(encode([n['revision'],n['data']]))}
    saved=store.cursor('project-closure:'+project,{'revision':0,'checks':{}});checks=[]
    for i,label in enumerate(LABELS):
        identifier='closure-'+str(i+1);row=saved['checks'].get(identifier,{'state':'pending','evidence':[],'reason':''})
        stale=any(e['source'] not in sources or sources[e['source']]['fingerprint']!=e['fingerprint'] for e in row.get('evidence',[]))
        if i==8 and any(n['kind']=='Experience' and n['status']=='CANDIDATE' and n['project']==project for n in nodes):stale=True
        checks.append({**row,'id':identifier,'label':label,'stale':stale,'complete':row['state'] in ('checked','not_applicable') and not stale})
    count=sum(c['complete'] for c in checks)
    return {'project':project,'project_id':project_node['id'] if project_node else None,'project_status':project_node['status'] if project_node else 'ACTIVE',
            'revision':saved['revision'],'checks':checks,'sources':list(sources.values()),'completed':count,'total':len(checks),'ready':count==len(checks),
            'closed':saved.get('closed'),'scope':'每项由人核对当前证据；资料改变后重新提示。勾选不代替原生恢复、实际复跑或科研判断审核。'}


def save(body):
    project=body.get('project','山药')
    with _lock():
        current=overview(project);store=Store()
        if body.get('revision')!=current['revision']:raise ValueError('关闭检查已在其他窗口更新，请刷新后再核对')
        if current['project_status']=='CLOSED':raise ValueError('项目已经关闭，关闭证据保留在原记录中')
        check=next((r for r in current['checks'] if r['id']==body.get('id')),None)
        if not check or body.get('state') not in ('pending','checked','not_applicable'):raise ValueError('请选择有效检查项和核对结果')
        reason=body.get('reason','');evidence=body.get('evidence',[])
        if not isinstance(reason,str) or len(reason)>4000 or not isinstance(evidence,list) or len(evidence)>10:raise ValueError('关闭检查说明无效')
        reason=reason.strip()
        if body['state']=='not_applicable' and len(reason)<4:raise ValueError('请说明此项为何不适用；不省略原检查项')
        if body['state']=='checked' and (not evidence or len(reason)<4):raise ValueError('请关联当前证据，并说明实际核对结果')
        sources={s['id']:s for s in current['sources']};validated=[]
        for e in evidence:
            source=sources.get(e.get('source')) if isinstance(e,dict) else None
            if not source or e.get('fingerprint')!=source['fingerprint']:raise ValueError('依据资料已变化，请重新打开后核对')
            location=e.get('location','').strip()
            if not 1<=len(location)<=2000:raise ValueError('请填写依据中的具体位置或恢复/复跑记录')
            validated.append({'source':source['id'],'fingerprint':source['fingerprint'],'location':location})
        saved=store.cursor('project-closure:'+project,{'checks':{}})
        saved.update(revision=current['revision']+1,checks={**saved['checks'],check['id']:{'state':body['state'],'evidence':validated,'reason':reason,'checked':w.now(),'actor':'local-human'}})
        store.commit_page('project-closure:'+project,[],saved)
        with store.connection() as db:store.log(db,'project.closure_check',current['project_id'] or project,{'item':check['id'],'state':body['state'],'revision':saved['revision']})
        return overview(project)


def complete(body):
    project=body.get('project','山药');summary=body.get('summary','')
    if not isinstance(summary,str) or not 10<=len(summary.strip())<=20000:raise ValueError('请填写项目总结与未解决问题，至少 10 字')
    if body.get('confirm') is not True:raise ValueError('请确认关闭当前项目')
    with lifecycle.lifecycle_lock(project),_lock(),k.editing():
        current=overview(project);store=Store();key='project-closure:'+project;saved=store.cursor(key,{'checks':{}})
        if saved.get('closed'):return saved['closed']
        intent=saved.get('intent')
        if not intent and (body.get('revision')!=current['revision'] or not current['ready']):raise ValueError('关闭检查尚未完成或证据已变化，请核对当前版本')
        node=store.node(current['project_id']) if current['project_id'] else None
        if not node or node['owner']!='Markdown':raise ValueError('项目主稿尚未登记，不能关闭')
        project_path=k.path_for(node['uri']);before=project_path.read_text('utf-8-sig');project_sha=w.digest(before)
        # The saved finalization intent makes an interrupted write resume the same record.
        if not intent:
            text='# '+project+' · 项目关闭\n\n## 项目总结与未解决问题\n\n'+summary.strip()+'\n\n## 关闭检查\n\n'
            sources={s['id']:s for s in current['sources']}
            for row in current['checks']:
                text+='- [x] '+row['label']+('（不适用）' if row['state']=='not_applicable' else '')+'：'+row['reason']+'\n'
                for e in row['evidence']:text+='  - '+sources[e['source']]['title']+'（'+e['source']+'）：'+e['location']+'；版本 '+e['fingerprint']+'\n'
            intent={'id':store.allocate('CLOSE'),'summary':summary.strip(),'project_before':project_sha,'created':w.now(),'text':text,'check_revision':current['revision']}
            saved['intent']=intent;store.commit_page(key,[],saved)
        if intent['summary']!=summary.strip():raise ValueError('上次关闭提交尚待接续，请沿已保存总结完成后再编辑')
        if project_sha!=intent['project_before'] and k.split(before)[0].get('closure_id')!=intent['id']:raise ValueError('项目主稿已变化，请先核查，未覆盖原稿')
        text=intent['text']
        identifier=intent['id'];path=(w.KB/'笔记'/project/'项目关闭'/(identifier+'.md')).resolve();relative=path.relative_to(w.KB.resolve()).as_posix()
        raw=k.properties('',{'id':identifier,'type':'research_record','record_type':'Closure','title':project+' · 项目关闭','project':project,'project_status':'CLOSED'})+text
        if path.exists() and path.read_text('utf-8-sig')!=raw:raise ValueError('已保存的关闭原稿有变化，未覆盖')
        if not path.exists():k.persist(path,'',raw,w.KB)
        store.put_node(identifier,'Closure','Markdown',project=project,uri=relative,status='VERIFIED',data={'title':project+' · 项目关闭','document_sha256':w.digest(text.rstrip()),'source':'human-closure','check_revision':intent['check_revision']})
        after=k.properties(before,{'project_status':'CLOSED','closure_id':identifier,'closed_at':intent['created']});k.persist(project_path,before,after,w.KB)
        node=store.node(node['id']);store.put_node(node['id'],node['kind'],node['owner'],project=project,uri=node['uri'],external_id=node['external_id'],expected=node['revision'],status='CLOSED',data={**node['data'],'closure_id':identifier})
        lifecycle.mark_closed(project)
        closed={'id':identifier,'path':relative,'project_status':'CLOSED','checked':intent['created']}
        store.commit_page(key,[],{**saved,'closed':closed,'revision':current['revision']+1})
        with store.connection() as db:store.log(db,'project.closed',node['id'],closed)
        return closed
