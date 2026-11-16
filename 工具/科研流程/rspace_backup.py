"""Native MariaDB hot backup and RSpace media; no live database-file copying."""
import subprocess
import time
import secrets
import tarfile
import hashlib
import uuid
import zipfile
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
import workflow as w


def export(folder):
    from rspace_runtime import deployment
    deployed=deployment()
    if not deployed.get('installed'):return {'status':'not_deployed'}
    folder=Path(folder);sql=folder/'rspace.sql';media=folder/'rspace-media.tar'
    prefix=['wsl.exe','-d','Ubuntu-24.04','-u','root','--exec','docker','exec']
    tasks=[(sql,['yanxu-rspace-db','sh','-c','exec mariadb-dump --single-transaction --routines --triggers --hex-blob -u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE"']),
           (media,['yanxu-rspace-app','tar','cf','-','-C','/media/rspace','.'])]
    prepared=os.environ.get('RESEARCH_RSPACE_PREPARED_EXPORT')
    if prepared:
        source=Path(prepared).resolve();proof=w.read_json(source/'native-rspace.json',{})
        if not source.is_relative_to((w.ROOT/'备份/_临时').resolve()) or not source.name.startswith('native-rspace-'):
            raise ValueError('原生导出必须来自统一备份入口的暂存目录。')
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(proof.get('created','1970-01-01T00:00:00+00:00'))).total_seconds()
        if proof.get('status')!='exported' or Path(proof.get('workspace','')).resolve()!=w.ROOT.resolve() or not 0<=age<=600:
            raise ValueError('原生 RSpace 导出凭据过期或不属于当前工作区；未发布备份。')
        for target,_ in tasks:
            original=source/target.name;expected=proof.get('files',{}).get(target.name,{})
            if original.is_symlink() or not original.is_file() or not original.stat().st_size or __import__('backup_crypto').file_digest(original)!=expected.get('sha256'):
                raise ValueError('原生 RSpace 导出校验失败；未发布备份。')
            shutil.copyfile(original,target)
    else:
        for target,args in tasks:
            with target.open('wb') as output:
                result=subprocess.run(prefix+args,stdout=output,stderr=subprocess.PIPE,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode or not target.stat().st_size:raise ValueError('RSpace 原生备份未完成，请使用统一备份入口；实例和旧备份保留')
    runtime=Path(deployed['runtime']);config=folder/'rspace-runtime.zip'
    with zipfile.ZipFile(config,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in runtime.rglob('*'):
            if path.is_file() and path.suffix not in ('.war','.download'):archive.write(path,path.relative_to(runtime).as_posix())
    receipt={'status':'exported','version':deployed['version'],'created':w.now(),
             'files':{p.name:{'bytes':p.stat().st_size,'sha256':__import__('backup_crypto').file_digest(p)} for p in [sql,media,config]},
             'scope':'MariaDB 单事务原生导出及其后收集的媒体文件。备份期间不能运行永久清空回收站/物理清理；正常新增媒体不会被纳入更早的数据库版本。独立实例恢复另行验收。'}
    w.write_json(folder/'rspace-backup.json',receipt);return receipt


def rehearse(folder):
    """Restore only into a newly labelled, portless native test container."""
    folder=Path(folder).resolve();receipt=w.read_json(folder/'rspace-backup.json',{})
    if not receipt:return {'status':'not_in_backup'}
    for name,info in receipt['files'].items():
        if name not in ('rspace.sql','rspace-media.tar','rspace-runtime.zip') or __import__('backup_crypto').file_digest(folder/name)!=info['sha256']:raise ValueError('RSpace 备份校验失败，未尝试恢复')
    with zipfile.ZipFile(folder/'rspace-runtime.zip') as archive:
        definition=__import__('yaml').safe_load(archive.read('compose.yaml'));image=definition['services']['rspace-db']['image']
    if '@sha256:' not in image:raise ValueError('恢复测试要求固定原生数据库镜像')
    prepared=os.environ.get('RESEARCH_RSPACE_NATIVE_RESTORE_STAGE')
    if prepared:
        target=Path(prepared).resolve()
        allowed=(w.DATA/'备份/_临时').resolve()
        if not target.is_relative_to(allowed) or not target.name.startswith('native-restore-'):
            raise ValueError('原生恢复暂存路径无效')
        target.mkdir(exist_ok=False)
        for name in ('rspace.sql','rspace-media.tar'):shutil.copyfile(folder/name,target/name)
        expected={}
        with tarfile.open(folder/'rspace-media.tar') as archive:
            for member in archive:
                normalized=__import__('posixpath').normpath(member.name)
                if normalized.startswith('../') or normalized.startswith('/'):raise ValueError('媒体备份路径无效')
                if member.isfile():expected['/tmp/rspace-media/'+normalized]=hashlib.file_digest(archive.extractfile(member),'sha256').hexdigest()
        w.write_json(target/'request.json',{'image':image,'files':{n:receipt['files'][n] for n in ('rspace.sql','rspace-media.tar')},'media':expected})
        return {'status':'awaiting_native_restore','stage':str(target),'current_instance_changed':False}

    root=folder/'rspace-test.env';root.write_text('MARIADB_ROOT_PASSWORD='+secrets.token_urlsafe(32)+'\nMARIADB_DATABASE=rspace\n',encoding='utf-8')
    linux='/mnt/'+root.drive[0].lower()+'/'+root.relative_to(root.anchor).as_posix();name='yanxu-rspace-restore-'+uuid.uuid4().hex[:12]
    prefix=['wsl.exe','-d','Ubuntu-24.04','-u','root','--exec','docker'];created=False
    def command(args,**kwargs):
        result=subprocess.run(prefix+args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW,**kwargs)
        if result.returncode:raise ValueError('RSpace 原生隔离恢复步骤未完成；现用实例未改写')
        return result.stdout
    try:
        command(['run','-d','--name',name,'--label','research.workspace=software-restore-only','--env-file',linux,
                 '--health-cmd','healthcheck.sh --connect --innodb_initialized','--health-interval','1s','--health-timeout','5s',image]);created=True
        for attempt in range(40):
            check=subprocess.run(prefix+['inspect',name,'--format','{{.State.Health.Status}}'],capture_output=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
            if check.returncode==0 and check.stdout.strip()==b'healthy':break
            time.sleep(1)
        else:raise ValueError('隔离数据库尚未就绪，未改写现用实例')
        with (folder/'rspace.sql').open('rb') as source:
            command(['exec','-i',name,'sh','-c','exec mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" rspace'],stdin=source)
        check=command(['exec',name,'sh','-c','exec mariadb-check -uroot -p"$MARIADB_ROOT_PASSWORD" --check --all-in-1 rspace'])
        if b'error' in check.lower() or b'corrupt' in check.lower():raise ValueError('原生数据库恢复后的完整性检查未通过')
        expected={}
        with tarfile.open(folder/'rspace-media.tar') as archive:
            for member in archive:
                if member.isfile():
                    normalized=__import__('posixpath').normpath(member.name)
                    if normalized.startswith('../') or normalized.startswith('/'):raise ValueError('媒体备份路径无效')
                    expected['/tmp/rspace-media/'+normalized]=hashlib.file_digest(archive.extractfile(member),'sha256').hexdigest()
        with (folder/'rspace-media.tar').open('rb') as source:command(['exec','-i',name,'sh','-c','mkdir -p /tmp/rspace-media && tar xf - -C /tmp/rspace-media'],stdin=source)
        output=command(['exec',name,'find','/tmp/rspace-media','-type','f','-exec','sha256sum','{}','+']).decode('utf-8')
        actual={line[66:]:line[:64] for line in output.splitlines()}
        if actual!=expected:raise ValueError('恢复的 RSpace 媒体与备份不一致')
        return {'status':'restored','database_tables_checked':check.count(b'OK'),'media_files_verified':len(actual),'current_instance_changed':False,'scope':'原生 MariaDB 导入与完整性检查、逐文件媒体校验通过；未等同于真实签署/见证或真实实验验收。'}
    finally:
        if created:
            label=command(['inspect',name,'--format','{{index .Config.Labels "research.workspace"}}']).strip()
            if label==b'software-restore-only':command(['rm','-f','-v',name])
        root.unlink(missing_ok=True)
