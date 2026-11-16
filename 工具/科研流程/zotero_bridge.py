"""Official Zotero 10 API adapter and durable, reconciling intake outbox.

No native database access, no credentials in receipts, no background prompts.
Each write first checks its stable key/identity. Unknown writes are reconciled
before retry, including after Zotero or the workspace restarts.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import secrets
from urllib.parse import unquote, urlparse
import requests
import workflow as w
from research_store import Store, encode, now

BASE = 'http://127.0.0.1:23119/api'
PREFIX = '/users/0'
ALPHABET = '23456789ABCDEFGHIJKLMNPQRSTUVWXYZ'


def key_for(value):
    return ''.join(ALPHABET[b % len(ALPHABET)] for b in hashlib.sha256(value.encode()).digest()[:8])


def _secret(value=None):
    import win32crypt
    path = w.DATA / 'zotero-local.dpapi'
    if value is not None:
        path.write_bytes(win32crypt.CryptProtectData(encode(value).encode(), 'Research Zotero', None, None, None, 4))
        return value
    if not path.exists():
        return {}
    return json.loads(win32crypt.CryptUnprotectData(path.read_bytes(), None, None, None, 0)[1])


def _server():
    response = requests.get(BASE + '/', timeout=8)
    response.raise_for_status()
    server = response.headers.get('Zotero-Server-ID')
    if not server:
        raise ValueError('自动收录需要 Zotero 10 或更新版本')
    return server


def status():
    try:
        server = _server()
        saved = _secret()
        authorized = saved.get('server') == server and bool(saved.get('key'))
        return {'online': True, 'authorized': authorized, 'remembered': authorized and saved.get('remember', False),
                'message': '自动收录已连接' if authorized else '需要在 Zotero 中授权自动收录'}
    except (requests.RequestException, ValueError, OSError):
        return {'online': False, 'authorized': False, 'message': 'Zotero 未运行或本地接口未启用'}


def authorize():
    from filelock import FileLock, Timeout
    w.DATA.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(w.DATA / '.zotero-authorize.lock', timeout=0):
            return _authorize()
    except Timeout:
        raise ValueError('已有 Zotero 授权正在等待确认，请完成当前弹窗') from None


def _authorize():
    server = _server()
    try:
        response = requests.post(BASE + '/local/authorize', json={'appName': '研序科研工作区'},
                                 headers={'Zotero-Server-ID': server}, timeout=(10, 900))
    except requests.Timeout:
        raise ValueError('Zotero 授权等待已结束；待收录资料仍保留，可从连接与设置重新连接') from None
    if response.status_code == 403:
        raise ValueError('Zotero 写入未获授权，已保留待收录资料')
    response.raise_for_status()
    value = response.json()
    if not isinstance(value.get('key'), str) or len(value['key']) != 32:
        raise ValueError('Zotero 未返回有效授权')
    _secret({'server': server, 'key': value['key'], 'remember': value.get('remember', False)})
    return {'authorized': True, 'remembered': bool(value.get('remember')),
            'message': '已授权，后台将继续收录' if value.get('remember') else '本次授权只可写入一次；持续自动收录请选择“总是允许”'}


def _request(method, path, server, **kwargs):
    headers = {'Zotero-Server-ID': server, **kwargs.pop('headers', {})}
    if method != 'GET':
        saved = _secret()
        if saved.get('server') != server or not saved.get('key'):
            raise PermissionError('需要在连接设置中授权 Zotero 自动收录')
        headers['Zotero-API-Key'] = saved['key']
    response = requests.request(method, BASE + path, headers=headers, timeout=kwargs.pop('timeout',45), **kwargs)
    if response.status_code == 401 and method != 'GET':
        _secret({})
        raise PermissionError('Zotero 授权已失效，请重新连接')
    response.raise_for_status()
    return response


def _get_item(key, server):
    try:
        return _request('GET', PREFIX + '/items/' + key, server).json()['data']
    except requests.HTTPError as exc:
        if exc.response.status_code == 404:
            return None
        raise


def _create(item, server):
    payload={'version':0,'collections':[],'relations':{},**item}
    result = _request('POST', PREFIX + '/items', server, json=[payload],
                      headers={'Zotero-Write-Token': secrets.token_hex(16)}).json()
    if result.get('failed'):
        raise ValueError('Zotero 未接收条目，请核对题录或更新 Zotero')


def _schema(store):
    with store.connection() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS zotero_intake(
            id TEXT PRIMARY KEY,paper TEXT NOT NULL,payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',server TEXT,item_key TEXT,
            attachment_key TEXT,attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt TEXT,lease TEXT,error TEXT,updated TEXT NOT NULL)''')


def enqueue(record, artifact=None):
    if artifact:
        artifact = dict(artifact)
        path = Path(artifact['path'])
        actual = w.digest(path.read_bytes())
        if artifact.get('sha256') and actual != artifact['sha256']:
            raise ValueError('附件内容已变化，请先重新登记')
        artifact['sha256'] = actual
    identifier = 'ZI-' + w.digest(record['id'] + ':' + (artifact or {}).get('sha256', 'metadata'))[:24]
    store = Store(); _schema(store)
    with store.connection() as db:
        db.execute('INSERT OR IGNORE INTO zotero_intake(id,paper,payload,updated) VALUES(?,?,?,?)',
                   (identifier, record['id'], encode({'record': record, 'artifact': artifact}), now()))
    return identifier


def receipt(identifier):
    store = Store(); _schema(store)
    with store.connection() as db:
        row = db.execute('SELECT id,paper,status,item_key,attachment_key,attempts,error,updated FROM zotero_intake WHERE id=?', (identifier,)).fetchone()
    return dict(row) if row else None


def receipts():
    store = Store(); _schema(store)
    with store.connection() as db:
        return [dict(row) for row in db.execute('SELECT id,paper,status,item_key,attachment_key,attempts,error,updated FROM zotero_intake ORDER BY updated DESC LIMIT 100')]


def _checkpoint(store, identifier, **values):
    if not values.keys() <= {'status', 'server', 'item_key', 'attachment_key', 'next_attempt', 'lease', 'error'}:
        raise ValueError('Invalid intake checkpoint')
    values['updated'] = now()
    with store.connection() as db:
        db.execute('UPDATE zotero_intake SET ' + ','.join(k + '=?' for k in values) + ' WHERE id=?', (*values.values(), identifier))


def _metadata(record, key):
    creators = record.get('creators') or [{'creatorType': 'author', 'name': a} for a in record.get('authors', []) if isinstance(a, str)]
    issn = record.get('issn') or ''
    if isinstance(issn, list): issn = ' '.join(str(value) for value in issn)
    return {'key': key, 'itemType': 'journalArticle', 'title': record['title'], 'DOI': record.get('doi') or '',
            'date': str(record.get('publication_date') or record.get('year') or ''),
            'publicationTitle': record.get('journal') or '', 'ISSN': issn,
            'abstractNote': record.get('abstract') or '', 'creators': creators,
            'url': record.get('url') or ('https://doi.org/' + record['doi'] if record.get('doi') else ''),
            'tags': [{'tag': 'workspace-id:' + record['id']}], 'extra': 'Workspace ID: ' + record['id']}


def _identity(item, record):
    return ('workspace-id:' + record['id'] in [t['tag'] for t in item.get('tags', [])]
            or bool(record.get('doi') and w.normalize_doi(item.get('DOI')) == w.normalize_doi(record['doi'])))


def process(identifier, *, force=False):
    store = Store(); _schema(store)
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM zotero_intake WHERE id=?', (identifier,)).fetchone()
        if not row:
            raise ValueError('收录记录不存在')
        if row['status'] in ('completed', 'needs_review'):
            return {k: row[k] for k in ('id', 'paper', 'status', 'item_key', 'attachment_key', 'attempts', 'error', 'updated')}
        if row['lease'] and row['lease'] > now():
            return {k: row[k] for k in ('id', 'paper', 'status', 'item_key', 'attachment_key', 'attempts', 'error', 'updated')}
        if not force and row['next_attempt'] and row['next_attempt'] > now():
            return {k: row[k] for k in ('id', 'paper', 'status', 'item_key', 'attachment_key', 'attempts', 'error', 'updated')}
        db.execute('UPDATE zotero_intake SET lease=?,attempts=attempts+1 WHERE id=?',
                   ((datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(), identifier))
    payload = json.loads(row['payload']); record = payload['record']; artifact = payload['artifact']
    try:
        server = _server()
        if row['server'] and row['server'] != server:
            _checkpoint(store, identifier, status='needs_review', error='Zotero 文库已切换，需要核对原收录目标')
            return receipt(identifier)
        _checkpoint(store, identifier, server=server)
        # Match a durable workspace identity or DOI before any external write.
        response = _request('GET', PREFIX + '/items', server)
        items = [i['data'] for i in response.json()]
        matches = [i for i in items if i.get('itemType') not in ('note', 'annotation', 'attachment') and _identity(i, record)]
        if len(matches) > 1:
            _checkpoint(store, identifier, status='needs_review', error='Zotero 有多个相同来源条目，请先合并或指定正式条目')
            return receipt(identifier)
        key = matches[0]['key'] if matches else row['item_key'] or key_for(record['id'])
        _checkpoint(store, identifier, item_key=key)
        parent = matches[0] if matches else _get_item(key, server)
        if parent and not _identity(parent, record):
            raise ValueError('稳定书目键已被其他条目使用，未覆盖')
        if parent is None:
            _create(_metadata(record, key), server)
            parent = _get_item(key, server)
            if not parent or not _identity(parent, record):
                raise ValueError('Zotero 写入结果尚未核实')
        if artifact:
            path = Path(artifact['path']); raw = path.read_bytes()
            if w.digest(raw) != artifact['sha256']:
                raise ValueError('原附件已变化，未上传')
            md5 = hashlib.md5(raw).hexdigest()
            attached = next((i for i in items if i.get('parentItem') == key and i.get('md5') == md5), None)
            attachment_key = attached['key'] if attached else row['attachment_key'] or key_for(key + artifact['sha256'])
            _checkpoint(store, identifier, attachment_key=attachment_key)
            attachment = attached or _get_item(attachment_key, server)
            mime = 'application/pdf' if artifact['kind'] == 'pdf' else 'application/xml'
            if attachment and attachment.get('parentItem') != key:
                raise ValueError('附件键已被其他条目使用，未覆盖')
            if attachment is None:
                _create({'key': attachment_key, 'itemType': 'attachment', 'parentItem': key,
                         'linkMode': 'imported_file', 'title': '论文原文', 'contentType': mime,
                         'filename': path.name, 'tags': []}, server)
                attachment = _get_item(attachment_key, server)
            if attachment.get('md5') != md5:
                precondition = {'If-Match': attachment['md5']} if attachment.get('md5') else {'If-None-Match': '*'}
                endpoint = PREFIX + '/items/' + attachment_key + '/file'
                upload = _request('POST', endpoint, server, headers=precondition, data={
                    'md5': md5, 'filename': path.name, 'filesize': len(raw), 'mtime': int(path.stat().st_mtime * 1000)}).json()
                if not upload.get('exists'):
                    parsed = urlparse(upload['url'])
                    if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1') or parsed.port != 23119 or not parsed.path.startswith('/api/local/uploads/'):
                        raise ValueError('Zotero 返回的附件入口无效')
                    response = requests.post(upload['url'], data=raw, headers={'Content-Type': upload['contentType']}, timeout=60)
                    response.raise_for_status()
                    _request('POST', endpoint, server, headers=precondition, data={'upload': upload['uploadKey']})
            saved = _get_item(attachment_key, server)
            if saved.get('md5') != md5:
                raise ValueError('Zotero 附件校验尚未完成')
        _checkpoint(store, identifier, status='completed', error=None, next_attempt=None)
    except PermissionError as exc:
        _checkpoint(store, identifier, status='waiting_authorization', error=str(exc), next_attempt=None)
    except (requests.RequestException, OSError, ValueError, KeyError, TypeError) as exc:
        delay = min(3600, 30 * (2 ** min(row['attempts'], 7)))
        _checkpoint(store, identifier, status='retry', error='收录未完成：' + type(exc).__name__,
                    next_attempt=(datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat())
    finally:
        _checkpoint(store, identifier, lease=None)
    return receipt(identifier)


def submit(record, artifact=None):
    result = process(enqueue(record, artifact), force=True)
    return 'Zotero 书目及附件已核实' if result['status'] == 'completed' and artifact else 'Zotero 书目已核实' if result['status'] == 'completed' else '已登记待收录，后台将自动接续；' + (result.get('error') or '等待处理')


def drain(limit=5):
    store = Store(); _schema(store)
    with store.connection() as db:
        rows = db.execute("SELECT id FROM zotero_intake WHERE status IN ('queued','retry','waiting_authorization') AND (next_attempt IS NULL OR next_attempt<=?) ORDER BY updated LIMIT ?", (now(), limit)).fetchall()
    return [process(row['id']) for row in rows]


def attachment_path(key):
    response = requests.get(BASE + PREFIX + '/items/' + key + '/file', allow_redirects=False, timeout=10)
    if response.status_code != 302:
        return None
    parsed = urlparse(response.headers.get('Location', ''))
    if parsed.scheme != 'file' or parsed.netloc not in ('', 'localhost'):
        return None
    path = unquote(parsed.path).lstrip('/')
    return Path(path) if len(path) > 2 and path[1] == ':' else None
