"""Editable, bounded research records with optimistic concurrency and original copies."""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from datetime import datetime
from pathlib import Path
import re
import json
import threading
from contextvars import ContextVar
from urllib.parse import unquote, urlparse
import uuid
import yaml
import workflow as w

PREFIXES = ('背景', '项目', '更新记录', '文献/阅读卡片', '文献/条目', '文献/AI阅读记录', '笔记')
INDEXES = {'README.md', '开始.md', '科研资料首页.md', '文献/文献索引.md', '文献/新论文候选.md'}
PAPER_STATES = ['未读', '阅读中', '已读待核查', '已核查指定范围', '阅读范围见历史记录', '待核查阅读范围']
PROJECT_STATES = ['调研中', '待确定路线', '准备实验', '实验中', '分析中', '写作中', '已完成', '暂停']
LINE_STATES = ['待选择', '调研中', '已采用', '暂缓', '准备实验', '实验中', '分析中', '写作中', '已完成', '暂停', '不采用']
CANDIDATE_STATES = ['待核查', '不采纳', '已归档']
LOCK = threading.RLock()
FRONT = re.compile(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)', re.S)


def split(raw):
    match = FRONT.match(raw)
    try:
        meta = yaml.safe_load(match.group(1)) if match else {}
    except yaml.YAMLError:
        meta = {}
    return meta if isinstance(meta, dict) else {}, raw[match.end():] if match else raw, match


def path_for(relative, kb=None, existing=True):
    kb = (kb or w.KB).resolve()
    if not isinstance(relative, str) or not relative or '\x00' in relative:
        raise ValueError('资料路径无效')
    path = (kb/relative).resolve()
    if not path.is_relative_to(kb):
        raise ValueError('资料路径无效')
    name = path.relative_to(kb).as_posix()
    if path.suffix.lower() != '.md' or not (name in INDEXES or any(name.startswith(prefix+'/') for prefix in PREFIXES)):
        raise ValueError('只能编辑科研资料，不能访问设置、密钥或程序文件。')
    if existing and not path.is_file():
        raise ValueError('资料不存在')
    return path


def read(relative, kb=None):
    kb = kb or w.KB
    path = path_for(relative, kb)
    raw = path.read_text('utf-8-sig')
    meta, body, _ = split(raw)
    name = path.relative_to(kb.resolve()).as_posix()
    kind = '论文条目' if name.startswith('文献/条目/') else '阅读卡片' if name.startswith('文献/阅读卡片/') else 'AI 阅读记录' if name.startswith('文献/AI阅读记录/') else '背景候选' if name.startswith('更新记录/') else '项目记录' if name.startswith('项目/') else '共享背景' if name.startswith('背景/') else '笔记'
    if path.stem in {'领域脉络', '品种与材料身份脉络', '掺假研究脉络', '淀粉与热状态脉络'} and name.startswith('背景/'):
        kind = '领域导航'
    if meta.get('type') == 'ai_change_proposal': kind = 'AI 修改预览' if meta.get('status') == '待确认' else '修改历史'
    if meta.get('type') in ('organization_candidate', 'direction_candidate'): kind = '背景候选'
    if meta.get('type') == 'ai_analysis': kind = 'AI 分析记录'
    if meta.get('type') == 'personal_note': kind = meta.get('note_category') if meta.get('note_category') in ('项目经验','方法记录','论文批注') else '笔记'
    if meta.get('type') == 'ai_paper_note': kind = 'AI 阅读笔记'
    if meta.get('type') == 'ai_administrator_chat': kind = '管理员对话'
    if meta.get('type') == 'data_analysis': kind = '数据分析记录'
    options = PAPER_STATES if kind in ('论文条目', '阅读卡片') else CANDIDATE_STATES if kind == '背景候选' else PROJECT_STATES if path.name == '当前课题状态.md' else []
    status = str(meta.get('status') or ('待核查' if kind == '背景候选' else '未读' if kind in ('论文条目', '阅读卡片') else ''))
    if status and status not in options and options:
        options = [status]+options
    title = str(meta.get('title') or next((line[2:].strip() for line in body.splitlines() if line.startswith('# ')), path.stem))
    if kind == '阅读卡片' and title == path.stem:
        title = next((line[2:].strip() for line in body.splitlines() if line.startswith('# ')), title)
    if kind == 'AI 分析记录' and not meta.get('title'):
        headings = [line[2:].strip() for line in body.splitlines() if line.startswith('# ')]
        if len(headings)>1: title = headings[1]
    if meta.get('type') == 'ai_change_proposal' and not meta.get('title'):
        target = str(meta.get('target') or '科研记录')
        target = {'workflow':'自动流程','mainlines':'研究主线'}.get(target,Path(target).stem)
        summary = next((line.strip() for line in body.splitlines() if line.strip() and not line.startswith('#')), '')
        title = target+' · '+str(meta.get('status') or '修改预览')+' · '+summary[:65]
    paper_id = meta.get('paper_id')
    if not paper_id and kind == 'AI 阅读记录':
        referenced = set(re.findall(r'\[\[文献/条目/([\w.-]+)(?:\|[^\]]+)?\]\]', body))
        known = {r['id'] for r in w.read_json(kb/'文献/library.json', {'records': []})['records']}
        if len(referenced) == 1 and referenced.issubset(known): paper_id = referenced.pop()
    if not paper_id and kind == '阅读卡片':
        for record in w.read_json(kb/'文献/library.json', {'records': []})['records']:
            card = record.get('reading_card')
            if card and (Path(card) if Path(card).is_absolute() else kb/card).resolve() == path:
                paper_id = record['id']; break
    if kind == 'AI 阅读记录' and (not meta.get('title') or '功能验收' in title):
        record = next((r for r in w.read_json(kb/'文献/library.json', {'records': []})['records'] if r['id'] == paper_id), None)
        page = re.search(r'PDF 页码：\[([^\]]+)\]', body)
        question = re.search(r'(?m)^问题：(.*)', body)
        title = ((record.get('title') or record['id'])+' · 原页阅读'+(' · PDF '+page[1]+' 页' if page else '')) if record else '证据问答 · '+(question[1][:45] if question else path.stem)
    readonly_reason=('请在研究问题详情编辑解决方法。' if meta.get('question_id') else
                     '导航资料：请在对应背景、项目或论文入口维护内容。' if name in INDEXES else '')
    result = {'path': name, 'storage_path':str(path.resolve()), 'title': title, 'body': body, 'content': body, 'fingerprint': w.digest(raw), 'kind': kind, 'type': meta.get('type'),
            'status': status, 'status_options': options, 'reading_scope': str(meta.get('reading_scope') or ''),
            'project': str(meta.get('project') or (name.split('/')[1] if name.startswith('项目/') else '共享')), 'source_project':str(meta.get('source_project') or ''),
            'paper_id': paper_id, 'proposal_id': meta.get('proposal_id'), 'editable': path.name != '研究主线.md' and meta.get('type') != 'ai_change_proposal' and not readonly_reason,
            'readonly': bool(readonly_reason), 'readonly_reason': readonly_reason}
    from note_management import can_trash
    result['can_trash']=can_trash(result,kb)
    return result


_EDIT_DEPTH=ContextVar('knowledge_edit_depth',default=0)


@contextmanager
def editing():
    if _EDIT_DEPTH.get():
        yield
        return
    with LOCK, w.process_lock() as available:
        if not available:
            raise ValueError('正在同步资料，请稍后保存；编辑内容仍保留在窗口中。')
        token=_EDIT_DEPTH.set(1)
        try:yield
        finally:_EDIT_DEPTH.reset(token)


def validate_fingerprint(path, fingerprint):
    before = path.read_text('utf-8-sig') if path.exists() else ''
    if not isinstance(fingerprint, str) or w.digest(before) != fingerprint:
        raise ValueError('此记录已在其他窗口更新。请重新打开后合并，未覆盖原稿。')
    return before


def persist(path, before, after, kb):
    if before == after:
        return
    backup = w.DATA/'编辑备份'/w.digest(str(path.relative_to(kb.resolve())))[:16]
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
    if before:
        w.atomic_text(backup/(stamp+'.md'), before)
    w.atomic_text(path, after)
    w.write_json(backup/(stamp+'.json'), {'path': path.relative_to(kb.resolve()).as_posix(), 'time': w.now(), 'before': w.digest(before), 'after': w.digest(after)})


def properties(raw, updates):
    _, body, front = split(raw)
    metadata = front.group(1) if front else ''
    for key, value in updates.items():
        # Replace a complete YAML property (including block values), preserving unrelated sync data.
        pattern = re.compile(r'(?m)^'+re.escape(key)+r':[^\n]*(?:\n(?:[ \t]+[^\n]*|-[ \t]+[^\n]*|[ \t]*))*(?=\n[^ \t\n]|\Z)')
        encoded = key+': '+json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else yaml.safe_dump({key: value}, allow_unicode=True, sort_keys=False).rstrip()
        if pattern.search(metadata):
            metadata = pattern.sub(lambda _: encoded, metadata)
        else:
            metadata = metadata.rstrip()+'\n'+encoded
    return '---\n'+metadata.strip()+'\n---\n'+body


def save(relative, body, fingerprint, kb=None, title=None, *, notify=True):
    kb = kb or w.KB
    path = path_for(relative, kb)
    if split(path.read_text('utf-8-sig'))[0].get('record_type')=='Stage':
        raise ValueError('请在项目阶段详情中编辑；输入保留，未绕过阶段记录结构。')
    if not isinstance(body, str) or not body.strip() or len(body) > 100000:
        raise ValueError('正文不能为空，最多保存 10 万字。')
    if path.name == '研究主线.md':
        raise ValueError('请使用研究主线编辑入口保存，图表会同步更新。')
    current = read(relative, kb)
    if title is not None and (not isinstance(title, str) or not title.strip() or len(title) > 500):
        raise ValueError('请填写标题，最多 500 字。')
    if current.get('readonly') or current.get('proposal_id'):
        raise ValueError(current.get('readonly_reason') or '此记录是修改预览，请使用对应的确认入口。')
    with editing():
        before = validate_fingerprint(path, fingerprint)
        _, _, front = split(before)
        after = (before[:front.end()] if front else '')+body.rstrip()+'\n'
        if title is not None:
            heading = re.compile(r'(?m)^# [^\n]*')
            body = heading.sub(lambda _: '# '+title.strip(), body, count=1) if heading.search(body) else '# '+title.strip()+'\n\n'+body
            after = properties(after, {'title': title.strip()})
            _, _, updated_front = split(after)
            after = after[:updated_front.end()]+body.rstrip()+'\n'
        if split(before)[0].get('standard_template') is True:
            after = properties(after, {'standard_template': False})
        persist(path, before, after, kb)
    if notify and before!=after and kb.resolve()==w.KB.resolve():
        import workspace_catalog as catalog
        catalog.notify_change(path)
    return read(relative, kb)


def save_legacy(data):
    """Keep the old path-based editor under the same original-owner check."""
    from project_profiles import original_path_edit
    relative=path_for(data.get('path')).relative_to(w.KB.resolve()).as_posix()
    with original_path_edit('科研知识库/'+relative,data):
        return save(relative,data.get('body'),data.get('fingerprint'),title=data.get('title'))


def change_status_legacy(data):
    from project_profiles import original_path_edit
    relative=path_for(data.get('path')).relative_to(w.KB.resolve()).as_posix()
    with original_path_edit('科研知识库/'+relative,data):
        return change_status(relative,data.get('status'),data.get('fingerprint'),data.get('scope',''))


def change_status(relative, status, fingerprint, scope='', kb=None, accepted=False):
    kb = kb or w.KB
    path = path_for(relative, kb)
    doc = read(relative, kb)
    if status not in doc['status_options'] and not (accepted and status == '已采纳' and doc['kind'] == '背景候选'):
        raise ValueError('此记录不支持该状态。')
    if status == '已核查指定范围' and (not isinstance(scope, str) or not scope.strip()):
        raise ValueError('请填写实际核查的 PDF 页码、章节或图号。')
    if not isinstance(scope, str) or len(scope) > 2000:
        raise ValueError('核查范围不合适。')
    with editing():
        before = validate_fingerprint(path, fingerprint)
        updates = {'status': status, 'status_updated': w.now()}
        if scope.strip():
            updates['reading_scope'] = scope.strip()
        persist(path, before, properties(before, updates), kb)
        if doc['kind'] in ('论文条目', '阅读卡片'):
            library_path = kb/'文献/library.json'
            library = w.read_json(library_path, {'records': []})
            code = {'未读': 'unread', '阅读范围见历史记录': 'see_linked_historical_review_scope', '待核查阅读范围': 'not_asserted_by_this_import'}.get(status, status)
            identifier = doc['paper_id'] or (path.stem if doc['kind'] == '论文条目' else None)
            for record in library['records']:
                if record['id'] == identifier:
                    record['reading_status'] = code
                    record['reading_status_updated'] = updates['status_updated']
                    if scope.strip(): record['reading_scope'] = scope.strip()
                    elif not record.get('reading_scope') and doc['reading_scope']:
                        record['reading_scope'] = doc['reading_scope']
            if library_path.exists(): w.write_json(library_path, library)
    result=read(relative,kb)
    if status=='不采纳' and result['can_trash']:
        import note_management
        # A candidate decision leaves formal evidence unchanged and is recoverable.
        if kb.resolve()!=w.KB.resolve():return result
        row=note_management.move({'path':relative,'fingerprint':result['fingerprint'],'reason':'不采纳候选'})
        result.update(trashed=True,trash_id=row['id'])
    return result


def default_lines(project):
    if project != '山药': return []
    return [
        {'id': 'identity', 'title': '品种与材料身份', 'status': '待选择', 'goal': '材料可追溯、独立批次与身份核查', 'paper_ids': ['LASSO_2024', 'PMC12530841']},
        {'id': 'adulteration', 'title': '掺假与定量', 'status': '待选择', 'goal': '掺入物、比例与独立验证集', 'paper_ids': ['LIBS_YAM_2022_MDPI', 'FTIR_2012']},
        {'id': 'thermal', 'title': '热处理与淀粉状态', 'status': '待选择', 'goal': '加热、水分、DSC / XRD 与 THz 适用边界', 'paper_ids': ['NAKAJIMA_2021_FT_THz_accepted_manuscript', 'PMC12993170']},
    ]


def line_path(project, kb):
    if not isinstance(project, str) or not re.fullmatch(r'[^/\\<>:"|?*\x00-\x1f]{1,60}', project) or project in ('.', '..'):
        raise ValueError('项目不存在')
    folder = (kb/'项目'/project).resolve()
    if not folder.is_relative_to((kb/'项目').resolve()) or not folder.is_dir(): raise ValueError('项目不存在')
    return folder/'研究主线.md'


def project_background(project, kb=None):
    """One background manuscript per project; the existing yam manuscript keeps its identity."""
    kb = kb or w.KB
    line_path(project, kb)
    return '背景/太赫兹光谱与山药研究背景.md' if project == '山药' else f'项目/{project}/方向背景.md'


def plain_label(text):
    return re.sub(r'["<>\[\]{}|`\\\r\n]', ' ', str(text))[:90]


def lines(project, kb=None):
    kb = kb or w.KB
    path = line_path(project, kb)
    raw = path.read_text('utf-8-sig') if path.exists() else ''
    meta, _, _ = split(raw)
    rows = meta.get('research_lines', default_lines(project))
    diagram = ['flowchart LR', f'P["{plain_label(project)} · 研究主线"]']
    for index, row in enumerate(rows):
        diagram += [f'P --> L{index}["{plain_label(row["title"])} · {plain_label(row["status"])}"]', f'L{index} --> G{index}["{plain_label(row.get("goal", ""))}"]']
    if not rows: diagram += ['P --> Q["尚未登记研究主线；点击下方添加"]']
    return {'path': path.relative_to(kb.resolve()).as_posix(), 'canvas': path.with_suffix('.canvas').relative_to(kb.resolve()).as_posix(), 'fingerprint': w.digest(raw), 'rows': rows, 'diagram': '\n'.join(diagram), 'status_options': LINE_STATES}


def validate_lines(rows, kb=None):
    kb = kb or w.KB
    if not isinstance(rows, list) or len(rows) > 30: raise ValueError('主线最多 30 条。')
    known = {r['id'] for r in w.read_json(kb/'文献/library.json', {'records': []})['records']}
    result = []; used = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict): raise ValueError('主线格式无效')
        identifier = row.get('id') or 'line_'+uuid.uuid4().hex[:8]
        title, goal, status = row.get('title'), row.get('goal', ''), row.get('status', '待选择')
        ids = row.get('paper_ids', [])
        if not isinstance(identifier, str) or not re.fullmatch(r'[\w.-]{1,80}', identifier) or identifier in used: raise ValueError('主线 ID 无效或重复')
        if not isinstance(title, str) or not title.strip() or len(title) > 120 or not isinstance(goal, str) or len(goal) > 2000 or status not in LINE_STATES: raise ValueError('请填写主线名称、目标和有效状态。')
        if not isinstance(ids, list) or any(not isinstance(i, str) or i not in known for i in ids): raise ValueError('关联的文献 ID 不在本地库中。')
        result.append({'id': identifier, 'title': title.strip(), 'status': status, 'goal': goal, 'paper_ids': list(dict.fromkeys(ids))}); used.add(identifier)
    return result


def save_lines(project, rows, fingerprint, kb=None, *, already_locked=False):
    kb = kb or w.KB
    path = line_path(project, kb)
    rows = validate_lines(rows, kb)
    with nullcontext() if already_locked else editing():
        before = validate_fingerprint(path, fingerprint)
        _, body, _ = split(before)
        remarks = body.split('## 我的补充', 1)[1] if '## 我的补充' in body else '\n'
        table = ['# '+project+'研究主线', '', '[在科研工作台编辑主线](http://127.0.0.1:8503/?section=home)。名称、状态和关联论文直接用于图表。初始导航不代表已确定课题路线。', '', '| 主线 | 状态 | 目标 | 关联论文 |', '| --- | --- | --- | --- |']
        for row in rows:
            cells = [row['title'], row['status'], row['goal'], '、'.join('[[文献/条目/'+i+']]' for i in row['paper_ids'])]
            table.append('| '+' | '.join(c.replace('|', '\\|').replace('\n', '<br>') for c in cells)+' |')
        table += ['', '## 我的补充'+remarks]
        after = properties(before, {'type': 'research_lines', 'project': project, 'research_lines': rows, 'updated': w.now()})
        meta, _, front = split(after)
        persist(path, before, after[:front.end()]+'\n'.join(table).rstrip()+'\n', kb)
        refresh_line_canvas(project, rows, kb)
    return lines(project, kb)


def refresh_line_canvas(project, rows, kb=None):
    kb = (kb or w.KB).resolve()
    path = line_path(project, kb).with_suffix('.canvas')
    previous = w.read_json(path, {})
    if previous and previous.get('workspace_generated') != 'research_lines':
        return {'status': 'preserved_existing_layout'}
    positions = {n['id']: n for n in previous.get('nodes', [])}
    nodes = []; edges = []
    def add(identifier, kind, value, x, y, width=350, height=230):
        old = positions.get(identifier, {})
        nodes.append({'id': identifier, 'type': kind, 'file' if kind == 'file' else 'text': value,
                      **{key: old.get(key, default) for key, default in [('x', x), ('y', y), ('width', width), ('height', height)]}})
    add('project', 'file', f'项目/{project}/当前课题状态.md', 0, 0, 390, 330)
    from knowledge_graph import paper_display
    records={record['id']:record for record in w.read_json(kb/'文献/library.json',{'records':[]})['records']}
    for index, row in enumerate(rows):
        identifier = 'line-'+row['id']; y = index*350
        add(identifier, 'text', '# '+row['title']+'\n\n**状态：'+row['status']+'**\n\n'+row['goal'], 470, y)
        edges.append({'id': 'project-'+identifier, 'fromNode': 'project', 'fromSide': 'right', 'toNode': identifier, 'toSide': 'left'})
        for pi, paper in enumerate(row['paper_ids']):
            node_id = identifier+'-'+paper
            source=paper_display(records[paper],kb)['path'] if paper in records else '文献/条目/'+paper+'.md'
            add(node_id, 'file', source, 940+pi*390, y, 350, 330)
            edges.append({'id': 'edge-'+node_id, 'fromNode': identifier, 'fromSide': 'right', 'toNode': node_id, 'toSide': 'left'})
    # Preserve user-added cards and edges; only the generated mainline cards are refreshed.
    own = {n['id'] for n in nodes}
    nodes += [n for n in previous.get('nodes', []) if n['id'] not in own and n['id'] != 'project' and not n['id'].startswith('line-')]
    edge_ids = {e['id'] for e in edges}
    all_ids = {n['id'] for n in nodes}
    edges += [e for e in previous.get('edges', []) if e['id'] not in edge_ids and e.get('fromNode') in all_ids and e.get('toNode') in all_ids]
    value = {'workspace_generated': 'research_lines', 'nodes': nodes, 'edges': edges}
    if previous != value: w.write_json(path, value)
    return {'status': 'updated', 'path': path.relative_to(kb).as_posix()}


def inventory(project, kb=None):
    kb = (kb or w.KB).resolve()
    result = []
    paths = list((kb/'背景').glob('*.md'))+list((kb/'项目'/project).glob('*.md'))+list((kb/'文献/阅读卡片').glob('*.md'))+list((kb/'文献/AI阅读记录').glob('*.md'))
    paths += [p for p in (kb/'更新记录').glob('*.md') if split(p.read_text('utf-8-sig'))[0].get('type') == 'ai_change_proposal' and split(p.read_text('utf-8-sig'))[0].get('status') != '待确认']
    paths += list((kb/'项目'/project/'数据分析').glob('*.md'))
    paths += list((kb/'笔记').rglob('*.md'))
    records = w.read_json(kb/'文献/library.json', {'records': []})['records']
    line_rows=lines(project,kb)['rows'];linked={identifier for row in line_rows if row['status']!='不采用' for identifier in row['paper_ids']}
    for path in paths:
        if not path.read_text('utf-8-sig').strip(): continue
        doc = read(path.relative_to(kb.resolve()).as_posix(), kb)
        if doc['kind']=='管理员对话' or doc['status']=='不采纳':continue
        ids = []
        for record in records:
            card = record.get('reading_card')
            if card and (Path(card) if Path(card).is_absolute() else kb/card).resolve() == path.resolve(): ids.append(record['id'])
        ids += re.findall(r'\[\[文献/条目/([\w.-]+)', doc['body'])
        if doc.get('paper_id'):ids.append(doc['paper_id'])
        meta=split(path.read_text('utf-8-sig'))[0]
        ids += meta.get('paper_ids',[]) if isinstance(meta.get('paper_ids',[]),list) else []
        from note_management import can_trash
        if doc['project'] not in (project,'共享') and not set(ids)&linked:continue
        result.append({key: doc[key] for key in ('path', 'title', 'kind', 'project', 'status','storage_path','fingerprint','source_project')} | {'paper_ids': list(dict.fromkeys(ids)), 'line_ids':meta.get('mainline_ids',[]), 'can_trash':can_trash(doc,kb)})
    for item in result:
        item['mainlines']=[{'id':row['id'],'title':row['title']} for row in line_rows if row['status']!='不采用' and (row['id'] in item['line_ids'] or set(row['paper_ids'])&set(item['paper_ids']))]
    for item in result:
        item['related_notes']=[{'path':other['path'],'title':other['title'],'relation':'同一论文' if set(item['paper_ids'])&set(other['paper_ids']) else '同一主线'} for other in result if other['path']!=item['path'] and (set(item['paper_ids'])&set(other['paper_ids']) or {r['id'] for r in item['mainlines']}&{r['id'] for r in other['mainlines']})][:12]
    return result


def paper_note(identifier, kb=None):
    kb = (kb or w.KB).resolve()
    if not isinstance(identifier, str) or not re.fullmatch(r'[\w.-]{1,100}', identifier): raise ValueError('论文不存在')
    with editing():
        library_path = kb/'文献/library.json';library = w.read_json(library_path)
        record = next((r for r in library['records'] if r['id'] == identifier), None)
        if record is None: raise ValueError('论文不存在')
        if record.get('reading_card'):
            existing = (Path(record['reading_card']) if Path(record['reading_card']).is_absolute() else kb/record['reading_card']).resolve()
            if existing.is_relative_to(kb.resolve()) and existing.is_file():
                from paper_notes import note_path
                completed = note_path(identifier, kb)
                if split(existing.read_text('utf-8-sig'))[0].get('standard_template') is True and completed.is_file(): return read(completed.relative_to(kb).as_posix(), kb)
                return read(existing.relative_to(kb.resolve()).as_posix(), kb)
        from paper_notes import note_path
        completed = note_path(identifier, kb)
        if completed.is_file(): return read(completed.relative_to(kb).as_posix(), kb)
        path = kb/'文献/阅读卡片'/(identifier+'.md')
        if not path.exists():
            raw = properties('', {'type': 'reading_card', 'paper_id': identifier, 'project': record.get('project') or '共享', 'status': '待核查', 'standard_template': True, 'title': record['title']+' · 阅读笔记'})
            raw += '# '+record['title']+' · 阅读笔记\n\n对应论文：[[文献/条目/'+identifier+']]\n\n'
            raw += '## 文献身份\n\n题名：'+record['title']+'\n\n作者：'+str(record.get('authors') or '题录待补，不猜测')+'\n\n年份：'+str(record.get('publication_date') or record.get('year') or '题录待补')+'\n\nDOI：'+str(record.get('doi') or '未登记')+'\n\n'
            raw += '## 实际阅读范围\n\n请填写实际查看的 PDF 页码、章节和图号；尚未阅读时保留未核查。\n\n## 研究问题与主要结论\n\n每条发现注明文献 ID 与原文位置。\n\n## 方法、样品与实验条件\n\n## 数据与图表\n\n记录图号、页码、坐标轴、单位和能支持的判断。\n\n## 对当前课题的价值与限制\n\n## 我的批注与下一步\n\n## AI 建议与待核问题\n'
            w.atomic_text(path, raw)
        record['reading_card'] = path.resolve().as_posix(); w.write_json(library_path, library)
    return read(path.relative_to(kb.resolve()).as_posix(), kb)


def resolve_note(target, base='', kb=None):
    kb = kb or w.KB
    if not isinstance(target, str) or len(target) > 2000: raise ValueError('链接无效')
    target = unquote(target).split('#', 1)[0]
    if Path(target).suffix.lower() in {'.pdf', '.xml'}:
        matches = []
        target_name = Path(target).name.casefold()
        for record in w.read_json(kb/'文献/library.json', {'records': []})['records']:
            for artifact in record.get('artifacts', []):
                if artifact.get('kind') in ('pdf', 'jats_xml') and Path(artifact['path']).is_file() and Path(artifact['path']).name.casefold() == target_name:
                    matches.append((record['id'], artifact['kind']))
        matches = list(dict.fromkeys(matches))
        if len(matches) == 1:
            identifier, kind = matches[0]
            return {'kind': 'paper_reference', 'paper_id': identifier, 'artifact_kind': kind}
        raise ValueError('未找到唯一对应的已登记原文，请使用这篇论文的原文入口。')
    absolute = Path(target)
    if absolute.is_absolute() and absolute.resolve().is_relative_to(kb.resolve()):
        return read(absolute.resolve().relative_to(kb.resolve()).as_posix(), kb)
    if urlparse(target).scheme or '?' in target: raise ValueError('这是外部链接，请使用原文入口。')
    possibilities = [(kb/target), (kb/Path(base).parent/target)]
    for path in possibilities:
        if not path.suffix: path = path.with_suffix('.md')
        try: return read(path.resolve().relative_to(kb.resolve()).as_posix(), kb)
        except (ValueError, OSError): pass
    # Original research reports stay in place and are shown read-only.
    for path in possibilities:
        path = path.resolve()
        if kb.resolve() == w.KB.resolve() and path.suffix.lower() == '.md' and path.is_file() and any(path.is_relative_to((w.ROOT/prefix).resolve()) for prefix in ('research', 'output')):
            _, body, _ = split(path.read_text('utf-8-sig'))
            return {'path': path.relative_to(w.ROOT).as_posix(), 'title': path.stem, 'body': body, 'content': body, 'kind': '原始研究报告', 'project': '历史原稿', 'editable': False, 'readonly': True, 'status_options': []}
    matches = [p for prefix in PREFIXES for p in (kb/prefix).rglob('*.md') if p.stem == Path(target).stem and p.read_text('utf-8-sig').strip()]
    if len(matches) == 1: return read(matches[0].relative_to(kb.resolve()).as_posix(), kb)
    raise ValueError('未找到唯一对应的科研笔记，请从资料目录选择；原文件仍保留。')


def refresh_navigation(kb=None):
    """Generate one native index; formal records, pending proposals and history are distinct."""
    kb = (kb or w.KB).resolve()
    rows = ['# 科研资料首页', '', '日常编辑、状态切换和 AI 修改：[打开科研工作台](http://127.0.0.1:8503)。这里沿用同一套资料，点击名称打开对应记录。', '',
            '正式背景保存已核查且注明来源的认识；项目记录保存你的决定与当前进展；阅读笔记对应具体论文；候选与 AI 记录进入待确认或历史。', '', '## 背景与个人条件', '']
    for p in sorted((kb/'背景').glob('*.md')):
        doc = read(p.relative_to(kb.resolve()).as_posix(), kb)
        if doc['kind'] != '共享背景': continue
        rows.append('- [['+doc['path']+'|'+doc['title']+']]')
    rows += ['', '## 领域与研究主线导航', '']
    for p in sorted((kb/'背景').glob('*.md')):
        doc = read(p.relative_to(kb.resolve()).as_posix(), kb)
        if doc['kind'] == '领域导航': rows.append('- [['+doc['path']+'|'+doc['title']+']] · 导览，以正式背景及当前主线为准')
    rows += ['', '## 当前项目', '']
    for folder in sorted((kb/'项目').iterdir()) if (kb/'项目').exists() else []:
        if not folder.is_dir(): continue
        rows.append('### '+folder.name)
        for name in ['当前课题状态.md', '研究主线.md', '任务.md']:
            p = folder/name
            if p.is_file(): rows.append('- [['+p.relative_to(kb.resolve()).as_posix()+'|'+name[:-3]+']]')
        canvas = folder/'研究主线.canvas'
        if canvas.exists(): rows.append('- [['+canvas.relative_to(kb.resolve()).as_posix()+'|当前主线图（随保存更新）]]')
    rows += ['', '## 论文与对应阅读笔记', '', '原文与附件以 Zotero 为准。每个文献 ID 对应一个正式条目，阅读范围写在卡片中。', '']
    for record in w.read_json(kb/'文献/library.json', {'records': []})['records']:
        from knowledge_graph import paper_display
        row = '- [[文献/条目/'+record['id']+'|'+paper_display(record,kb)['label']+']]'
        card = record.get('reading_card')
        if card:
            p = (Path(card) if Path(card).is_absolute() else kb/card).resolve()
            if p.is_relative_to(kb.resolve()) and p.exists(): row += ' · [['+p.relative_to(kb.resolve()).as_posix()+'|对应阅读卡片]]'
        from paper_notes import note_path
        note=note_path(record['id'],kb)
        if note.is_file():row+=' · [['+note.relative_to(kb.resolve()).as_posix()+'|中文阅读笔记]]'
        rows.append(row)
    rows += ['', '## 待确认更新', '', '[在工作台核查与确认修改](http://127.0.0.1:8503/?section=updates)。候选不会自动覆盖正式背景。', '']
    for p in sorted((kb/'更新记录').glob('*.md'), reverse=True):
        doc = read(p.relative_to(kb.resolve()).as_posix(), kb)
        if doc['status'] in ('待核查', '待确认'): rows.append('- [['+doc['path']+'|'+doc['title']+']] · '+doc['status'])
    rows += ['', '## 历史阅读与 AI 记录', '', '[在工作台按论文找历史记录](http://127.0.0.1:8503/?section=history)。AI 分析不是已核查事实。', '']
    for p in sorted((kb/'文献/AI阅读记录').glob('*.md'), reverse=True)[:20]:
        doc = read(p.relative_to(kb.resolve()).as_posix(), kb)
        rows.append('- [['+doc['path']+'|'+doc['title']+' · '+p.stem[:8]+']]')
    path = kb/'科研资料首页.md'
    if path.exists() and not path.read_text('utf-8-sig').startswith('---\ntype: workspace_index\n'):
        raise ValueError('同名资料首页属于原有记录，未覆盖。')
    text = '---\ntype: workspace_index\n---\n'+'\n'.join(rows)+'\n'
    if not path.exists() or path.read_text('utf-8-sig') != text: w.atomic_text(path, text)
    return {'path': '科研资料首页.md'}
