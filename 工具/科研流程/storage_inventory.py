"""Read-only logical-size inventory; never follows links or proposes automatic deletion.

Run with no arguments for JSON on stdout. --sqlite PATH adds bounded, read-only
aggregate counts; --output PATH explicitly creates a new JSON file inside root.
Sizes are logical bytes, not allocated disk space or a reclaimable-space promise.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta, timezone
import heapq
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import time

DEFAULT_ROOT = Path(__file__).resolve().parents[2]


def allocated_bytes(path):
    """Actual filesystem allocation, including transparent NTFS compression."""
    path = Path(path)
    if os.name != 'nt':
        return path.stat().st_blocks * 512
    import ctypes
    from ctypes import wintypes
    native = ctypes.WinDLL('kernel32', use_last_error=True).GetCompressedFileSizeW
    native.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    native.restype = wintypes.DWORD
    high = wintypes.DWORD()
    ctypes.set_last_error(0)
    low = native(str(path.absolute()), ctypes.byref(high))
    if low == 0xffffffff and ctypes.get_last_error():
        raise ctypes.WinError(ctypes.get_last_error())
    return high.value * 2**32 + low


def compress_history_snapshot(path, *, root=DEFAULT_ROOT):
    """Explicit, reversible NTFS compression; original path and bytes survive.

    Only old frozen test/rollback snapshots below the existing historical output
    area qualify. Active databases, WAL/SHM files and linked files are rejected.
    This is never called by ordinary inventory or background maintenance.
    """
    path = checked_path(root, path)
    allowed = Path(root).absolute() / 'output/科研工作区重构/_临时'
    if (not path.is_relative_to(allowed) or not path.is_file()
            or path.suffix.lower() not in {'.sqlite', '.sqlite3', '.db'} or path.stat().st_nlink > 1):
        raise ValueError('只可显式压缩历史验收目录内的普通冻结快照，原文件未改。')
    if time.time() - path.stat().st_mtime < 86400 or any(path.with_name(path.name + end).exists() for end in ('-wal', '-shm', '-journal')):
        raise ValueError('快照过新或存在事务文件，不能按冻结历史处理。')
    with path.open('rb') as stream:
        if stream.read(16) != b'SQLite format 3\x00':
            raise ValueError('不是可识别的 SQLite 历史快照。')
        stream.seek(0)
        before_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    before = allocated_bytes(path)
    if os.name != 'nt':
        raise ValueError('历史原路径透明压缩仅适用于 Windows NTFS。')
    executable = Path(os.environ['SystemRoot']) / 'System32/compact.exe'
    result = subprocess.run([str(executable), '/C', '/I', '/Q', str(path)], capture_output=True,
                            creationflags=subprocess.CREATE_NO_WINDOW, timeout=120)
    with path.open('rb') as stream:
        after_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    if after_sha != before_sha:
        raise RuntimeError('历史快照压缩后的内容哈希变化，请保留现场核查。')
    after = allocated_bytes(path)
    return {'path': path.relative_to(Path(root).absolute()).as_posix(), 'sha256': before_sha,
            'logical_bytes': path.stat().st_size, 'allocated_before': before, 'allocated_after': after,
            'released_allocated_bytes': before - after, 'exit_code': result.returncode,
            'content_unchanged': True, 'path_unchanged': True}


def is_link(path):
    info = Path(path).lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def checked_path(root, path):
    """Reject escapes and every existing link component, including junctions."""
    root = Path(root).absolute()
    if any(is_link(parent) for parent in (root, *root.parents)) or not root.is_dir():
        raise ValueError('Inventory root must be an existing directory, not a link.')
    path = Path(path)
    path = Path(os.path.abspath(path if path.is_absolute() else root / path))
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        raise ValueError('Path is outside the inventory root.') from None
    current = root
    for part in parts:
        current = current / part
        try:
            if is_link(current):
                raise ValueError('Directory and file links are not traversed.')
        except FileNotFoundError:
            continue
    return path


def category(relative):
    parts = relative.parts
    if any(part in {'.git', '文献', '组内文献'} for part in parts) or relative.suffix.lower() in {'.pdf', '.xml'}:
        return 'research_originals_and_history'
    if any(part in {'_临时', 'tmp', 'output'} for part in parts):
        return 'historical_outputs_review_required'
    if relative.suffix.lower() in {'.sqlite', '.sqlite3', '.db', '.clog'} or '数据' in parts:
        return 'persistent_data_protected'
    if any(part.startswith(('.venv', 'runtime-')) or part in {'node_modules', '模型', 'weights'} for part in parts):
        return 'runtime_dependencies_protected'
    if len(parts) > 1 and parts[:2] == ('工具', '日志'):
        return 'runtime_diagnostics_review_required'
    return 'source_and_materials_review_required'


def inventory(root=DEFAULT_ROOT, *, depth=2, top=20):
    if type(depth) is not int or not 1 <= depth <= 6 or type(top) is not int or not 1 <= top <= 100:
        raise ValueError('depth must be 1–6; top must be 1–100.')
    root = checked_path(root, '.')
    totals = defaultdict(lambda: [0, 0])
    categories = defaultdict(lambda: [0, 0])
    largest, links, errors = [], [], []
    total_bytes = files = 0
    pending = [root]
    while pending:
        folder = pending.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError as exc:
            errors.append({'path': folder.relative_to(root).as_posix(), 'error_type': type(exc).__name__})
            continue
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root)
            try:
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    links.append({'path': relative.as_posix(), 'counted_bytes': 0})
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                size = info.st_size
                total_bytes += size
                files += 1
                group = categories[category(relative)]
                group[0] += size
                group[1] += 1
                for level in range(1, min(len(relative.parts), depth + 1)):
                    group = totals[Path(*relative.parts[:level]).as_posix()]
                    group[0] += size
                    group[1] += 1
                candidate = (size, relative.as_posix())
                if len(largest) < top:
                    heapq.heappush(largest, candidate)
                elif candidate > largest[0]:
                    heapq.heapreplace(largest, candidate)
            except OSError as exc:
                errors.append({'path': relative.as_posix(), 'error_type': type(exc).__name__})
    return {'root': str(root), 'generated_at': datetime.now(timezone.utc).isoformat(),
            'measurement': 'logical_bytes; links excluded; live files may change during scan',
            'total_bytes': total_bytes, 'GB': total_bytes / 10**9, 'GiB': total_bytes / 2**30, 'files': files,
            'directories': [{'path': key, 'bytes': size, 'files': count}
                            for key, (size, count) in sorted(totals.items(), key=lambda row: (-row[1][0], row[0]))],
            'largest_files': [{'path': path, 'bytes': size} for size, path in sorted(largest, reverse=True)],
            'categories': [{'category': key, 'bytes': size, 'files': count, 'auto_cleanup_allowed': False}
                           for key, (size, count) in sorted(categories.items())],
            'links': sorted(links, key=lambda row: row['path']), 'errors': errors}


def sqlite_summary(path, *, root=DEFAULT_ROOT):
    """Use SQLite's read-only URI, preserving committed WAL visibility and writers."""
    path = checked_path(root, path)
    if not path.is_file():
        raise FileNotFoundError(path)
    summary = {'path': path.relative_to(Path(root).absolute()).as_posix(),
               'file_bytes': path.stat().st_size, 'tables': []}
    deadline = time.monotonic() + 3
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=0.5)) as database:
        database.execute('PRAGMA query_only=ON')
        database.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        summary['pages'] = {key: database.execute('PRAGMA ' + key).fetchone()[0]
                            for key in ('page_size', 'page_count', 'freelist_count', 'journal_mode')}
        summary['table_count'] = database.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0]
        summary['tables_limit'] = 40
        summary['counts_partial'] = summary['table_count'] > summary['tables_limit']
        tables = database.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name LIMIT 40").fetchall()
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        for (table,) in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            item = {'table': table}
            try:
                item['rows'] = database.execute('SELECT count(*) FROM ' + quoted).fetchone()[0]
                columns = {row[1] for row in database.execute('PRAGMA table_info(' + quoted + ')')}
                if table in {'jobs', 'audit'} and 'created' in columns:
                    item['last_24h_rows'] = database.execute('SELECT count(*) FROM ' + quoted + ' WHERE created>=?', (cutoff,)).fetchone()[0]
                if table=='jobs' and {'kind','status','result'} <= columns:
                    groups=database.execute("""SELECT kind,status,count(*),
                        coalesce(sum(length(CAST(result AS BLOB))),0) FROM jobs
                        GROUP BY kind,status ORDER BY count(*) DESC,kind,status LIMIT 31""").fetchall()
                    item['groups_partial']=len(groups)>30
                    item['groups']=[{'kind':kind,'status':status,'rows':count,'result_bytes':size}
                                    for kind,status,count,size in groups[:30]]
            except sqlite3.DatabaseError as exc:
                item['error_type'] = type(exc).__name__
                summary['counts_partial'] = True
                summary['tables'].append(item)
                break
            summary['tables'].append(item)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--depth', type=int, default=2)
    parser.add_argument('--top', type=int, default=20)
    parser.add_argument('--sqlite', action='append', default=[], metavar='PATH')
    parser.add_argument('--budgets', action='store_true', help='Include current technical archive/search/log budget usage.')
    parser.add_argument('--output', type=Path, help='Create a new JSON file inside root; never overwrite.')
    args = parser.parse_args(argv)
    try:
        output = checked_path(args.root, args.output) if args.output else None
        if output and (output.suffix.lower() != '.json' or output.exists()):
            raise ValueError('Explicit output must be a new .json file inside root.')
        report = inventory(args.root, depth=args.depth, top=args.top)
        if args.budgets:
            from storage_budget import budget_report
            report['budgets'] = budget_report(args.root)
        report['sqlite'] = []
        for path in args.sqlite:
            report['sqlite'].append(sqlite_summary(path, root=args.root))
        serialized = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
        if output:
            with output.open('x', encoding='utf-8') as target:
                target.write(serialized)
        else:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stdout.write(serialized)
    except (OSError, ValueError, sqlite3.DatabaseError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
