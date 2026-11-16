"""DeepSeek proposes bounded changes; only a confirmed, current proposal is applied."""
from __future__ import annotations
import json
import re
import threading
import uuid
import difflib
from contextlib import nullcontext
from pathlib import PurePosixPath
import knowledge as k
import workflow as w
import automation_controls as automation
import research_prompts

LOCK = threading.Lock()


def target_for(data):
    project = data.get('project') or '山药'
    kind = data.get('target') or 'project'
    if kind=='files':
        import note_management
        return note_management.file_target(project)
    if kind == 'auto':
        instruction = data.get('instruction', '')
        kind = 'workflow' if re.search(r'流程|每天|每日|运行时间|同步间隔|暂停同步|关闭同步', instruction) else 'mainlines' if '主线' in instruction else 'background' if re.search(r'背景|设备|偏好', instruction) else 'project'
        matched = []
        for record in w.read_json(w.LIBRARY, {'records': []})['records']:
            short = record['id'].split('_', 1)[0]
            named = record['id'].casefold() in instruction.casefold() or record.get('title') and record['title'].casefold() in instruction.casefold() or len(short) >= 4 and short.casefold() in instruction.casefold()
            if named and re.search(r'状态|未读|阅读中|已读|核查', instruction): matched.append(record)
        if len(matched) == 1:
            data = {**data, 'path': '文献/条目/'+matched[0]['id']+'.md'}; kind = 'status'
        elif matched:
            raise ValueError('指令对应多篇论文，请从其中一篇的状态入口选择后再修改。')
        elif kind == 'project' and re.search(r'状态|调研中|准备实验|实验中|分析中|写作中|已完成', instruction):
            if '论文' in instruction: raise ValueError('请从这篇论文的状态入口指定对象后再修改。')
            kind = 'status'
    if kind == 'workflow':
        current = automation.settings()
        return {'kind': kind, 'fingerprint': current['fingerprint'], 'before': current['values']}
    if kind == 'mainlines':
        current = k.lines(project)
        return {'kind': kind, 'project': project, 'fingerprint': current['fingerprint'], 'before': current['rows']}
    path = data.get('path') or (f'项目/{project}/当前课题状态.md' if kind in ('project', 'status') else k.project_background(project) if kind == 'background' else '')
    current = k.read(path)
    if not current['editable']: raise ValueError(current.get('readonly_reason') or '请从资料所属的编辑入口修改。')
    if kind == 'status':
        return {'kind': kind, 'path': current['path'], 'title': current['title'], 'fingerprint': current['fingerprint'], 'before': current['status'], 'status_options': current['status_options'], 'reading_scope': current['reading_scope']}
    return {'kind': 'document', 'path': current['path'], 'title': current['title'], 'fingerprint': current['fingerprint'], 'before': current['body']}


def validate(plan, target):
    if not isinstance(plan, dict) or plan.get('kind') != target['kind']: raise ValueError('AI 未返回所选入口的修改方案，请调整指令重试。')
    if plan.get('path', target.get('path')) != target.get('path'): raise ValueError('AI 不能改写所选资料之外的文件。')
    summary = plan.get('summary', '按照指令修改')
    if not isinstance(summary, str) or len(summary) > 2000: raise ValueError('AI 修改摘要格式无效。')
    kind = target['kind']
    if kind == 'document':
        value = plan.get('body')
        if not isinstance(value, str) or not value.strip() or len(value) > 100000 or k.FRONT.match(value): raise ValueError('AI 正文格式无效，正文不得包含系统属性。')
    elif kind == 'mainlines': value = k.validate_lines(plan.get('rows'))
    elif kind == 'workflow': value = automation.validate({**target['before'], **plan.get('values', {})})
    elif kind == 'status':
        value = plan.get('status')
        if value not in target['status_options'] or value == '已核查指定范围': raise ValueError('AI 不能替你确认已核查原文，请使用状态菜单填写核查范围。')
    elif kind=='files':
        import note_management
        value=note_management.validate_actions(plan.get('actions'),target)
    else: raise ValueError('修改类型不受支持。')
    return {'kind': kind, 'summary': summary, 'after': value}


def store_proposal(target, plan, instruction, project, sources=None, *, automatic=False, already_locked=False, document_sources=None):
    with nullcontext() if already_locked else k.editing():
        return _store_proposal(target,plan,instruction,project,sources,automatic=automatic,document_sources=document_sources)


def _store_proposal(target, plan, instruction, project, sources, *, automatic, document_sources):
    validated = validate(plan, target)
    identifier = uuid.uuid4().hex
    if validated['kind']=='document' and validated['after'].rstrip()==target['before'].rstrip():
        # Keep an execution receipt, without creating another empty report or task.
        proposal={'id':identifier,'status':'无需修改','created':w.now(),'project':project,'instruction':instruction,
                  'target':target,'before':target['before'],**validated,'sources':sources or [],'document_sources':document_sources or [],'automatic':automatic}
        w.write_json(w.DATA/'AI修改'/(identifier+'.json'),proposal)
        return {**proposal,'fingerprint':revision(proposal),'target_state':'no_change'}
    previous={}
    if automatic:
        entries=[w.read_json(p,{}) for p in (w.DATA/'AI修改').glob('*.json')]
        for entry in sorted(entries,key=lambda p:p.get('created',''),reverse=True):
            if entry.get('automatic') and entry.get('status')=='待确认' and entry.get('project')==project and entry.get('target')==target:
                old=k.path_for(entry['note_path'],existing=False)
                if old.is_file() and entry.get('managed_hash')==w.digest(old.read_bytes()):identifier=entry['id'];previous=entry;break
    proposal = {'id': identifier, 'status': '待确认', 'created': w.now(), 'project': project, 'instruction': instruction,
                'target': target, 'before': target['before'], **validated, 'sources': sources or [], 'document_sources':document_sources or [], 'automatic':automatic}
    if previous:proposal['revisions']=(previous.get('revisions',[])+[{'time':previous['created'],'after':previous['after']}])[-10:]
    # A proposal is a dated research record, not a second formal background.
    path = (w.KB/'更新记录'/('AI修改_'+identifier[:12]+'.md')).resolve()
    body = readable_change(proposal['kind'], proposal['after'])
    header = {'type': 'ai_change_proposal', 'status': '待确认', 'project': project, 'proposal_id': identifier, 'target': target.get('path') or target['kind']}
    raw = k.properties('', header)+f'# AI 修改预览\n\n{validated["summary"]}\n\n用户要求：{instruction}\n\n目标：{header["target"]}\n\n## 拟保存的内容\n\n{body}\n'
    if sources: raw += '\n## 本次证据\n\n'+'\n'.join('- [[文献/条目/'+source['id']+']] · '+source.get('location', '位置见检索片段') for source in sources)+'\n'
    if document_sources:
        raw+='\n## 本次项目资料\n\n'
        for source in document_sources:
            source_path=source['path']
            if source_path.startswith('科研知识库/'):source_path=source_path[len('科研知识库/'):]
            ranges='、'.join(str(start)+'–'+str(end) for start,end in source.get('provided_ranges',[]))
            raw+='- [['+source_path+'|'+source['title']+']] · '+source['document_id']+' · 版本 '+source['version']+' · 提供文字位置 '+(ranges or '见范围记录')+'；'+source.get('notice','资料节选，不代表人工核查。')+'\n'
    if previous and previous.get('managed_hash')!=w.digest(path.read_bytes()):raise ValueError('预览笔记已被修改，本次未覆盖，请重新核对。')
    k.persist(path,path.read_text('utf-8-sig') if path.exists() else '',raw,w.KB.resolve())
    proposal['note_path'] = path.relative_to(w.KB.resolve()).as_posix()
    proposal['managed_hash']=w.digest(path.read_bytes())
    w.write_json(w.DATA/'AI修改'/(identifier+'.json'), proposal)
    return {**proposal, 'fingerprint': revision(proposal)}


def readable_change(kind, value):
    if kind=='files':
        if isinstance(value,dict):return '当前可管理笔记：'+str(len(value['notes']))+' 份；垃圾箱：'+str(len(value['trash']))+' 份。正式原稿与附件受保护。'
        return '\n'.join('- '+{'trash':'移入垃圾箱','restore':'恢复文件','associate':'论文归类与关联','new_note':'新建笔记'}[a['op']]+'：'+str(a.get('path') or a.get('title') or a.get('paper_ids') or a.get('id')) for a in value)
    if kind in ('document', 'status'): return value
    if kind == 'workflow':
        labels = {'daily_time': '每日更新时间', 'sync_minutes': '同步间隔（分钟）', 'sync_enabled': '定时同步文献与笔记', 'daily_enabled': '每日积累流程', 'discover_enabled': '发现新论文候选', 'acquire_enabled': '获取开放全文', 'ai_enabled': 'DeepSeek 生成背景修改预览'}
        rows = ['| 设置 | 内容 |', '| --- | --- |']
        for key, title in labels.items():
            item = value[key]
            text = ('开启' if item else '关闭') if isinstance(item, bool) else str(item)
            rows.append('| '+title+' | '+text+' |')
        return '\n'.join(rows)
    return '| 主线 | 状态 | 目标 | 关联论文 |\n| --- | --- | --- | --- |\n'+'\n'.join('| '+' | '.join(str(cell).replace('|', '\\|').replace('\n', '<br>') for cell in [row['title'], row['status'], row['goal'], '、'.join(row['paper_ids']) or '尚未关联'])+' |' for row in value)


def document_operations(before, operations):
    if not isinstance(operations,list) or not 1<=len(operations)<=12:raise ValueError('请提供 1–12 项局部修改。')
    body=before
    for operation in operations:
        if not isinstance(operation,dict):raise ValueError('局部修改格式无效。')
        if operation.get('op')=='set_section':
            heading,text=operation.get('heading'),operation.get('text')
            if not isinstance(heading,str) or not heading.strip() or len(heading)>120 or re.search(r'[\r\n#]',heading) or not isinstance(text,str) or not text.strip() or len(text)>20000:raise ValueError('段落标题或正文无效。')
            matches=list(re.finditer(r'(?m)^## '+re.escape(heading.strip())+r'[ \t]*$',body))
            replacement='## '+heading.strip()+'\n\n'+text.strip()+'\n\n'
            if len(matches)>1:raise ValueError('同名段落不唯一，请指定唯一标题。')
            if not matches:body=body.rstrip()+'\n\n'+replacement
            else:
                match=matches[0];following=re.search(r'(?m)^#{1,2} ',body[match.end():]);end=match.end()+following.start() if following else len(body)
                body=body[:match.start()]+replacement+body[end:]
        elif operation.get('op')=='replace_text':
            old,new=operation.get('before'),operation.get('after')
            if not isinstance(old,str) or not old or not isinstance(new,str) or len(old)>20000 or len(new)>20000 or body.count(old)!=1:raise ValueError('原文片段未唯一匹配，未实施模糊替换。')
            body=body.replace(old,new,1)
        else:raise ValueError('只支持指定段落或唯一原文片段的局部修改。')
    if len(body)>100000:raise ValueError('局部修改后的正文过长。')
    return body


def propose(data):
    if data.get('enabled') is False: return {'status': 'skipped', 'message': '此流程的 AI 步骤已关闭。'}
    instruction = data.get('instruction') or ''
    if not isinstance(instruction, str): raise ValueError('请用文字填写整理或分析要求。')
    kind = data.get('target') or ''
    if data.get('action') != 'ai_update':
        if kind == 'organize' or kind == 'auto' and re.search(r'整理资料|整理文献|自动整理|归类|分类整理', instruction):
            import organization
            return organization.organize(data)
        if kind == 'directions' or kind == 'auto' and re.search(r'发现.*方向|寻找.*方向|领域方向', instruction):
            import direction_discovery
            return direction_discovery.discover(data)
        if kind == 'analysis' or kind == 'auto' and re.search(r'评估|可行性|分析这|分析内容|润色|综述|梳理论文|核查稿件|设计图表', instruction):
            import administrator
            return administrator.analyze(data)
    from model_gateway import call_deepseek, model_status
    if not model_status()['configured']: return {'status': 'needs_configuration', 'message': '请先在本机设置 DeepSeek。'}
    instruction = data.get('instruction') or '对照新增证据维护研究背景；保留用户决定，新增信息区分文献发现、AI 建议和待核条件。无变化时保留现有内容。'
    if not isinstance(instruction, str) or not 1 <= len(instruction.strip()) <= 8000: raise ValueError('请填写修改要求，最多 8000 字。')
    project = data.get('project') or '山药'
    if project not in {p.name for p in (w.KB/'项目').iterdir() if p.is_dir()}: raise ValueError('项目不存在')
    # A caller chooses the actual tool. Model data cannot select an executable or a private path.
    if data.get('action') == 'ai_update': data = {**data, 'target': 'background'}
    target = target_for(data)
    sources = []; evidence = []
    if target['kind'] in ('document', 'mainlines') and data.get('use_evidence', True):
        matches = w.search(project+' '+instruction, include_notes=False, limit=6).get('results', [])
        records = {p.get('open_notebook_source_id'): p for p in w.read_json(w.LIBRARY)['records']}
        for item in matches:
            record = records.get(item.get('parent_id') or item.get('id'))
            if not record: continue
            text = '\n'.join(p if isinstance(p, str) else str(p.get('text') or p.get('content') or '') for p in item.get('matches', []))[:6500]
            evidence.append('['+record['id']+'] '+item.get('title', '')+'\n'+text)
            sources.append({'id': record['id'], 'title': item.get('title', '')})
    ledger_path = w.DATA/'ai-inputs.json'
    schemas = {'document': {'kind': 'document', 'summary': '修改理由', 'body': '完整新正文，保留其他部分'}, 'mainlines': {'kind': 'mainlines', 'summary': '修改理由', 'rows': target['before']}, 'workflow': {'kind': 'workflow', 'summary': '修改理由', 'values': target['before']}, 'status': {'kind': 'status', 'summary': '修改理由', 'status': target['before']}}
    context = []
    if target['kind'] in ('document', 'mainlines'):
        for path in ['背景/个人与实验条件.md', f'项目/{project}/当前课题状态.md']:
            try: context.append(k.read(path)['body'])
            except ValueError: pass
    rule_task='project' if target.get('path','').replace('\\','/').startswith(('项目/','科研知识库/项目/')) or target['kind'] in ('mainlines','status') else 'knowledge'
    prompt = research_prompts.task(rule_task)+'\n你是用户的科研维护助手。只输出 JSON，格式严格按示例。通过所选入口修改笔记正文、主线、状态或自动流程配置，只实施用户要求的修改，保留无关内容。流程字段仅允许已有时间、间隔和步骤开关，不提供代码、命令或密钥。主线状态可用：'+json.dumps(k.LINE_STATES, ensure_ascii=False)+'。示例：'+json.dumps(schemas[target['kind']], ensure_ascii=False)
    fingerprint = w.digest(json.dumps({'prompt': prompt, 'target': target, 'instruction': instruction, 'evidence': sorted(evidence), 'background': context}, ensure_ascii=False, sort_keys=True))
    ledger = w.read_json(ledger_path, {})
    if fingerprint in ledger and not data.get('force'):
        previous = w.read_json(w.DATA/'AI修改'/(ledger[fingerprint]+'.json'), {})
        if previous.get('status') in ('待确认','无需修改'): return {**previous, 'reused': True}
    import structured_response
    plan = structured_response.request({'model': 'deepseek-flash', 'response_format': {'type': 'json_object'}, 'max_tokens': 8000, 'thinking': {'type': 'disabled'}, 'messages': [{'role': 'system', 'content': prompt}, {'role': 'user', 'content': json.dumps({'instruction': instruction, 'selected_target': target, 'background': context, 'evidence': evidence}, ensure_ascii=False)}]},'AI 修改预览')
    proposal = store_proposal(target, plan, instruction, project, sources)
    ledger[fingerprint] = proposal['id']; w.write_json(ledger_path, ledger)
    return proposal


def get(identifier):
    if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9]{32}', identifier): raise ValueError('修改预览不存在')
    proposal = w.read_json(w.DATA/'AI修改'/(identifier+'.json'), {})
    if not proposal: raise ValueError('修改预览不存在')
    state,current=target_state(proposal)
    return {**proposal, 'fingerprint': revision(proposal), 'diff': change_diff(proposal),
            'target_state':state,'current':current,'source_stale':not sources_current(proposal),
            'current_diff':change_diff({**proposal,'before':current['body']}) if current else []}


def sources_current(proposal):
    references=proposal.get('document_sources') or []
    if not references:return True
    import workspace_catalog as catalog
    documents={doc['id']:doc for doc in catalog.rows(reconcile_records=False)}
    for reference in references:
        doc=documents.get(reference.get('document_id'))
        if not doc or doc.get('archived'):return False
        if reference.get('sha'):
            if reference['sha']!=doc['sha']:return False
        elif reference.get('version')!=catalog.document_version(doc):return False
    return True


def target_state(proposal):
    if proposal.get('kind')!='document':return 'current',None
    if proposal['before'].rstrip()==proposal['after'].rstrip():return 'no_change',None
    try:current=k.read(proposal['target']['path'])
    except (ValueError,OSError):return 'unavailable',None
    value={'body':current['body'],'fingerprint':current['fingerprint']}
    if current['body'].rstrip()==proposal['after'].rstrip():return 'already_current',value
    return ('current' if current['fingerprint']==proposal['target']['fingerprint'] else 'stale'),value


def change_diff(proposal):
    before = readable_change(proposal['kind'],proposal['before']).splitlines()
    after = readable_change(proposal['kind'],proposal['after']).splitlines()
    rows = []
    for tag, a, b, c, d in difflib.SequenceMatcher(None,before,after,autojunk=False).get_opcodes():
        if tag=='equal': rows.extend({'kind':'same','text':line} for line in before[a:b])
        else:
            rows.extend({'kind':'removed','text':line} for line in before[a:b])
            rows.extend({'kind':'added','text':line} for line in after[c:d])
    return rows


def revision(proposal):
    identity={'after':proposal['after'],'target_fingerprint':proposal['target'].get('fingerprint')}
    if proposal.get('document_sources'):identity['document_sources']=proposal['document_sources']
    return w.digest(json.dumps(identity, ensure_ascii=False, sort_keys=True))


def valid_revision(proposal, fingerprint):
    legacy=w.digest(json.dumps(proposal['after'],ensure_ascii=False,sort_keys=True))
    return fingerprint==revision(proposal) or (not proposal.get('rebased') and not proposal.get('document_sources') and fingerprint==legacy)


def revise(data):
    """Edit a saved preview locally; preserve its source target and original fingerprint."""
    with k.editing(), LOCK:
        proposal = get(data.get('id'))
        if proposal['status'] != '待确认': raise ValueError('此预览已处理，不能再修改。')
        if not valid_revision(proposal,data.get('fingerprint')): raise ValueError('预览已在其他窗口修改，请重新打开。')
        previous_base={'before':proposal['before'],'target_fingerprint':proposal['target'].get('fingerprint')}
        if data.get('rebase') is True:
            if proposal['kind']!='document':raise ValueError('只有正文预览支持与当前稿合并。')
            current=k.read(proposal['target']['path'])
            if data.get('current_fingerprint')!=current['fingerprint']:raise ValueError('合并期间原稿又有更新，请重新比较；未覆盖原稿。')
            proposal['target']={**proposal['target'],'before':current['body'],'fingerprint':current['fingerprint']}
            proposal['before']=current['body']
            proposal['rebased']=True
        field = {'document':'body', 'mainlines':'rows', 'workflow':'values', 'status':'status','files':'actions'}[proposal['kind']]
        validated = validate({'kind':proposal['kind'], 'summary':proposal['summary'], field:data.get('after')}, proposal['target'])
        proposal.setdefault('revisions', []).append({'time':w.now(), 'after':proposal['after'],**previous_base})
        proposal.update(after=validated['after'], revised=w.now())
        proposal['revisions'] = proposal['revisions'][-10:]
        note = k.path_for(proposal['note_path']); before = note.read_text('utf-8-sig')
        replacement = '## 拟保存的内容\n\n'+readable_change(proposal['kind'],proposal['after'])+'\n'
        after = re.sub(r'(?s)## 拟保存的内容\n.*?(?=\n## 本次证据|\Z)', lambda _: replacement, before, count=1)
        k.persist(note, before, after, w.KB.resolve())
        for field in ('current','target_state','current_diff','diff','fingerprint','source_stale'):proposal.pop(field,None)
        w.write_json(w.DATA/'AI修改'/(proposal['id']+'.json'), proposal)
        return get(proposal['id'])


def pending(project):
    proposals = [w.read_json(p, {}) for p in (w.DATA/'AI修改').glob('*.json')]
    latest={}
    for p in sorted(proposals,key=lambda p:p.get('created',''),reverse=True):
        if p.get('project') not in (project, '共享'):continue
        target=p['target'].get('path') or p['kind']
        latest.setdefault((target,bool(p.get('automatic') and not p.get('revised'))),p)
    active={}
    for (target,automatic),p in sorted(latest.items(),key=lambda entry:entry[0][1]):
        if p.get('status')=='待确认':active.setdefault(target,{**p,'automatic':automatic})
    return [{'id':p['id'],'summary':p['summary'],'created':p['created'],'target_label':target,
             'automatic':bool(p.get('automatic')),
             'target':{'path':p['target'].get('path'),'kind':p['target'].get('kind',p['kind'])},'target_state':state}
            for target,p in active.items()
            for state,_ in [target_state(p)] if state not in ('no_change','already_current')]


def history(project):
    k.lines(project)
    current={p['id'] for p in pending(project)}
    proposals=[w.read_json(p,{}) for p in (w.DATA/'AI修改').glob('*.json')]
    labels={'no_change':'没有正文改动','already_current':'当前正文已包含该预览内容'}
    return [{'id':p['id'],'summary':p['summary'],'created':p['created'],'status':labels.get(target_state(p)[0],'历史预览（已有新版或已处理）' if p.get('status')=='待确认' else p['status']),'target':p['target'].get('path') or p['kind']}
            for p in sorted(proposals,key=lambda p:p.get('created',''),reverse=True) if p.get('project') in (project, '共享') and p.get('status')!='不采纳' and p['id'] not in current][:30]


def apply(data, *, automatic=False):
    if data.get('confirmed') is not True: raise ValueError('请先核对修改预览并确认保存。')
    import project_profiles as profiles
    initial=get(data.get('id'))
    target=initial['target']
    path=PurePosixPath(str(target.get('path','')).replace('\\','/'))
    owner=(path.parts[1] if len(path.parts)>2 and path.parts[0]=='项目' else
           target.get('project') if initial['kind'] in ('mainlines','files') else None)
    with (profiles.lifecycle_lock(owner) if owner else nullcontext()), k.editing(), LOCK:
        if owner and profiles.archived(owner):raise ValueError('原稿所属项目已归档，请恢复项目后再采纳。')
        proposal = get(data.get('id'))
        if proposal['status'] != '待确认': raise ValueError('此修改已处理，请重新生成预览。')
        if data.get('fingerprint')!=revision(proposal): raise ValueError('预览版本缺失或已修改，请重新核对后保存。')
        if proposal['source_stale']:raise ValueError('依据资料已变化，请重新准备建议；原稿未覆盖。')
        target, after, kind = proposal['target'], proposal['after'], proposal['kind']
        if kind == 'document': result = k.save(target['path'], after, target['fingerprint'])
        elif kind == 'mainlines': result = k.save_lines(target['project'], after, target['fingerprint'])
        elif kind == 'status': result = k.change_status(target['path'], after, target['fingerprint'])
        elif kind == 'workflow': result = automation.save(after, target['fingerprint'])
        elif kind=='files':
            import note_management
            result=note_management.apply_actions(after,target)
        else: raise ValueError('此修改类型不受支持。')
        receipt_error=''
        if automatic and kind=='document':
            try:
                import workspace_catalog
                doc=workspace_catalog.maintenance_document(target['path'])
                workspace_catalog.update_after_automatic_write(doc['id'],k.read(target['path'])['body'])
            except (ValueError,OSError) as error:
                receipt_error=str(error)
        proposal.update(status='已采纳', applied=w.now(), automatic_applied=automatic,
                        **({'receipt_error':receipt_error} if receipt_error else {}))
        w.write_json(w.DATA/'AI修改'/(proposal['id']+'.json'), proposal)
        note = k.path_for(proposal['note_path'])
        raw = note.read_text('utf-8-sig'); w.atomic_text(note, k.properties(raw, {'status': '已采纳', 'applied': proposal['applied']}))
        return {'status': 'applied', 'result': result}


def reject(identifier,fingerprint):
    with k.editing(), LOCK:
        proposal = get(identifier)
        if proposal['status'] != '待确认': raise ValueError('此修改已处理。')
        if fingerprint!=revision(proposal):raise ValueError('预览版本缺失或已修改，请重新核对后处理。')
        import note_management as notes
        doc=k.read(proposal['note_path']);item=notes.move({'path':doc['path'],'fingerprint':doc['fingerprint'],'reason':'不采纳修改预览'})
        proposal.update(status='不采纳',trashed=item['id']);w.write_json(w.DATA/'AI修改'/(identifier+'.json'),proposal)
        return {'status':'rejected','trash_id':item['id']}
