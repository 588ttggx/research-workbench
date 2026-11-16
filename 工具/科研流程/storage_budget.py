"""Explicit growth budgets and lossless cold-search archival.

Research originals, manual states, databases, environments and model weights are
never deleted here. Cold search responses can be compressed in their original
run directory, with verified hashes and transparent reading; full budgets stop
new disposable output instead of deleting user history.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import zipfile

from storage_inventory import checked_path, is_link, DEFAULT_ROOT

MIB = 1024 ** 2
LIMITS = {'native_logs': 400 * MIB, 'archives': 512 * MIB,
          'search_active': 256 * MIB, 'search_archives': 512 * MIB}
RUN_ID = re.compile(r'\d{8}T\d{6}-[a-f0-9]{8}')
SEARCH_ARTIFACT_SUFFIXES = {'.json', '.jsonl', '.bib', '.txt', '.csv'}


class StorageBudgetExceeded(ValueError):
    pass


def files_under(root, path):
    """Reject links rather than accidentally treating linked data as disposable."""
    path = checked_path(root, path)
    if not path.exists():
        return []
    found, pending = [], [path]
    while pending:
        folder = pending.pop()
        for entry in os.scandir(folder):
            item = checked_path(root, entry.path)
            if is_link(item) or item.stat().st_nlink > 1:
                raise ValueError('容量维护范围含目录链接或硬链接，原资料保留。')
            if entry.is_dir(follow_symlinks=False):
                pending.append(item)
            elif entry.is_file(follow_symlinks=False):
                found.append(item)
    return found


def budget_report(root=DEFAULT_ROOT):
    root = checked_path(root, '.')
    groups = {key: [] for key in LIMITS}
    groups['native_logs'] = [p for p in files_under(root, '工具/日志')
                             if re.fullmatch(r'[a-z][a-z0-9-]*\.(?:stdout|stderr)\.log(?:\.[1-4])?', p.name)]
    groups['archives'] = (files_under(root, '工具/科研流程/数据/归档')
                          + files_under(root, '工具/科研流程/数据/任务历史'))
    protected_files = []
    search_root = root / 'output/文献检索'
    for path in files_under(root, search_root):
        if not RUN_ID.fullmatch(path.relative_to(search_root).parts[0]):
            protected_files.append(path)
            continue
        key = 'search_archives' if path.name in {'search-history.zip', 'archive-manifest.json'} else 'search_active'
        groups[key].append(path)
    result = {}
    for key, paths in groups.items():
        size = sum(path.stat().st_size for path in paths)
        result[key] = {'bytes': size, 'files': len(paths), 'limit_bytes': LIMITS[key], 'over_budget': size > LIMITS[key]}
    result['protected_search_materials'] = {'bytes': sum(path.stat().st_size for path in protected_files),
                                           'files': len(protected_files), 'auto_cleanup_allowed': False}
    return result


def require_capacity(root, group, *, reserve_bytes=0):
    if group not in LIMITS or type(reserve_bytes) is not int or reserve_bytes < 0:
        raise ValueError('容量预算类别或预留字节无效。')
    item = budget_report(root)[group]
    if item['bytes'] + reserve_bytes > item['limit_bytes']:
        raise StorageBudgetExceeded('维护产物已达到容量预算；旧资料已保留，请先核查归档空间后再生成新产物。')
    return item


def _sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_search_artifact(run, name):
    run = Path(run).absolute()
    relative = PurePosixPath(name)
    if relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name:
        raise ValueError('检索产物路径无效。')
    path = checked_path(run, name)
    if path.is_file():
        return path.read_bytes()
    archive_path = checked_path(run, 'search-history.zip')
    try:
        with zipfile.ZipFile(archive_path) as archive:
            if archive.getinfo('archive-manifest.json').file_size > MIB:
                raise ValueError('检索归档清单过大，未读取。')
            manifest = json.loads(archive.read('archive-manifest.json'))
            entry = manifest['files'][name]
            if (type(entry['bytes']) is not int or not 0 <= entry['bytes'] <= LIMITS['search_active']
                    or archive.getinfo(name).file_size != entry['bytes']):
                raise ValueError('检索归档产物长度不符。')
            raw = archive.read(name)
            if hashlib.sha256(raw).hexdigest() != entry['sha256']:
                raise ValueError('检索归档校验失败。')
            return raw
    except (OSError, KeyError, zipfile.BadZipFile, json.JSONDecodeError) as error:
        raise ValueError('检索归档不可读取或不完整，未使用损坏内容。') from error


def protected_search_runs(store, rules=()):
    """Manual screening and subscribed searches keep their original loose files."""
    with store.connection() as database:
        rows = database.execute("SELECT key,value FROM cursors WHERE key LIKE 'scholarly:screen:%'").fetchall()
    return ({row['key'].removeprefix('scholarly:screen:') for row in rows if json.loads(row['value'])}
            | {rule['origin_search'] for rule in rules if rule.get('origin_search')})


def prepare_search(root, store, *, rules=()):
    """Run under the existing search lock before any network request or new run."""
    protected = protected_search_runs(store, rules)
    source_paths = [Path(root) / '科研知识库/文献/library.json']
    project_root = Path(root) / '科研知识库/项目'
    if project_root.exists():
        source_paths += [p for p in files_under(root, project_root) if p.suffix.lower() == '.md']
    for path in source_paths:
        checked_path(root, path)
        if path.is_file():
            protected.update(RUN_ID.findall(path.read_text('utf-8-sig')))
    try:
        archived = archive_searches(root, protected=protected)
    except StorageBudgetExceeded:
        archived = {'archived_runs': 0, 'status': 'blocked_budget', 'original_artifacts_preserved': True}
    capacity = require_capacity(root, 'search_active', reserve_bytes=16 * MIB)
    return {'archive': archived, 'capacity': capacity}


def archive_searches(root=DEFAULT_ROOT, *, protected, keep_recent=30, days=90, now_at=None):
    if type(keep_recent) is not int or keep_recent < 0 or type(days) is not int or days < 7:
        raise ValueError('检索归档至少保留7天，最近检索数不得为负。')
    root = checked_path(root, '.')
    folder = checked_path(root, 'output/文献检索')
    result = {'archived_runs': 0, 'released_logical_bytes': 0, 'protected_runs': 0, 'archives': []}
    if not folder.exists():
        return result
    moment = datetime.fromisoformat(now_at) if now_at else datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError('检索归档时间必须包含时区。')
    cutoff = moment - timedelta(days=days)
    paths = sorted((p for p in folder.iterdir() if RUN_ID.fullmatch(p.name)), reverse=True)
    for index, run in enumerate(paths):
        checked_path(root, run)
        if (index < keep_recent or run.name in protected or (run / 'search-history.zip').exists()
                or not (run / 'papers/index.json').is_file()):
            result['protected_runs'] += 1
            continue
        receipt = checked_path(root, run / 'search-log.json')
        try:
            metadata = json.loads(receipt.read_text('utf-8-sig'))
            generated = datetime.fromisoformat(metadata['generated_at'])
            plan = metadata.get('plan') or {}
            if generated.tzinfo is None or generated > cutoff or plan.get('project') not in (None, '', '共享'):
                continue
        except (OSError, ValueError, KeyError):
            continue
        files = files_under(root, run)
        if any(path.suffix.lower() not in SEARCH_ARTIFACT_SUFFIXES for path in files):
            result['protected_runs'] += 1
            continue
        before = sum(path.stat().st_size for path in files)
        require_capacity(root, 'search_archives', reserve_bytes=before)
        manifest = {'run_id': run.name, 'created': moment.isoformat(), 'files': {
            path.relative_to(run).as_posix(): {'bytes': path.stat().st_size, 'sha256': _sha(path)} for path in files}}
        destination = checked_path(root, run / 'search-history.zip')
        descriptor, temporary_name = tempfile.mkstemp(prefix='search-history-', suffix='.tmp', dir=run)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, 'w+b') as stream:
                with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
                    for path in files:
                        archive.write(path, path.relative_to(run).as_posix())
                    archive.writestr('archive-manifest.json', json.dumps(manifest, ensure_ascii=False))
                stream.seek(0)
                with zipfile.ZipFile(stream) as archive:
                    for name, entry in manifest['files'].items():
                        with archive.open(name) as source:
                            if hashlib.file_digest(source, 'sha256').hexdigest() != entry['sha256']:
                                raise ValueError('检索压缩归档校验失败，原文件保留。')
            # Recheck every input before publishing or removing a loose artifact.
            if any(_sha(path) != manifest['files'][path.relative_to(run).as_posix()]['sha256'] for path in files):
                raise ValueError('检索产物在归档期间变化，原文件保留。')
            os.replace(temporary, destination)
            manifest_path = checked_path(root, run / 'archive-manifest.json')
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
            removed = 0
            for path in files:
                checked_path(root, path)
                if _sha(path) == manifest['files'][path.relative_to(run).as_posix()]['sha256']:
                    removed += path.stat().st_size
                    path.unlink()
            result['archived_runs'] += 1
            result['released_logical_bytes'] += removed - destination.stat().st_size - manifest_path.stat().st_size
            result['archives'].append({'path': destination.relative_to(root).as_posix(), 'sha256': _sha(destination),
                                       'files': len(files), 'original_bytes': before, 'archive_bytes': destination.stat().st_size})
        finally:
            if temporary.exists():
                checked_path(root, temporary).unlink()
    return result
