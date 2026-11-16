"""Display identity and reversible work archives, separate from formal closure."""
from filelock import FileLock
from contextlib import contextmanager
from functools import wraps
import contextvars
import re
import knowledge as k
import workflow as w
from research_store import Store,encode


class AutomaticStopped(ValueError):
    """Expected lifecycle cancellation; paid responses remain in their ledger."""

_TOKEN=contextvars.ContextVar('project_automatic_token',default=None)
_LOCKED=contextvars.ContextVar('project_lifecycle_locks',default=frozenset())

@contextmanager
def lifecycle_lock(project):
    k.line_path(project,w.KB)
    if project in _LOCKED.get():
        yield
        return
    with FileLock(str(w.DATA/('.project-lifecycle-'+w.digest(project)[:20]+'.lock')),timeout=20):
        token=_LOCKED.set(_LOCKED.get()|{project})
        try:yield
        finally:_LOCKED.reset(token)


@contextmanager
def active_edit(project, data, *, archived_message='项目已归档，请恢复项目后编辑。'):
    with lifecycle_lock(project):
        profile=get(project)
        if profile['archived']:raise ValueError(archived_message)
        if data.get('lifecycle_revision',profile['lifecycle_revision'])!=profile['lifecycle_revision']:
            raise ValueError('项目状态已变化，请重新读取；输入保留。')
        yield


@contextmanager
def original_path_edit(path, data):
    """Serialize edits with archive/restore using the physical project owner."""
    from pathlib import PurePosixPath
    parts=PurePosixPath(path).parts
    owner=parts[2] if len(parts)>3 and parts[:2]==('科研知识库','项目') else None
    if not owner:
        yield
        return
    with active_edit(owner,data,archived_message='原稿所属项目已归档，请恢复项目后编辑。'):
        yield


def original_edit(function):
    """Generic editors obey the lifecycle of the original's physical project."""
    @wraps(function)
    def guarded(data,*args,**kwargs):
        import workspace_catalog as catalog
        doc=catalog.stored_document(data.get('id'))
        with original_path_edit(doc['path'],data):
            return function(data,*args,**kwargs)
    return guarded

def capture_automatic(project):
    with lifecycle_lock(project):
        current=get(project)
        if current['archived']:raise AutomaticStopped('项目已归档，自动处理已暂停。')
        return int(current.get('lifecycle_revision',0))

@contextmanager
def automatic_commit(project, expected_revision=None):
    __import__('administrator_state').check_running(project)
    token=_TOKEN.get()
    if expected_revision is None and token and token[0]==project:expected_revision=token[1]
    with lifecycle_lock(project):
        current=get(project)
        if current['archived'] or expected_revision is not None and current.get('lifecycle_revision',0)!=expected_revision:
            raise AutomaticStopped('项目状态已变化，本次旧任务已停止，原稿保留。')
        yield

def automatic(function):
    @wraps(function)
    def run(data, *args, **kwargs):
        project=(data.get('project') or '山药') if isinstance(data,dict) else data
        parent=_TOKEN.get()
        try:
            revision=parent[1] if parent and parent[0]==project else (data.get('_lifecycle_revision',capture_automatic(project)) if isinstance(data,dict) else capture_automatic(project))
            with automatic_commit(project,revision):pass
            marker=_TOKEN.set((project,revision))
            try:return function(data,*args,**kwargs)
            finally:_TOKEN.reset(marker)
        except AutomaticStopped as error:
            if parent and parent[0]==project:raise
            return {'status':'archived','stopped':True,'message':str(error),'organized':0,'written':0,'remaining':0}
    return run


def key(project):return 'project-profile:'+project


def get(project):
    folder=k.line_path(project,w.KB).parent
    saved=Store().cursor(key(project),{})
    path=folder/'当前课题状态.md'
    meta=k.split(path.read_text('utf-8-sig'))[0] if path.is_file() else {}
    status='CLOSED' if meta.get('project_status')=='CLOSED' else saved.get('status','ACTIVE')
    return {**saved,'project':project,'title':saved.get('title') or project,'topic':saved.get('topic',''),
            'status':status,'archived':status in ('ARCHIVED','CLOSED'),'fingerprint':w.digest(encode(saved)),
            'lifecycle_revision':saved.get('lifecycle_revision',0),'formal_closure':meta.get('closure_id')}


def listing():
    root=w.KB/'项目'
    return sorted((get(p.name) for p in root.iterdir() if p.is_dir()),key=lambda p:(p['archived'],p['title'])) if root.is_dir() else []


def archived(project):
    # Settings may be read before a project has been created during first setup.
    try:return get(project)['archived']
    except ValueError:return False


def save(data):
    project=data.get('project');store=Store()
    with lifecycle_lock(project):
        current=get(project)
        if data.get('fingerprint')!=current['fingerprint']:raise ValueError('项目设置已在其他窗口变化，请重新打开。')
        saved=store.cursor(key(project),{});op=data.get('op')
        if op=='update':
            for field in ('title','topic'):
                value=data.get(field,current[field])
                if not isinstance(value,str) or len(value)>80 or any(c in value for c in '\n\r\x00') or field=='title' and not value.strip():raise ValueError('项目名称或方向格式无效。')
                saved[field]=value.strip()
            if 'plan_document_id' in data:
                if current['archived']:raise ValueError('项目已归档，请恢复后更换方案。')
                identifier=data['plan_document_id']
                if identifier is not None:
                    if not isinstance(identifier,str) or not re.fullmatch(r'DOC-[0-9a-f]{20}',identifier):
                        raise ValueError('请选择已选用的有效方案原稿。')
                    from project_materials import snapshot
                    if identifier not in snapshot(project)['documents']:
                        raise ValueError('请先将这份有效原稿明确选入当前项目，再指定为当前方案。')
                saved['plan_document_id']=identifier
        elif op=='archive':
            if current['status']=='CLOSED':raise ValueError('此项目已正式关闭，可查看原记录。')
            summary=data.get('summary','')
            if not isinstance(summary,str) or len(summary)>10000 or '\x00' in summary:raise ValueError('归档说明过长或格式无效。')
            saved.update(status='ARCHIVED',ended_at=w.now(),summary=summary.strip())
        elif op=='restore':
            if current['status']=='CLOSED':raise ValueError('正式关闭记录保留；请建立新的接续项目。')
            saved.update(status='ACTIVE',restored_at=w.now())
        else:raise ValueError('项目操作无效。')
        if op in ('archive','restore') and saved.get('status')!=current['status']:
            saved['lifecycle_revision']=current['lifecycle_revision']+1
        saved['updated']=w.now()
        store.commit_page(key(project),[],saved)
        with store.connection() as db:store.log(db,'project.'+op,project,{'status':saved.get('status','ACTIVE'),'title':saved.get('title',project)})
        if op=='update' and saved.get('plan_document_id')!=current.get('plan_document_id'):
            __import__('administrator').schedule(project,'项目当前方案已变化')
        return get(project)


def initialize_plan(project):
    """Explicit one-time migration from the state manuscript's exact plan link.

    Never invoked by GET; an explicitly cleared null pointer stays cleared.
    Ambiguous, missing, archived and foreign links do not initialize a plan.
    """
    import workspace_catalog as catalog
    store=Store()
    with lifecycle_lock(project):
        saved=store.cursor(key(project),{})
        if 'plan_document_id' in saved:return get(project)
        path=k.line_path(project,w.KB).parent/'当前课题状态.md'
        if not path.is_file():return get(project)
        raw=path.read_text('utf-8-sig');body=k.split(raw)[1]
        docs=catalog.rows();by_path={d['path']:d['id'] for d in docs};by_id={d['id']:d for d in docs}
        source=path.relative_to(w.ROOT.resolve()).as_posix()
        identifiers={catalog.resolve_target(target,source,by_path,{}) for label,target in re.findall(r'\[([^\]]+)\]\(([^)]+)\)',body)
                     if '预实验方案' in label}
        identifiers.discard(None)
        if len(identifiers)!=1:return get(project)
        identifier=identifiers.pop();doc=by_id[identifier]
        if doc['archived'] or doc['visibility']=='system' or not catalog.bounded(doc['path']).is_relative_to(path.parent.resolve()):
            return get(project)
        # A deliberate exclusion from the project remains authoritative.
        from project_materials import snapshot
        if identifier not in snapshot(project)['documents']:return get(project)
        saved.update(plan_document_id=identifier,updated=w.now())
        store.commit_page(key(project),[],saved)
        with store.connection() as db:store.log(db,'project.plan_initialize',project,{'document_id':identifier})
        return get(project)


def check_current():
    token=_TOKEN.get()
    if token:
        with automatic_commit(*token):pass


def mark_closed(project):
    """Caller holds lifecycle_lock and the existing resumable closure intent."""
    store=Store();saved=store.cursor(key(project),{})
    if saved.get('status')!='CLOSED':
        saved.update(status='CLOSED',lifecycle_revision=saved.get('lifecycle_revision',0)+1,updated=w.now())
        store.commit_page(key(project),[],saved)
