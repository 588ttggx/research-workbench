"""One access boundary for preferences and received maintenance events."""
from filelock import FileLock
from functools import lru_cache
from functools import wraps
from contextvars import ContextVar
import json
import workflow as w
import knowledge as k

@lru_cache(maxsize=16)
def _lock(path):return FileLock(path,timeout=30)

def state_lock():
    w.DATA.mkdir(parents=True,exist_ok=True)
    return _lock(str((w.DATA/'.administrator-state.lock').resolve()))

DEFAULTS = {'enabled':False, 'auto_analysis':False, 'auto_discovery':False, 'auto_updates':True,
            'auto_notes':True, 'auto_relations':True, 'auto_canvas':True, 'auto_project':False, 'auto_mainlines':False,
            'auto_followups':False, 'auto_maintain':False, 'auto_maintain_shared':False,
            'default_mainline':''}
RETIRED_OPTIONS = {'auto_updates', 'auto_notes', 'auto_mainlines', 'auto_followups',
                   'auto_maintain', 'auto_maintain_shared'}
METADATA_EVENTS = {'knowledge_visibility', 'display', 'decision_result'}


class AutomationPaused(ValueError):
    pass


_RUN_CONTROL=ContextVar('administrator_run_control',default=None)


def check_running(project):
    token=_RUN_CONTROL.get()
    if token and token[0]==project:
        current=settings(project)
        observed={key:current.get(key) for key in token[1]}
        if not current.get('enabled') or observed!=token[1]:
            raise AutomationPaused('自动设置已变化，本轮停止接续；已完成结果和未处理资料保留。')


def automatic_run(function):
    @wraps(function)
    def guarded(data,*args,**kwargs):
        project=data['project'];cfg=settings(project)
        controls={key:cfg.get(key) for key in DEFAULTS if key=='enabled' or key.startswith('auto_')}
        marker=_RUN_CONTROL.set((project,controls))
        try:return function(data,*args,**kwargs)
        finally:_RUN_CONTROL.reset(marker)
    return guarded


def require_enabled(project,flag=None):
    check_running(project)
    current=settings(project)
    if not current.get('enabled') or flag and not current.get(flag):
        raise AutomationPaused('自动设置已暂停，本轮不再启动后续步骤；已完成结果保留。')
    return current


def settings(project=None, *, effective=True):
    saved=w.read_json(w.DATA/'科研管理员.json', {})
    selected=saved.get('project','山药');project=project or selected
    profiles=saved.get('projects',{})
    profile=profiles.get(project,{})
    if not profiles and project==selected:
        profile={key:value for key,value in saved.items() if key in (*DEFAULTS,'default_project')}
    result={**DEFAULTS,'default_project':project,**profile,'project':project}
    if effective:
        result.update(dict.fromkeys(RETIRED_OPTIONS,False))
    if effective and __import__('project_profiles').archived(project):result['enabled']=False;result['auto_canvas']=False
    return result


def _configure(data):
    saved=w.read_json(w.DATA/'科研管理员.json', {})
    selected=saved.get('project','山药');project=data.get('project') or selected
    profiles=dict(saved.get('projects',{}))
    if not profiles:profiles[selected]={key:value for key,value in settings(effective=False).items() if key!='project'}
    current = settings(project,effective=False)
    for field,expected in data.get('expected',{}).items():
        if field in data and field not in RETIRED_OPTIONS and current.get(field)!=expected:
            raise ValueError('该设置已在其他窗口变化，请重新打开后合并。')
    for key in DEFAULTS.keys()-RETIRED_OPTIONS-{'default_mainline'}:
        if key in data:
            if type(data[key]) is not bool:
                raise ValueError('管理员开关格式无效。')
            current[key] = data[key]
    if 'project' in data:
        k.lines(data['project']); current['project'] = data['project']
        if 'default_project' not in data and data.get('select_project',True):current['default_project']=project
    if 'default_project' in data:
        if data['default_project'] not in ('共享', '待归类'): k.lines(data['default_project'])
        current['default_project'] = data['default_project']
    line_project=current['default_project'] if current['default_project'] not in ('共享','待归类') else current['project']
    allowed_lines={r['id'] for r in k.lines(line_project)['rows']}
    if 'default_mainline' in data:
        if data['default_mainline'] and data['default_mainline'] not in allowed_lines: raise ValueError('默认主线不存在，请重新选择。')
        current['default_mainline'] = data['default_mainline']
    elif current['default_mainline'] not in allowed_lines:
        current['default_mainline']=''
    profiles[project]={key:value for key,value in current.items() if key!='project'}
    top=current if data.get('select_project',True) or project==selected else settings(selected,effective=False)
    w.write_json(w.DATA/'科研管理员.json', {**top,'projects':profiles})
    return settings(project)


def runtime(project):
    saved=w.read_json(w.DATA/'管理员运行.json',{})
    return saved.get('projects',{}).get(project, saved if saved.get('project')==project else {})


def save_runtime(project,value):
    with state_lock():
        saved=w.read_json(w.DATA/'管理员运行.json',{});profiles=dict(saved.get('projects',{}))
        if saved.get('project'):profiles.setdefault(saved['project'],{key:v for key,v in saved.items() if key!='projects'})
        current=profiles.get(project,{})
        generation=value.get('_expected_generation',value.get('run_generation'))
        if generation is not None and generation!=current.get('run_generation',generation):return False
        profiles[project]={**current,**{key:v for key,v in value.items() if key!='projects' and not key.startswith('_')}}
        w.write_json(w.DATA/'管理员运行.json',{**profiles[project],'projects':profiles})
        return True


def configure(data):
    if not isinstance(data,dict) or not isinstance(data.get('expected',{}),dict):raise ValueError('设置格式无效。')
    if 'select_project' in data and type(data['select_project']) is not bool:raise ValueError('项目上下文格式无效。')
    with state_lock():return _configure(data)

def configured_projects():
    saved=w.read_json(w.DATA/'科研管理员.json',{})
    return list(saved.get('projects',{})) or [saved.get('project','山药')]

def queue():
    with state_lock():
        value=w.read_json(w.DATA/'自动处理队列.json',{'items':[]})
        if any('seq' not in item for item in value['items']):
            for index,item in enumerate(value['items'],1):
                item['seq']=index
                item.setdefault('id',w.digest(json.dumps([item.get('project'),item.get('reason'),item.get('paper_id')],ensure_ascii=False))[:20])
            value['next_seq']=len(value['items'])+1
            w.write_json(w.DATA/'自动处理队列.json',value)
        value.setdefault('next_seq',max((i.get('seq',0) for i in value['items']),default=0)+1)
        return value

def schedule(project,reason,paper_id=None,*,document_id=None,version=None,change_type=None,changed_work_ids=()):
    with state_lock():
        value=queue();seq=value['next_seq']
        if document_id:
            identity=['document',document_id]
            if change_type in METADATA_EVENTS:identity.append('metadata')
        else:
            identity=[project,reason,paper_id]
        key=w.digest(json.dumps(identity,ensure_ascii=False))[:20]
        existing=next((item for item in value['items'] if item['id']==key),None)
        if document_id and existing and existing.get('version')==version and set(changed_work_ids)<=set(existing.get('changed_work_ids',())):
            return existing
        rows=[item for item in value['items'] if item['id']!=key]
        event={'id':key,'project':project,'reason':reason,'paper_id':paper_id,'created':w.now(),'seq':seq}
        if document_id:event.update(document_id=document_id,version=version,change_type=change_type or 'content')
        if changed_work_ids:event['changed_work_ids']=sorted(set(changed_work_ids))
        rows.append(event)
        dropped=rows[:-200]
        if dropped:value['dropped_through_seq']=max(value.get('dropped_through_seq',0),max(i['seq'] for i in dropped))
        value.update(items=rows[-200:],next_seq=seq+1)
        w.write_json(w.DATA/'自动处理队列.json',value)
        return event


def selected_documents(project):
    # Read selection before taking the short configuration lock. A removed or
    # archived original may no longer occur in the effective analysis snapshot.
    from project_materials import selected_document_ids
    return selected_document_ids(project)


def event_applies(event,project,selected):
    if event.get('document_id'):
        return event['project']==project or event['document_id'] in selected
    return event['project'] in (project,'共享','待归类')


def legacy_pending(value):
    if 'legacy_update_pending' in value:return bool(value['legacy_update_pending'])
    return bool(value.get('update_pending') and not value.get('document_updates') and not value.get('update_paper_ids'))


def updates_pending(value):
    return bool(value.get('update_paper_ids') or value.get('document_updates') or
                legacy_pending(value) or value.get('full_reconcile_pending'))

def pending_events(project):
    value=queue();received=runtime(project).get('received_seq',0)
    selected=selected_documents(project) if any(i.get('document_id') for i in value['items']) else set()
    return [i for i in value['items'] if i['seq']>received and event_applies(i,project,selected)]

def receive(project):
    selected=selected_documents(project)
    with state_lock():
        value=queue();current=runtime(project);received=current.get('received_seq',0)
        incoming=[i for i in value['items'] if i['seq']>received and event_applies(i,project,selected)]
        pending=list(dict.fromkeys(current.get('update_paper_ids',[])+[i['paper_id'] for i in incoming if i.get('paper_id')]))
        documents=dict(current.get('document_updates',{}))
        for event in incoming:
            if event.get('document_id') and event.get('change_type') not in METADATA_EVENTS:
                documents[event['document_id']]={field:event.get(field) for field in ('seq','version','change_type')}
        patch={'project':project,'received_seq':value['next_seq']-1,'update_paper_ids':pending,
               'document_updates':documents,
               'legacy_update_pending':legacy_pending(current) or any(not i.get('document_id') and not i.get('paper_id') for i in incoming),
               'run_generation':current.get('run_generation',0)+1,'_expected_generation':current.get('run_generation',0)}
        if received<value.get('dropped_through_seq',0):patch['full_reconcile_pending']=True
        patch['update_pending']=updates_pending({**current,**patch})
        save_runtime(project,patch)
        return runtime(project)


def finish_updates(project,value,*,processed_documents=None,complete_legacy=False):
    """Confirm only the versions handled by this run, preserving newer receipts."""
    with state_lock():
        current=runtime(project)
        if value.get('run_generation')!=current.get('run_generation'):
            return False
        documents=dict(current.get('document_updates',{}))
        for identifier,observed in (processed_documents or {}).items():
            if documents.get(identifier)==observed:documents.pop(identifier)
        merged={**current,**value,'document_updates':documents}
        merged['legacy_update_pending']=False if complete_legacy else legacy_pending(current)
        merged['update_pending']=updates_pending(merged)
        return save_runtime(project,merged)

def run_lock(project):
    return _lock(str((w.DATA/('.administrator-run-'+w.digest(project)[:20]+'.lock')).resolve()))


def serial_run(function):
    from functools import wraps
    @wraps(function)
    def run(data,*args,**kwargs):
        project=data.get('project') or settings()['project']
        with run_lock(project):return function({**data,'project':project},*args,**kwargs)
    return run
