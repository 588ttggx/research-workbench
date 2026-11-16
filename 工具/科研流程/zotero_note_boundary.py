"""Supported native Better Notes bridge; no preference/database surgery."""
import re
import requests
from filelock import FileLock, Timeout
import workflow as w
import note_reconciliation as notes
import zotero_bridge as zotero

BOUNDARY_KEY = 'connector:better-notes-boundary'


def package():
    import io,zipfile
    source=w.HERE/'zotero-addon';output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in ('manifest.json','bootstrap.js'):
            entry=zipfile.ZipInfo(name,(2026,10,14,0,0,0));entry.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(entry,(source/name).read_bytes())
    return output.getvalue()


def updates():
    """Native local update descriptor; no external code or credential endpoint."""
    manifest=__import__('json').loads((w.HERE/'zotero-addon/manifest.json').read_text('utf-8'))
    application=manifest['applications']['zotero']
    return {'addons':{application['id']:{'updates':[{'version':manifest['version'],
        'update_link':'http://127.0.0.1:8503/api/note-sync/plugin',
        'update_hash':'sha256:'+w.digest(package()),
        'applications':{'zotero':{k:application[k] for k in ('strict_min_version','strict_max_version')}}}]}}}


def native(operation='inspect',records=None):
    return zotero._request('POST',zotero.PREFIX+'/workspace/better-notes',zotero._server(),json={'operation':operation,**({'records':records} if records is not None else {})},**({'timeout':300} if operation=='backup' else {})).json()


def inspect_records():
    result = native()
    records = result.get('records') if isinstance(result, dict) else None
    if not isinstance(records, list) or any(
        not isinstance(row, dict) or not re.fullmatch(r'[A-Z0-9]{8}', str(row.get('key', '')))
        for row in records
    ) or len({row['key'] for row in records}) != len(records):
        raise ValueError('原生同步注册结果不完整')
    return result


def _observe(ledger, records):
    """Commit an observation only after the native endpoint confirms its registrations."""
    last = ledger.cursor(BOUNDARY_KEY, {})
    active = {row['key'] for row in records}
    pending = last.get('pending_detach', [])
    remaining = [row for row in pending if row['key'] in active]
    finished = {row['key'] for row in pending if row['key'] not in active}
    retired = set(last.get('retired_keys') or last.get('detached') or []) | finished
    observed = {**last, 'registered_keys': sorted(active)}
    if last.get('status') in ('completed', 'needs_recheck', 'detach_pending'):
        with ledger.connection() as db:
            known = {row[0] for row in db.execute('SELECT native_key FROM note_sync_current')}
        reappeared = (retired | known) & active
        observed.update(
            status='detach_pending' if remaining else 'needs_recheck' if reappeared else 'completed',
            reappeared=sorted(reappeared),
            remaining_workspace_registrations=len(reappeared),
            retired_keys=sorted(retired),
        )
        if remaining:
            observed['pending_detach'] = remaining
        else:
            observed.pop('pending_detach', None)
        if finished:
            observed['detached'] = sorted(set(last.get('detached', [])) | finished)
    if observed != last:
        observed['checked'] = w.now()
        ledger.commit_page(BOUNDARY_KEY, [], observed)
        if finished:
            with ledger.connection() as db:
                ledger.log(db, 'better-notes.boundary', BOUNDARY_KEY,
                           {'status': observed['status'], 'detached': sorted(finished), 'preserved_originals': True})
    return observed


def _inspect_and_record(ledger):
    with FileLock(str(w.DATA/'better-notes-boundary.lock'), timeout=3):
        result = inspect_records()
        return result, _observe(ledger, result['records'])


def registered_keys(ledger):
    """None means there is no current native evidence for a new comparison."""
    try:
        result, _ = _inspect_and_record(ledger)
    except (requests.RequestException, ValueError, OSError, Timeout):
        return None
    return {row['key'] for row in result['records']}


def status():
    ledger = notes.store()
    last = ledger.cursor(BOUNDARY_KEY, {})
    def saved():
        history = notes.entries()['records']
        return {'history': [{'id': r['id'], 'title': r['title'], 'status': r['status']} for r in history], 'last': last}
    try:
        result, last = _inspect_and_record(ledger)
        message='本工作区旧双向同步已解除，Markdown 主稿与 Zotero 历史各自保留。' if last.get('status')=='completed' else '原生笔记连接已启用；比较并保留两端原稿后，可取消本工作区的旧双向同步。'
        if last.get('status') == 'detach_pending':
            message = '上一次取消同步仍有注册待核验。两端原稿已保留，可以继续核对。'
        return {**saved(),'status':'ready','records':result['records'],'connector_version':result.get('version','1.0.0'),'message':message}
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code==404:return {**saved(),'status':'restart_required','records':[],'message':'原生连接尚未加载，可正常重开 Zotero 或在插件管理器安装下方连接包。已有历史与最近的边界核验记录保留。'}
        return {**saved(),'status':'unavailable','records':[],'message':'Zotero 原生连接暂不可用；旧稿与最近的边界核验记录继续保留。'}
    except (requests.RequestException,ValueError,OSError,Timeout):
        return {**saved(),'status':'unavailable','records':[],'message':'请打开 Zotero 并保持已有本机收录授权；保存的历史稿仍可查看。'}


def detach():
    knowledge = __import__('knowledge')
    with knowledge.editing(), FileLock(str(w.DATA/'better-notes-boundary.lock'), timeout=60):
        ledger = notes.store()
        before = {row['key']: row for row in inspect_records()['records']}
        previous = _observe(ledger, list(before.values()))
        items = w.zotero_items() if before else []
        pairs = notes.compare(items, locked=True, native_keys=set(before))['records']
        selected = []
        for pair in pairs:
            current=before.get(pair['native_key'])
            if not current:continue
            native_item = next((item for item in items if item['key'] == pair['native_key']), None)
            if not native_item:
                continue
            path=knowledge.path_for(pair['local_path']);original=path.read_text('utf-8-sig')
            native_original = native_item.get('note') or ''
            if (w.digest(original) != pair['local_sha'] or w.digest(native_original) != pair['native_sha']
                    or current.get('note_sha256') != pair['native_sha']):
                raise ValueError('原稿已变化，未取消同步；请重新比较')
            selected.append(current)
        pending = {row['key']: row for row in previous.get('pending_detach', [])}
        pending.update((row['key'], row) for row in selected)
        if selected:
            intent = {**previous, 'status': 'detach_pending', 'pending_detach': list(pending.values()),
                      'detached': previous.get('detached', []) if previous.get('pending_detach') else [],
                      'checked': w.now(), 'preserved_originals': True}
            ledger.commit_page(BOUNDARY_KEY, [], intent)
            try:
                for start in range(0, len(selected), 50):
                    native('detach', selected[start:start+50])
            except requests.RequestException:
                # Zotero may have applied the request before the connection failed.
                # Only an independent inspection can complete the saved intent.
                pass
        elif not pending and previous.get('status') is None:
            ledger.commit_page(BOUNDARY_KEY, [], {**previous, 'status': 'completed', 'detached': [],
                                                 'preserved_originals': True, 'checked': w.now()})
        try:
            receipt = _observe(ledger, inspect_records()['records'])
        except (requests.RequestException, ValueError, OSError) as error:
            raise ValueError('无法核验原生注册。已保留原稿，恢复连接后可继续核对。') from error
        if receipt.get('status') != 'completed':
            raise ValueError('部分原生注册尚未移除；保留原稿，重试会先核查当前状态')
        return receipt
