"""Archive Zotero's own online SQLite snapshot, never its live database."""
from contextlib import closing
from pathlib import Path
import re
import sqlite3
import backup_crypto
import workflow as w
import zotero_note_boundary as bridge


def database_summary(path,items,storage,linked):
    # Native backUpDatabase has closed this consistent snapshot. Immutable
    # read mode avoids creating SQLite WAL/SHM sidecars in Zotero's directory.
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Zotero 原生快照未通过完整性检查')
        keys={row[0] for row in db.execute('SELECT key FROM items')}
        if not {item['key'] for item in items}.issubset(keys):raise ValueError('Zotero 原生快照缺少已读取的条目 ID')
        attachments=list(db.execute('SELECT i.key,a.path,a.linkMode FROM itemAttachments a JOIN items i ON i.itemID=a.itemID'))
        expected={key:raw for key,raw,mode in attachments if mode==2}
        actual={entry['key']:entry for entry in linked}
        if len(actual)!=len(linked) or set(actual)!=set(expected):raise ValueError('Zotero 原生快照与外链附件清单不一致，请重新备份；未漏过失联附件')
        for key,raw in expected.items():
            entry=actual[key]
            if entry.get('native_path') is not None:
                matches=entry['native_path']==raw
            else:
                # Version 1.0.1 supported absolute linked paths. Relative
                # paths require 1.0.2's native raw-path identity, not guessing.
                matches=bool(raw) and Path(raw).is_absolute() and Path(raw).resolve()==Path(entry['original_path']).resolve()
            if not matches:raise ValueError('Zotero 外链附件路径在快照后变化或连接需更新，请重新备份')
        for key,raw,mode in attachments:
            if not raw or not raw.startswith('storage:'):continue
            if not re.fullmatch('[A-Z0-9]{8}',key):raise ValueError('Zotero 附件 ID 无效')
            base=(storage/key).resolve();file=(base/raw[len('storage:'):]).resolve()
            if not base.is_relative_to(storage.resolve()) or not file.is_relative_to(base):raise ValueError('Zotero 附件路径越界')
            if not file.is_file():raise ValueError('Zotero 已登记的原生附件缺失，未生成不完整的新备份')
        tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts={label:db.execute('SELECT count(*) FROM '+table).fetchone()[0] if table in tables else 0
                for label,table in [('items','items'),('collections','collections'),('notes','itemNotes'),('annotations','itemAnnotations')]}
    return counts


def export(stage,items):
    descriptor=bridge.native('backup')
    database=Path(descriptor.get('database',''));storage=Path(descriptor.get('storage',''))
    if (not database.is_absolute() or database.name!='zotero.sqlite.research-workspace.bak'
        or not database.is_file() or not storage.is_absolute() or not storage.is_dir()
        or storage.resolve()!=database.parent.resolve()/'storage'):
        raise ValueError('原生备份连接尚未更新或未返回有效的一致快照；未复制正在使用的文献数据库')
    sources=[(database,'Zotero/zotero.sqlite')]
    for file in sorted(storage.rglob('*')):
        if not file.resolve().is_relative_to(storage.resolve()):raise ValueError('Zotero 附件目录含越界链接')
        if file.is_file():sources.append((file,'Zotero/storage/'+file.relative_to(storage).as_posix()))
    linked=[]
    for entry in descriptor.get('linked',[]):
        key=entry.get('key','');file=Path(entry.get('path',''))
        if not re.fullmatch('[A-Z0-9]{8}',key) or not file.is_absolute() or not file.is_file():
            raise ValueError('Zotero 外链附件缺失或 ID 无效，未生成不完整的新备份')
        name='Zotero/linked/'+key+'/'+file.name
        if any(archive_name==name for _,archive_name in sources):raise ValueError('Zotero 外链附件 ID 冲突')
        sources.append((file,name));linked.append({'key':key,'original_path':str(file),'native_path':entry.get('raw_path'),'archive_path':name})
    summary=database_summary(database,items,storage,linked)
    inventory={name:{'bytes':file.stat().st_size,'sha256':backup_crypto.file_digest(file)} for file,name in sources}
    receipt={'schema':1,'created':w.now(),'engine':descriptor.get('engine'),
             'connector_version':descriptor.get('version'),'application_version':descriptor.get('app_version'),
             'source_root':str(database.parent),'summary':summary,'files':inventory,'linked':linked,
             'complete_profile':False,'scope':'Zotero 原生一致数据库和全部现存 storage/外链附件；保留条目 ID、笔记、批注与分类，不包含账号、密码和全部程序偏好'}
    w.write_json(stage/'zotero-native-backup.json',receipt)
    return sources


def rehearse(stage,items):
    receipt=w.read_json(stage/'数据库/zotero-native-backup.json',{})
    if receipt.get('schema')!=1:raise ValueError('备份缺少 Zotero 原生恢复清单')
    for name,expected in receipt['files'].items():
        path=(stage/name).resolve()
        if not name.startswith('Zotero/') or not path.is_relative_to(stage.resolve()) or not path.is_file():
            raise ValueError('恢复的 Zotero 原生文件缺失或越界')
        if path.stat().st_size!=expected['bytes'] or backup_crypto.file_digest(path)!=expected['sha256']:
            raise ValueError('恢复的 Zotero 原生文件校验失败')
    summary=database_summary(stage/'Zotero/zotero.sqlite',items,stage/'Zotero/storage',receipt['linked'])
    if summary!=receipt['summary']:raise ValueError('恢复的 Zotero 原生记录数量不一致')
    return {**summary,'storage_files':sum(name.startswith('Zotero/storage/') for name in receipt['files']),
            'linked_files':len(receipt['linked']),'stable_keys_preserved':True,
            'source_files_used':False,'complete_profile':False,
            'linked_paths_require_relink':bool(receipt['linked']),
            'scope':receipt['scope'],'application_version':receipt['application_version']}
