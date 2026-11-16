"""A bounded research administrator: drafts, existing skills and incremental background work."""
from __future__ import annotations
import project_profiles as lifecycle
from datetime import datetime, timedelta, timezone
import json
import re
import threading
import knowledge as k
import organization as org
import direction_discovery as directions
import workflow as w

import skill_registry
import research_prompts
SKILLS = {name:row['label'] for name,row in skill_registry.SKILLS.items()}



def schedule(project, reason, paper_id=None, **detail):
    return state.schedule(project,reason,paper_id,**detail)


def select_skill(selected,instruction):return skill_registry.select(selected,instruction)

def read_skill(name,references=()):return skill_registry.read(name,references)


from administrator_state import DEFAULTS, settings, configure, runtime, save_runtime
import administrator_state as state
import maintenance_batches as batches


def overview(project):
    import overview as views
    import ai_updates
    pending=len(views.candidates(project))+len(ai_updates.pending(project))
    return {'settings': settings(project), 'organization': org.view(project), 'discovery': directions.view(project),
            'skills': skill_registry.menu(), 'pending_count': pending, 'last_run': runtime(project), 'maintenance':w.read_json(w.DATA/'一键维护.json',{})}


@lifecycle.automatic
def analyze(data):
    from model_gateway import call_deepseek, model_status
    project = data.get('project') or '山药'
    k.lines(project)
    instruction = org.short_text(data.get('instruction'), 12000, '分析要求')
    document=None
    if data.get('path'):
        from administrator_chat import project_document
        selected_document,_=project_document(project,path=data['path'])
        document={**selected_document,'path':selected_document.get('kb_path') or selected_document['path']}
    selection=data.get('skill') or 'auto'
    if data.get('automatic') and selection!='auto':
        registration=skill_registry.metadata(selection,include_disabled=True)
        if registration and not registration['enabled']:
            return {'status':'skipped','message':'此技能已停用看板内置 AI。','skill':selection}
    name = select_skill(selection, instruction) or 'research-organizer'
    skill = read_skill(name, data.get('skill_references', ()))
    paper_limit = skill_registry.limit(name)
    skill_label = skill_registry.label(name)
    inputs, lines = org.paper_inputs(project)
    selected = data.get('paper_ids')
    if selected is not None:
        known = {p['id'] for p in inputs}
        if not isinstance(selected, list) or not selected or len(selected) > paper_limit or any(not isinstance(i, str) or i not in known for i in selected):
            raise ValueError(f'请选 1–{paper_limit} 篇已登记、属于当前课题的资料。')
        inputs = [p for p in inputs if p['id'] in selected]
    retrieval = org.retrieve_papers(project, instruction, inputs, limit=paper_limit, preferred=selected or ())
    ranked = retrieval['papers']
    material = {'project': project, 'instruction': instruction, 'context': org.context(project), 'mainlines': lines, 'papers': ranked,
                'document': document['body'][:60000] if document else None, 'local_retrieval': retrieval['retrieval']}
    if name == 'deep-research':
        import scholarly_search
        if not data.get('automatic') and model_status()['configured']:
            material['online_search'] = scholarly_search.for_message(data.get('query') or instruction)
        else:
            material['online_clues'] = directions.gather(project, data.get('query') or '')
    capability = '\n运行能力：你是看板中的 DeepSeek API 模型，分析本次提供的资料。浏览器、实验、下载或任意文件工具只在本次实际提供时可用；完整 skill 中缺少工具的步骤保留为后续建议。输出 Markdown，作为待核查分析记录。'
    capability+='\n'+skill_registry.language(name,instruction)
    if material.get('online_search') is not None:capability+=__import__('scholarly_search').SEARCH_PROMPT
    prompt=skill+'\n'+research_prompts.common()+capability
    fingerprint = w.digest(json.dumps({'prompt': prompt, 'material': material}, ensure_ascii=False, sort_keys=True))
    path = w.KB/'文献/AI阅读记录'/('技能分析_'+fingerprint[:20]+'.md')
    automatic=bool(data.get('automatic'));ledger_path=w.DATA/'自动分析记录.json';ledger=w.read_json(ledger_path,{})
    key=project+':'+name;previous=ledger.get(key,{})
    if automatic:
        path=w.KB/'文献/AI阅读记录'/('当前分析_'+w.digest(key)[:16]+'.md')
    relative=path.resolve().relative_to(w.KB.resolve()).as_posix()
    import note_management
    if note_management.suppressed(relative):return {'status':'trashed','message':'此分析已移入垃圾箱，自动维护保持移除状态。','reused':True}
    if path.is_file():
        if not automatic or previous.get('fingerprint')==fingerprint:return {'status': 'analysis_saved', 'path': previous.get('path',relative) if automatic else relative, 'skill': name, 'reused': True}
    if not model_status()['configured']:
        return {'status': 'needs_configuration', 'message': '请先在本机设置 DeepSeek。'}
    lifecycle.check_current()
    response = call_deepseek({'model': 'deepseek-flash', 'thinking': {'type': 'disabled'}, 'max_tokens': 7500, '_interactive':not automatic,
                             'messages': [{'role': 'system', 'content': prompt}, {'role': 'user', 'content': json.dumps(material, ensure_ascii=False)}]})
    if response.get('error'):
        raise ValueError(response['error'])
    answer = org.short_text(response.get('answer'), 100000, '分析正文')
    title = project+' · '+skill_label+' · '+instruction.splitlines()[0][:60]
    body = k.properties('', {'type': 'ai_analysis', 'title': title, 'project': project, 'status': '待核查', 'skill': name})+'# '+title+'\n\n日期：'+w.now()+'；AI 分析草稿，未替代原文核查。\n\n要求：'+instruction+'\n\n'+answer+'\n\n## 提供给本次分析的材料\n\n'
    for paper in ranked:
        body += '- [[文献/条目/'+paper['id']+']] · '+('；'.join(s['location'] for s in paper['sources']) or '仅题录')+'\n'
    if document:
        body += '\n## 分析的正文\n\n[['+document['path']+'|'+document['title']+']]\n'
    body += '\n## 本次本地检索\n\n'+(retrieval['retrieval']['notice'] or '使用 Qwen3 Embedding 4B 检索当前项目活动原文。')+'\n'
    from filelock import FileLock
    proposal_id=None
    with lifecycle.automatic_commit(project), FileLock(str(w.DATA/'.automatic-analysis.lock'),timeout=20), k.editing():
        prior=w.read_json(ledger_path,{})
        current=prior.get(key,previous)
        changed=path.is_file() and current.get('hash')!=w.digest(path.read_bytes())
        if changed and automatic:
            import ai_updates
            document=k.read(relative)
            target={'kind':'document','path':document['path'],'title':document['title'],'before':document['body'],'fingerprint':document['fingerprint']}
            proposal=ai_updates.store_proposal(target,{'kind':'document','body':k.split(body)[1],'summary':'分析输入更新，核对后更新同一份主稿。'},instruction,project,automatic=True,already_locked=True)
            proposal_id=proposal['id'];saved_hash=current.get('hash')
        else:
            if path.is_file() and not automatic:raise ValueError('分析笔记已被修改，本次未覆盖。')
            w.atomic_text(path,body);saved_hash=w.digest(path.read_bytes())
        if automatic:
            prior[key]={'fingerprint':fingerprint,'hash':saved_hash,'path':relative,'proposal_id':proposal_id}
            w.write_json(ledger_path,prior)
    return {'status':'analysis_saved','path':relative,'skill':name,'reused':False,'proposal_id':proposal_id,
            'reasoning_content':response.get('reasoning_content') or '','model':response.get('model') or ''}




@state.serial_run
@lifecycle.automatic
def maintain(data, progress=None):
    """One user action drains bounded batches; every completed step stays reviewable."""
    project = data.get('project') or settings()['project']; k.lines(project); cfg = settings(project)
    initial_runtime=state.receive(project)
    pending_documents=dict(initial_runtime.get('document_updates',{}));completed_documents={}
    steps = []; errors = []
    def execute(label, function):
        lifecycle.check_current()
        if progress: progress(label)
        try:
            result = batches.checked(function())
            steps.append({'label':label, 'status':'完成', 'result':result}); return result
        except lifecycle.AutomaticStopped:
            raise
        except Exception as error:
            errors.append(label+'：'+(str(error) if isinstance(error, ValueError) else type(error).__name__))
            steps.append({'label':label, 'status':'需重试', 'error':errors[-1]}); return None
    execute('同步论文、笔记与附件', w.sync)
    execute('按默认选项关联新论文主线', lambda: attach_defaults(project))
    for _ in range(100):
        result = execute('整理新增与变化的资料', lambda: batches.materials(project))
        if not result or not result.get('remaining'): break
    if cfg['auto_project']:
        execute('检查项目过程修改建议',lambda:__import__('change_impacts').automatic(project))
    if result and result.get('remaining'):errors.append('资料处理达到本次批次上限，保留接续。')
    if cfg['auto_analysis']: execute('分析当前研究方向与证据缺口', lambda: analyze({'project':project,'automatic':True,'skill':'tech-paper-template','instruction':'结合当前用户主线与资料，分析方向、证据缺口和可执行的下一步。保留用户决定。'}))
    if cfg['auto_discovery']: execute('发现领域方向', lambda: directions.discover({'project':project}))
    import workspace
    execute('核对稳定文献索引', workspace.refresh_views)
    execute('同步整理结果到本地检索', w.sync)
    result = {'status':'partial' if errors else 'completed', 'project':project, 'checked':w.now(), 'steps':steps, 'errors':errors}
    with lifecycle.automatic_commit(project):w.write_json(w.DATA/'一键维护.json', result)
    progress_state=runtime(project)
    progress_state.update(project=project,checked=w.now(),status='部分步骤待重试' if errors else '一键维护已完成',error='；'.join(errors),notes_written=0,notes_remaining=0,next_check=(datetime.now(timezone.utc)+timedelta(minutes=1 if errors else 10)).isoformat())
    if not errors:progress_state.update(analysis_pending=False,full_reconcile_pending=False,context_fingerprint=w.digest(json.dumps({'context':org.context(project),'mainlines':k.lines(project)['rows']},ensure_ascii=False,sort_keys=True)))
    for step in steps:
        if step['status']!='完成':continue
        if step['label']=='分析当前研究方向与证据缺口':progress_state.update(analysis_path=step['result'].get('path'),analyzed_day=datetime.now(timezone.utc).date().isoformat())
        if step['label']=='发现领域方向' and step['result'].get('directions'):progress_state['discovered_day']=datetime.now(timezone.utc).date().isoformat()
    progress_state['run_generation']=initial_runtime['run_generation']
    progress_state['update_paper_ids']=initial_runtime.get('update_paper_ids',[]) if errors else []
    if not errors:completed_documents=pending_documents
    with lifecycle.automatic_commit(project):
        state.finish_updates(project,progress_state,
            processed_documents=completed_documents,complete_legacy=not errors)
    return result


def attach_defaults(project):
    cfg=settings(project); selected=cfg.get('default_mainline','')
    if not selected:return {'associated':0}
    line_project=cfg['default_project'] if cfg['default_project'] not in ('共享','待归类') else cfg['project']
    if not selected or project!=line_project:return {'associated':0}
    ledger_path=w.DATA/'默认主线关联.json';ledger=w.read_json(ledger_path,{});lines=k.lines(project)
    row=next((item for item in lines['rows'] if item['id']==selected),None)
    if row is None:raise ValueError('默认主线已被删除，请重新选择。')
    events=state.queue()['items']
    records={record['id']:record for record in w.read_json(w.KB/'文献/library.json',{'records':[]})['records']}
    ids=[]
    for event in events:
        identifier=event.get('paper_id')
        already=ledger.get(identifier,{}).get('project')==project and ledger.get(identifier,{}).get('mainline')==selected
        if identifier in records and not already and event['reason'] in ('新论文已登记','收件箱发现新论文','新增 Zotero 条目','获取开放全文') and records[identifier].get('project') == project and w.chosen_artifact(records[identifier]) is not None:
            ids.append(identifier)
    if ids:
        row['paper_ids']=list(dict.fromkeys(row['paper_ids']+ids));k.save_lines(project,lines['rows'],lines['fingerprint'])
        for identifier in ids:ledger[identifier]={'project':project,'mainline':selected,'time':w.now()}
        w.write_json(ledger_path,ledger)
    return {'associated':len(ids)}


def pending_project():
    pending=[]
    for project in state.configured_projects():
        cfg=settings(project)
        if not cfg['enabled']:continue
        try:k.lines(project)
        except ValueError:continue
        previous=runtime(project)
        missed=previous.get('received_seq',0)<state.queue().get('dropped_through_seq',0)
        if missed or state.pending_events(project) or previous.get('next_check','')<=w.now():pending.append((previous.get('checked',''),project))
    return min(pending)[1] if pending else None


def due():
    return pending_project() is not None


def tick(progress=None):
    project=pending_project()
    if project is None:return {'status':'not_due' if settings().get('enabled') else 'disabled'}
    with state.run_lock(project):return _tick_project({'project':project},progress)

@lifecycle.automatic
@state.automatic_run
def _tick_project(data,progress=None):
    project=data['project']
    cfg = settings(project)
    previous = state.receive(project)
    received_documents=dict(previous.get('document_updates',{}))
    completed_documents={};completed_legacy=False
    if previous.get('project') != cfg['project']:
        previous = {}
    project = cfg['project']
    try:
        if progress:progress('登记新增资料与更新题录')
        state.require_enabled(project)
        followup=__import__('change_impacts').automatic(project)
        attach_defaults(project)
        import bibliography
        bibliography.refresh_dates()
        __import__('journal_rank_sources').scheduled_refresh()
        if progress:progress('整理新增与变化的资料')
        outcome = batches.materials(project)
        cfg=state.require_enabled(project)
        if outcome.get('status') == 'needs_configuration':
            raise ValueError('管理员等待本机 DeepSeek 配置。')
        previous['notes_remaining'] = 0
        previous['notes_written'] = 0
        now = datetime.now(timezone.utc)
        cfg=state.require_enabled(project)
        context_fingerprint = w.digest(json.dumps({'context': org.context(project), 'mainlines': k.lines(project)['rows']}, ensure_ascii=False, sort_keys=True))
        pending_analysis = bool(outcome.get('organized') or previous.get('analysis_pending') or previous.get('context_fingerprint') != context_fingerprint)
        completed_legacy=not outcome.get('remaining')
        if completed_legacy:
            # Project suggestions have their own source watermarks and receipts.
            completed_documents=received_documents
            previous['update_paper_ids']=[]
        # Finish changed batches before analysis; changed context is analyzed once per day.
        if not outcome.get('remaining') and pending_analysis and previous.get('analyzed_day') != now.date().isoformat():
            if cfg['auto_analysis']:
                if progress:progress('分析当前研究问题与证据缺口')
                analysis = analyze({'project': project, 'automatic':True, 'skill': 'tech-paper-template', 'instruction': '结合当前用户主线与资料，分析方向、证据缺口和可执行的下一步。保留用户决定。'})
                previous['analysis_path'] = analysis.get('path')
            previous['analyzed_day'] = now.date().isoformat()
            previous['analysis_pending'] = False
            previous['context_fingerprint'] = context_fingerprint
        else:
            previous['analysis_pending'] = pending_analysis
        # Direction discovery has its own daily schedule, even when local papers are unchanged.
        if not outcome.get('remaining') and cfg['auto_discovery'] and previous.get('discovered_day') != now.date().isoformat():
            if progress:progress('检索领域方向线索')
            directions.discover({'project': project})
            previous['discovered_day'] = now.date().isoformat()
        if completed_legacy:previous['full_reconcile_pending']=False
        remaining_documents={identifier:receipt for identifier,receipt in received_documents.items() if completed_documents.get(identifier)!=receipt}
        previous.update(status='部分资料待接续' if remaining_documents else '已检查', project=project, checked=w.now(), organized=outcome.get('organized', 0), error='',
                        documents_remaining=len(remaining_documents),
                        next_check=(now+timedelta(minutes=1 if followup.get('status')=='prepared' or followup.get('remaining') or outcome.get('remaining') or remaining_documents else 10)).isoformat())
    except state.AutomationPaused as error:
        previous.update(status='已暂停',project=project,checked=w.now(),error='',update_pending=True)
        state.save_runtime(project,previous)
        return {**previous,'status':'paused','message':str(error)}
    except lifecycle.AutomaticStopped:
        raise
    except Exception as error:
        completed_documents={};completed_legacy=False
        previous.update(status='等待重试', project=project, checked=w.now(), error=str(error) if isinstance(error, ValueError) else '管理员暂未完成：'+type(error).__name__, next_check=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat())
    with lifecycle.automatic_commit(project):
        state.finish_updates(project,previous,processed_documents=completed_documents,complete_legacy=completed_legacy)
    saved=runtime(project)
    return {**saved,'status':'partial' if saved.get('error') or saved.get('update_pending') or saved.get('notes_remaining') else 'completed'}
