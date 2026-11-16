"""Immutable data versions in the existing Git/DVC repository."""
from pathlib import Path
import os
import subprocess
import sys
import threading
from filelock import FileLock
import workflow as w
from research_store import Store

WRITER_LOCKS={}
WRITER_GUARD=threading.Lock()


def repository(validation=False):
    folder=(w.ROOT/('数据/软件验证/数据版本' if validation else '数据/数据版本')).resolve()
    folder.relative_to(w.ROOT.resolve())
    if validation and not (folder/'.git').exists():
        folder.mkdir(parents=True,exist_ok=True)
        command(['git','init','-q'],folder)
    if validation and not (folder/'.dvc').is_dir():
        command([sys.executable,'-m','dvc','init','-q'],folder)
    if not (folder/'.git').exists() or not (folder/'.dvc').is_dir():
        raise ValueError('数据版本仓库尚未初始化，输入已保留，不能宣称已受 DVC 管理')
    actual=command(['git','rev-parse','--show-toplevel'],folder).strip()
    if Path(actual).resolve()!=folder:
        raise ValueError('数据仓库根目录不匹配')
    return folder


def command(args,folder,timeout=120,*,site_cache=None):
    env=__import__('git_support').environment();env['PATH']=str(Path(sys.executable).parent)+os.pathsep+env.get('PATH','')
    env.setdefault('DVC_SITE_CACHE_DIR',str(w.ROOT/'runtime/cache/DVC'));env.setdefault('DVC_NO_ANALYTICS','1')
    if site_cache is not None:env['DVC_SITE_CACHE_DIR']=str(site_cache)
    env.update(PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    result=subprocess.run(args,cwd=folder,env=env,capture_output=True,text=True,encoding='utf-8',
                          errors='replace',timeout=timeout,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        w.DATA.mkdir(parents=True,exist_ok=True)
        w.atomic_text(w.DATA/'数据版本操作.log',w.now()+'\n'+args[0]+'\n'+result.stdout[-4000:]+'\n'+result.stderr[-8000:])
        # Never echo process environment or configuration values to the UI.
        raise ValueError('数据版本操作未完成：'+args[0]+'（'+str(result.returncode)+'）')
    return result.stdout


def commit_paths(folder,paths,message):
    # Native DVC initialization files are necessary for an independent clone.
    paths=[*paths,folder/'.dvc/.gitignore',folder/'.dvcignore']
    config=folder/'.dvc/config'
    if config.is_file() and not config.read_text('utf-8').strip():paths.append(config)
    paths=[Path(p).relative_to(folder).as_posix() for p in paths if Path(p).is_file()]
    staged=set(command(['git','diff','--cached','--name-only'],folder).splitlines())
    if staged-set(paths):
        return {'status':'pending_git','message':'数据仓库中有其他暂存修改，未替用户提交'}
    command(['git','add','--',*paths],folder)
    if command(['git','diff','--cached','--name-only'],folder).strip():
        command(['git','-c','user.name=Research Workspace','-c','user.email=research-workspace@localhost',
                 'commit','-m',message],folder)
    return {'status':'committed','commit':command(['git','rev-parse','HEAD'],folder).strip()}


def writer():
    w.DATA.mkdir(parents=True,exist_ok=True)
    path=str((w.DATA/'数据版本写入.lock').resolve())
    with WRITER_GUARD:
        return WRITER_LOCKS.setdefault(path,FileLock(path,timeout=45))


def store_input(text,project,filename):
    raw=text.encode('utf-8');checksum=w.digest(raw);identifier='DATA-'+checksum[:16]
    folder=repository();version=folder/'datasets'/identifier/checksum
    with writer():
        version.mkdir(parents=True,exist_ok=True);path=version/'raw.csv'
        if path.exists() and w.digest(path.read_bytes())!=checksum:
            raise ValueError('原始输入版本校验失败，未覆盖数据')
        if not path.exists():path.write_bytes(raw)
        command([sys.executable,'-m','dvc','add',str(path)],folder)
        pointer=path.with_suffix(path.suffix+'.dvc')
        definition=__import__('yaml').safe_load(pointer.read_text('utf-8'))
        object_id=definition['outs'][0].get('md5')
        result={'id':identifier,'version':checksum,'sha256':checksum,'bytes':len(raw),
                'uri':path.relative_to(w.ROOT.resolve()).as_posix(),
                'dvc_pointer':pointer.relative_to(w.ROOT.resolve()).as_posix(),'dvc_object':object_id,
                'dvc_tracked':True,'backup_status':'尚未配置独立 DVC Remote；本地缓存不是容灾备份'}
        receipt=version/'version.json'
        if not receipt.exists():w.write_json(receipt,{**result,'first_filename':filename,'created':w.now()})
        git=commit_paths(folder,[pointer,version/'.gitignore',receipt],identifier+' input '+checksum[:12])
        result.update(git_commit=git.get('commit'),git_status=git['status'])
    return result


def source_file(result):
    base=w.ROOT if result.get('source_root')=='workspace' else w.KB
    path=(base/result['source']).resolve()
    allowed=(w.ROOT/'数据/数据版本/datasets').resolve() if base==w.ROOT else w.KB.resolve()
    path.relative_to(allowed)
    if not path.is_file() or w.digest(path.read_bytes())!=result['source_sha256']:
        raise ValueError('运行输入缺失或校验失败')
    return path


def store_collection(manifest):
    """Version a registered native collection without moving its source files."""
    import shutil
    identifier=manifest['id'];checksum=manifest['version']
    source=Path(manifest['source_root']).resolve()
    with writer():
        folder=repository(validation=manifest.get('purpose')=='software_validation')
        version=folder/'datasets'/identifier/checksum;raw=version/'raw'
        version.mkdir(parents=True,exist_ok=True)
        for entry in manifest['files']:
            origin=(source/entry['path']).resolve();origin.relative_to(source)
            target=(raw/entry['path']).resolve();target.relative_to(raw.resolve())
            if not origin.is_file() or w.digest(origin.read_bytes())!=entry['sha256']:
                raise ValueError('原始文件已变化，请重新检查后建立版本')
            if target.exists() and w.digest(target.read_bytes())!=entry['sha256']:
                raise ValueError('保存的数据版本已变化，未覆盖现有版本')
            if not target.exists():
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(origin,target)
            if w.digest(target.read_bytes())!=entry['sha256']:raise ValueError('数据版本复制校验失败')
        if {p.relative_to(raw).as_posix() for p in raw.rglob('*') if p.is_file()}!={entry['path'] for entry in manifest['files']}:
            raise ValueError('保存的数据版本中有额外文件，未覆盖现有版本')
        pointer=raw.with_suffix('.dvc')
        if not pointer.is_file():command([sys.executable,'-m','dvc','add',str(raw)],folder)
        definition=__import__('yaml').safe_load(pointer.read_text('utf-8'))
        object_id=definition['outs'][0].get('md5')
        receipt=version/'manifest.json'
        if not receipt.exists():w.write_json(receipt,manifest)
        elif w.read_json(receipt)['version']!=checksum:raise ValueError('版本清单不匹配')
        git=commit_paths(folder,[pointer,version/'.gitignore',receipt],identifier+' native collection '+checksum[:12])
        # A later collection's commit must not change this version's identity.
        version_commit=command(['git','log','-1','--format=%H','--',pointer.relative_to(folder).as_posix()],folder).strip() if git['status']=='committed' else None
        return {'dvc_tracked':True,'dvc_pointer':pointer.relative_to(w.ROOT).as_posix(),
                'dvc_object':object_id,'snapshot_uri':raw.relative_to(w.ROOT).as_posix(),
                'git_status':git['status'],'git_commit':version_commit,
                'backup_status':'验证原件与受版本管理快照；不是真实实验。独立 DVC Remote / 异地备份尚未配置'}
