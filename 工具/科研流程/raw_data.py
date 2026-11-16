"""Read-only native file intake. No guessed binary decoder or sample identity."""
from collections import Counter
from pathlib import Path
import os
import re
from filelock import FileLock
import workflow as w
from research_store import Store

PURPOSE='software_validation'

def ledger():
    # User-supplied verification files must never enter the scientific ledger.
    return Store(w.DATA/'validation.sqlite3')

def index_root():
    return w.ROOT/'数据/软件验证/原始数据索引'


def _root(path):
    path=Path(path).absolute()
    if not path.is_dir() or path.is_symlink() or getattr(path.lstat(),'st_file_attributes',0)&0x400:
        raise ValueError('数据目录不存在或是目录链接，请使用原始目录')
    return path.resolve()


def inspect(path):
    root=_root(path);files=[];total=0
    for folder,dirs,names in os.walk(root,followlinks=False):
        for name in [*dirs,*names]:
            entry=Path(folder)/name
            if entry.is_symlink() or getattr(entry.lstat(),'st_file_attributes',0)&0x400:
                raise ValueError('数据中包含目录链接，未跨目录扫描')
        for name in sorted(names):
            entry=Path(folder)/name;before=entry.stat();total+=before.st_size
            if len(files)>=50000 or total>4*1024**3:raise ValueError('本次接收超过文件或大小限制，请按批次登记')
            raw=entry.read_bytes();after=entry.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
                raise ValueError('数据正在写入，检查未完成，请待采集结束后重试')
            relative=entry.relative_to(root).as_posix()
            files.append({'id':'FILE-'+w.digest(relative)[:20],'path':relative,'bytes':len(raw),
                          'sha256':w.digest(raw),'extension':entry.suffix.lower(),
                          'binary':b'\0' in raw[:4096],'header_hex':raw[:16].hex()})
    if not files:raise ValueError('目录中没有可登记的原始文件')
    files.sort(key=lambda item:item['path'])
    identity='DATA-'+w.digest(root.as_uri())[:16]
    content=[{k:row[k] for k in ('path','bytes','sha256')} for row in files]
    version=w.digest(__import__('json').dumps(content,sort_keys=True,ensure_ascii=False))
    counts=Counter(row['extension'] for row in files)
    return {'schema':1,'id':identity,'title':root.name,'source_root':str(root),'source_uri':root.as_uri(),
            'version':version,'files':files,'file_count':len(files),'bytes':total,
            'extensions':dict(counts),'identical_file_groups':sum(n>1 for n in Counter(row['sha256'] for row in files).values()),
            'signal_filename_hints':counts.get('.sigtds',0),'reference_filename_hints':counts.get('.reftds',0),
            'format_status':'unverified','measurement_type':'未知','material':'未知','independent_samples':'未知',
            'units':'未知','reference_pairing':'未知','instrument':'未知','conditions':'未知',
            'purpose':PURPOSE,'formal':False,
            'scope':'用户提供的软件验证资料，不是真实实验；不用于科研结论。扩展名不证明仪器、波段、单位或独立样品数量。','created':w.now()}


def register(path,project='软件验证',progress=None):
    """Administrative intake only; arbitrary paths are not accepted by the HTTP API."""
    root=_root(path);identifier='DATA-'+w.digest(root.as_uri())[:16]
    w.DATA.mkdir(parents=True,exist_ok=True)
    with FileLock(str(w.DATA/(identifier+'.intake.lock')),timeout=45),__import__('dataset_store').writer():
        if progress:progress('正在核对原始文件及校验值')
        manifest=inspect(root);store=ledger();old=store.node(identifier)
        if old and (old['owner']!='Data Storage' or old['data'].get('source_root')!=str(root)):
            raise ValueError('已有身份的权威来源不匹配')
        location=index_root()/identifier/manifest['version']/'manifest.json'
        if location.exists():manifest=w.read_json(location)
        if progress:progress('正在建立原生 Git / DVC 数据版本')
        stored=__import__('dataset_store').store_collection(manifest)
        if not location.exists():w.write_json(location,manifest)
        data={**manifest,**stored,'manifest':location.relative_to(w.ROOT).as_posix()}
        data.pop('files')
        old=store.node(identifier)
        for field in ('measurement_type','material','independent_samples','units','reference_pairing','instrument','conditions','notes','metadata_source','metadata_updated'):
            if old and field in old['data']:data[field]=old['data'][field]
        if old and old['data'].get('version')==manifest['version']:
            for field in ('format_status','format_observation'):
                if field in old['data']:data[field]=old['data'][field]
        result=store.put_node(identifier,'Dataset','Data Storage',external_id=root.as_uri(),uri=root.as_uri(),
                              project='软件验证',status='VALIDATION_ONLY',data=data,expected=old['revision'] if old else None)
        return {**result,'reused':bool(old and old['data'].get('version')==manifest['version'])}


def _node(identifier):
    node=ledger().node(identifier) if isinstance(identifier,str) and re.fullmatch(r'DATA-[a-f0-9]{16}',identifier) else None
    if not node or node['owner']!='Data Storage' or not node['data'].get('manifest'):
        raise ValueError('原始数据尚未登记')
    return node


def _manifest(node):
    path=(w.ROOT/node['data']['manifest']).resolve();path.relative_to(index_root().resolve())
    value=w.read_json(path)
    if not value or value.get('id')!=node['id'] or value.get('version')!=node['data']['version']:
        raise ValueError('数据版本清单缺失或不匹配')
    return value


def listing(project=None):
    return [node for node in ledger().nodes(kind='Dataset') if node['owner']=='Data Storage' and node['data'].get('manifest')]


def detail(identifier):
    node=_node(identifier);manifest=_manifest(node)
    directory=index_root()/identifier
    versions=[{'version':v['version'],'created':v['created'],'files':v['file_count']} for path in directory.glob('*/manifest.json') if (v:=w.read_json(path))]
    return {**node,'files':manifest['files'],'versions':sorted(versions,key=lambda row:row['created'],reverse=True)}


def rescan(identifier,progress=None):
    node=_node(identifier)
    return register(node['data']['source_root'],node['project'],progress)


def file(identifier,file_id):
    node=_node(identifier);manifest=_manifest(node)
    entry=next((row for row in manifest['files'] if row['id']==file_id),None)
    if not entry:raise ValueError('文件未登记')
    root=_root(node['data']['source_root']);path=(root/entry['path']).resolve();path.relative_to(root)
    if not path.is_file() or w.digest(path.read_bytes())!=entry['sha256']:
        raise ValueError('原文件已变化或缺失；请重新检查数据，旧版本快照保留')
    return path


def update_metadata(data):
    node=_node(data.get('id'))
    fields=('measurement_type','material','independent_samples','units','reference_pairing','instrument','conditions','notes')
    changes={key:data[key].strip() or '未知' for key in fields if key in data and isinstance(data[key],str) and len(data[key])<=4000}
    if len(changes)!=len(set(data)-{'id','revision','project'}):raise ValueError('数据说明字段无效或过长')
    if data.get('project','软件验证')!='软件验证':raise ValueError('验证资料不能转入正式项目；真实实验需要另行登记')
    if type(data.get('revision')) is not int:raise ValueError('请重新打开当前数据版本再保存')
    return ledger().put_node(node['id'],node['kind'],node['owner'],external_id=node['external_id'],uri=node['uri'],
                            project='软件验证',status=node['status'],expected=data['revision'],
                            data={**node['data'],**changes,'metadata_source':'user-confirmed','metadata_updated':w.now()})
