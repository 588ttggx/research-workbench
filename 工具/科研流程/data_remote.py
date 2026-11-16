"""Native DVC remote copies and isolated pulls; the data IDs keep one authority."""
from datetime import datetime,timezone,timedelta
import ctypes
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from filelock import FileLock
import workflow as w
import dataset_store as data
from research_store import Store,encode

KEY='data:remote'
SCOPES={'research':('正式数据','数据/数据版本'),'validation':('软件验证','数据/软件验证/数据版本')}


def _lock():
    w.DATA.mkdir(parents=True,exist_ok=True)
    return FileLock(str(w.DATA/'远程数据备份.lock'),timeout=20)


def _volume(path):
    path=Path(path).resolve()
    if os.name!='nt':return w.digest(str(path.stat().st_dev))
    serial=ctypes.c_uint32();flags=ctypes.c_uint32();maximum=ctypes.c_uint32()
    native=ctypes.WinDLL('kernel32',use_last_error=True)
    ok=native.GetVolumeInformationW(ctypes.c_wchar_p(path.anchor),None,0,ctypes.byref(serial),ctypes.byref(maximum),ctypes.byref(flags),None,0)
    return w.digest(str(serial.value)) if ok else None


def _storage_scope(path):
    if _volume(path) and _volume(path)==_volume(w.ROOT):return 'same_volume'
    letters=[Path(w.ROOT).drive,Path(path).drive]
    if os.name=='nt' and all(re.fullmatch('[A-Za-z]:',letter) for letter in letters):
        script='@('+','.join("(Get-Partition -DriveLetter '"+letter[0]+"').DiskNumber" for letter in letters)+') | ConvertTo-Json -Compress'
        result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
        if not result.returncode:
            disks=__import__('json').loads(result.stdout.decode('utf-8-sig'))
            if len(disks)==2 and all(type(number) is int for number in disks):return 'same_physical_disk' if disks[0]==disks[1] else 'different_physical_disk'
    return 'independence_unverified'


def _repository(scope):
    return (w.ROOT/SCOPES[scope][1]).resolve()


def _native_url(scope,name):
    native=__import__('json').loads(data.command([sys.executable,str(w.HERE/'dvc_unicode.py'),'--workspace-remotes-json'],_repository(scope)))
    url=native.get(name,{}).get('url')
    return str(Path(url).resolve()) if url and '://' not in url else url


def _signature(scope):
    repository=_repository(scope)
    if not (repository/'.dvc').is_dir():return None
    pointers=[*repository.glob('datasets/*/*/*.dvc'),*repository.glob('runs/*/dvc.lock')]
    return w.digest(encode(sorted((p.relative_to(repository).as_posix(),w.digest(p.read_bytes())) for p in pointers))) if pointers else None


def status():
    config=Store().cursor(KEY,{'enabled':False,'revision':0,'remotes':{},'synced':{}})
    state='paused' if not config['enabled'] else 'configured'
    for scope,remote in config['remotes'].items():
        try:matches=_native_url(scope,remote['name'])==remote['path']
        except ValueError:matches=False
        if not matches:state='conflict';break
    local=w.read_json(w.DATA/'最近备份.json',{})
    if local:
        check=w.read_json(w.ROOT/'工具/日志/科研备份验收.json',{});restore=w.read_json(w.ROOT/'output/科研工作区重构/恢复演练验收.json',{})
        local={**local,'path':str((w.ROOT/local['file']).resolve()),'verified':check.get('sha256')==local['sha256'] and check.get('verified') is True,
               'restored':restore.get('backup')==local['file'] and restore.get('production_changed') is False}
        if local['restored'] and restore.get('zotero_native'):local['zotero_native']=restore['zotero_native']
    return {**config,'status':state,'local_backup':local or None,'scope':'原生 DVC 只复制受版本管理的数据与计算产物，不成为第二个编辑真源。完整工作区、账号和解密恢复另行验收。',
            'message':{'conflict':'DVC 原生配置已变化或暂不可读取，自动备份暂停；请核对后重新连接。','paused':'远程数据备份已暂停。' if config.get('destination') else '尚未连接独立存储。准备好外置硬盘或 NAS 后，可以在这里连接。','configured':'数据版本变化后自动备份，旧版本继续保留；本机后台运行期间执行。'}[state]}


def configure(body):
    if type(body.get('enabled')) is not bool or type(body.get('revision')) is not int:raise ValueError('备份设置无效')
    with _lock(),data.writer():
        old=status();store=Store()
        if body.get('revision')!=old['revision']:raise ValueError('备份设置已变化，请刷新后再保存')
        if not body['enabled']:
            store.commit_page(KEY,[],{**old,'enabled':False,'revision':old['revision']+1});return status()
        value=body.get('path') or old.get('destination')
        if not isinstance(value,str) or not value.strip() or len(value)>2000 or '\x00' in value or '://' in value:raise ValueError('请提供已有的外置硬盘或 NAS 目录；登录信息使用系统连接，不填写在路径中')
        root=Path(value.strip()).expanduser()
        if not root.is_absolute() or not root.is_dir():raise ValueError('备份目录不存在或当前不可访问，请先连接存储')
        root=root.resolve();base=root/('科研工作区版本备份-'+w.digest(w.ROOT.resolve().as_uri())[:10])
        source_roots=[w.ROOT.resolve(),*[Path(n['data']['source_root']).resolve() for n in __import__('raw_data').listing()]]
        if any(base.is_relative_to(source) or source.is_relative_to(base) for source in source_roots):raise ValueError('备份不能写进工作区、原始数据或它们的子目录')
        if base.exists() and (base.is_symlink() or getattr(base.lstat(),'st_file_attributes',0)&0x400):raise ValueError('备份子目录是目录链接，请核对目标')
        revision=old['revision']+1;remotes={};created=[]
        try:
            for scope,(label,relative) in SCOPES.items():
                repository=_repository(scope)
                if not (repository/'.dvc').is_dir():continue
                target=base/scope
                if target.exists() and (target.is_symlink() or getattr(target.lstat(),'st_file_attributes',0)&0x400):raise ValueError('备份目录包含目录链接，未修改目标')
                target.resolve().relative_to(base.resolve());target.mkdir(parents=True,exist_ok=True);name='workspace_backup_'+w.digest(str(target))[:10]+'_'+str(revision)
                if _native_url(scope,name) is not None:raise ValueError('同名 DVC 连接已有原生配置，未覆盖；请先核查')
                data.command([sys.executable,str(w.HERE/'dvc_unicode.py'),'remote','add','--local',name,str(target)],repository)
                created.append((scope,name));remotes[scope]={'name':name,'path':str(target),'label':label,'volume':_volume(target)}
            if not remotes:raise ValueError('数据版本仓库尚未初始化')
        except Exception:
            for scope,name in created:data.command([sys.executable,str(w.HERE/'dvc_unicode.py'),'remote','remove','--local',name],_repository(scope))
            raise
        store.commit_page(KEY,[],{'enabled':True,'revision':revision,'destination':str(root),'storage_scope':_storage_scope(root),'remotes':remotes,'synced':{},'failures':0,'checked':w.now()})
        return status()


def _save(config,changes):
    with _lock():
        store=Store();current=store.cursor(KEY,{})
        if current.get('revision')==config['revision'] and current.get('enabled'):store.commit_page(KEY,[],{**current,**changes})


def synchronize(progress=None):
    config=status()
    if not config['enabled']:return {'status':'skipped','message':config['message']}
    if config['status']=='conflict':raise ValueError(config['message'])
    results=[];synced=dict(config.get('synced',{}));failures=[]
    for scope,remote in config['remotes'].items():
        signature=_signature(scope)
        if not signature:results.append({'scope':scope,'status':'no_data'});continue
        if synced.get(scope)==signature:results.append({'scope':scope,'status':'reused'});continue
        try:
            target=Path(remote['path'])
            if not target.is_dir():raise ValueError('备份存储暂不可用，保留版本后重试')
            if target.resolve()!=target:raise ValueError('备份目录已变成目录链接，请核对目标后重新连接')
            if remote.get('volume') and _volume(target)!=remote['volume']:raise ValueError('备份盘身份已变化，未向不同的盘写入；请核对连接')
            if progress:progress('正在通过原生 DVC 备份'+remote['label'])
            with data.writer():
                current=status()
                if current['revision']!=config['revision'] or not current['enabled']:return {'status':'skipped','message':'设置已变化，原任务不继续写入'}
                if current['status']=='conflict':raise ValueError(current['message'])
                # Every immutable DATA version and RUN keeps its own pointer in
                # the current tree. Native push covers these retained versions;
                # historical-ref scanning loses local remote settings in DVC.
                data.command([sys.executable,'-m','dvc','push','-r',remote['name']],_repository(scope),timeout=600)
            synced[scope]=signature;_save(config,{'synced':synced});results.append({'scope':scope,'status':'copied'})
        except Exception as exc:failures.append(str(exc) if isinstance(exc,ValueError) else '远程数据备份暂未完成')
    if failures:
        count=config.get('failures',0)+1;_save(config,{'failures':count,'last_error':'; '.join(failures),'retry_after':(datetime.now(timezone.utc)+timedelta(minutes=min(60,2**min(count,5)))).isoformat()})
        raise ValueError('; '.join(failures))
    _save(config,{'last_success':w.now(),'last_error':None,'retry_after':None,'failures':0})
    return {'status':'completed','repositories':results,'scope':config['scope']}


def dispatch(start_job):
    config=status()
    if not config['enabled'] or config['status']=='conflict':return {'status':config['status']}
    if config.get('retry_after') and datetime.now(timezone.utc)<datetime.fromisoformat(config['retry_after']):return {'status':'waiting'}
    signatures={scope:_signature(scope) for scope in config['remotes']}
    if all(not value or config.get('synced',{}).get(scope)==value for scope,value in signatures.items()):return {'status':'unchanged'}
    key='dvc-remote:'+w.digest(encode([config['revision'],signatures]));result=start_job('data_remote_sync',{'idempotency_key':key});store=Store();job=store.job(result['job_id'])
    if job and job['status']=='failed':store.retry(job['id']);start_job('data_remote_sync',resume_id=job['id'])
    return {'status':'queued',**result}


def verify(progress=None):
    config=status()
    if not config['enabled'] or config['status']=='conflict':raise ValueError('请先连接当前备份目录')
    results=[];temporary=w.ROOT/'_临时/科研区维护';temporary.mkdir(parents=True,exist_ok=True)
    for scope,remote in config['remotes'].items():
        if not _signature(scope):continue
        if progress:progress('正在隔离恢复'+remote['label']+'，使用空缓存验证远程副本')
        with tempfile.TemporaryDirectory(prefix='dvc-remote-restore-',dir=temporary) as directory:
            stage=Path(directory).resolve();stage.relative_to(temporary.resolve());clone=stage/'repository'
            data.command(['git','clone','--no-hardlinks','--local',str(_repository(scope)),str(clone)],stage)
            data.command([sys.executable,str(w.HERE/'dvc_unicode.py'),'remote','add','--local','restore_probe',remote['path']],clone)
            data.command([sys.executable,str(w.HERE/'dvc_unicode.py'),'config','--local','cache.dir',str(stage/'empty-cache')],clone)
            pointers=sorted(clone.glob('datasets/**/*.dvc'))
            if not pointers:results.append({'scope':scope,'status':'no_dataset'});continue
            outputs=[]
            for pointer in pointers:
                definition=__import__('yaml').safe_load(pointer.read_text('utf-8'));output=(pointer.parent/definition['outs'][0]['path']).resolve();output.relative_to(clone)
                if output.exists():raise ValueError('隔离恢复发现已有数据，没有证明从空缓存恢复')
                outputs.append((pointer,output))
            data.command([sys.executable,'-m','dvc','pull','-r','restore_probe'],clone,timeout=600)
            files=0
            for pointer,output in outputs:
                manifest=w.read_json(pointer.parent/'manifest.json',{});version=w.read_json(pointer.parent/'version.json',{})
                if manifest.get('files'):
                    for item in manifest['files']:
                        path=(output/item['path']).resolve();path.relative_to(output)
                        if not path.is_file() or w.digest(path.read_bytes())!=item['sha256']:raise ValueError('远程恢复的原始文件 SHA256 不一致')
                    files+=len(manifest['files'])
                elif version.get('sha256'):
                    if not output.is_file() or w.digest(output.read_bytes())!=version['sha256']:raise ValueError('远程恢复的输入 SHA256 不一致')
                    files+=1
                else:raise ValueError('隔离恢复缺少可核对的 SHA256 清单')
            results.append({'scope':scope,'status':'verified','files':files,'versions':len(outputs),'empty_cache':True})
    if not any(row['status']=='verified' for row in results):raise ValueError('目前没有可用于恢复验证的数据版本')
    receipt={'checked':w.now(),'repositories':results,'source_originals_used':False,'scope':'从空缓存经原生 DVC 拉取并逐文件 SHA256 核对；不等同于完整系统容灾恢复。'}
    _save(config,{'last_verified':receipt});return receipt
