"""One Markdown source for project work, including legacy task entry points."""
import copy
from datetime import date, timedelta
import json
import re

import knowledge as k
import workflow as w
import project_profiles as profiles
from research_store import Store, encode

TASK = re.compile(r'(?m)^(\s*[-*+]\s+\[)([ xX])(\]\s+)(.*)$')
MARKER = re.compile(r'\s*<!--\s*((?:(?:question|task|suggestion|step):[\w.-]+\s*)+)-->\s*$')
PHASES = ('待定', '进行中', '等待', '暂停')
META_FIELDS = {'phase', 'kind', 'next_step', 'due_on', 'due_date_rule', 'references', 'depends_on', 'pin_rank', 'stage_ids', 'item_type', 'execution_notes'}


def path_for(project):
    return k.line_path(project, w.KB).parent/'任务.md'


def _parse(project, raw):
    meta, body, front = k.split(raw)
    extension = meta.get('work_items', {})
    warnings = []
    if front:
        try:
            import yaml
            parsed=yaml.safe_load(front.group(1))
            if not isinstance(parsed,dict):warnings.append('任务稿YAML必须是字段映射，原稿未修改。')
        except yaml.YAMLError:
            warnings.append('任务稿YAML格式损坏，原稿未修改。')
    if not isinstance(extension, dict):
        extension = {}; warnings.append('work_items格式无效，请先核对原稿。')
    rows = []; seen = set()
    offset = front.end() if front else 0
    for index, match in enumerate(TASK.finditer(raw, offset)):
        marker = MARKER.search(match[4])
        tags = dict(re.findall(r'(question|task|suggestion|step):([\w.-]+)', marker[1])) if marker else {}
        identifier = tags.get('task') or 'legacy-'+str(index)
        extra = extension.get(identifier, {})
        if not isinstance(extra, dict):
            warnings.append(identifier+'的扩展字段无效。'); extra = {}
        extra=copy.deepcopy(extra)
        for name in ('depends_on','references','stage_ids'):
            if name in extra and (not isinstance(extra[name],list) or any(
                    not isinstance(v,dict if name=='references' else str) for v in extra[name])):
                warnings.append(identifier+'的'+name+'格式无效，原稿未修改。');extra[name]=[]
        for name in ('kind','next_step','due_on','execution_notes'):
            if extra.get(name) is not None and not isinstance(extra[name],str):
                warnings.append(identifier+'的'+name+'格式无效，原稿未修改。');extra[name]=None
        if extra.get('pin_rank') is not None and (type(extra['pin_rank']) is not int or extra['pin_rank']<0):
            warnings.append(identifier+'的pin_rank格式无效。');extra['pin_rank']=None
        if not _valid_due_rule(extra.get('due_date_rule')):
            warnings.append(identifier+'的日期规则格式无效，原稿未修改。');extra['due_date_rule']=None
        extra.setdefault('stage_ids',[])
        extra.setdefault('item_type','work')
        if extra['item_type'] not in ('work','plan'):
            warnings.append(identifier+'的事项类别无效。');extra['item_type']='work'
        phase = extra.get('phase', '待定')
        if phase not in PHASES:
            warnings.append(identifier+'的phase无效，原稿未修改。'); phase = '待定'
        done = match[2].lower() == 'x'
        title = MARKER.sub('', match[4]).strip()
        rows.append({**copy.deepcopy(extra), 'id': identifier, 'title': title, 'text': title,
                     'done': done, 'phase': phase, 'status': '完成' if done else phase,
                     'question_id': tags.get('question'), 'step_id': tags.get('step'),
                     'suggestion_id': tags.get('suggestion'), 'legacy': 'task' not in tags,
                     'removed': bool(extra.get('removed')), 'index': index,
                     '_start': match.start(), '_end': match.end(), '_tags': tags,
                     '_prefix': match[1], '_middle': match[3]})
        if identifier in seen: warnings.append('重复task ID：'+identifier)
        seen.add(identifier)
    return rows, extension, warnings


def read(project):
    path = path_for(project)
    raw = path.read_text('utf-8-sig') if path.is_file() else ''
    rows, _, warnings = _parse(project, raw)
    return {'project': project, 'source_path': path.relative_to(w.KB.resolve()).as_posix(),
            'fingerprint': w.digest(raw), 'items': [{key: value for key, value in row.items()
               if not key.startswith('_')} for row in rows], 'warnings': warnings}


def item_fingerprint(project, identifier, raw=None):
    """Bind one work item to its own content and direct work dependencies."""
    if raw is None:
        path=path_for(project)
        raw=path.read_text('utf-8-sig') if path.is_file() else ''
    rows,extension,_=_parse(project,raw)
    by_id={row['id']:row for row in rows}
    if identifier not in by_id:raise ValueError('工作不存在，请刷新。')
    def snapshot(task_id,trail=()):
        if task_id in trail:return {'id':task_id,'cycle':True}
        row=by_id[task_id]
        public={key:value for key,value in row.items() if not key.startswith('_') and key!='index'}
        meta=copy.deepcopy(extension.get(task_id,{}))
        return {'item':public,'metadata':meta,
                'dependencies':[snapshot(dep,trail+(task_id,)) for dep in meta.get('depends_on',[]) if dep in by_id]}
    return w.digest(json.dumps(snapshot(identifier),ensure_ascii=False,sort_keys=True))


def _payload(data):
    return {key: value for key, value in data.items()
            if key not in ('fingerprint', 'preview_token', 'request_id', 'lifecycle_revision')}


def _operation_key(project, request):
    return 'work-operation:'+project+':'+request


def _complete(store, key, intent):
    completed = {**intent, 'state': 'completed','notification_pending':True}
    with store.connection() as db:
        store.log(db, 'project.work_'+intent['op'], intent['project'],
                  {'request_id': intent['request_id'], 'task_ids': intent['result_ids']})
        db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)', (key, encode(completed), w.now()))
    try:
        derived=bool(intent.get('decision_id'))
        __import__('workspace_catalog').notify_change(path_for(intent['project']),
            'decision_result' if derived else 'work',changed_work_ids=() if derived else intent['result_ids'])
    except (OSError,ValueError):
        return completed
    completed['notification_pending']=False
    store.commit_page(key,[],completed)
    return completed


def _recover(project, raw, store):
    prefix = 'work-operation:'+project+':'
    with store.connection() as db:
        pending = [(row[0], json.loads(row[1])) for row in db.execute(
            'SELECT key,value FROM cursors WHERE substr(key,1,?)=?', (len(prefix), prefix))]
    digest = w.digest(raw)
    for key, intent in pending:
        if intent.get('state') != 'pending': continue
        if digest == intent['after']:
            _complete(store, key, intent)
        elif digest == intent['before']:
            store.commit_page(key, [], {**intent, 'state': 'retryable'})
        else:
            raise ValueError('有未完成操作且原稿已再次变化；请核对当前稿与操作历史，未覆盖新稿。')


def _title(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 1000 or any(
            c in value for c in ('\n', '\r', '\x00', '<!--')):
        raise ValueError('请填写1000字以内的单行工作标题。')
    return value.strip()


def _valid_due_rule(rule):
    return rule is None or (isinstance(rule,dict) and set(rule)=={'task_id','offset_days'} and
        isinstance(rule['task_id'],str) and type(rule['offset_days']) is int and abs(rule['offset_days'])<=3650)


def _apply_fields(row, extra, fields, project, retained_stages=()):
    allowed = META_FIELDS | {'title', 'text', 'status', 'done', 'question_id', 'step_id', 'suggestion_id'}
    if not isinstance(fields, dict) or set(fields)-allowed: raise ValueError('工作字段无效。')
    if 'title' in fields or 'text' in fields: row['title'] = _title(fields.get('title', fields.get('text')))
    if 'status' in fields:
        if fields['status'] not in (*PHASES, '完成'): raise ValueError('工作状态无效。')
        row['done'] = fields['status'] == '完成'
        if not row['done']: extra['phase'] = fields['status']
    if 'done' in fields:
        if type(fields['done']) is not bool: raise ValueError('完成标志无效。')
        row['done'] = fields['done']
    for key in META_FIELDS & fields.keys():
        value = fields[key]
        if key == 'item_type':
            if value not in ('work','plan'):raise ValueError('事项类别无效。')
            if '_start' in row and value!=row.get('item_type','work'):raise ValueError('工作与计划分别保存，不能通过编辑互换类别。')
        if key == 'stage_ids':
            if not isinstance(value,list) or len(value)>100 or any(not isinstance(x,str) for x in value):raise ValueError('阶段关联无效。')
            from project_stages import path_for as stage_path, parse as parse_stage
            value=list(dict.fromkeys(value))
            for identifier in value:
                path=stage_path(project,identifier)
                if not path.is_file():raise ValueError('请选择本项目已有阶段。')
                meta0,_,_=parse_stage(path.read_text('utf-8-sig'))
                if meta0.get('project')!=project or meta0.get('stage_removed') and identifier not in [*extra.get('stage_ids',[]),*retained_stages]:raise ValueError('请选择本项目活动阶段。')
        if key == 'phase' and value not in PHASES: raise ValueError('工作阶段无效。')
        if key in ('kind', 'next_step', 'execution_notes') and value is not None and (not isinstance(value, str) or len(value) > (50000 if key=='execution_notes' else 4000)):
            raise ValueError('工作说明格式无效。')
        if key == 'due_on' and value is not None:
            try:
                if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value: raise ValueError()
            except (TypeError, ValueError): raise ValueError('日期请使用YYYY-MM-DD，或留空。')
        if key == 'due_date_rule' and not _valid_due_rule(value):
            raise ValueError('日期规则须选择依赖事项，偏移为 -3650 至 3650 天的整数。')
        if key == 'due_date_rule' and value is None:
            extra.pop(key,None)
            continue
        if key == 'pin_rank' and value is not None and (type(value) is not int or value < 0):
            raise ValueError('置顶顺序无效。')
        if key == 'depends_on' and (not isinstance(value, list) or len(value) > 100 or
                                   any(not isinstance(x, str) for x in value)):
            raise ValueError('依赖列表无效。')
        if key == 'references':
            if not isinstance(value, list) or len(value) > 100: raise ValueError('资料引用无效。')
            from project_materials import reference_scope
            scope = reference_scope(project)
            retained={ref.get('material_id') for ref in (extra.get('references') or ()) if isinstance(ref,dict)}
            for ref in value:
                if not isinstance(ref, dict) or not isinstance(ref.get('material_id'), str):
                    raise ValueError('请选择已登记资料。')
                kind, _, identifier = ref['material_id'].partition(':')
                members = scope['papers'] if kind == 'paper' else {**scope['documents'], **scope['history']} if kind == 'doc' else {}
                if identifier not in members and ref['material_id'] not in retained: raise ValueError('请先将资料明确选入本项目。')
                if any(not isinstance(v, str) or len(v) > 2000 for k0, v in ref.items() if k0 != 'material_id'):
                    raise ValueError('引用位置或说明无效。')
        extra[key] = copy.deepcopy(value)
    for field, tag in [('question_id', 'question'), ('step_id', 'step'), ('suggestion_id', 'suggestion')]:
        if field not in fields: continue
        value = fields[field]
        if value is not None:
            if not isinstance(value, str) or not re.fullmatch(r'[\w.-]+', value): raise ValueError('关联身份无效。')
            if tag == 'question' and value not in {q['id'] for q in k.lines(project)['rows']}:
                raise ValueError('关联研究问题不存在。')
            row['_tags'][tag] = value
        else: row['_tags'].pop(tag, None)


def _validate_graph(rows, metadata):
    ids = [row['id'] for row in rows]
    edges = {identifier: metadata.get(identifier, {}).get('depends_on', []) for identifier in ids}
    visiting = set(); complete = set(); ordered = []
    def visit(identifier):
        if identifier in visiting: raise ValueError('工作依赖不能形成循环。')
        if identifier in complete: return
        visiting.add(identifier)
        for target in edges[identifier]:
            if target not in edges or target.startswith('legacy-'): raise ValueError('依赖工作不存在或尚无稳定ID。')
            visit(target)
        visiting.remove(identifier); complete.add(identifier); ordered.append(identifier)
    for identifier in ids: visit(identifier)
    return ordered


def _apply_due_rules(rows, metadata):
    ordered=_validate_graph(rows,metadata)
    by_id={row['id']:row for row in rows}
    for identifier in ordered:
        entry=metadata.get(identifier,{})
        rule=entry.get('due_date_rule')
        if not rule:continue
        source_id=rule['task_id']
        if source_id not in entry.get('depends_on',[]):raise ValueError('日期规则的来源须是已选依赖事项。')
        if by_id[identifier]['done'] or entry.get('removed') or entry.get('replacement'):continue
        source=metadata.get(source_id,{})
        if not source.get('due_on') or source.get('removed') or source.get('replacement'):continue
        try:entry['due_on']=(date.fromisoformat(source['due_on'])+timedelta(days=rule['offset_days'])).isoformat()
        except (ValueError, OverflowError):raise ValueError('日期规则的来源日期无效，或计算结果超出日期范围。') from None


def _render_row(row):
    tags = dict(row['_tags']); tags['task'] = row['id']
    order = ('question', 'task', 'suggestion', 'step')
    marker = ' <!-- '+' '.join(key+':'+tags[key] for key in order if key in tags)+' -->'
    return row['_prefix']+('x' if row['done'] else ' ')+row['_middle']+row['title']+marker


def _calculate(project, raw, data, reserved, stamp):
    rows, extension, warnings = _parse(project, raw)
    if len({row['id'] for row in rows}) != len(rows): raise ValueError('存在重复task ID，请先核对原任务稿。')
    if warnings: raise ValueError('原任务扩展字段有格式问题，请先核对原稿：'+'；'.join(warnings))
    meta = copy.deepcopy(extension); changes = {}; added = []; result_ids = []
    by_id = {row['id']: row for row in rows}; op = data['op']; fields = data.get('fields', {})
    def new_row(title, payload, retained_stages=()):
        identifier = reserved[len(added)]
        if identifier in by_id:raise ValueError('新工作编号已存在，请使用新request_id。')
        row = {'id': identifier, 'title': _title(title), 'done': False,
               '_tags': {}, '_prefix': '- [', '_middle': '] '}
        extra = {'phase': '待定', 'created_at': stamp, 'item_type':'work'}
        _apply_fields(row, extra, payload, project, retained_stages)
        meta[identifier] = extra; added.append(row); return row
    if op == 'associate_stages':
        selected=data.get('task_ids');stage_id=data.get('stage_id')
        if not isinstance(selected,list) or not selected or len(selected)!=len(set(selected)) or any(i not in by_id for i in selected):raise ValueError('请选择有效计划。')
        for identifier in selected:
            row=by_id[identifier]
            if meta.get(identifier,{}).get('removed') or meta.get(identifier,{}).get('replacement'):raise ValueError('请选择活动计划。')
            if row['legacy']:
                row['id']=reserved[len(result_ids)];meta[row['id']]=meta.pop(identifier,{})
            extra=meta.setdefault(row['id'],{})
            linked=list(extra.get('stage_ids',[]))
            linked=[x for x in linked if x!=stage_id] if data.get('mode')=='remove' else list(dict.fromkeys([*linked,stage_id]))
            _apply_fields(row,extra,{'stage_ids':linked},project)
            changes[row['index']]=row;result_ids.append(row['id'])
    elif op == 'migrate':
        for row in rows:
            if not row['legacy']:continue
            row['id']=reserved[len(result_ids)]
            if row['id'] in by_id:raise ValueError('调整编号已存在，请重新预览。')
            changes[row['index']]=row;result_ids.append(row['id'])
    elif op == 'add':
        row = new_row(fields.get('title', fields.get('text', data.get('title'))), fields)
        result_ids.append(row['id'])
    elif op in ('split', 'merge'):
        originals = data.get('task_ids') or [data.get('task_id')]
        if not isinstance(originals, list) or len(originals) != len(set(originals)) or any(x not in by_id for x in originals):
            raise ValueError('请选择有效的原工作。')
        if any(by_id[x]['legacy'] or meta.get(x, {}).get('replacement') or meta.get(x, {}).get('removed') for x in originals):
            raise ValueError('原工作尚无稳定ID、已移除或已被替代，请先核对。')
        item_type=by_id[originals[0]]['item_type']
        if any(by_id[x]['item_type']!=item_type for x in originals):raise ValueError('工作和计划不能混合合并。')
        if op == 'split':
            children = data.get('children', data.get('items'))
            if len(originals) != 1 or not isinstance(children, list) or not 2 <= len(children) <= 100:
                raise ValueError('拆分需选择一项并填写至少两项新工作。')
            for child in children:
                if not isinstance(child, dict): raise ValueError('子工作格式无效。')
                inherited=meta.get(originals[0],{}).get('stage_ids',[])
                if child.get('item_type',item_type)!=item_type:raise ValueError('拆分必须保留原事项类别。')
                row = new_row(child.get('title', child.get('text')), {'stage_ids':inherited,**child,'item_type':item_type},inherited); result_ids.append(row['id'])
        else:
            if len(originals) < 2: raise ValueError('合并需要至少两项工作。')
            inherited=list(dict.fromkeys(s for identifier in originals for s in meta.get(identifier,{}).get('stage_ids',[])))
            if fields.get('item_type',item_type)!=item_type:raise ValueError('合并必须保留原事项类别。')
            row = new_row(data.get('title', fields.get('title')), {'stage_ids':inherited,**fields,'item_type':item_type},inherited); result_ids.append(row['id'])
        for identifier in originals:
            meta.setdefault(identifier, {})['replacement'] = {'kind': op, 'targets': result_ids[:]}
    else:
        row = by_id.get(data.get('task_id'))
        if row is None: raise ValueError('工作不存在，请刷新。')
        old_id = row['id']
        if row['legacy']:
            row['id'] = reserved[0]; meta[row['id']] = meta.pop(old_id, {})
        extra = meta.setdefault(row['id'], {})
        if op in ('check', 'update'): _apply_fields(row, extra, fields, project)
        elif op in ('remove', 'restore'): extra['removed'] = op == 'remove'
        elif op == 'pin': _apply_fields(row, extra, {'pin_rank': fields.get('pin_rank', 0)}, project)
        else: raise ValueError('工作操作不存在。')
        changes[row['index']] = row; result_ids.append(row['id'])
    _apply_due_rules(rows+added, meta)
    after = raw
    for row in reversed(rows):
        if row['index'] in changes: after = after[:row['_start']]+_render_row(row)+after[row['_end']:]
    if added: after = after.rstrip()+'\n\n'+'\n'.join(_render_row(row) for row in added)+'\n'
    after = k.properties(after, {'work_items': meta})
    return after, result_ids


def preview_updates(project, changes, raw=None):
    """Simulate ordered edits to existing, stable work items without writing."""
    if raw is None:
        path=path_for(project)
        raw=path.read_text('utf-8-sig') if path.is_file() else ''
    for change in changes:
        identifier=change.get('task_id')
        if change.get('op','update')!='update' or not isinstance(identifier,str) or identifier.startswith('legacy-'):
            raise ValueError('预览只接受已有稳定编号的工作或计划更新。')
        raw,_=_calculate(project,raw,{**change,'op':'update'},[],'')
    return raw


def preview(data):
    project = data.get('project') or '山药'; current = read(project)
    if data.get('fingerprint') != current['fingerprint']: raise ValueError('工作已变化，请重新预览。')
    if data.get('op') not in ('split', 'merge', 'migrate'): raise ValueError('此操作不需要预览。')
    from project_materials import reference_scope
    scope = reference_scope(project)['membership_fingerprint']
    token = w.digest(encode([_payload(data), current['fingerprint'], scope]))
    reserved = [w.digest(encode([project,data.get('request_id') or _payload(data),i]))[:16] for i in range(max(100,len(current['items'])))]
    raw = path_for(project).read_text('utf-8-sig') if path_for(project).exists() else ''
    after, ids = _calculate(project, raw, data, reserved, w.now())
    return {'preview_token': token, 'before': current,
            'after': [{key: value for key, value in row.items() if not key.startswith('_')} for row in _parse(project, after)[0]],
            'notice': '原工作保留且不自动完成；引用原工作的依赖需逐项核对。'}


def commit(data):
    return change(data)


def change(data, *, decision_id=None):
    project = data.get('project') or '山药'; path = path_for(project)
    request = data.get('request_id')
    if not isinstance(request, str) or not re.fullmatch(r'[\w.\-\[\] ,\x27:]{1,200}', request):
        raise ValueError('请提供有效request_id。')
    store = Store(); key = _operation_key(project, request); signature = w.digest(encode(_payload(data)))
    with profiles.lifecycle_lock(project), k.editing():
        profile = profiles.get(project)
        if profile['archived']: raise ValueError('项目已归档，请先恢复后修改工作。')
        if 'lifecycle_revision' in data and data['lifecycle_revision'] != profile['lifecycle_revision']:
            raise ValueError('项目状态已变化，请刷新。')
        raw = path.read_text('utf-8-sig') if path.exists() else ''
        __import__('research_records').recover_decisions(project,store)
        _recover(project, raw, store)
        intent = store.cursor(key, {})
        if intent and intent['payload_hash'] != signature: raise ValueError('同一request_id不能用于不同内容。')
        if intent.get('state') == 'completed':
            if intent.get('notification_pending'):_complete(store,key,intent)
            return {**read(project), 'result_ids': intent['result_ids'], 'reused': True}
        if data.get('item_fingerprint') is not None:
            current_local=item_fingerprint(project,data.get('task_id'),raw=raw)
            if data['item_fingerprint']!=current_local:
                raise ValueError('该工作或其直接依赖已变化，请重新预览；其他工作改动不会阻断本项。')
        elif data.get('fingerprint') != w.digest(raw):
            raise ValueError('工作已在其他窗口变化，请刷新后合并；输入未覆盖原稿。')
        if data.get('op') in ('split', 'merge', 'migrate'):
            if data.get('preview_token') != preview(data)['preview_token']: raise ValueError('预览已失效，请重新查看。')
        reserved = intent.get('reserved_ids') or [w.digest(encode([project,request,i]))[:16] for i in range(max(100,len(_parse(project,raw)[0])))]
        stamp = intent.get('time') or w.now()
        after, ids = _calculate(project, raw, data, reserved, stamp)
        intent = {'project': project, 'request_id': request, 'op': data['op'], 'payload_hash': signature,
                  'before': w.digest(raw), 'after': w.digest(after), 'result_ids': ids,
                  'reserved_ids': reserved, 'time': stamp, 'state': 'pending'}
        if decision_id:intent['decision_id']=decision_id
        store.commit_page(key, [], intent)
        if profiles.get(project)['lifecycle_revision'] != profile['lifecycle_revision']:
            raise ValueError('项目状态已变化，未写入。')
        k.persist(path, raw, after, w.KB.resolve())
        _complete(store, key, intent)
        return {**read(project), 'result_ids': ids, 'reused': False}
