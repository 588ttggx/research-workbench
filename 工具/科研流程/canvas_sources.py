"""Source adapters for the project canvas; prose remains in its original Markdown."""
import copy
from pathlib import Path
import re

import knowledge as k
import project_questions as questions
import workflow as w
import workspace_catalog as catalog

KINDS = {'question':'研究问题','idea':'想法','task':'任务','experiment':'实验计划','note':'笔记','result':'结果记录','paper':'文献'}
STATUSES = ['未开始','进行中','待核查','已完成','暂缓']


def snapshot(project):
    from project_materials import source_snapshot
    return source_snapshot(project)


def material_papers(materials, snap):
    result=set()
    for material in materials:
        if material.startswith('paper:'):result.add(material[6:])
        elif material.startswith('doc:'):result.update(snap['documents'].get(material[4:],{}).get('paper_ids',[]))
    return result


def resolve(row, snap, *, full=False):
    source=row['source'];kind=source.get('kind');result=copy.deepcopy(row)
    result.update(body='',paper_ids=[],source_fingerprint='',path='',document_id=None,editable=False,max_body=100000,content_role='project_process' if kind in ('question','step','task') else 'knowledge')
    if kind=='task' or source.get('task_id'):
        import project_tasks as work
        current=work.read(snap['project'])
        item=next((r for r in current['items'] if r['id']==source.get('task_id')),None)
        if item is None:return None
        path=work.path_for(snap['project']);relative=path.relative_to(w.ROOT.resolve()).as_posix()
        result.update(title=item['title'],body=item.get('next_step') or '',next_step=item.get('next_step') or '',
            status={'完成':'已完成','暂停':'暂缓','待定':'未开始'}.get(item['status'],item['status']),
            work_status=item['status'],work_removed=item['removed'],work_replacement=item.get('replacement'),
            path=relative,document_id=catalog.identify(relative),source_fingerprint=current['fingerprint'],
            source={**source,'kind':'task','task_id':item['id']})
    elif kind in ('question','step'):
        original=snap['questions'].get(source.get('question_id'))
        if not original:return None
        path,raw,line,state=original
        result.update(path=path.relative_to(w.ROOT.resolve()).as_posix(),source_fingerprint=questions.revision(raw,line),max_body=4000)
        result['document_id']=catalog.identify(result['path']) if path.exists() else None
        current=state
        materials=list(state.get('manual',[]))
        paper_ids=set(line.get('paper_ids',[]))
        if kind=='step':
            current=next((s for s in state.get('steps',[]) if s['id']==source.get('step_id') and not s.get('deleted')),None)
            if current is None:return None
            materials=current.get('manual',[]);paper_ids=set()
        result.update(title=current.get('title',line['title']),body=current.get('progress',''),next_step=current.get('next_step',''),goal=line.get('goal',''))
        result.setdefault('status',current.get('status') or state.get('phase') or line.get('status') or '未开始')
        paper_ids.update(material_papers(materials,snap))
        paper_ids.update(re.findall(r'\[\[文献/条目/([\w.-]+)',result['body']))
        result['paper_ids']=sorted(paper_ids.intersection(snap['papers']))
    elif kind=='document':
        doc=snap['documents'].get(source.get('document_id'))
        if not doc or doc['visibility']=='system' or doc['archived'] and not (source.get('allow_archived') and '报告' in doc['kind']):return None
        path=catalog.bounded(doc['path']);raw=path.read_text('utf-8-sig')
        from project_knowledge import owned
        result.update(title=doc['display_title'],body=k.split(raw)[1],path=doc['path'],document_id=doc['id'],
                      source_fingerprint=w.digest(raw),paper_ids=doc['paper_ids'],editable=doc['editable'] and owned(snap['project'],doc) and not doc['archived'],review_status=doc.get('status'),document_kind=doc['kind'],source_archived=doc['archived'],content_role=doc.get('content_role','knowledge'))
        if doc['archived']:result['content_scope']='历史报告（已归档）：保留当时的检索与讨论范围，当前决定及修订事实以项目主稿和单篇阅读卡片为准。'
        result.setdefault('status','未开始')
    elif kind=='paper':
        paper=snap['papers'].get(source.get('paper_id'))
        if not paper:return None
        result.update(title=paper.get('display_title') or paper['title'],paper_ids=[paper['id']],body=paper.get('abstract') or '',content_scope='书目摘要；原文与实际阅读范围在文献详情查看',source_fingerprint=w.digest(__import__('research_store').encode(paper)))
        result.setdefault('status','待核查')
    else:return None
    result['excerpt']=re.sub(r'[#*\[\]`]', '',result['body']).strip()[:180]
    result['body_truncated']=not full and len(result['body'])>6000
    if result['body_truncated']:result['body']=result['body'][:6000]
    return result


def pool(project, snap, nodes, explicit, *, saved=None, scope=None):
    from project_materials import snapshot as members
    scope=members(project,base=snap,saved=saved if saved is not None else {'nodes':{n['id']:n for n in nodes},'papers':explicit}) if scope is None else scope
    reasons={i:set(row['reasons']) for i,row in scope['papers'].items()}
    result=[]
    for identifier,why in reasons.items():
        p=snap['papers'][identifier]
        notes=[{'id':d['id'],'title':d['display_title'],'project':d['project']} for d in scope['documents'].values()
               if identifier in d['paper_ids'] and not d['archived'] and d['visibility']!='system']
        result.append({'id':identifier,'title':p.get('display_title') or p['title'],'year':p.get('year'),'doi':p.get('doi'),
                       'reading_status':p.get('reading_status'),'reasons':sorted(why),'notes':notes,
                       'node_ids':[n['id'] for n in nodes if identifier in n['paper_ids']]})
    return sorted(result,key=lambda p:(not p['node_ids'],p['title']))


def save_source(project, node, fields, fingerprint):
    """Delegate content saves to the existing versioned, conflict-safe editor."""
    if fingerprint!=node['source_fingerprint']:raise ValueError('节点正文已在其他窗口变化，请重新读取后合并；原稿未覆盖。')
    source=node['source'];kind=source['kind']
    if not node['editable']:raise ValueError('这份来源请在原入口修改。')
    if 'body' in fields and (not isinstance(fields['body'],str) or len(fields['body'])>node['max_body'] or '\x00' in fields['body']):
        raise ValueError('笔记长度或格式无效。')
    if kind!='document':raise ValueError('请在研究问题详情编辑解决方法，旧步骤只供回看。')
    catalog.save({'id':node['document_id'],'title':fields.get('title',node['title']),'body':fields.get('body',node['body']) or '# '+fields.get('title',node['title']), 'fingerprint':fingerprint})


def create_note(project, identifier, title, body, paper_ids=(), *, ai=False):
    """A stable canvas ID also names its single original, so interrupted retries reuse it."""
    path=k.line_path(project,w.KB).parent/'画布笔记'/(identifier+'.md')
    if path.resolve().parent!=path.parent.resolve():raise ValueError('笔记路径无效。')
    if not path.resolve().is_relative_to((w.KB/'项目'/project).resolve()):raise ValueError('笔记路径超出项目。')
    with k.editing():
        if not path.exists():
            raw=k.properties('',{'title':title,'type':'personal_note','note_category':'研究笔记','project':project,
                                  'canvas_node':identifier,'paper_ids':sorted(set(paper_ids)),'ai_canvas_draft':ai})
            w.atomic_text(path,raw+'# '+title+'\n\n'+body.rstrip()+'\n')
        elif k.split(path.read_text('utf-8-sig'))[0].get('canvas_node')!=identifier:
            raise ValueError('这个位置已有其他原稿，未覆盖。')
    rel=path.relative_to(w.ROOT.resolve()).as_posix()
    return {'kind':'document','document_id':catalog.identify(rel)}
