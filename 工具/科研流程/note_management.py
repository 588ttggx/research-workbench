"""Recoverable local trash and suppression of automatic note recreation."""
from pathlib import Path
import re
import uuid
from contextlib import nullcontext
import knowledge as k
import workflow as w


def ledger():
    return w.read_json(w.DATA/'垃圾箱.json', {'records': []})


def active():
    return [row for row in ledger()['records'] if row.get('status') == 'trashed']


def suppressed(relative):
    return any(row['path'] == relative for row in active())


def remote_ids():
    return {row['remote_note_id'] for row in active() if row.get('remote_note_id')}


def archived_paths():
    """Catalog paths remain on disk; only their active derivatives are suppressed."""
    import workspace_catalog as catalog
    with catalog.database().connection() as db:
        paths = [row['path'] for row in db.execute('SELECT path FROM documents WHERE archived=1 AND present=1')]
    base = w.KB.resolve()
    return {(w.ROOT/path).resolve().relative_to(base).as_posix() for path in paths
            if (w.ROOT/path).resolve().is_relative_to(base)}


def inactive_remote_ids(state):
    archived = archived_paths()
    return remote_ids() | {entry['note_id'] for relative, entry in state.get('notes', {}).items()
                           if relative in archived and entry.get('note_id')}


def sync_archived(state, remote_notes, archived):
    present = {note['id']:note for note in remote_notes}
    removed = set()
    for relative, entry in state.get('notes', {}).items():
        if relative not in archived:
            entry.pop('archived', None)
            continue
        identifier = entry.get('note_id')
        if identifier in present:
            remote = present[identifier]
            w.write_json(w.DATA/'备份/归档笔记'/(w.digest(identifier+str(remote))[:24]+'.json'), remote)
            w.api('DELETE', '/notes/'+identifier)
        if identifier:removed.add(identifier)
        entry['archived'] = True
    return removed


def can_trash(doc, kb=None):
    if not doc['path'].startswith(('文献/AI阅读记录/', '文献/阅读卡片/', '笔记/', '更新记录/')):
        return False
    meta = k.split(k.path_for(doc['path'],kb).read_text('utf-8-sig'))[0]
    if meta.get('$itemKey') or meta.get('$libraryID'):
        return False
    return doc['path'].startswith(('文献/AI阅读记录/', '文献/阅读卡片/', '笔记/')) or meta.get('type') in ('ai_change_proposal', 'background_candidate', 'direction_candidate', 'organization_candidate')


def move(data, *, already_locked=False):
    relative = data.get('path')
    with nullcontext() if already_locked else k.editing():
        doc = k.read(relative)
        if not can_trash(doc):raise ValueError('正式背景、主线及已绑定双向同步的原稿保留；此入口只管理笔记和 AI 草稿。')
        source = k.path_for(relative)
        k.validate_fingerprint(source, data.get('fingerprint'))
        store = ledger()
        identifier = uuid.uuid4().hex
        destination = (w.KB/'垃圾箱'/identifier/source.name).resolve()
        if not destination.is_relative_to(w.KB.resolve()) or destination.exists():raise ValueError('垃圾箱目标无效。')
        state = w.load_state()
        row = {'id':identifier, 'status':'trashed', 'path':relative, 'trash_path':destination.relative_to(w.KB.resolve()).as_posix(),
               'title':doc['title'], 'kind':doc['kind'], 'project':doc['project'], 'source_project':doc.get('source_project',''), 'paper_id':doc.get('paper_id'),
               'proposal_id':doc.get('proposal_id'), 'hash':w.digest(source.read_bytes()), 'deleted':w.now(),
               'remote_note_id':state.get('notes',{}).get(relative,{}).get('note_id'), 'reason':data.get('reason') or '用户移入垃圾箱'}
        destination.parent.mkdir(parents=True,exist_ok=True)
        source.replace(destination)
        try:
            store['records'].append(row);w.write_json(w.DATA/'垃圾箱.json',store)
        except Exception:
            destination.replace(source);raise
        return row


def trash_file(row):
    path = (w.KB/row['trash_path']).resolve()
    if not path.is_relative_to((w.KB/'垃圾箱').resolve()) or not path.is_file():raise ValueError('垃圾箱文件不存在。')
    return path


def restore(identifier, *, already_locked=False):
    if not isinstance(identifier,str) or not re.fullmatch(r'[a-f0-9]{32}',identifier):raise ValueError('垃圾箱记录不存在。')
    with nullcontext() if already_locked else k.editing():
        store=ledger();row=next((r for r in store['records'] if r['id']==identifier and r['status']=='trashed'),None)
        if row is None:raise ValueError('此记录已经恢复或不存在。')
        source=trash_file(row);destination=k.path_for(row['path'],existing=False)
        if destination.exists():raise ValueError('原位置已有新稿，未覆盖。请先核对新稿后恢复。')
        if w.digest(source.read_bytes())!=row['hash']:raise ValueError('垃圾箱内容已被修改，请先核对后恢复。')
        original=source.read_bytes();changed={w.DATA/'垃圾箱.json':(w.DATA/'垃圾箱.json').read_bytes()}
        destination.parent.mkdir(parents=True,exist_ok=True);source.replace(destination)
        try:
            if row.get('proposal_id'):
                path=w.DATA/'AI修改'/(row['proposal_id']+'.json');proposal=w.read_json(path,{})
                if proposal:
                    changed[path]=path.read_bytes();proposal.update(status='待确认');proposal.pop('trashed',None);w.write_json(path,proposal)
                    w.atomic_text(destination,k.properties(destination.read_text('utf-8-sig'),{'status':'待确认'}))
            else:
                meta=k.split(destination.read_text('utf-8-sig'))[0]
                if meta.get('type') in ('background_candidate','organization_candidate','direction_candidate') and meta.get('status')=='不采纳':w.atomic_text(destination,k.properties(destination.read_text('utf-8-sig'),{'status':'待核查'}))
            if row.get('remote_removed'):
                changed[w.STATE]=w.STATE.read_bytes() if w.STATE.exists() else None
                state=w.load_state();state.get('notes',{}).pop(row['path'],None);w.write_json(w.STATE,state)
            row.update(status='restored',restored=w.now());w.write_json(w.DATA/'垃圾箱.json',store)
        except Exception:
            destination.replace(source);source.write_bytes(original)
            for path,before in changed.items():
                if before is None:path.unlink(missing_ok=True)
                else:path.write_bytes(before)
            raise
        return k.read(row['path'])


def view(project=None):
    rows=[{**row,'storage_path':str(trash_file(row))} for row in active() if not project or row['project'] in (project,'共享')]
    import direction_discovery as directions
    projects=[project] if project else [p.name for p in (w.KB/'项目').iterdir() if p.is_dir()]
    for name in projects:
        for item in directions.view(name)['directions']:
            if item['status']=='不采用':rows.append({'id':item['id'],'kind':'方向候选','title':item['title'],'project':name,'direction':True,'deleted':item.get('selected',''),'path':f'项目/{name}/方向选择.md','storage_path':str((w.KB/'项目'/name/'方向选择.md').resolve())})
    return {'records':sorted(rows,key=lambda r:r.get('deleted',''),reverse=True),'folder':str((w.KB/'垃圾箱').resolve())}


def sync_remote(state, remote_notes, *, protected_ids=frozenset()):
    store=ledger();present={n['id']:n for n in remote_notes};changed=False
    for row in store['records']:
        if row.get('status')!='trashed' or not row.get('remote_note_id') or row.get('remote_removed'):continue
        identifier=row['remote_note_id']
        if identifier in protected_ids or row.get('remote_preserved') == 'shared_identity':
            if row.get('remote_preserved') != 'shared_identity':
                row['remote_preserved'] = 'shared_identity'
                changed = True
            continue
        if identifier in present:
            w.write_json(w.DATA/'垃圾箱远端备份'/(row['id']+'.json'),present[identifier])
            w.api('DELETE','/notes/'+identifier)
        row['remote_removed']=True;changed=True
    if changed:w.write_json(w.DATA/'垃圾箱.json',store)


def preview(identifier):
    row=next((r for r in active() if r['id']==identifier),None)
    if row is None:raise ValueError('垃圾箱记录不存在。')
    path=trash_file(row);_,body,_=k.split(path.read_text('utf-8-sig'))
    return {'title':row['title'],'body':body,'path':row['path'],'storage_path':str(path),'kind':'垃圾箱 · 可恢复','project':row['project'],'readonly':True,'can_trash':False,'status_options':[]}


NOTE_KINDS={'阅读卡片','AI 阅读笔记','AI 阅读记录','AI 分析记录','笔记','项目经验','方法记录','论文批注'}


def create(data, *, ai=False, already_locked=False):
    project=data.get('project') or '山药';lines=k.lines(project)
    title=data.get('title');body=data.get('body');ids=data.get('paper_ids',[]);selected=data.get('mainline_ids',[])
    category=data.get('category','笔记');scope=data.get('scope','project')
    if category not in ('笔记','项目经验','方法记录','论文批注') or scope not in ('project','shared'):raise ValueError('笔记类别或保存范围无效。')
    if scope=='shared' and selected:raise ValueError('共享笔记请关联论文，项目主线可在具体项目笔记中选择。')
    if not isinstance(title,str) or not 1<=len(title.strip())<=200:raise ValueError('请填写笔记标题（最多 200 字）。')
    if not isinstance(body,str) or not body.strip() or len(body)>100000 or k.FRONT.match(body):raise ValueError('请填写笔记正文，属性由系统保存。')
    known={r['id'] for r in w.read_json(w.KB/'文献/library.json',{'records':[]})['records']}
    if not isinstance(ids,list) or len(ids)>100 or any(i not in known for i in ids):raise ValueError('请选择已登记论文。')
    if not isinstance(selected,list) or any(i not in {r['id'] for r in lines['rows']} for i in selected):raise ValueError('请选择当前项目的主线。')
    folder=(w.KB/'笔记'/('共享' if scope=='shared' else project)).resolve()
    if not folder.is_relative_to((w.KB/'笔记').resolve()):raise ValueError('笔记保存位置无效。')
    name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',title.strip()).strip(' .')[:50] or '笔记'
    path=folder/('笔记_'+name+'_'+uuid.uuid4().hex[:8]+'.md')
    text=k.properties('',{'type':'ai_analysis' if ai else 'personal_note','note_category':category,'title':title.strip(),'project':'共享' if scope=='shared' else project,'source_project':project,'status':'AI 草稿 · 待核查' if ai else '我的笔记','paper_ids':list(dict.fromkeys(ids)),'mainline_ids':list(dict.fromkeys(selected))})+'# '+title.strip()+'\n\n'+body.rstrip()+'\n'
    with nullcontext() if already_locked else k.editing():k.persist(path,'',text,w.KB.resolve())
    if not ai:
        import administrator
        administrator.schedule(project,'自己的笔记、经验或方法已保存')
    return k.read(path.relative_to(w.KB.resolve()).as_posix())


def count_notes():
    projects=[p.name for p in (w.KB/'项目').iterdir() if p.is_dir()]
    return len({item['path'] for project in projects for item in k.inventory(project) if item['kind'] in NOTE_KINDS})


def owned_by_project(doc,project):
    """A legacy project label cannot transfer ownership of another original."""
    if doc.get('project')!=project or doc.get('source_project') not in (None,'',project):return False
    parts=Path(doc['path']).parts
    if len(parts)>2 and parts[0] in ('项目','笔记') and (w.KB/'项目'/parts[1]).is_dir() and parts[1]!=project:return False
    return True


def owned_trash(row,project):
    if row.get('project')!=project:return False
    try:
        original=trash_file(row).read_text('utf-8-sig')
        meta=k.split(original)[0]
    except (OSError,ValueError,UnicodeError):return False
    return owned_by_project({**row,'project':meta.get('project') or row.get('project'),
                             'source_project':meta.get('source_project') or row.get('source_project')},project)


def file_target(project):
    import daily_workspace as daily
    inventory=k.inventory(project)
    material={'notes':[{'path':i['path'],'title':i['title'],'fingerprint':i['fingerprint'],'can_trash':i['can_trash']} for i in inventory if i['kind'] in NOTE_KINDS and owned_by_project(i,project)],
              'trash':[{'id':i['id'],'title':i['title']} for i in active() if owned_trash(i,project)],
              'papers':[{'id':r['id'],'title':r['title']} for r in w.read_json(w.KB/'文献/library.json',{'records':[]})['records']],
              'mainlines':k.lines(project),'library_fingerprint':daily.fingerprint(w.read_json(w.KB/'文献/library.json',{'records':[]}))}
    import json
    return {'kind':'files','project':project,'before':material,'fingerprint':w.digest(json.dumps(material,ensure_ascii=False,sort_keys=True))}


def validate_actions(actions,target):
    if not isinstance(actions,list) or not 1<=len(actions)<=10:raise ValueError('一次文件管理最多 10 项操作。')
    material=target['before'];notes={i['path']:i for i in material['notes']};trashed={i['id'] for i in material['trash']}
    papers={i['id'] for i in material['papers']};lines={i['id'] for i in material['mainlines']['rows']}
    seen=set()
    for action in actions:
        if not isinstance(action,dict):raise ValueError('文件管理操作无效。')
        op=action.get('op')
        allowed={'trash':{'op','path'},'restore':{'op','id'},'associate':{'op','paper_ids','mainline_ids','topic','mode','role','reason','scope'},'new_note':{'op','title','body','paper_ids','mainline_ids','category','scope'}}
        if op not in allowed or set(action)-allowed[op]:raise ValueError('文件管理包含不支持的操作或参数。')
        resource=(op,action.get('path') or action.get('id'))
        if op in ('trash','restore'):
            if resource in seen:raise ValueError('同一文件不能在一份预览中重复操作。')
            seen.add(resource)
        if op=='trash':
            if action.get('path') not in notes or not notes[action['path']]['can_trash']:raise ValueError('只可移除列表中允许管理的笔记；正式原稿受保护。')
        elif op=='restore':
            if action.get('id') not in trashed:raise ValueError('只能恢复当前垃圾箱中的文件。')
        elif op=='associate':
            ids=action.get('paper_ids');selected=action.get('mainline_ids',[])
            if not isinstance(ids,list) or not ids or any(i not in papers for i in ids) or not isinstance(selected,list) or any(i not in lines for i in selected):raise ValueError('只能关联已有论文和当前主线。')
            if action.get('mode','add') not in ('add','remove') or not isinstance(action.get('topic',''),str) or len(action.get('topic',''))>120:raise ValueError('分类或关联格式无效。')
            if not selected and not action.get('topic'):raise ValueError('请指定主题分类或研究主线。')
            if action.get('role','待判断') not in ('待判断','背景依据','方法参考','支持证据','限制或反例') or not isinstance(action.get('reason',''),str) or len(action.get('reason',''))>2000 or not isinstance(action.get('scope',''),str) or len(action.get('scope',''))>500:raise ValueError('关联用途或依据说明无效。')
        elif op=='new_note':
            if not isinstance(action.get('title'),str) or not 1<=len(action['title'].strip())<=200 or not isinstance(action.get('body'),str) or not 1<=len(action['body'].strip())<=30000 or k.FRONT.match(action['body']):raise ValueError('新笔记需要标题和正文，不能写入系统属性。')
            ids=action.get('paper_ids',[]);selected=action.get('mainline_ids',[])
            if not isinstance(ids,list) or any(i not in papers for i in ids) or not isinstance(selected,list) or any(i not in lines for i in selected) or action.get('category','笔记') not in ('笔记','项目经验','方法记录','论文批注') or action.get('scope','project') not in ('project','shared') or action.get('scope')=='shared' and selected:raise ValueError('新笔记的类别或关联范围无效。')
        else:raise ValueError('仅支持新建笔记、归类关联、移入垃圾箱和恢复，不能执行任意文件或命令操作。')
    return actions


def apply_actions(actions,target):
    with k.editing():return apply_actions_locked(actions,target)


def apply_actions_locked(actions,target):
    import daily_workspace as daily
    validate_actions(actions,target)
    if file_target(target['project'])['fingerprint']!=target['fingerprint']:raise ValueError('文件或主线已更新，请重新核对管理预览。')
    for action in actions:
        if action['op']=='restore':
            row=next(r for r in active() if r['id']==action['id'])
            if k.path_for(row['path'],existing=False).exists() or w.digest(trash_file(row).read_bytes())!=row['hash']:raise ValueError('恢复位置或垃圾箱内容已改变，请先核对；本次尚未执行操作。')
    results=[]
    for action in actions:
        op=action['op']
        if op=='trash':
            original=next(i for i in target['before']['notes'] if i['path']==action['path'])
            result=move({'path':action['path'],'fingerprint':original['fingerprint'],'reason':'管理员按用户要求整理文件'},already_locked=True)
        elif op=='restore':result=restore(action['id'],already_locked=True)
        elif op=='associate':result=daily.associate({**action,'project':target['project']},already_locked=True)
        else:
            result=create({**action,'project':target['project']},ai=True,already_locked=True)
        results.append({'op':op,'result':result})
    return {'operations':results}


def migrate_rejected():
    moved=[]
    for path in list((w.KB/'更新记录').glob('*.md')):
        meta,_,_=k.split(path.read_text('utf-8-sig'))
        if meta.get('type') not in ('ai_change_proposal','background_candidate','direction_candidate','organization_candidate') or meta.get('status')!='不采纳':continue
        doc=k.read(path.relative_to(w.KB.resolve()).as_posix())
        if can_trash(doc):moved.append(move({'path':doc['path'],'fingerprint':doc['fingerprint'],'reason':'此前明确不采纳的 AI 草稿'}))
    return {'moved':len(moved)}
