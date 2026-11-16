"""Resume approved file-inspection runs on the existing scheduler, without AI calls."""
from datetime import datetime,timezone,timedelta
import os
from pathlib import Path
import zipfile
from filelock import FileLock
import workflow as w
import raw_data
from research_store import Store,encode

KEY='validation:watch'
METHOD_FILES=('validation_replay.py','cct_bridge.py','cct_decode.ps1','scientific_figures.py')


def method():
    return w.digest(encode({name:w.digest((w.HERE/name).read_bytes()) for name in METHOD_FILES}))


def _lock():
    w.DATA.mkdir(parents=True,exist_ok=True)
    return FileLock(str(w.DATA/'实战自动接续.lock'),timeout=10)


def status():
    config=raw_data.ledger().cursor(KEY,{'enabled':False,'revision':0})
    if config.get('enabled') and config.get('method')!=method():
        return {**config,'status':'method_changed','message':'读取或绘图方法已更新；先手动运行当前方法，再恢复自动接续。旧结果保留。'}
    return {**config,'status':config.get('status','watching' if config['enabled'] else 'paused'),
            'message':config.get('message','文件变化后自动检查、生成版本并接续同组演练；仅在本机后台运行期间执行。' if config['enabled'] else '自动接续已暂停。')}


def configure(body):
    if type(body.get('enabled')) is not bool:raise ValueError('自动接续设置无效')
    with _lock():
        store=raw_data.ledger();old=store.cursor(KEY,{'enabled':False,'revision':0})
        if body.get('revision')!=old['revision']:raise ValueError('自动接续设置已变化，请刷新后再保存')
        if not body['enabled']:
            store.commit_page(KEY,[],{**old,'enabled':False,'revision':old['revision']+1,'status':'paused','message':'自动接续已暂停。'})
            return status()
        import validation_runs
        run=validation_runs.detail(body.get('run') or old.get('run'))
        if run['status']!='COMPLETED':raise ValueError('先完成一次当前方法的演练，再开启自动接续')
        request=run['data']['request'];archive=w.ROOT/request['code']['archive']
        if w.digest(archive.read_bytes())!=request['code']['archive_sha256']:raise ValueError('保存代码校验失败')
        with zipfile.ZipFile(archive) as saved:
            fingerprint=w.digest(encode({name:w.digest(saved.read(name)) for name in METHOD_FILES}))
        if fingerprint!=method():raise ValueError('读取或绘图方法已变化，请先手动运行当前方法')
        identifiers=sorted(i for i,v in request['dataset_versions'])
        for identifier in identifiers:raw_data._node(identifier)
        config={'enabled':True,'revision':old['revision']+1,'datasets':identifiers,'options':request['options'],
                'method':fingerprint,'run':run['id'],'observation':None,'status':'watching','failures':0,
                'message':'文件变化后自动接续同组演练；旧版本保留。','updated':w.now()}
        store.commit_page(KEY,[],config)
        return status()


def run_approved(identifiers=None,options=None,progress=None):
    before=status()
    result=__import__('validation_runs').run(identifiers,options,progress)
    current=status()
    if current['revision']==before['revision'] and (current['enabled'] or current['revision']==0):
        try:result['automation']=configure({'enabled':True,'revision':current['revision'],'run':result['id']})
        except ValueError as exc:result['automation']={'status':'needs_attention','message':str(exc)}
    return result


def observe(identifiers):
    """Cheap change detection; the subsequent intake still hashes every byte."""
    observations=[]
    for identifier in identifiers:
        root=raw_data._root(raw_data._node(identifier)['data']['source_root']);files=[];total=0
        for folder,dirs,names in os.walk(root,followlinks=False):
            for name in [*dirs,*names]:
                entry=Path(folder)/name
                if entry.is_symlink() or getattr(entry.lstat(),'st_file_attributes',0)&0x400:raise ValueError('数据包含目录链接，自动接续已保留原版本')
            for name in names:
                entry=Path(folder)/name;value=entry.stat();total+=value.st_size
                if len(files)>=50000 or total>4*1024**3:raise ValueError('资料超出本轮接收范围，请分批检查')
                files.append((entry.relative_to(root).as_posix(),value.st_size,value.st_mtime_ns))
        if not files:raise ValueError('原文件暂不可用，旧版本和结果保留')
        observations.append((identifier,sorted(files)))
    return w.digest(encode(observations))


def _save_if_current(config,changes):
    with _lock():
        store=raw_data.ledger();current=store.cursor(KEY,{})
        if current.get('revision')==config['revision'] and current.get('enabled'):
            store.commit_page(KEY,[],{**current,**changes})


def _failure(config,exc):
    failures=config.get('failures',0)+1
    delay=min(60,2**min(failures,5))
    _save_if_current(config,{'status':'waiting','failures':failures,'message':str(exc) if isinstance(exc,ValueError) else '文件检查暂未完成，保留进度后重试。',
                             'retry_after':(datetime.now(timezone.utc)+timedelta(minutes=delay)).isoformat(),'last_attempt':w.now()})


def dispatch(start_job):
    config=status()
    if not config['enabled'] or config['status']=='method_changed':return {'status':config['status']}
    if config.get('retry_after') and datetime.now(timezone.utc)<datetime.fromisoformat(config['retry_after']):return {'status':'waiting'}
    try:observation=observe(config['datasets'])
    except Exception as exc:_failure(config,exc);return {'status':'waiting'}
    if observation==config.get('observation'):return {'status':'unchanged'}
    store=Store()
    with store.connection() as db:
        active=db.execute("SELECT id FROM jobs WHERE kind='validation_update' AND status IN ('queued','running') LIMIT 1").fetchone()
    if active:return {'status':'queued','job_id':active['id']}
    key='validation-update:'+w.digest(encode([config['revision'],observation]))
    queued=start_job('validation_update',{'revision':config['revision'],'observation':observation,'idempotency_key':key})
    previous=store.job(queued['job_id'])
    if previous and previous['status']=='failed':
        store.retry(previous['id']);start_job('validation_update',resume_id=previous['id'])
    return {'status':'queued',**queued}


def tick(payload,progress=None):
    config=status()
    if not config['enabled'] or config['revision']!=payload.get('revision'):return {'status':'skipped','message':'设置已变化，旧任务不再接续'}
    if config['status']=='method_changed':return {'status':'needs_attention','message':config['message']}
    try:
        before=observe(config['datasets'])
        if before==config.get('observation'):return {'status':'unchanged'}
        for identifier in config['datasets']:raw_data.rescan(identifier,progress)
        if method()!=config['method']:raise ValueError('方法在检查期间变化，旧结果保留；请手动运行当前方法')
        result=__import__('validation_runs').run(config['datasets'],config['options'],progress)
        _save_if_current(config,{'observation':before,'run':result['id'],'status':'watching','failures':0,'retry_after':None,
                                 'last_success':w.now(),'message':'最近一次文件检查与演练已完成；继续等待文件变化。'})
        return {'status':'completed','run':result['id'],'reused':result['reused']}
    except Exception as exc:_failure(config,exc);raise
