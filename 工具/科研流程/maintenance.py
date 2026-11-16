"""Back up mutable data with supported APIs; do not copy live database files."""
import io
from contextlib import closing,contextmanager
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime,timedelta,timezone
import zipfile
import secrets
import socket
import hashlib
import shutil
import requests
import win32crypt
from filelock import FileLock
import workflow as w
import backup_crypto


def archive_job_snapshots(store):
    """Archive only redundant, completed routine snapshots already owned by SQLite."""
    folder = (w.DATA/'jobs').resolve()
    if not folder.exists(): return {'archived': 0}
    if not folder.is_relative_to(w.DATA.resolve()):
        raise ValueError('任务快照目录指向数据目录之外，未归档或清理。')
    with store.connection() as db:
        known = {r['id']: r['kind'] for r in db.execute("SELECT id,kind FROM jobs WHERE status='completed' AND safe_retry=1 AND kind IN ('sync','versions','relation_tick','administrator_tick','rspace_sync')")}
    files = []
    for path in sorted(folder.glob('*.json')):
        if path.is_symlink() or path.resolve().parent != folder or path.stem not in known: continue
        raw = path.read_bytes()
        try: snapshot = json.loads(raw)
        except (ValueError, UnicodeError): continue
        if isinstance(snapshot, dict) and snapshot.get('id') == path.stem and snapshot.get('kind') == known[path.stem] and snapshot.get('status') == 'completed':
            files.append((path, raw, w.digest(raw)))
    if not files: return {'archived': 0}
    from storage_budget import require_capacity
    require_capacity(w.ROOT, 'archives', reserve_bytes=sum(len(raw) + 2048 for _, raw, _ in files) + 65536)
    manifest = {p.name: {'sha256': sha, 'bytes': len(raw)} for p, raw, sha in files}
    destination = w.DATA/'任务历史'/('普通成功快照_'+w.digest(json.dumps(manifest, sort_keys=True))[:20]+'.zip')
    if not destination.parent.resolve().is_relative_to(w.DATA.resolve()):
        raise ValueError('任务归档目录指向数据目录之外，原文件保留。')
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix='job-history-', suffix='.zip.tmp', dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, 'w+b') as stream:
            with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
                for path, raw, _ in files: archive.writestr(path.name, raw)
                archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False))
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                for name, entry in manifest.items():
                    if w.digest(archive.read(name)) != entry['sha256']:
                        raise ValueError('任务快照归档校验失败，原文件保留。')
        os.replace(temporary, destination)
    finally:
        if temporary.exists() and temporary.resolve().parent == destination.parent.resolve():
            temporary.unlink()
    removed = 0
    for path, _, sha in files:
        if path.resolve().parent == folder and not path.is_symlink() and path.is_file() and w.digest(path.read_bytes()) == sha:
            path.unlink(); removed += 1
    return {'archived': removed, 'archive': str(destination.resolve())}


def housekeeping(store=None):
    """Use the existing sync clock; run bounded history maintenance once per day."""
    from research_store import Store
    store = store or Store()
    today = datetime.now(timezone.utc).date().isoformat()
    with FileLock(str(w.DATA/'.history-maintenance.lock'), timeout=1):
        previous = store.cursor('maintenance:history', {})
        if previous.get('day') == today: return previous
        from storage_budget import budget_report, StorageBudgetExceeded
        budgets = budget_report(w.ROOT)
        archive_allowed = not budgets['archives']['over_budget']
        def archive_step(function):
            nonlocal archive_allowed
            if not archive_allowed:
                return {}
            try:
                return function()
            except StorageBudgetExceeded:
                archive_allowed = False
                return {}
        failure_cutoff=(datetime.now(timezone.utc)-timedelta(days=7)).isoformat()
        result = {'day': today, 'archived': 0, **archive_step(lambda: archive_job_snapshots(store)), **store.compact_jobs(),
                  **store.close_unresolved_jobs(),
                  **store.close_historical_failures(kind='discover',before=failure_cutoff),
                  **archive_step(store.compact_seen), **archive_step(store.compact_audit),
                  'storage': {'budgets': budgets, 'archive_status': 'within_budget' if archive_allowed else 'blocked_budget'}}
        store.commit_page('maintenance:history', [], result)
        return result


def backup_folder():
    configured=w.read_json(w.DATA/'备份位置.json',{}).get('path')
    if not configured:return w.ROOT/'备份'
    path=Path(configured)
    if not path.is_absolute() or not path.is_dir():raise ValueError('已配置的本机备份目录当前不可用，旧备份保留；未改写其他目录')
    return path.resolve()


def backup_label(path):
    path=Path(path).resolve()
    return str(path.relative_to(w.ROOT.resolve())) if path.is_relative_to(w.ROOT.resolve()) else str(path)


@contextmanager
def backup_lock():
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        with w.process_lock() as acquired:
            if acquired:
                yield
                return
        time.sleep(1)
    raise ValueError('同步任务尚未结束，请稍后备份。')


def _n8n_registration():
    folder = w.ROOT/'工具/n8n'
    registration = w.read_json(folder/'流程登记.json', {})
    flows = registration.get('flows') if isinstance(registration, dict) else None
    if not isinstance(flows, list) or not flows or any(
        not isinstance(flow, dict) or not isinstance(flow.get('id'), str) or not flow['id']
        for flow in flows
    ):
        raise ValueError('n8n 流程登记缺失或不完整，未发布备份。')
    workflow_ids = {flow['id'] for flow in flows}
    activation = w.read_json(folder/'流程已启用.json', {})
    enabled = activation.get('flows', []) if isinstance(activation, dict) else None
    if (not isinstance(enabled, list) or any(not isinstance(item, str) for item in enabled)
            or not set(enabled).issubset(workflow_ids)):
        raise ValueError('n8n 已启用流程与登记不一致，未发布备份。')
    credential = registration.get('credential') or {}
    if not isinstance(credential, dict) or (credential and not isinstance(credential.get('id'), str)):
        raise ValueError('n8n 凭据登记不完整，未发布备份。')
    return {'workflow_ids': sorted(workflow_ids), 'credential_id': credential.get('id')}


def _check_n8n(db, registration):
    required = {'workflow_entity', 'workflow_history', 'credentials_entity'}
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not required.issubset(tables):
        raise ValueError('n8n 数据库缺少必要表，未确认完整备份。')
    workflows = dict(db.execute('SELECT id, activeVersionId FROM workflow_entity'))
    if not set(registration['workflow_ids']).issubset(workflows):
        raise ValueError('n8n 数据库缺少已登记流程，未确认完整备份。')
    for identifier in registration['workflow_ids']:
        version = workflows[identifier]
        if version and not db.execute('SELECT 1 FROM workflow_history WHERE workflowId=? AND versionId=?',
                                      (identifier, version)).fetchone():
            raise ValueError('n8n 数据库缺少已发布流程版本，未确认完整备份。')
    credential = registration.get('credential_id')
    if credential and not db.execute('SELECT 1 FROM credentials_entity WHERE id=?', (credential,)).fetchone():
        raise ValueError('n8n 数据库缺少已登记的凭据记录，未确认完整备份。')


def _snapshot_n8n(destination):
    database = (w.ROOT/'工具/n8n/data/.n8n/database.sqlite').resolve()
    if not database.is_file() or database.stat().st_size == 0:
        raise ValueError('n8n 数据库文件缺失或为空，未发布备份。')
    registration = _n8n_registration()
    try:
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)) as source:
            _check_n8n(source, registration)
            with closing(sqlite3.connect(destination)) as target:
                source.backup(target)
                if target.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise ValueError('n8n 一致快照完整性检查未通过，未发布备份。')
                _check_n8n(target, registration)
    except sqlite3.Error as exc:
        raise ValueError('n8n 原生数据库无法读取或生成一致快照，未发布备份。') from exc
    return registration


def _publish_archive(source, destination, expected):
    if destination.exists():
        raise ValueError('同名备份已存在，未覆盖旧备份。')
    with tempfile.TemporaryDirectory(prefix='backup-publish-', dir=destination.parent) as directory:
        temporary = Path(directory)/destination.name
        with source.open('rb') as input_stream, temporary.open('xb') as output:
            shutil.copyfileobj(input_stream, output, length=backup_crypto.CHUNK)
            output.flush()
            os.fsync(output.fileno())
        if backup_crypto.file_digest(temporary) != expected:
            raise ValueError('备份发布校验失败，已保留本机已验证的暂存档。')
        temporary.rename(destination)


def backup(*, native_staging=False):
    with backup_lock(),FileLock(str(w.DATA/'实战演练.lock'),timeout=180),__import__('dataset_store').writer():
        stamp=datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d_%H%M%S_%f')
        destination_folder=backup_folder()
        if destination_folder == w.ROOT/'备份':
            destination_folder.mkdir(parents=True,exist_ok=True)
        folder=w.DATA/'备份/_临时/原生暂存' if native_staging else destination_folder
        folder.mkdir(parents=True,exist_ok=True)
        temporary_root=folder/'_临时';temporary_root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as temporary:
            staging=Path(temporary)
            n8n=_snapshot_n8n(staging/'n8n.sqlite')
            # Zotero itself makes the online snapshot; never copy its live DB.
            try:items=w.zotero_items()
            except requests.RequestException:raise ValueError('Zotero 原生接口当前离线；旧备份保留，未生成不完整的新备份') from None
            __import__('rspace_backup').export(staging)
            versions=w.read_json(w.ROOT/'工具/工具版本.json')
            app=w.ROOT/versions['open_notebook']['runtime']
            environment=os.environ.copy()
            for line in (app/'.env').read_text('utf-8').splitlines():
                if '=' in line and not line.startswith('#'):
                    key,value=line.split('=',1);environment[key]=value.strip('"\'')
            environment['SURREAL_USER']=environment.get('SURREAL_USER') or environment.get('SURREAL_USERNAME','root')
            environment['SURREAL_PASS']=environment.get('SURREAL_PASSWORD','root')
            export=staging/'open-notebook.surql'
            command=[str(w.ROOT/'工具/OpenNotebook/bin/surreal.exe'),'export','--endpoint','http://127.0.0.1:8000','--namespace',environment.get('SURREAL_NAMESPACE','open_notebook'),'--database',environment.get('SURREAL_DATABASE','open_notebook'),'--log','none',str(export)]
            result=subprocess.run(command,env=environment,capture_output=True,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode or not export.is_file() or export.stat().st_size == 0:raise ValueError('知识检索库导出未完成，未生成不完整备份。')
            w.write_json(staging/'zotero-items.json',items)
            native_zotero=__import__('zotero_native_backup').export(staging,items)
            from research_store import Store
            Store().backup(staging/'research.sqlite3')
            if (w.DATA/'validation.sqlite3').exists():Store(w.DATA/'validation.sqlite3').backup(staging/'validation.sqlite3')
            archive=staging/'workspace.zip'
            with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=3) as bundle:
                file_manifest={}
                def include(path,name):
                    if name in file_manifest:return
                    before=path.stat();digest=hashlib.sha256();size=0
                    with path.open('rb') as source,bundle.open(name,'w',force_zip64=True) as target:
                        for block in iter(lambda:source.read(backup_crypto.CHUNK),b''):
                            target.write(block);digest.update(block);size+=len(block)
                    after=path.stat()
                    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('备份期间来源文件发生变化，请重新备份；旧备份保留')
                    file_manifest[name]={'bytes':size,'sha256':digest.hexdigest()}
                output_bases=[w.ROOT/'output'/name for name in ('科研工作区重构','科研工作区体验诊断','组内样品选择核查','THz数据格式核查','pdf')]
                for base in [w.KB,w.HERE,w.ROOT/'.agents',w.ROOT/'工具/ZoteroBridge',w.ROOT/'数据',*output_bases,w.ROOT/'research',w.ROOT/'tasks',w.ROOT/'工具/n8n/flows',w.ROOT/'工具/日志/独立验收']:
                    for path in base.rglob('*'):
                        relative=path.relative_to(w.ROOT)
                        persistent_lock=path.name in {'uv.lock','dvc.lock','pixi.lock','poetry.lock','Pipfile.lock'}
                        if path.is_file() and path.resolve().is_relative_to(w.ROOT.resolve()) and path.suffix!='.tmp' and (path.suffix!='.lock' or persistent_lock) and not path.name.startswith(('research.sqlite3','validation.sqlite3')) and not any(p in {'.venv','__pycache__','browser-profile','node_modules','_临时'} for p in relative.parts):include(path,relative.as_posix())
                # Preserve historical Markdown reports without copying unrelated
                # video databases, installers or dependency trees from output/.
                for path in (w.ROOT/'output').rglob('*.md'):
                    if path.resolve().is_relative_to(w.ROOT.resolve()) and not any(p in {'_临时','node_modules','.venv'} for p in path.relative_to(w.ROOT).parts):include(path,path.relative_to(w.ROOT).as_posix())
                for path in [w.ROOT/'工具/工具版本.json',w.ROOT/'工具/n8n/流程登记.json',w.ROOT/'工具/n8n/流程已启用.json',w.ROOT/'工具/n8n/data/local-credentials.dpapi',w.ROOT/'工具/n8n/data/.n8n/config',app/'.env']:
                    if path.exists():include(path,path.relative_to(w.ROOT).as_posix())
                for extension in versions.get('cytoscape_extensions',{}).values():
                    path=(w.ROOT/extension['runtime']).resolve();path.relative_to(w.ROOT.resolve())
                    if not path.is_file() or w.digest(path.read_bytes())!=extension['sha256']:
                        raise ValueError('已登记的专业扩展文件缺失或校验不一致，未登记完整备份')
                    include(path,path.relative_to(w.ROOT.resolve()).as_posix())
                entrypoints=[w.ROOT/name for name in ['AGENTS.md','打开科研区.cmd','备份科研区.cmd','检查科研区更新.cmd','工具/启动科研区.ps1','工具/检查可升级版本.ps1','工具/OpenNotebook/管理服务.ps1']]
                entrypoints.extend((w.ROOT/'工具/n8n').glob('*.ps1'))
                entrypoints.extend((w.ROOT/'工具/n8n').glob('*.py'))
                entrypoints.extend(w.ROOT/'工具/日志'/name for name in ['独立验收结论.md','科研工作台可编辑验收.json','科研工作台真实验收.json','科研工作台原页验收.json','科研工作台收尾验收.json','科研工作台最终验收.json','工作台界面依赖审计.json'])
                for path in entrypoints:
                    if path.is_file(): include(path,path.relative_to(w.ROOT).as_posix())
                original_count=0
                for record in w.read_json(w.LIBRARY)['records']:
                    for index,artifact in enumerate(record.get('artifacts',[])):
                        path=Path(artifact['path'])
                        if path.is_file():
                            include(path,f'原文/{record["id"]}/{index}-{path.name}');original_count+=1
                for source,name in native_zotero:include(source,name)
                for name,expected in w.read_json(staging/'zotero-native-backup.json')['files'].items():
                    if file_manifest.get(name)!=expected:raise ValueError('Zotero 附件在备份期间发生变化，请重新备份；旧备份保留')
                for path in staging.iterdir():
                    if path!=archive:include(path,'数据库/'+path.name)
                bundle.writestr('备份清单.json',json.dumps({'schema':3,'created':w.now(),'versions':versions,'original_files':original_count,'files':file_manifest,'zotero_native':True,'n8n':n8n,'scope':'知识库/历史报告/专业图与分析产物/需求/Git/接入代码/状态/原文/Zotero 原生一致数据库与附件/API 导出/n8n SQLite 一致快照/SurrealQL 导出/恢复所需配置；逐文件 SHA256；运行库和模型权重不复制'},ensure_ascii=False,indent=2))
            name='科研区_'+stamp
            path=folder/(name+'.zip.dpapi')
            destination=destination_folder/path.name
            transfer=path.resolve()!=destination.resolve()
            prepared=staging/path.name
            backup_crypto.protect(archive,prepared)
            receipt={'time':w.now(),'file':backup_label(destination),'bytes':prepared.stat().st_size,'original_files':original_count,'sha256':backup_crypto.file_digest(prepared),'encryption':'AES-256-GCM 分块读写 + Windows DPAPI 密钥保护，限本机解密','container_schema':4}
            receipt['verification']=_verify_archive(prepared,receipt)
            if path.exists():
                raise ValueError('同名备份已存在，未覆盖旧备份。')
            prepared.rename(path)
            sidecar=folder/(name+'.json')
            if transfer:
                w.write_json(sidecar,{**receipt,'file':backup_label(path),'archive_target':str(destination),'archive_pending':True})
                _publish_archive(path,destination,receipt['sha256'])
            w.write_json(destination_folder/(name+'.json'),receipt)
            w.write_json(w.ROOT/'工具/日志/科研备份验收.json',receipt['verification'])
            w.write_json(w.DATA/'最近备份.json',receipt)
            if transfer:
                # Publication is complete. A locked staging file may be removed later.
                try:
                    path.unlink(missing_ok=True)
                    sidecar.unlink(missing_ok=True)
                except OSError:
                    receipt['staging_cleanup_pending']=True
            return receipt


def verify_file_manifest(archive,manifest):
    if manifest.get('schema',1)<3:return 0
    files=manifest.get('files',{})
    if not files or set(files)!=set(archive.namelist())-{'备份清单.json'}:
        raise ValueError('备份文件清单与实际内容不一致')
    for name,expected in files.items():
        size=0;digest=hashlib.sha256()
        with archive.open(name) as source:
            for block in iter(lambda:source.read(backup_crypto.CHUNK),b''):size+=len(block);digest.update(block)
        if size!=expected['bytes'] or digest.hexdigest()!=expected['sha256']:
            raise ValueError('备份文件内容校验失败')
    return len(files)


def verify(path):
    path=Path(path).resolve()
    if not any(path.is_relative_to(folder.resolve()) for folder in (w.ROOT/'备份',backup_folder(),w.DATA/'备份/_临时/原生暂存')):raise ValueError('备份不在已登记的本机备份位置')
    receipt=w.read_json(path.with_name(path.name.replace('.zip.dpapi','.json')))
    result=_verify_archive(path,receipt)
    w.write_json(w.ROOT/'工具/日志/科研备份验收.json',result)
    return result


def _verify_archive(path, receipt):
    if receipt['sha256']!=backup_crypto.file_digest(path):raise ValueError('备份文件校验失败')
    with backup_crypto.opened(path,w.DATA/'备份/_临时/原生暂存/_临时') as decrypted,zipfile.ZipFile(decrypted) as archive:
        if archive.testzip():raise ValueError('压缩包内容校验失败')
        manifest=json.loads(archive.read('备份清单.json'))
        hashed_files=verify_file_manifest(archive,manifest)
        required_files=['数据库/n8n.sqlite','数据库/open-notebook.surql','数据库/zotero-items.json','科研知识库/背景/个人与实验条件.md']
        if manifest.get('schema',1)>=2:
            required_files.extend(['打开科研区.cmd','工具/启动科研区.ps1','工具/OpenNotebook/管理服务.ps1','工具/n8n/setup_flows.py'])
        if manifest.get('schema',1)>=3:required_files.append('工具/科研流程/uv.lock')
        if manifest.get('zotero_native'):required_files.extend(['Zotero/zotero.sqlite','数据库/zotero-native-backup.json'])
        names=set(archive.namelist())
        for required in required_files:
            if required not in names or archive.getinfo(required).file_size==0:raise ValueError('备份缺少必要数据')
        result={'verified':True,'sha256':receipt['sha256'],'files':len(archive.namelist()),'hashed_files':hashed_files,'original_files':manifest['original_files'],'scope':'解密、CRC、逐文件 SHA256（清单 v3）和关键数据检查；未覆盖现用数据库'}
        return result


def restore_surreal_schema(raw):
    """Work around the 2.x export/import field bug in a restore copy only.

    Relation/array types implicitly create fields. Native exports then define
    them again without OVERWRITE (upstream #6075, fixed in 3.1). Keep the
    original archive, record data, field types and permissions byte-for-byte.
    """
    output=[];schema=False;count=0
    for line in raw.splitlines(keepends=True):
        if line.startswith(b'-- TABLE:'):schema=True
        if line.startswith(b'-- TABLE DATA:'):schema=False
        if schema and line.startswith(b'DEFINE FIELD ') and not line.startswith((b'DEFINE FIELD OVERWRITE ',b'DEFINE FIELD IF NOT EXISTS ')):
            line=line.replace(b'DEFINE FIELD ',b'DEFINE FIELD OVERWRITE ',1);count+=1
        output.append(line)
    return b''.join(output),count


def verify_validation_snapshots(staging):
    """Check recovered bytes only, without consulting the E-drive originals."""
    root=(staging/'数据/软件验证').resolve();collections=versions=files=0
    for directory in (root/'原始数据索引').glob('DATA-*'):
        collections+=1
        for path in directory.glob('*/manifest.json'):
            manifest=w.read_json(path)
            if manifest.get('purpose')!='software_validation' or manifest.get('formal') is not False:
                raise ValueError('验证资料的隔离标识缺失')
            snapshot=root/'数据版本/datasets'/manifest['id']/manifest['version']/'raw'
            snapshot.resolve().relative_to(root)
            for entry in manifest['files']:
                file=(snapshot/entry['path']).resolve();file.relative_to(snapshot.resolve())
                if not file.is_file() or w.digest(file.read_bytes())!=entry['sha256']:
                    raise ValueError('恢复的验证数据缺失或校验失败')
                files+=1
            if not snapshot.with_suffix('.dvc').is_file():raise ValueError('恢复的 DVC 数据指针缺失')
            versions+=1
    runs=artifacts=0;database=staging/'数据库/validation.sqlite3'
    if database.is_file():
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as db:
            for uri,raw in db.execute("SELECT uri,data FROM nodes WHERE kind='RUN' AND status='COMPLETED'"):
                node=json.loads(raw);folder=(staging/uri).resolve();folder.relative_to(root/'数据版本/runs')
                for entry in node.get('artifacts',[]):
                    path=(folder/entry['path']).resolve();path.relative_to(folder)
                    if not path.is_file() or w.digest(path.read_bytes())!=entry['sha256']:raise ValueError('恢复的演练运行产物缺失或校验失败')
                    artifacts+=1
                runs+=1
    return {'collections':collections,'versions':versions,'files':files,'runs':runs,'run_artifacts':artifacts,'formal':False,'source_files_used':False}


def rehearse(path):
    """Restore into an isolated directory and a private temporary Surreal server.

    Existing databases, files, services and accounts are never replaced. This
    does not claim that a same-machine DPAPI archive is independent disaster
    recovery or that Zotero's complete native profile has been restored.
    """
    path=Path(path).resolve();verify(path)
    root=w.DATA/'备份/_临时/原生暂存/_临时';root.mkdir(parents=True,exist_ok=True)
    result={'checked':w.now(),'backup':backup_label(path),
            'production_changed':False,'independent_disaster_recovery':False}
    with tempfile.TemporaryDirectory(prefix='restore-',dir=root) as directory:
        staging=Path(directory).resolve()
        with backup_crypto.opened(path,root) as decrypted,zipfile.ZipFile(decrypted) as archive:
            names=archive.namelist()
            selected=[name for name in names if name.startswith(('数据库/','数据/','科研知识库/','工具/科研流程/','原文/','output/','research/','tasks/','Zotero/'))]
            for name in selected:
                target=(staging/name).resolve()
                if not target.is_relative_to(staging):raise ValueError('恢复包包含越界路径')
                target.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(name) as source,target.open('wb') as destination:shutil.copyfileobj(source,destination,length=backup_crypto.CHUNK)
            manifest=json.loads(archive.read('备份清单.json'))
        counts={}
        databases=[('research.sqlite3','nodes'),('n8n.sqlite','workflow_entity')]
        if (staging/'数据库/validation.sqlite3').exists():databases.append(('validation.sqlite3','nodes'))
        for filename,table in databases:
            file=staging/'数据库'/filename
            with closing(sqlite3.connect(file.as_uri()+'?mode=ro',uri=True)) as db:
                integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
                violations=db.execute('PRAGMA foreign_key_check').fetchall()
                if integrity!='ok' or violations:raise ValueError('恢复的 SQLite 数据未通过完整性检查')
                if filename == 'n8n.sqlite' and 'n8n' in manifest:
                    _check_n8n(db, manifest['n8n'])
                counts[filename]={'integrity_check':integrity,'foreign_key_violations':0,
                                  'records':db.execute('SELECT count(*) FROM '+table).fetchone()[0]}
        result['sqlite']=counts
        result['rspace']=__import__('rspace_backup').rehearse(staging/'数据库')
        result['validation_data']=verify_validation_snapshots(staging)
        if result['validation_data']['collections']:
            repository=staging/'数据/软件验证/数据版本'
            from dataset_store import command
            command(['git','fsck','--full'],repository)
            result['validation_data']['native_git_fsck']='passed'
            samples=[]
            for path in (staging/'数据/软件验证/原始数据索引').glob('DATA-*/*/manifest.json'):
                version=w.read_json(path);entry=version['files'][0]
                file=(repository/'datasets'/version['id']/version['version']/'raw'/entry['path']).resolve()
                file.relative_to(staging)
                samples.append((file,entry['sha256']));file.unlink()
            command([__import__('sys').executable,'-m','dvc','checkout'],repository,site_cache=staging/'dvc-site-cache')
            if any(not file.is_file() or w.digest(file.read_bytes())!=sha for file,sha in samples):
                raise ValueError('隔离恢复的 DVC 缓存未能还原验证文件')
            result['validation_data']['native_dvc_checkout_files']=len(samples)
            recovered=[]
            with closing(sqlite3.connect((staging/'数据库/validation.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
                for uri,raw in db.execute("SELECT uri,data FROM nodes WHERE kind='RUN' AND status='COMPLETED'"):
                    folder=(staging/uri).resolve();folder.relative_to(repository/'runs');node=json.loads(raw)
                    entry=next((e for e in node.get('artifacts',[]) if e['path']=='computed/figure.svg'),None)
                    if not entry:raise ValueError('恢复的演练缺少原生图产物')
                    file=folder/entry['path'];file.relative_to(staging);file.unlink()
                    command([__import__('sys').executable,'-m','dvc','checkout','dvc.yaml'],folder,site_cache=staging/'dvc-site-cache')
                    if not file.is_file() or w.digest(file.read_bytes())!=entry['sha256']:raise ValueError('隔离 DVC 缓存未能恢复演练图产物')
                    recovered.append(uri)
            result['validation_data']['native_dvc_checkout_runs']=len(recovered)
        items=w.read_json(staging/'数据库/zotero-items.json')
        if manifest.get('zotero_native'):result['zotero_native']=__import__('zotero_native_backup').rehearse(staging,items)
        restored_library=w.read_json(staging/'科研知识库/文献/library.json')
        restored_originals=list((staging/'原文').glob('*/*'))
        if len(restored_originals)!=manifest['original_files']:raise ValueError('恢复的原文数量不一致')
        result['zotero_api_items']=len(items);result['papers']=len(restored_library['records'])
        result['original_files']=len(restored_originals)
        professional=staging/'output/科研工作区重构'
        for file in (professional/'专业网络').glob('**/*.cys'):
            if not zipfile.is_zipfile(file):raise ValueError('恢复的专业网络会话无效')
        result['saved_professional_files']=sum(1 for folder in ['专业网络','文献计量'] for file in (professional/folder).rglob('*') if file.is_file())
        native_export=staging/'数据库/open-notebook.surql'
        compatible,adjustments=restore_surreal_schema(native_export.read_bytes())
        restore_import=staging/'open-notebook.restore.surql'
        restore_import.write_bytes(compatible)
        result['surreal_restore_compatibility']={'upstream_issue':'surrealdb/surrealdb#6075',
            'relation_field_definitions':adjustments,'original_archive_changed':False,
            'record_data_changed':False}
        # A different process, temporary port, credentials and in-memory DB.
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
        url='http://127.0.0.1:'+str(port);secret=secrets.token_urlsafe(32)
        environment=os.environ.copy();environment.update(SURREAL_USER='restore',SURREAL_PASS=secret,
            SURREAL_BIND='127.0.0.1:'+str(port),SURREAL_LOG='error')
        executable=w.ROOT/'工具/OpenNotebook/bin/surreal.exe'
        with (staging/'surreal.log').open('wb') as log:
            process=subprocess.Popen([str(executable),'start','memory'],env=environment,
                stdout=log,stderr=log,stdin=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                deadline=time.monotonic()+30
                while True:
                    if process.poll() is not None:raise ValueError('隔离恢复库未能启动')
                    try:
                        if requests.get(url+'/health',timeout=1).status_code==200:break
                    except requests.RequestException:pass
                    if time.monotonic()>deadline:raise ValueError('隔离恢复库启动超时')
                    time.sleep(.25)
                imported=subprocess.run([str(executable),'import','--endpoint',url,'--namespace','recovery',
                    '--database','recovery','--log','none',str(restore_import)],
                    env=environment,capture_output=True,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
                if imported.returncode:
                    diagnostic=win32crypt.CryptProtectData(imported.stdout+b'\n'+imported.stderr,'Research Restore Diagnostic',None,None,None,4)
                    (w.DATA/'恢复诊断.dpapi').write_bytes(diagnostic)
                    raise ValueError('隔离检索库导入未完成（'+str(imported.returncode)+'）；诊断已加密保存在本机')
                response=requests.post(url+'/sql',data='SELECT count() AS total FROM source GROUP ALL; SELECT count() AS total FROM note GROUP ALL;',
                    headers={'Accept':'application/json','Surreal-NS':'recovery','Surreal-DB':'recovery'},
                    auth=('restore',secret),timeout=30)
                response.raise_for_status();values=response.json()
                if any(row.get('status')!='OK' for row in values):raise ValueError('隔离检索库查询未通过')
                result['open_notebook']={'restored':True,'sources':values[0]['result'][0]['total'] if values[0]['result'] else 0,
                                        'notes':values[1]['result'][0]['total'] if values[1]['result'] else 0,
                                        'isolated_native_server':True}
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=15)
                    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=10)
        source=staging/'工具/科研流程'
        git=subprocess.run(['git','-C',str(source),'fsck','--full'],capture_output=True,timeout=60,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        if git.returncode:raise ValueError('恢复的代码 Git 对象未通过检查')
        result['source_git_fsck']='passed'
        result['scope']='隔离解包、原文数量、SQLite 原生重开/完整性、Surreal 原生导入查询、代码 Git 对象；不覆盖现用数据库，不等同于 Zotero 全部原生配置或异机容灾恢复'
    w.write_json(w.ROOT/'output/科研工作区重构/恢复演练验收.json',result)
    return result


if __name__=='__main__':
    import sys
    if len(sys.argv)>1 and sys.argv[1]=='rehearse':
        selected=Path(sys.argv[2]) if len(sys.argv)>2 else w.ROOT/w.read_json(w.DATA/'最近备份.json')['file']
        result=rehearse(selected)
    elif len(sys.argv)>2 and sys.argv[1]=='verify':result=verify(sys.argv[2])
    else:
        result=backup(native_staging='--native-staging' in sys.argv)
    print(json.dumps(result,ensure_ascii=True))
