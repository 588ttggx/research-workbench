"""Editable Markdown method policies with version-bound human approval."""
from pathlib import Path
import json
import knowledge as k
import workflow as w
from research_store import Store,encode
from thz_domain import validate_policy,THRESHOLDS

PRESET={'model':'single_pass_weak_absorption','frequency_min_thz':None,'frequency_max_thz':None,
 'reference_floor_fraction':.01,'phase_offset_turns':0,'baseline':'none','savgol_window':0,'thresholds':{}}
SOURCE={'doi':'10.1063/1.5047659','url':'https://doi.org/10.1063/1.5047659',
 'location':'作者公开 PDF 第 11–12 页，§VI C/F，式 25、31–33；已核对该方法段落，未声称本人实验验证。'}


def _current(node):
    path=k.path_for(node['uri']);raw=path.read_text('utf-8-sig');meta,body,_=k.split(raw)
    policy=meta.get('method_policy');fingerprint=w.digest(encode([body.rstrip(),policy]))
    if fingerprint!=node['data'].get('policy_fingerprint'):
        node=Store().put_node(node['id'],'Method','Markdown',project=node['project'],uri=node['uri'],expected=node['revision'],status='CANDIDATE',
                              data={**node['data'],'policy_fingerprint':fingerprint,'document_sha256':w.digest(body.rstrip())})
    archived=False
    with Store().connection() as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='documents'").fetchone():
            row=db.execute('SELECT archived FROM documents WHERE id=?',('DOC-'+w.digest('科研知识库/'+node['uri'])[:20],)).fetchone()
            archived=bool(row and row['archived'])
    return {**node,'policy':policy,'fingerprint':fingerprint,'path':node['uri'],'archived':archived}


def listing():
    rows=[]
    for node in Store().nodes(kind='Method'):
        if node['owner']=='Markdown' and node['data'].get('policy_type')=='thz':rows.append(_current(node))
    return {'records':rows,'preset':PRESET,'source':SOURCE,'thresholds':THRESHOLDS,
            'scope':'参数和方法正文属于同一 Markdown 主稿。修改任何方法内容后，批准状态失效；正式使用前由人核对方法适用条件与验证证据。'}


def save(body):
    title=body.get('title');policy=body.get('policy');validate_policy(policy)
    if not isinstance(title,str) or not 1<=len(title.strip())<=200:raise ValueError('请填写方法名称')
    with k.editing():
        old=Store().node(body.get('id')) if body.get('id') else None
        if old:
            if old['kind']!='Method' or old['owner']!='Markdown' or old['data'].get('policy_type')!='thz':raise ValueError('方法对象不符')
            current=_current(old)
            if current['fingerprint']!=body.get('fingerprint'):raise ValueError('方法已变化，请重新打开当前参数')
            if current['policy']==policy and current['data']['title']==title.strip():return current
            old=current
            path=k.path_for(old['uri']);raw=path.read_text('utf-8-sig');meta,prose,_=k.split(raw)
            backup=w.KB/'编辑备份/方法'/old['id']/(w.digest(raw)+'.md')
            if not backup.exists():w.atomic_text(backup,raw)
            identifier=old['id'];project=old['project']
        else:
            identifier=Store().allocate('METHOD');project='共享';path=w.KB/'笔记/共享/方法'/(identifier+'.md')
            raw='';prose='# '+title.strip()+'\n\n## 适用条件\n\n近法向、均匀平行样片，空气参考；内部反射已排除，界面吸收相位可忽略。结果属于有效样片；不自动推断纯组分性质。\n\n## 方法依据\n\n'+SOURCE['url']+'\n'+SOURCE['location']+'\n\n## 验证证据\n\n待本人方法验证与审核，软件数值测试不替代实验验证。\n'
        if old and prose.startswith('# '+old['data']['title']+'\n'):prose=prose.replace('# '+old['data']['title']+'\n','# '+title.strip()+'\n',1)
        updated=k.properties(raw,{'id':identifier,'title':title.strip(),'project':project,'type':'research_record','record_type':'Method','method_policy':policy})
        _,_,front=k.split(updated);text=updated[:front.end()]+prose
        w.atomic_text(path,text);meta,prose,_=k.split(text);fingerprint=w.digest(encode([prose.rstrip(),policy]))
        node=Store().put_node(identifier,'Method','Markdown',project=project,uri=path.resolve().relative_to(w.KB.resolve()).as_posix(),status='CANDIDATE',expected=old['revision'] if old else None,
                               data={'title':title.strip(),'policy_type':'thz','policy_fingerprint':fingerprint,'document_sha256':w.digest(prose.rstrip()),'source':'human-configured-method','method_source':SOURCE})
        return _current(node)


def approved(identifier,fingerprint):
    node=Store().node(identifier) if isinstance(identifier,str) else None
    if not node or node['owner']!='Markdown' or node['data'].get('policy_type')!='thz':raise ValueError('请先在分析区创建并核对方法')
    current=_current(node)
    if current['archived'] or current['status']!='VERIFIED' or current['fingerprint']!=fingerprint:raise ValueError('方法已归档、尚未通过当前版本核对，或参数已变化；请在方法详情审核')
    validate_policy(current['policy']);return current
