"""Compare Better Notes originals without letting either side overwrite knowledge.

This adapter reads the supported Zotero API. Disabling the plugin's own old
bidirectional registrations is a separate native operation; a comparison or
acknowledgement must never claim that it has changed those registrations.
"""
import html
from contextlib import nullcontext
import re
import knowledge as k
import workflow as w
from research_store import Store, now


def store():
    result=Store()
    with result.connection() as db:
        db.executescript('''
          CREATE TABLE IF NOT EXISTS note_sync_pairs(
            id TEXT PRIMARY KEY,native_key TEXT NOT NULL,local_path TEXT NOT NULL,
            local_sha TEXT NOT NULL,native_sha TEXT NOT NULL,title TEXT NOT NULL,
            snapshot TEXT,plain_same INTEGER NOT NULL,created TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS note_sync_current(
            native_key TEXT PRIMARY KEY,pair_id TEXT NOT NULL REFERENCES note_sync_pairs(id),
            status TEXT NOT NULL,checked TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS note_sync_reviews(
            pair_id TEXT PRIMARY KEY REFERENCES note_sync_pairs(id),
            reason TEXT NOT NULL,created TEXT NOT NULL);
        ''')
    return result


def plain(value,markdown=False):
    if markdown:
        value=re.sub(r'!?(\[[^\]]*\])\([^\n)]+\)',r'\1',value)
        value=re.sub(r'\\([\[\]_*])',r'\1',value)
        value=re.sub(r'(?m)^\s*(?:#{1,6}\s+|[-*+]\s+|\d+\.\s+)','',value)
        value=re.sub(r'[`*_\[\]]','',value)
    parser=w.NoteTextParser();parser.feed(value)
    return re.sub(r'\s+','',html.unescape(''.join(parser.parts)))


def retired_keys(ledger=None):
    boundary=(ledger or store()).cursor('connector:better-notes-boundary',{})
    keys=set(boundary.get('retired_keys') or boundary.get('detached') or [])
    if 'registered_keys' in boundary:return keys-set(boundary['registered_keys'])
    if boundary.get('status')=='completed':return keys
    if boundary.get('status')=='needs_recheck':return keys-set(boundary.get('reappeared',[]))
    return set()


def preserve_pair(key, identity, original, native):
    folder = w.KB/'同步冲突/BetterNotes'/key/identity[:20]
    for name, value in [('Markdown原稿.md', original), ('Zotero原稿.html', native)]:
        target = folder/name
        if target.exists() and target.read_text('utf-8') != value:
            raise ValueError('旧稿保留位置的内容已修改，未覆盖')
        if not target.exists():
            w.atomic_text(target, value)
    return folder.relative_to(w.KB).as_posix()


def compare(items,*,locked=False,native_keys=None):
    natives={item['key']:item for item in items if item.get('itemType')=='note'}
    ledger=store()
    with nullcontext() if locked else k.editing():
        if native_keys is None:
            native_keys = __import__('zotero_note_boundary').registered_keys(ledger)
        # A linked item key is not proof of a current Better Notes registration.
        # On unavailable inspection, retain existing comparisons without creating new ones.
        eligible = ((native_keys or set()) & natives.keys()) - retired_keys(ledger)
        if not eligible:
            return entries()
        for path in w.KB.rglob('*.md'):
            if any(part in ('同步冲突','编辑备份','垃圾箱') for part in path.relative_to(w.KB).parts):continue
            original=path.read_text('utf-8-sig');meta,body,_=k.split(original)
            key=meta.get('$itemKey')
            if not re.fullmatch(r'[A-Z0-9]{8}',str(key or '')) or key not in eligible:continue
            relative=path.resolve().relative_to(w.KB.resolve()).as_posix()
            native=natives[key].get('note') or ''
            local_sha=w.digest(original);native_sha=w.digest(native)
            identity=w.digest(relative+':'+key+':'+local_sha+':'+native_sha)
            same=plain(body,markdown=True)==plain(native)
            snapshot=preserve_pair(key,identity,original,native)
            with ledger.connection() as db:
                db.execute('INSERT OR IGNORE INTO note_sync_pairs VALUES(?,?,?,?,?,?,?,?,?)',
                    (identity,key,relative,local_sha,native_sha,str(meta.get('title') or path.stem),snapshot,int(same),now()))
                db.execute('UPDATE note_sync_pairs SET snapshot=? WHERE id=? AND snapshot IS NULL',(snapshot,identity))
                reviewed=db.execute('SELECT 1 FROM note_sync_reviews WHERE pair_id=?',(identity,)).fetchone()
                status='matched_text' if same else 'reviewed' if reviewed else 'needs_review'
                db.execute('INSERT OR REPLACE INTO note_sync_current VALUES(?,?,?,?)',(key,identity,status,now()))
    return entries()


def entries():
    ledger=store()
    with ledger.connection() as db:
        rows=[dict(row) for row in db.execute('''SELECT p.*,c.status,c.checked
            FROM note_sync_current c JOIN note_sync_pairs p ON p.id=c.pair_id ORDER BY p.local_path''')]
    retired=retired_keys(ledger)
    boundary=ledger.cursor('connector:better-notes-boundary',{})
    registered=set(boundary['registered_keys']) if 'registered_keys' in boundary else None
    for row in rows:
        try:
            current=k.path_for(row['local_path']).read_text('utf-8-sig')
            row['local_changed']=w.digest(current)!=row['local_sha']
        except (OSError,ValueError):
            row['local_changed']=True
        if row['native_key'] in retired or (registered is not None and row['native_key'] not in registered):
            row['comparison_status']=row['status'];row['status']='retired_history'
        elif row['local_changed']:
            row['status']='needs_refresh'
    return {'records':rows,'authority':'Markdown',
            'boundary_status':boundary.get('status','native_registrations_not_changed'),'boundary_checked':boundary.get('checked'),
            'message':'已保留两端原稿。上次核验已取消本工作区旧双向同步，知识正文在 Markdown 维护。' if boundary.get('status')=='completed' else '已保留两端原稿。Markdown 是知识主稿；原生同步边界在连接设置单独核验。'}


def refresh_pair(data):
    with store().connection() as db:
        row=db.execute('SELECT native_key FROM note_sync_pairs WHERE id=?',(data.get('id'),)).fetchone()
    if not row:raise ValueError('对照记录不存在')
    current=next((r for r in entries()['records'] if r['native_key']==row['native_key']),None)
    if current and current['status']=='retired_history':return detail(current['id'])
    items=w.zotero_items()
    if not any(i.get('key')==row['native_key'] for i in items):
        raise ValueError('未能读取这份 Zotero 旧同步稿，请确认 Zotero 已打开；原稿未改变')
    current=next((r for r in compare(items)['records'] if r['native_key']==row['native_key']),None)
    if not current:raise ValueError('本地主稿已不存在，请先恢复资料')
    if current['plain_same']:
        return {**current,'document_id':'DOC-'+w.digest('科研知识库/'+current['local_path'])[:20]}
    return detail(current['id'])


def detail(identifier):
    with store().connection() as db:
        row=db.execute('SELECT * FROM note_sync_pairs WHERE id=?',(identifier,)).fetchone()
    if not row:raise ValueError('两端原稿对照不存在')
    folder=(w.KB/(row['snapshot'] or ('同步冲突/BetterNotes/'+row['native_key']+'/'+row['id'][:20]))).resolve()
    if not folder.is_relative_to((w.KB/'同步冲突/BetterNotes').resolve()):raise ValueError('对照路径无效')
    local=(folder/'Markdown原稿.md').read_text('utf-8')
    native=(folder/'Zotero原稿.html').read_text('utf-8')
    if w.digest(local)!=row['local_sha'] or w.digest(native)!=row['native_sha']:
        raise ValueError('对照原稿的校验值已变化')
    parser=w.NoteTextParser();parser.feed(native)
    state=entries();current=next((r for r in state['records'] if r['native_key']==row['native_key']),{})
    return {**dict(row),'local_body':k.split(local)[1],'native_text':''.join(parser.parts),
            'status':current.get('status'),'local_changed':current.get('local_changed',True),'boundary_status':state['boundary_status'],
            'document_id':'DOC-'+w.digest('科研知识库/'+row['local_path'])[:20]}


def acknowledge(data):
    row=detail(data.get('id'))
    if row['status']=='retired_history':raise ValueError('旧同步已解除，这份对照只作为历史保存，无需重复审核')
    reason=data.get('reason','').strip()
    if not 4<=len(reason)<=1000:raise ValueError('请记录核对情况')
    local=k.path_for(row['local_path'])
    if w.digest(local.read_text('utf-8-sig'))!=row['local_sha']:
        raise ValueError('Markdown 主稿已修改，请先重新同步后核对')
    native=next((item for item in w.zotero_items() if item.get('key')==row['native_key']),None)
    if not native or w.digest(native.get('note') or '')!=row['native_sha']:
        raise ValueError('Zotero 原稿已修改，请先重新同步后核对')
    ledger=store()
    with ledger.connection() as db:
        current=db.execute('SELECT pair_id FROM note_sync_current WHERE native_key=?',(row['native_key'],)).fetchone()
        if not current or current['pair_id']!=row['id']:raise ValueError('原稿版本已变化，请重新核对')
        db.execute('INSERT OR REPLACE INTO note_sync_reviews VALUES(?,?,?)',(row['id'],reason,now()))
        db.execute("UPDATE note_sync_current SET status='reviewed' WHERE native_key=?",(row['native_key'],))
        ledger.log(db,'note-sync-reviewed',row['native_key'],{'pair':row['id'],'reason':reason,'overwrote_originals':False})
    return {'status':'reviewed','overwrote_originals':False,'boundary_status':entries()['boundary_status']}
