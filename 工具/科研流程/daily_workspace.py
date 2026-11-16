"""Local intake guidance, visible processing results and direct batch editing."""
from pathlib import Path
from contextlib import nullcontext
from datetime import datetime
import json
import knowledge as k
import workflow as w


def fingerprint(library):
    return w.digest(json.dumps([{key: r.get(key) for key in ('id', 'project', 'reading_status', 'title','topic','mainline_relations')} for r in library['records']], ensure_ascii=False, sort_keys=True))


def overview(project):
    import administrator as admin
    k.lines(project)
    library = w.read_json(w.LIBRARY)
    state = w.load_state()
    cfg = admin.settings(project)
    organized = admin.org.view(project)
    from paper_notes import note_path
    completed_count = 0
    replies = []
    # Processing stages already report paper classification; avoid a second per-paper feed.
    for item in k.inventory(project):
        if item['kind'] not in ('AI 阅读记录', 'AI 阅读笔记', 'AI 分析记录', '阅读卡片'):
            continue
        path = w.KB/item['path']
        replies.append({'title': item['title'], 'kind': item['kind'], 'path': item['path'], 'updated': str(path.stat().st_mtime), 'summary': '点击查看全文；直接编辑标题与正文。'})
    def result_time(item):
        try: return datetime.fromisoformat(item['updated']).timestamp()
        except (ValueError, TypeError): return float(item.get('updated') or 0)
    replies.sort(key=result_time, reverse=True)
    stages = []
    for record in reversed(library['records']):
        if record.get('project') not in (None, project, '共享', '待归类'):
            continue
        local = state.get('papers', {}).get(record['id'], {})
        stage = '索引已完成' if local.get('status') == 'indexed' else '索引需检查' if local.get('status') == 'error' else '等待本地索引'
        completed = note_path(record['id']).is_file()
        card = record.get('reading_card')
        if card:
            card_path = Path(card) if Path(card).is_absolute() else w.KB/card
            if card_path.resolve().is_relative_to(w.KB.resolve()) and card_path.is_file() and k.split(card_path.read_text('utf-8-sig'))[0].get('standard_template') is not True: completed = True
        if completed: completed_count += 1; stage += ' · 阅读笔记已保存'
        if record['id'] in organized.get('papers', {}): stage += ' · 有 AI 整理草稿'
        elif not cfg['enabled']: stage += ' · AI 自动处理暂停'
        else: stage += ' · 等待自动整理'
        stages.append({'id': record['id'], 'title': record['title'], 'stage': stage})
    return {'project': project, 'inbox': str((w.KB/'文献/待入库').resolve()), 'administrator': cfg, 'last_sync': state.get('last_completed'), 'papers': stages[:12], 'paper_count':len(stages), 'notes_ready':completed_count, 'organized_count':len(organized.get('papers',{})), 'results': replies[:20], 'fingerprint': fingerprint(library), 'queue': __import__('administrator_state').queue()['items']}


def bulk_edit(data):
    if data.get('confirmed') is not True:
        raise ValueError('请检查选中论文与修改内容后确认保存。')
    ids = data.get('paper_ids')
    if not isinstance(ids, list) or not ids or len(ids) > 100 or any(not isinstance(i, str) for i in ids):
        raise ValueError('请选择 1–100 篇论文。')
    project = data.get('project'); status = data.get('status')
    if project not in (None, '共享', '待归类'): k.lines(project)
    if status not in (None, '未读', '阅读中'):
        raise ValueError('批量操作仅设置未读或阅读中；核查范围请逐篇登记。')
    if project is None and status is None: raise ValueError('请选择要修改的项目或状态。')
    with k.editing():
        library = w.read_json(w.LIBRARY)
        if data.get('fingerprint') and data['fingerprint'] != fingerprint(library):
            raise ValueError('论文信息已变化，请重新打开批量修改；尚未保存。')
        records = {r['id']: r for r in library['records']}
        if any(i not in records for i in ids): raise ValueError('选中资料含不存在的论文。')
        originals = {}; updates = {}
        status_updated = w.now() if status is not None else None
        for identifier in dict.fromkeys(ids):
            path = k.path_for('文献/条目/'+identifier+'.md', w.KB)
            before = path.read_text('utf-8-sig'); values = {}
            if project is not None: values['project'] = project; records[identifier]['project'] = project
            if status is not None:
                values.update(status=status, status_updated=status_updated)
                records[identifier].update(reading_status='unread' if status == '未读' else status,
                                           reading_status_updated=status_updated)
            originals[path] = before; updates[path] = k.properties(before, values)
        library_before = w.LIBRARY.read_text('utf-8-sig')
        try:
            for path, after in updates.items(): k.persist(path, originals[path], after, w.KB.resolve())
            w.write_json(w.LIBRARY, library)
        except Exception:
            for path, before in originals.items(): w.atomic_text(path, before)
            w.atomic_text(w.LIBRARY, library_before)
            raise
    import administrator
    administrator.schedule(project or administrator.settings()['project'], '论文归类或阅读状态变化')
    return {'saved': len(updates), 'message': '选中论文已保存；其他论文与原文保留。'}


def associate(data, *, already_locked=False):
    project=data.get('project');current=k.lines(project)
    ids=data.get('paper_ids');selected=data.get('mainline_ids',[]);topic=data.get('topic');mode=data.get('mode','add')
    if not isinstance(ids,list) or not 1<=len(ids)<=100 or any(not isinstance(i,str) for i in ids):raise ValueError('请选择 1–100 篇论文。')
    if not isinstance(selected,list) or any(i not in {r['id'] for r in current['rows']} for i in selected):raise ValueError('请选择当前项目中的研究主线。')
    if mode not in ('add','remove'):raise ValueError('关联方式无效。')
    if topic is not None and (not isinstance(topic,str) or len(topic)>120):raise ValueError('分类名称最多 120 字。')
    if topic is None and not selected:raise ValueError('请填写主题分类或选择要关联的主线。')
    role=data.get('role','待判断');reason=data.get('reason','');scope=data.get('scope','')
    if role not in ('待判断','背景依据','方法参考','支持证据','限制或反例'):raise ValueError('关联用途无效。')
    if not isinstance(reason,str) or len(reason)>2000 or not isinstance(scope,str) or len(scope)>500:raise ValueError('关联说明或阅读范围过长。')
    with nullcontext() if already_locked else k.editing():
        library=w.read_json(w.LIBRARY);known={r['id']:r for r in library['records']}
        if any(i not in known for i in ids):raise ValueError('论文不存在。')
        if data.get('fingerprint') and data['fingerprint']!=fingerprint(library):raise ValueError('论文信息已更新，请重新选择。')
        fresh=k.lines(project)
        if fresh['fingerprint']!=current['fingerprint'] or data.get('lines_fingerprint') and data['lines_fingerprint']!=fresh['fingerprint']:raise ValueError('主线已更新，请重新选择。')
        originals={};library_before=w.LIBRARY.read_text('utf-8-sig');line_file=k.line_path(project,w.KB);line_before=line_file.read_text('utf-8-sig') if line_file.exists() else None
        for identifier in dict.fromkeys(ids):
            record=known[identifier];record['project']=project
            if topic is not None:record['topic']=topic.strip()
            relations=record.setdefault('mainline_relations',{})
            for line in selected:
                if mode=='remove':relations.pop(line,None)
                elif any(field in data for field in ('role','reason','scope')):relations[line]={'role':role,'reason':reason.strip(),'scope':scope.strip(),'source':'用户记录','updated':w.now()}
            path=k.path_for('文献/条目/'+identifier+'.md');originals[path]=path.read_text('utf-8-sig')
        rows=fresh['rows']
        for row in rows:
            if row['id'] in selected:row['paper_ids']=list(dict.fromkeys(row['paper_ids']+ids)) if mode=='add' else [i for i in row['paper_ids'] if i not in ids]
        try:
            for path,before in originals.items():
                record=known[path.stem];values={'project':project}
                if topic is not None:values['topic']=topic.strip()
                k.persist(path,before,k.properties(before,values),w.KB.resolve())
            w.write_json(w.LIBRARY,library);k.save_lines(project,rows,fresh['fingerprint'],already_locked=True)
        except Exception:
            w.atomic_text(w.LIBRARY,library_before)
            for path,before in originals.items():w.atomic_text(path,before)
            if line_before is not None:w.atomic_text(line_file,line_before)
            raise
    import administrator
    administrator.schedule(project,'论文分类与主线关联已更新')
    return {'saved':len(set(ids)),'message':'分类与主线关联已保存；笔记关联和图表将同步刷新。'}
