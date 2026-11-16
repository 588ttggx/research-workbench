"""Reproducible local view setup. Does not overwrite existing research text."""
import hashlib
import json
from pathlib import Path
import requests
import workflow as w
import workspace


def setup():
    vault=w.KB
    configuration=vault/'.obsidian'
    configuration.mkdir(exist_ok=True)
    plugin=configuration/'plugins/obsidian-git'
    plugin.mkdir(parents=True,exist_ok=True)
    checksums={}
    for name in ('main.js','manifest.json','styles.css'):
        url='https://github.com/Vinzent03/obsidian-git/releases/download/2.41.1/'+name
        destination=plugin/name
        if not destination.exists():
            response=requests.get(url,timeout=60);response.raise_for_status();destination.write_bytes(response.content)
        checksums[name]=hashlib.sha256(destination.read_bytes()).hexdigest()
    w.write_json(w.ROOT/'工具/工具版本.json',{
        'schema':1,
        'obsidian':{'version':'1.14.4','executable':'工具/Obsidian/runtime-1.14.4/Obsidian.exe','source':'https://github.com/obsidianmd/obsidian-releases/releases/tag/v1.14.4'},
        'obsidian_git':{'version':'2.41.1','checksums':checksums,'source':'https://github.com/Vinzent03/obsidian-git/releases/tag/2.41.1'},
        'n8n':{'version':'2.42.4','runtime':'工具/n8n/runtime-2.42.4','data':'工具/n8n/data','source':'https://github.com/n8n-io/n8n'},
        'open_notebook':{'version':'1.15.0','runtime':'工具/OpenNotebook/open-notebook-1.15.0','data':'工具/OpenNotebook/data'},
        'integration':{'schema':2,'entry':'工具/科研流程/dashboard.py','data':'工具/科研流程/数据'}
    })
    w.write_json(configuration/'community-plugins.json',['obsidian-git'])
    w.write_json(configuration/'core-plugins.json',['file-explorer','global-search','switcher','graph','backlink','outgoing-link','tag-pane','properties','page-preview','daily-notes','templates','note-composer','command-palette','editor-status','bookmarks','outline','word-count','file-recovery','canvas','bases'])
    w.write_json(configuration/'app.json',{'alwaysUpdateLinks':True,'newLinkFormat':'absolute','useMarkdownLinks':False,'defaultViewMode':'preview','showLineNumber':False,'promptDelete':True,'attachmentFolderPath':'附件'})
    w.write_json(configuration/'graph.json',{'hideUnresolved':True,'showOrphans':True,'showTags':False,'colorGroups':[{'query':'path:背景','color':{'a':1,'rgb':3058595}},{'query':'path:项目','color':{'a':1,'rgb':11497613}},{'query':'path:文献/条目','color':{'a':1,'rgb':4059869}}]})
    w.write_json(plugin/'data.json',{'autoSaveInterval':0,'autoPushInterval':0,'autoPullInterval':0,'autoPullOnBoot':False,'disablePush':True,'showStatusBar':True,'showChangedFilesCount':True,'commitMessage':'科研积累：{{date}}','dateFormat':'YYYY-MM-DD HH:mm','listChangedFilesInMessageBody':True})
    w.atomic_text(vault/'项目总览.base','''filters:
  and:
    - 'file.inFolder("项目")'
    - 'file.ext == "md"'
views:
  - type: table
    name: 项目与任务
    order:
      - file.name
      - project
      - status
      - file.mtime
  - type: kanban
    name: 拖拽项目状态
    groupBy:
      property: status
      direction: ASC
    order:
      - file.name
      - project
''')
    w.atomic_text(vault/'文献阅读.base','''filters:
  and:
    - 'file.inFolder("文献/条目")'
views:
  - type: table
    name: 共用文献与阅读状态
    order:
      - file.name
      - project
      - status
      - availability
      - doi
  - type: kanban
    name: 拖拽阅读状态
    groupBy:
      property: status
      direction: ASC
    order:
      - file.name
      - project
''')
    w.atomic_text(vault/'开始.md','''# 科研区 · 从已有积累继续

日常双击根目录 **打开科研区.cmd**，首页会检查服务并提供所有入口。

| 我现在要做什么 | 从这里开始 |
| --- | --- |
| 阅读和检索论文、查看原页图表 | [论文首页](http://127.0.0.1:8503)；[[文献阅读.base]] |
| 沿用我的条件和偏好 | [[背景/个人与实验条件]] |
| 看这个方向已有背景 | [[背景/太赫兹光谱与山药研究背景]] |
| 看项目与下一步 | [[项目总览.base]]；[[项目/山药/当前课题状态]] |
| 看知识之间的联系 | [[科研关系.canvas]]；左侧“关系图谱”图标打开动态全局图 |
| 看上次到这次改了什么 | 命令面板输入 **Git: Open history view** 或 **Git: Open diff view** |
| 修改自动流程 | [n8n 自动流程](http://127.0.0.1:5678)；首页“自动流程”按钮会自动登录本机账号 |
| 新建课题 | 首页“新项目”输入名称，自动沿用共享条件并建立独立目录 |
| 有哪些新论文或新判断 | [[文献/新论文候选]]；[[更新记录]] |

## 平时只需要记住三件事

1. 新论文保存到 Zotero，阅读标注在原文旁做。已有文献会自动去重、保留原文并接入检索。
2. 新项目从首页建立；笔记、决定和任务写在项目目录，条件不重复填写。
3. 新背景候选先查看来源与原页，核查后再更新正式背景。AI 分析不自动成为科研事实。

模型问答需要在首页本机设置中填写 DeepSeek 密钥；关系图、版本和本地检索不依赖它。

升级与备份见 [[维护与升级]]。运行首页只汇总状态，资料仍是本地 Markdown、Zotero 原文和成熟软件的数据。
''')
    nodes=[]
    paths=['背景/个人与实验条件.md','背景/太赫兹光谱与山药研究背景.md','项目/山药/当前课题状态.md','文献/阅读卡片/LASSO_2024.md','文献/阅读卡片/LIBS_YAM_2022.md','文献/阅读卡片/NAKAJIMA_2021.md']
    for i,path in enumerate(paths):
        nodes.append({'id':'n'+str(i),'type':'file','file':path,'x':(i%3)*450,'y':(i//3)*500,'width':420,'height':440})
    edges=[{'id':'e'+str(i),'fromNode':'n1','fromSide':'bottom','toNode':'n'+str(target),'toSide':'top','label':label} for i,(target,label) in enumerate([(0,'沿用个人条件'),(2,'提供领域背景'),(3,'阅读证据与限制'),(4,'阅读证据与限制'),(5,'阅读证据与限制')])]
    canvas=vault/'科研关系.canvas'
    if not canvas.exists():w.write_json(canvas,{'nodes':nodes,'edges':edges})
    # Keep file identities and restore declared aliases, without inventing scientific links.
    for path in [vault/'项目/山药/当前课题状态.md',*(vault/'文献/阅读卡片').glob('*.md')]:
        content=path.read_text('utf-8')
        name='山药当前课题状态' if '项目/山药' in path.as_posix() else path.stem
        if 'aliases:' not in content:
            content=content.replace('---\n','---\naliases: ['+json.dumps(name,ensure_ascii=False)+']\n',1)
        if path.name=='当前课题状态.md' and 'project:' not in content:
            content=content.replace('---\n','---\nproject: 山药\nstatus: 预实验待开展\n',1)
        workspace.write_if_changed(path,workspace.restore_wikilinks(content))
    task=vault/'项目/山药/任务.md'
    if not task.exists():w.atomic_text(task,'---\ntype: task\nproject: 山药\nstatus: 待办\n---\n# 山药 · 当前待办\n\n依据 [[当前课题状态]] 保存已知未知条件，不表示用户已决定实验方向。\n\n- [ ] 核对本机实际可用太赫兹设备和有效频段\n- [ ] 确定品种、掺假或热状态中的本轮研究问题\n- [ ] 保存实际材料身份、批次与可用数据\n- [ ] 用预实验检验可分性与制样影响\n')
    w.write_json(configuration/'workspace.json',{'main':{'id':'main','type':'split','children':[{'id':'tabs','type':'tabs','children':[{'id':'start','type':'leaf','state':{'type':'markdown','state':{'file':'开始.md','mode':'preview','source':False}}},{'id':'graph','type':'leaf','state':{'type':'graph','state':{}}},{'id':'canvas','type':'leaf','state':{'type':'canvas','state':{'file':'科研关系.canvas'}}}],'currentTab':0}],'direction':'vertical'},'left':{'id':'left','type':'split','children':[{'id':'left-tabs','type':'tabs','children':[{'id':'files','type':'leaf','state':{'type':'file-explorer','state':{}}}]}],'direction':'horizontal','width':260},'active':'start','lastOpenFiles':['开始.md']})
    profile=w.ROOT/'工具/Obsidian/profile';profile.mkdir(parents=True,exist_ok=True)
    w.write_json(profile/'obsidian.json',{'vaults':{'research-workspace':{'path':str(vault),'ts':0,'open':True}},'locale':'zh'})
    workspace.refresh_views()
    print(json.dumps({'obsidian':'1.14.4','git_plugin':'2.41.1','vault':str(vault)},ensure_ascii=True))

if __name__=='__main__':setup()
