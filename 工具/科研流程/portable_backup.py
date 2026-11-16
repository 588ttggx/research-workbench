"""Move a completed workspace backup to another Windows installation."""
import argparse
from getpass import GetPassWarning, getpass
import json
import ntpath
import os
from pathlib import Path, PureWindowsPath
import shutil
import stat
import sys
import tempfile
import warnings
import zipfile
from win32com.shell import shell, shellcon

import backup_crypto


MANIFEST = '备份清单.json'
LIBRARY = '科研知识库/文献/library.json'
ORIGINAL_LIBRARY = '迁移记录/原文献登记.json'
MISSING_ORIGINALS = '迁移记录/缺失原文'
SURREAL_EXPORT = '数据库/open-notebook.surql'
SURREAL_IMPORT = '迁移记录/open-notebook.restore.surql'


def _path(value, *, new=False):
    path = Path(os.path.abspath(value))
    if not path.name or ntpath.isreserved(path.name):
        raise ValueError('备份或恢复目标的文件名无效')
    _check_directory(path.parent)
    if new:
        if os.path.lexists(path):
            raise ValueError('目标已存在，请选择一个尚不存在的新路径')
    else:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or _is_reparse_point(metadata):
            raise ValueError('备份必须是普通文件')
    return path.parent.resolve(strict=True) / path.name


def _is_reparse_point(metadata):
    return bool(getattr(metadata, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _check_directory(path):
    for directory in (*reversed(path.parents), path):
        metadata = directory.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or _is_reparse_point(metadata):
            raise ValueError('备份与恢复路径必须使用普通目录')


def _private_temp():
    # The Windows account's own local Temp, independent of the chosen output
    # disk and of caller-provided TMP/TEMP environment variables.
    root = Path(shell.SHGetFolderPath(0, shellcon.CSIDL_LOCAL_APPDATA, None, 0)) / 'Temp'
    _check_directory(root)
    return root.resolve(strict=True)


def _validated_members(archive):
    """Reject Windows aliases, links and file/directory collisions before extracting."""
    from maintenance import verify_file_manifest

    files = set()
    directories = {}
    for entry in archive.infolist():
        parts = entry.filename.split('/')
        kind = stat.S_IFMT(entry.external_attr >> 16)
        if (entry.orig_filename != entry.filename or entry.is_dir() or kind not in (0, stat.S_IFREG)
                or entry.external_attr & stat.FILE_ATTRIBUTE_REPARSE_POINT
                or any(not part or part in ('.', '..') or '\\' in part or ntpath.isreserved(part) for part in parts)):
            raise ValueError('备份包含不安全的文件路径或特殊文件')
        name = entry.filename.casefold()
        if name in files or name in directories:
            raise ValueError('备份文件路径重复或冲突')
        files.add(name)
        for depth in range(1, len(parts)):
            directory = '/'.join(parts[:depth])
            key = directory.casefold()
            if key in files or directories.setdefault(key, directory) != directory:
                raise ValueError('备份目录路径冲突')

    if MANIFEST not in archive.namelist() or LIBRARY not in archive.namelist():
        raise ValueError('备份缺少清单或文献登记')
    manifest = json.loads(archive.read(MANIFEST))
    if manifest.get('schema') != 3:
        raise ValueError('迁移只支持有逐文件校验的第 3 版清单，请先生成新备份')
    if not isinstance(manifest.get('files'), dict):
        raise ValueError('备份缺少逐文件清单')
    return verify_file_manifest(archive, manifest)


def export(source, destination, passphrase):
    """Verify a completed local backup and publish a new portable copy."""
    if not isinstance(passphrase, str):
        raise ValueError('请提供迁移口令')
    source = _path(source)
    destination = _path(destination, new=True)
    if not source.name.endswith('.zip.dpapi') or destination.suffix != '.research-backup':
        raise ValueError('输入须为 .zip.dpapi 本机备份，输出须为 .research-backup 迁移包')
    with (tempfile.TemporaryDirectory(prefix='portable-export-', dir=destination.parent) as publish,
          tempfile.TemporaryDirectory(prefix='portable-private-', dir=_private_temp()) as temporary):
        work = Path(temporary)
        prepared = Path(publish) / 'migration.research-backup'
        with backup_crypto.opened(source, work) as raw:
            with zipfile.ZipFile(raw) as archive:
                count = _validated_members(archive)
            expected = backup_crypto.file_digest(raw)
            backup_crypto.protect(raw, prepared, passphrase=passphrase)
        with backup_crypto.opened(prepared, work, passphrase=passphrase) as verified:
            if backup_crypto.file_digest(verified) != expected:
                raise ValueError('迁移包复验未通过')
        # Windows rename fails if another process has already created the destination.
        prepared.rename(_path(destination, new=True))
    return {'status': 'exported', 'archive': str(destination), 'verified_files': count}


def _relink(archive, staging, destination):
    original = archive.read(LIBRARY)
    library = json.loads(original)
    names = set(archive.namelist())
    if (staging / MISSING_ORIGINALS).exists():
        raise ValueError('备份包含预留的缺失原文路径')
    restored = missing = 0
    for record in library['records']:
        for index, artifact in enumerate(record.get('artifacts', [])):
            file = PureWindowsPath(artifact['path']).name
            member = f'原文/{record["id"]}/{index}-{file}'
            if member in names:
                artifact['path'] = str(destination / member)
                restored += 1
            else:
                missing += 1
                # The source path can exist on the new machine but point to
                # a completely different file. Keep it only in the original log.
                artifact['path'] = str(destination / MISSING_ORIGINALS / f'{missing}.unavailable')
    saved = staging / ORIGINAL_LIBRARY
    saved.parent.mkdir(exist_ok=True)
    with saved.open('xb') as output:
        output.write(original)
    (staging / LIBRARY).write_text(json.dumps(library, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'relinked_artifacts': restored, 'missing_artifacts': missing}


def _prepare_surreal_import(staging):
    source = staging / SURREAL_EXPORT
    if not source.is_file():
        return False
    from maintenance import restore_surreal_schema

    compatible, _ = restore_surreal_schema(source.read_bytes())
    with (staging / SURREAL_IMPORT).open('xb') as output:
        output.write(compatible)
    return True


def _extract_verified(archive, destination):
    count = _validated_members(archive)
    if sum(entry.file_size for entry in archive.infolist()) > shutil.disk_usage(destination.parent).free:
        raise ValueError('恢复目录所在磁盘的空闲空间不足')
    with tempfile.TemporaryDirectory(prefix='portable-restore-', dir=destination.parent) as temporary:
        staging = Path(temporary) / 'restore'
        staging.mkdir()
        for entry in archive.infolist():
            target = staging / entry.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.parent.resolve() != target.parent:
                raise ValueError('备份包含目录别名')
            with archive.open(entry) as input_stream, target.open('xb') as output:
                shutil.copyfileobj(input_stream, output, backup_crypto.CHUNK)
        links = _relink(archive, staging, destination)
        prepared_import = _prepare_surreal_import(staging)
        staging.rename(_path(destination, new=True))
    return {'status': 'restored_data', 'directory': str(destination), 'verified_files': count,
            'open_notebook_import_prepared': prepared_import, **links}


def restore(source, destination, passphrase):
    """Extract verified data into a new recovery directory without starting services."""
    if not isinstance(passphrase, str):
        raise ValueError('请提供迁移口令')
    source = _path(source)
    destination = _path(destination, new=True)
    if source.suffix != '.research-backup':
        raise ValueError('输入须为 .research-backup 迁移包')
    with tempfile.TemporaryDirectory(prefix='portable-private-', dir=_private_temp()) as temporary:
        with backup_crypto.opened(source, temporary, passphrase=passphrase) as raw, zipfile.ZipFile(raw) as archive:
            return _extract_verified(archive, destination)


def cli(argv):
    parser = argparse.ArgumentParser(description='导出或恢复基于口令的跨电脑迁移备份')
    parser.add_argument('action', choices=('portable-export', 'portable-restore'))
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args(argv)
    if not sys.stdin.isatty():
        parser.exit(1, '请在支持隐藏输入口令的终端中运行。\n')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', GetPassWarning)
            passphrase = getpass('迁移口令：')
            if args.action == 'portable-export':
                if passphrase != getpass('再输入一次迁移口令：'):
                    raise ValueError('两次口令不一致')
                return export(args.source, args.destination, passphrase)
        return restore(args.source, args.destination, passphrase)
    except (GetPassWarning, EOFError):
        parser.exit(1, '请在支持隐藏输入口令的终端中运行。\n')
    except ValueError as error:
        parser.exit(1, f'{error}\n')
    except (OSError, zipfile.BadZipFile, backup_crypto.win32crypt.error):
        parser.exit(1, '无法读取、解密或写入备份，请检查备份来源、权限和磁盘空间。\n')
