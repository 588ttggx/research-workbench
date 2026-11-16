"""Read existing evidence and tasks for a single, local research homepage."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
import re
import threading

import yaml
import workflow as w
import knowledge
import automation_controls

TASK_LOCK = threading.Lock()
TASK = re.compile(r'(?m)^(\s*[-*+]\s+\[)([ xX])(\]\s+)(.*)$')
ALLOWED = ('背景', '项目', '更新记录', '文献/阅读卡片', '文献/条目', '文献/AI阅读记录')
def publication_year(record):
    value = record.get('year') or record.get('publication_date') or record.get('date')
    match = re.search(r'\b(19\d{2}|20\d{2})\b', str(value or ''))
    return match.group(1) if match else None


def paper_groups(records, lines):
    known = {record['id'] for record in records}
    grouped = {}; assigned = set()
    for line in lines:
        ids = [identifier for identifier in line.get('paper_ids', []) if identifier in known]
        if ids:
            grouped.setdefault(line['title'], []).extend(i for i in ids if i not in grouped.get(line['title'], []))
            assigned.update(ids)
    for record in records:
        if record['id'] in assigned:
            continue
        topic = str(record.get('topic') or '').strip()
        name = re.split(r'[；;/]', topic, maxsplit=1)[0].strip() if topic else ''
        if name in ('待归类', '未归类', ''):
            name = '待归类的新资料'
        grouped.setdefault(name, []).append(record['id'])
    return grouped


def project_folder(project, kb):
    if not isinstance(project, str) or not project or '/' in project or '\\' in project or project in {'.', '..'}:
        raise ValueError('项目不存在')
    folder = (kb/'项目'/project).resolve()
    if not folder.is_relative_to((kb/'项目').resolve()) or not folder.is_dir():
        raise ValueError('项目不存在')
    return folder


def document(relative, kb=None):
    return knowledge.read(relative, kb)


def candidates(project, kb=None):
    kb = kb or w.KB
    result = []
    for path in sorted((kb/'更新记录').glob('*.md'), key=lambda p:p.stat().st_mtime, reverse=True):
        raw = path.read_text('utf-8-sig')
        front = re.match(r'\A---\r?\n(.*?)\r?\n---', raw, re.S)
        try:
            meta = (yaml.safe_load(front.group(1)) or {}) if front else {}
        except yaml.YAMLError:
            meta = {}
        if not isinstance(meta, dict):
            continue
        if meta.get('type') not in ('background_candidate', 'organization_candidate', 'direction_candidate'):
            continue
        if meta.get('project') not in (None, project, '共享'):
            continue
        if meta.get('status','待核查') not in ('待核查','待确认'):continue
        relative = path.relative_to(kb).as_posix()
        entry = document(relative, kb)
        ids = list(dict.fromkeys(re.findall(r'\[\[文献/条目/([\w.-]+)(?:\|[^\]]+)?\]\]', raw)))
        saved = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
        title = {'background_candidate': '背景检查', 'organization_candidate': 'AI 资料整理', 'direction_candidate': '领域方向候选'}[meta['type']]
        entry.update(title=title+' · '+saved.strftime('%m月%d日 %H:%M'), status=meta.get('status', '待核查'), paper_ids=ids, saved=saved.isoformat(timespec='seconds'))
        result.append(entry)
    latest={}
    for entry in result:latest.setdefault(entry.get('type') or entry['kind'],entry)
    return list(latest.values())


def tasks(project, kb=None):
    import project_tasks as work
    if kb is not None and kb.resolve()!=w.KB.resolve():
        # Isolated callers retain their explicitly supplied root.
        path=project_folder(project,kb)/'任务.md'
        raw=path.read_text('utf-8-sig') if path.exists() else ''
        rows,_,_=work._parse(project,raw)
        return {'path':f'项目/{project}/任务.md','fingerprint':w.digest(raw),
                'items':[{key:value for key,value in row.items() if not key.startswith('_')} for row in rows if not row['removed']]}
    result=work.read(project)
    return {**result,'path':result['source_path'],'items':[r for r in result['items'] if not r['removed']]}


def update_task(project,index,done,fingerprint,kb=None):
    import project_tasks as work
    if type(index) is not int or type(done) is not bool or not isinstance(fingerprint,str):
        raise ValueError('任务修改无效')
    if kb is not None and kb.resolve()!=w.KB.resolve():
        # Used only by standalone read/edit consumers with an isolated KB root.
        with TASK_LOCK:
            before=tasks(project,kb)
            if fingerprint!=before['fingerprint']:raise ValueError('任务已变化，请刷新。')
            path=project_folder(project,kb)/'任务.md';raw=path.read_text('utf-8-sig')
            matches=list(TASK.finditer(raw))
            if not 0<=index<len(matches):raise ValueError('任务不存在')
            match=matches[index];knowledge.persist(path,raw,raw[:match.start(2)]+('x' if done else ' ')+raw[match.end(2):],kb.resolve())
        return tasks(project,kb)
    target=next((r for r in work.read(project)['items'] if r['index']==index),None)
    if target is None:raise ValueError('任务不存在')
    work.change({'project':project,'op':'check','task_id':target['id'],'fields':{'done':done},
                 'fingerprint':fingerprint,'request_id':'legacy-'+w.digest(str([index,done,fingerprint]))[:32]})
    return tasks(project,kb)


def label(text):
    # Mermaid labels remain plain text; no external HTML, directives or click code.
    return re.sub(r'["<>\[\]{}|`\\\r\n]', ' ', str(text))[:65]


def evidence(identifier, kb=None):
    kb = kb or w.KB
    records = w.read_json(kb/'文献/library.json', {'records': []})['records']
    record = next((record for record in records if record['id'] == identifier), None)
    if record is None:
        raise ValueError('文献不存在')
    card = record.get('reading_card')
    if card:
        path = Path(card)
        if not path.is_absolute():
            path = kb/path
        path = path.resolve()
        if path.is_relative_to(kb.resolve()) and path.is_file():
            from paper_notes import note_path
            completed = note_path(identifier, kb)
            if knowledge.split(path.read_text('utf-8-sig'))[0].get('standard_template') is True and completed.is_file(): return document(completed.relative_to(kb.resolve()).as_posix(), kb)
            result = document(path.relative_to(kb.resolve()).as_posix(), kb)
            result['kind'] = '已保存阅读卡片（范围见正文）'
            return result
    from paper_notes import note_path
    completed = note_path(identifier, kb)
    if completed.is_file(): return document(completed.relative_to(kb.resolve()).as_posix(), kb)
    result = document(f'文献/条目/{identifier}.md', kb)
    result['kind'] = '文献条目；阅读范围请沿用历史核查记录'
    return result


def overview(project, kb=None):
    kb = kb or w.KB
    folder = project_folder(project, kb)
    records = w.read_json(kb/'文献/library.json', {'records': []})['records']
    by_id = {record['id']: record for record in records}
    mainlines = knowledge.lines(project, kb)
    grouped = paper_groups(records, mainlines['rows'])
    field = mainlines['diagram']
    relationships = ['flowchart LR', f'K["共用证据库 · {len(records)} 篇"]']
    paper_diagrams = {}
    evidence_groups = []
    for gi, (name, ids) in enumerate(grouped.items()):
        if not ids:
            continue
        relationships += [f'K --> G{gi}["{label(name)} · {len(ids)} 篇"]']
        group_diagram = ['flowchart LR', f'G["{label(name)} · {len(ids)} 篇"]']
        papers = []
        for pi, identifier in enumerate(ids):
            record = by_id[identifier]
            short = record.get('title', identifier)
            group_diagram += [f'G --> P{pi}["{label(short)}"]']
            papers.append({'id': identifier, 'title': short, 'doi': record.get('doi'), 'card': f'文献/条目/{identifier}.md'})
        evidence_groups.append({'name': name, 'papers': papers})
        paper_diagrams[name] = '\n'.join(group_diagram)
    timeline = ['timeline', 'title 已有卡片中的代表线索（按发表年份）']
    timeline_papers = []
    dates = w.read_json(w.DATA/'书目日期.json', {})
    def record_year(record):
        cached = dates.get(record['id'], {})
        return publication_year(record) or (cached.get('year') if cached.get('doi') == w.normalize_doi(record.get('doi')) else None)
    for record in sorted(records, key=lambda r: (record_year(r) or '9999', r.get('title', ''))):
        year = record_year(record)
        title = record.get('title', record['id'])
        timeline_papers.append({'year': year, 'id': record['id'], 'title': title, 'year_source': '已保存书目日期' if publication_year(record) else dates.get(record['id'], {}).get('source', '年份待补充')})
        if year:
            timeline.append(f'{year} : {label(title)}')
    if len(timeline) == 2:
        timeline.append('年份待补充 : 从 Zotero 题录同步发表日期；不从文件名猜测')
    task_state = tasks(project, kb)
    status_path = folder/'当前课题状态.md'
    project_status = knowledge.read(status_path.relative_to(kb.resolve()).as_posix(), kb)['status'] if status_path.is_file() else ''
    progress = ['flowchart LR', f'P["{label(project)} · {label(project_status or "状态待填写")}"]']
    for item in task_state['items']:
        progress.append(f'P --> T{item["index"]}["{"已完成" if item["done"] else "待办"} · {label(item["text"])}"]')
    if not task_state['items']:
        progress.append('P --> Q["尚未登记任务"]')
    readings = Counter(record.get('reading_status') or 'unread' for record in records)
    reading_labels = {'unread': '未读', 'see_linked_historical_review_scope': '有历史核查记录（范围见卡片）', 'not_asserted_by_this_import': '待核查阅读范围'}
    pie = ['pie showData', 'title 阅读范围记录'] + [f'"{label(reading_labels.get(code, code))}" : {count}' for code, count in readings.items()]
    accumulation = automation_controls.diagram()
    documents = []
    for path in [*sorted((kb/'背景').glob('*.md')), folder/'当前课题状态.md']:
        if path.exists():
            documents.append(document(path.relative_to(kb).as_posix(), kb))
    scope = '导航整理依据已保存背景与阅读卡片；覆盖当前积累的太赫兹×山药及邻近方法，关系线表示主题归类。' if project == '山药' else '当前项目沿用共享条件与文献库；专属领域脉络需结合该项目问题整理。'
    return {'project': project, 'scope': scope,
            'diagrams': {'field': field, 'papers': '\n'.join(relationships), 'timeline': '\n'.join(timeline), 'project': '\n'.join(progress), 'reading': '\n'.join(pie), 'workflow': accumulation},
            'paper_diagrams': paper_diagrams,
            'evidence_groups': evidence_groups, 'timeline_papers': timeline_papers, 'tasks': task_state,
            'documents': documents, 'background_candidates': candidates(project, kb), 'mainlines': mainlines,
            'inventory': knowledge.inventory(project, kb), 'project_status': project_status,
            'reading_counts': [{'label': reading_labels.get(code, code), 'count': count} for code, count in readings.items()]}
