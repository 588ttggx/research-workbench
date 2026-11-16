"""Edit real Markdown skill sources with existing backups and audit records."""
from difflib import unified_diff
import json
from pathlib import Path
import re
import yaml

import knowledge as k
import workflow as w
import skill_registry as registry
import research_prompts
from research_store import Store, encode, now


RULES = {file:row['label'] for file,row in research_prompts.definitions().items()}
RULE_DIRECTORY = Path('.agents/rules/research')
VERSION = re.compile(r'\d{8}_\d{6}_[a-f0-9]{8}\Z')


def _path(identifier,file):
    if identifier=='rules':
        if file not in RULES:raise ValueError('请选择已登记的Markdown短规则。')
        return registry.safe_path(RULE_DIRECTORY/file)
    main=registry.path_for(identifier)
    if not main.is_file():raise ValueError('技能主文不存在。')
    if file!='SKILL.md' and file not in registry.REFERENCE.findall(main.read_text('utf-8-sig')):
        raise ValueError('只能编辑当前技能主文明确声明的Markdown参考。')
    return registry.path_for(identifier,file)


def _files(identifier):
    if identifier=='rules':return [{'path':name,'label':label} for name,label in RULES.items()]
    main=registry.path_for(identifier).read_text('utf-8-sig')
    return [{'path':'SKILL.md','label':'技能主文'},*[{'path':name,'label':name} for name in sorted(set(registry.REFERENCE.findall(main)))]]


def _summary(identifier, *, usage=None):
    if identifier=='rules':return {'id':'rules','label':'任务短规则','description':'实际供内置助手加载的Markdown规则。','can_analyze':False,'kind':'rule'}
    source=registry.path_for(identifier)
    main=source.read_text('utf-8-sig')
    issue=''
    try:
        meta=registry.frontmatter(main)
        row=registry.metadata(identifier,main=main,include_disabled=True,usage=usage)
    except ValueError:
        meta={};row=None;issue='技能登记格式待修复；保存有效原稿后才可用于内置分析。'
    enabled=bool(row and row['enabled'])
    return {'id':identifier,'label':row['label'] if row else str(meta.get('name') or identifier),
            'description':str(meta.get('description') or ''),'can_analyze':enabled,
            'max_papers':row['max_papers'] if row else None,
            'usage':{'external':source.name==registry.MAIN_FILES[0],'dashboard':enabled,
                     'dashboard_available':row is not None},
            'kind':'skill','builtin':identifier in registry.SKILLS,
            'notice':issue or ('' if row else '这个技能还没有看板执行登记。')}


def listing():
    skills=[];usage=registry.dashboard_usage()
    for identifier in sorted(registry.local_names()):
        try:row={**_summary(identifier,usage=usage),'editable':True,'missing':False}
        except (OSError,ValueError):
            # No raw file content, exception path or arbitrary configuration is exposed.
            row={'id':identifier,'label':identifier,'description':'技能登记或路径无效，请核对本地原稿。','kind':'skill',
                 'editable':False,'can_analyze':False,'missing':True}
        skills.append(row)
    rules=[]
    for name,label in RULES.items():
        try:missing=not _path('rules',name).is_file()
        except ValueError:missing=True
        rules.append({**research_prompts.definitions()[name],'id':'rules','file':name,'label':label,'kind':'rule','editable':not missing,
                      'missing':missing,'can_analyze':False})
    return {'skills':skills,'rules':rules}


def detail(identifier,file='SKILL.md'):
    path=_path(identifier,file)
    if not path.is_file():raise ValueError('规则或参考文件缺失，请核对本地源文件。')
    content=path.read_text('utf-8-sig')
    row=_summary(identifier)
    rule=research_prompts.definitions()[file] if identifier=='rules' else {}
    return {**row,**rule,'file':file,'title':RULES[file] if identifier=='rules' else row['label']+' · '+file,
            'content':content,'fingerprint':w.digest(content),'editable':True,'files':_files(identifier),
            'version':w.digest(content)[:12],
            'source_path':path.relative_to(w.ROOT.resolve()).as_posix()}


def _validate(identifier,file,content):
    if not isinstance(content,str) or not content.strip() or '\x00' in content or len(content)>48000:
        raise ValueError('Markdown正文不能为空或包含空字符，最多48000字符。')
    if identifier=='rules':
        if len(content)>12000:raise ValueError('任务短规则最多12000字符，请保留简短约束。')
        return
    if file=='SKILL.md':
        meta=registry.frontmatter(content,strict=True)
        if meta.get('name')!=identifier:raise ValueError('技能name必须与稳定目录ID一致。')
        if not isinstance(meta.get('description'),str) or not 1<=len(meta['description'].strip())<=2000:
            raise ValueError('技能需要简明的description，最多2000字。')
        main=content
    else:main=registry.path_for(identifier).read_text('utf-8-sig')
    if registry.metadata(identifier,main=main,include_disabled=True) is not None:
        registry.read(identifier,overrides={file:content},include_disabled=True)


def _record(path,before,after,event):
    k.persist(path,before,after,w.ROOT.resolve())
    with Store().connection() as db:
        Store.log(db,event,path.relative_to(w.ROOT.resolve()).as_posix(),{'before':w.digest(before),'after':w.digest(after)})


def save(data):
    identifier=data.get('id');file=data.get('file') or 'SKILL.md';content=data.get('content')
    with k.editing():
        path=_path(identifier,file)
        before=k.validate_fingerprint(path,data.get('fingerprint'))
        _validate(identifier,file,content)
        if before!=content:_record(path,before,content,'rule.saved' if identifier=='rules' else 'skill.saved')
    return detail(identifier,file)


def preview(data):
    identifier=data.get('id');file=data.get('file') or 'SKILL.md';content=data.get('content')
    before=k.validate_fingerprint(_path(identifier,file),data.get('fingerprint'))
    _validate(identifier,file,content)
    diff='\n'.join(unified_diff(before.split('\n'),content.split('\n'),
                               fromfile='当前版本',tofile='拟保存版本',lineterm=''))
    return {'id':identifier,'file':file,'fingerprint':w.digest(before),'diff':diff}


def set_usage(data):
    identifier=data.get('id');channel=data.get('channel')
    enabled=data.get('enabled');expected=data.get('expected')
    if channel not in ('external','dashboard') or type(enabled) is not bool or type(expected) is not bool:
        raise ValueError('请选择有效的技能开关状态。')
    with k.editing():
        source=_path(identifier,'SKILL.md')
        state=_summary(identifier)['usage']
        if channel=='dashboard' and not state['dashboard_available']:
            raise ValueError('此技能需要有效的看板执行登记。')
        if state[channel]==enabled:
            return detail(identifier)
        if state[channel]!=expected:
            raise ValueError('技能启用状态已在其他窗口修改，请重新读取。')
        store=Store()
        if channel=='external':
            active,disabled=registry.main_paths(identifier)
            target=active if enabled else disabled
            if target.exists():raise ValueError('技能文件状态已变化，请重新读取。')
            source.rename(target)
        elif enabled:
            registry.read(identifier,include_disabled=True)
        with store.connection() as db:
            if channel=='dashboard':
                current=db.execute('SELECT value FROM cursors WHERE key=?',(registry.DASHBOARD_USAGE,)).fetchone()
                usage=json.loads(current['value']) if current else {}
                usage[identifier]=enabled
                db.execute('INSERT INTO cursors(key,value,updated) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated',
                           (registry.DASHBOARD_USAGE,encode(usage),now()))
            Store.log(db,'skill.usage',identifier,{'channel':channel,'enabled':enabled})
    return detail(identifier)


def create(data):
    identifier=registry.validate_name(data.get('id'))
    if identifier=='rules':raise ValueError('rules保留给任务短规则，请使用其他技能ID。')
    path=registry.path_for(identifier)
    label=data.get('label') or identifier;description=data.get('description');content=data.get('content')
    if not isinstance(description,str) or not 1<=len(description.strip())<=2000:raise ValueError('请填写技能用途与适用场景。')
    if not isinstance(content,str) or not content.strip():raise ValueError('请填写技能正文。')
    if registry.frontmatter(content):raise ValueError('新建时填写技能正文即可，登记开头由本次字段生成。')
    registration={'enabled':True,'label':label,'max_papers':data.get('max_papers',8),
                  'language_policy':data.get('language_policy','user'),'required_refs':[]}
    raw='---\n'+yaml.safe_dump({'name':identifier,'description':description.strip(),'workbench':registration},allow_unicode=True,sort_keys=False)+'---\n'+content.rstrip()+'\n'
    _validate(identifier,'SKILL.md',raw)
    with k.editing():
        path=registry.path_for(identifier)
        if path.parent.exists():raise ValueError('这个技能目录已经存在，请使用已有技能编辑入口。')
        _record(path,'',raw,'skill.created')
    return detail(identifier)


def _backups(path):
    folder=w.DATA/'编辑备份'/w.digest(str(path.relative_to(w.ROOT.resolve())))[:16]
    resolved=folder.resolve()
    if not resolved.is_relative_to(w.DATA.resolve()):raise ValueError('修改历史路径无效。')
    current=w.DATA
    for part in folder.relative_to(w.DATA).parts:
        current=current/part
        if current.is_symlink() or current.exists() and getattr(current.lstat(),'st_file_attributes',0)&0x400:
            raise ValueError('修改历史不能经目录链接访问。')
    return folder


def _history(identifier,file):
    path=_path(identifier,file)
    paths=registry.main_paths(identifier) if identifier!='rules' and file=='SKILL.md' else [path]
    versions=[]
    for path in paths:
        relative=path.relative_to(w.ROOT.resolve()).as_posix()
        for metadata in _backups(path).glob('*.json'):
            if not VERSION.fullmatch(metadata.stem):continue
            original=metadata.with_suffix('.md')
            if metadata.is_symlink() or original.is_symlink():continue
            row=w.read_json(metadata,{})
            if row.get('path')!=relative or not original.is_file():continue
            versions.append(({'id':metadata.stem,'time':row.get('time'),'sha':row.get('before')},original))
    versions.sort(key=lambda pair:(pair[0].get('time') or '',pair[0]['id']),reverse=True)
    return versions


def history(identifier,file='SKILL.md'):
    return {'id':identifier,'file':file,'versions':[row for row,_ in _history(identifier,file)]}


def version(identifier,version_id,file='SKILL.md'):
    if not isinstance(version_id,str) or not VERSION.fullmatch(version_id):raise ValueError('修改历史版本无效。')
    selected=next((pair for pair in _history(identifier,file) if pair[0]['id']==version_id),None)
    if selected is None:raise ValueError('未找到这份原稿的历史版本。')
    row,original=selected
    content=original.read_text('utf-8-sig')
    if w.digest(content)!=row['sha'] and w.digest(content.replace('\n','\r\n'))!=row['sha']:
        raise ValueError('历史正文校验不一致，未加载。')
    return {'id':identifier,'file':file,'version_id':version_id,'content':content,'time':row['time'],
            'notice':'历史内容只加载到编辑器；保存仍核对当前原稿版本。'}
