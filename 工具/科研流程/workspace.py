"""Adapters for canonical Markdown and explicit legacy native views."""
from __future__ import annotations

from datetime import datetime
import json
import queue
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid
import yaml
from urllib.parse import quote

import workflow as w

READING_LABELS={'unread':'未读','see_linked_historical_review_scope':'阅读范围见历史记录','not_asserted_by_this_import':'待核查阅读范围'}


def restore_wikilinks(content):
    parts = re.split(r'(```[\s\S]*?```|`[^`\n]*`)',content)
    for index in range(0,len(parts),2):
        parts[index] = re.sub(r'\\\[\\\[([^\n]*?)\]\]',lambda m:'[['+m.group(1).replace('\\_','_')+']]',parts[index])
    return ''.join(parts)


def create_project(name,kb=None):
    kb=kb or w.KB
    if not isinstance(name,str) or not re.fullmatch(r'[\w\u4e00-\u9fff][\w\u4e00-\u9fff .（）()\-]{0,59}',name.strip()) or name.strip().endswith(('.', ' ')):
        raise ValueError('项目名请用汉字、字母、数字及括号，最多 60 字。')
    name=name.strip()
    if name.upper().split('.')[0] in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
        raise ValueError('此项目名不能作为本机目录。')
    folder=kb/'项目'/name
    if folder.exists():
        raise ValueError('项目已存在，已有资料保留。')
    folder.mkdir(parents=True)
    relative=f'项目/{name}/当前课题状态.md'
    text=f'''---
type: project
project: {json.dumps(name,ensure_ascii=False)}
status: 待明确问题
---
# {name}

建立日期：{datetime.now().astimezone().isoformat(timespec='seconds')}。

共享条件：[[背景/个人与实验条件]]。本项目背景：[[项目/{name}/方向背景]]。共用文献：[[文献/文献索引]]。

## 研究问题

待填写具体问题、研究对象和判断标准。

## 证据与决定

区分用户决定、已核查原文、AI 建议。新增判断带文献 ID、原文位置、适用范围和日期。

## 尚缺的条件

只补充本项目新增的未知条件，沿用已有设备与个人偏好。

## 下一步

[[项目/{name}/任务]]；[项目研究图](http://127.0.0.1:8503/#projects)。
'''
    w.atomic_text(kb/relative,text)
    w.atomic_text(folder/'方向背景.md',f'---\ntype: note\ncanvas_include: false\nproject: {json.dumps(name,ensure_ascii=False)}\n---\n# {name} · 方向背景\n\n沿用[[背景/个人与实验条件]]中的共享条件，文献引用共用库，不复制其他项目背景。\n\n## 已核查依据\n\n尚未登记本项目的已核查依据。\n\n## 适用范围与待核条件\n\n随本项目实际材料更新，不把其他项目的设备或结论自动当作本项目事实。\n')
    w.atomic_text(folder/'任务.md',f'---\ntype: task\ncanvas_include: false\nproject: {json.dumps(name,ensure_ascii=False)}\nstatus: 待办\n---\n# {name} · 下一步\n\n在项目研究图按实际需要新建笔记、任务和关联资料，不预设研究步骤。\n')
    w.atomic_text(folder/'研究主线.md',f'---\nproject: {json.dumps(name,ensure_ascii=False)}\nresearch_lines: []\n---\n# {name} · 研究问题索引\n')
    return {'project':name,'path':relative,'url':'http://127.0.0.1:8503/#projects'}


def save_background_candidate(question,answer,sources,kb=None,project=None):
    kb=kb or w.KB
    token=datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
    relative='更新记录/'+token+'.md'
    rows=['---','type: background_candidate','status: 待核查','project: '+json.dumps(project or '共享',ensure_ascii=False),'---','# 背景候选更新（待核查）','',f'日期：{w.now()}','',f'研究问题：{question}','','正式背景尚未改写。请核查来源后决定采纳、修正或拒绝。','','## 证据范围','']
    for source in sources:
        identifier=source.get('paper_id') or source.get('id') or source.get('parent_id')
        reference=f'[[文献/条目/{identifier}]]' if isinstance(identifier,str) and re.fullmatch(r'[\w.-]+',identifier) and (kb/'文献/条目'/(identifier+'.md')).exists() else str(identifier)
        rows.append(f"- 文献/来源 ID：{reference}；题名：{source.get('title','')}；页码/位置：{source.get('pages') or '见下文，需核查'}")
    rows += ['','## 对已有判断的更新建议','',answer,'','## 核查与采纳记录','','- 状态：待核查','- 核查人及日期：待填写','- 是否改变正式判断、理由及适用边界：待填写','']
    w.atomic_text(kb/relative,'\n'.join(rows))
    return {'path':relative}


def write_if_changed(path,text):
    if not path.exists() or path.read_text('utf-8')!=text:
        w.atomic_text(path,text)


def reconcile_paper_properties(library):
    """Reading status and project edited in native Bases are user decisions."""
    for record in library['records']:
        if not re.fullmatch(r'[\w.-]+',record['id']):continue
        path=w.KB/'文献/条目'/(record['id']+'.md')
        if not path.exists():continue
        match=re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)',path.read_text('utf-8'),re.S)
        if not match:continue
        try:properties=yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:continue
        if not isinstance(properties,dict):continue
        from paper_evidence import reading_state
        record.update(reading_state(record,properties))
        value=properties.get('project')
        if isinstance(value,str) and len(value)<=100:record['project']=value


def refresh_views():
    """Generate stable paper identities, not another copy of full text or a custom graph."""
    library=w.read_json(w.KB/'文献/library.json')
    reconcile_paper_properties(library)
    for record in library['records']:
        identifier=record['id']
        if not re.fullmatch(r'[\w.-]+',identifier):
            continue
        from paper_evidence import reading_state, original_availability
        record.update(reading_state(record))
        topic=record.get('project') or '待归类'
        reading=record.get('reading_status') or 'unread'
        availability = original_availability(record)
        availability_label = {'fulltext_on_disk':'已保存全文', 'original_missing':'原文路径失效', 'metadata_only':'PDF/XML待补'}[availability]
        metadata={'type':'paper','paper_id':identifier,'title':record['title'],'project':topic,'status':READING_LABELS.get(reading,reading),'availability':availability_label,'doi':record.get('doi') or ''}
        rows=['---',*(k+': '+json.dumps(v,ensure_ascii=False) for k,v in metadata.items()),'---','# '+record['title'],'',f'稳定文献 ID：{identifier}','']
        if record.get('zotero_key'):
            rows += [f"[在 Zotero 打开](zotero://select/library/items/{record['zotero_key']})",'']
        if record.get('doi'):
            rows += [f"[DOI 来源](https://doi.org/{quote(record['doi'],safe='/')})",'']
        artifact=w.chosen_artifact(record)
        if artifact and artifact['kind']=='pdf':
            rows += [f'[看原文与图表](http://127.0.0.1:8503/?paper={quote(identifier)})','']
        card=record.get('reading_card')
        if card:
            rows += [f'阅读卡片：[[{Path(card).with_suffix("").as_posix()}]]','']
        rows += ['索引成功、OCR 和 AI 分析不代表已核查原文。科研结论以证据卡片的阅读范围与原文位置为准。','']
        path=w.KB/'文献/条目'/(identifier+'.md')
        # Existing paper notes belong to the user, including extra properties and prose.
        if not path.exists():write_if_changed(path,'\n'.join(rows))
        else:
            content=path.read_text('utf-8')
            front=re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)',content,re.S)
            if front:
                updated=front.group(1)
                if not re.search(r'^title:',updated,re.M):updated+='\ntitle: '+json.dumps(record['title'],ensure_ascii=False)
                updated=re.sub(r'(?m)^status:\s*"?(unread|see_linked_historical_review_scope|not_asserted_by_this_import)"?\s*$',lambda match:'status: '+json.dumps(READING_LABELS[match.group(1)],ensure_ascii=False),updated)
                updated=re.sub(r'(?m)^availability:\s*"?fulltext_on_disk"?\s*$','availability: 已保存全文',updated)
                # Generated status is a view of the reconciled reading record. Keep user prose/properties.
                import knowledge
                revised=knowledge.properties('---\n'+updated+'\n---\n',
                    {'status':READING_LABELS.get(reading,reading),'reading_scope':record.get('reading_scope') or '',
                     'availability':availability_label})
                _,_,revised_front=knowledge.split(revised)
                updated=revised_front.group(1)
                write_if_changed(path,'---\n'+updated+'\n---\n'+content[front.end():])
        # The entry is an identity/index, not an empty reading note. Link the actual content.
        import knowledge
        from knowledge_graph import paper_display
        display=paper_display(record)
        if display['path'] != '文献/条目/'+identifier+'.md':
            content=path.read_text('utf-8'); metadata,body,front=knowledge.split(content)
            block='<!-- workspace-reading-link -->\n## 中文阅读笔记\n\n[['+display['path']+'|'+display['label']+']]\n\n[在工作台阅读或更新笔记](http://127.0.0.1:8503/?note='+quote(display['path'])+')\n<!-- /workspace-reading-link -->'
            if '<!-- workspace-reading-link -->' in body:body=re.sub(r'(?s)<!-- workspace-reading-link -->.*?<!-- /workspace-reading-link -->',lambda _:block,body)
            else:body=body.rstrip()+'\n\n'+block+'\n'
            write_if_changed(path,(content[:front.end()] if front else '')+body)
    # Legacy native navigation and Canvas exports remain explicit adapters.
    # Routine intake updates only stable paper indexes, never research prose.
    return {'paper_views':len(library['records'])}


def clean_native_graph():
    """One migration of the misleading default graph; later user filters are preserved."""
    marker=w.DATA/'原生图谱显示.json';path=w.KB/'.obsidian/graph.json'
    if marker.is_file() or not path.is_file():return
    before=path.read_text('utf-8-sig');config=json.loads(before)
    config.update(search='(path:背景 OR path:项目) -file:.canvas -file:.base -path:数据分析',showOrphans=False,showArrow=True,nodeSizeMultiplier=1.15,lineSizeMultiplier=1.6,linkDistance=170)
    import knowledge
    knowledge.persist(path.resolve(),before,json.dumps(config,ensure_ascii=False,indent=2)+'\n',w.KB.resolve())
    w.write_json(marker,{'version':1,'updated':w.now(),'reason':'中文笔记与全部论文关系在工作台知识图显示，原生图聚焦背景与项目；索引编号和技术文件不再混入默认图。'})


def launch_tool(name,path=None):
    config=w.read_json(w.ROOT/'工具/工具版本.json')
    if name in {'knowledge','history'}:
        if path is not None:
            if not isinstance(path,str):raise ValueError('笔记入口无效')
            target=(w.KB/path).resolve()
            if not target.is_relative_to(w.KB.resolve()) or not target.is_file() or target.suffix not in {'.md','.base','.canvas'}:raise ValueError('笔记入口无效')
            if any(part.startswith('.') for part in target.relative_to(w.KB.resolve()).parts):raise ValueError('设置文件不能作为笔记打开')
        exe=w.ROOT/config['obsidian']['executable']
        subprocess.Popen([str(exe),'--user-data-dir='+str(w.ROOT/'工具/Obsidian/profile')],cwd=str(exe.parent),creationflags=subprocess.CREATE_NO_WINDOW)
        # CLI can return exit code 0 for a JavaScript error: verify the visible main view.
        if path is not None:
            relative=target.relative_to(w.KB.resolve()).as_posix()
            action='const file=app.vault.getAbstractFileByPath('+json.dumps(relative)+');if(!file)throw Error("missing");const leaf=app.workspace.getLeaf("tab");await leaf.openFile(file);'
            expected='app.workspace.getActiveFile()?.path === '+json.dumps(relative)
        else:
            view='git-history-view' if name=='history' else 'graph'
            action='const type='+json.dumps(view)+';const leaf=app.workspace.getLeavesOfType(type).find(l=>l.getRoot()===app.workspace.rootSplit)||app.workspace.getLeaf("tab");await leaf.setViewState({type,active:true});'
            if view=='graph':action+='const options=JSON.parse(await app.vault.adapter.read(".obsidian/graph.json"));leaf.view.dataEngine?.setOptions(options);leaf.view.update?.();'
            expected='app.workspace.activeLeaf?.view?.getViewType() === type'
        script='(async()=>{'+action+'await app.workspace.revealLeaf(leaf);app.workspace.setActiveLeaf(leaf,{focus:true});return JSON.stringify({ok:('+expected+')&&app.workspace.activeLeaf===leaf&&leaf.getRoot()===app.workspace.rootSplit});})()'
        command=[str(exe.with_suffix('.com')),'vault=科研知识库','eval','code='+script]
        for attempt in range(10):
            try:
                result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=8,creationflags=subprocess.CREATE_NO_WINDOW)
                if obsidian_view_ready(result.stdout):break
            except subprocess.TimeoutExpired:
                pass
            if attempt==9:raise ValueError('知识库目标页面尚未打开，请稍后重试。')
            time.sleep(1)
    elif name=='automation':
        process=subprocess.Popen([str(w.HERE/'.venv/Scripts/python.exe'),str(w.ROOT/'工具/n8n/打开编辑器.py')],cwd=str(w.ROOT),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        messages=queue.Queue()
        def read_ready():
            try:messages.put(process.stdout.readline())
            except OSError:messages.put(b'')
        threading.Thread(target=read_ready,daemon=True).start()
        try:line=messages.get(timeout=40)
        except queue.Empty:
            if process.poll() is None:process.terminate()
            raise ValueError('打开本机流程编辑器超时，请重试。')
        process.stdout.close()
        try:result=json.loads(line)
        except (ValueError,TypeError):raise ValueError('本机流程编辑器未能打开，请检查运行记录。')
        if result.get('opened')!='automation':raise ValueError(result.get('error') or '本机流程编辑器未能打开。')
    else:
        raise ValueError('未知工具入口')
    return {'opened':name}


def obsidian_view_ready(output):
    for line in reversed(output.splitlines()):
        try:
            result=json.loads(line.strip().removeprefix('=>').strip())
        except ValueError:
            continue
        if isinstance(result,dict) and result.get('ok') is True:return True
    return False


def snapshot_versions():
    vault=str(w.KB.resolve())
    command=['git','-c','safe.directory='+vault.replace('\\','/'),'-C',vault]
    subprocess.run(command+['add','--all'],check=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    changed=subprocess.run(command+['diff','--cached','--quiet'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW).returncode
    if changed==0:return {'status':'unchanged'}
    if changed!=1:raise ValueError('知识版本检查未完成')
    subprocess.run(command+['commit','-m','科研积累：'+datetime.now().strftime('%Y-%m-%d %H:%M')],check=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    commit=subprocess.run(command+['rev-parse','--short','HEAD'],check=True,capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
    return {'status':'saved','commit':commit}
