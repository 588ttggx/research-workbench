"""Bound plain technical JSONL logs only; never use for research/audit databases.

Five files includes the current file and four archives, each at most 5 MiB.
The lock serializes threads in this process; this is not a multiprocess logger.
Existing oversized files require explicit migration rather than silent trimming.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import subprocess
import threading

DEFAULT_LOG_ROOT = Path(__file__).resolve().parent.parent / '日志'
_LOCK = threading.RLock()


def _rotate(path, archives):
    if archives:
        archives[-1].unlink(missing_ok=True)
        for source, target in zip(reversed(archives[:-1]), reversed(archives[1:])):
            if source.exists():
                source.replace(target)
        path.replace(archives[0])
    else:
        path.unlink()


def append_bytes(path, data, *, log_root=DEFAULT_LOG_ROOT, max_bytes=5 * 1024 * 1024, max_files=5):
    """Bound native stdout/stderr even when a child emits an enormous line."""
    if type(max_bytes) is not int or max_bytes < 32 or type(max_files) is not int or not 1 <= max_files <= 20:
        raise ValueError('Invalid native log byte/file limits.')
    if not isinstance(data, bytes):
        raise ValueError('Native log chunks must be bytes.')
    path = Path(path)
    if not path.is_absolute():
        path = Path(log_root) / path
    if path.suffix.lower() != '.log':
        raise ValueError('Only plain .log native output is supported.')
    with _LOCK:
        path = _check_path(log_root, path)
        archives = [_check_path(log_root, path.with_name(path.name + '.' + str(index)))
                    for index in range(1, max_files)]
        for existing in (path, *archives):
            if existing.exists() and (not existing.is_file() or existing.stat().st_size > max_bytes):
                raise ValueError('Legacy native log needs explicit migration before bounded capture.')
        path.parent.mkdir(parents=True, exist_ok=True)
        offset = 0
        while offset < len(data):
            size = path.stat().st_size if path.exists() else 0
            if size == max_bytes:
                _rotate(path, archives)
                size = 0
            end = min(len(data), offset + max_bytes - size)
            with path.open('ab') as target:
                target.write(data[offset:end])
            offset = end


def _stop_child(child):
    """Stop the owned process tree, including Windows venv launcher children."""
    if child.poll() is not None:
        return
    if os.name == 'nt':
        taskkill = Path(os.environ['SystemRoot']) / 'System32/taskkill.exe'
        subprocess.run([str(taskkill), '/PID', str(child.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=10)
    else:
        child.terminate()
    child.wait(timeout=5)


def relay_process(config, receipt, *, log_root=DEFAULT_LOG_ROOT, max_bytes=5 * 1024 * 1024, max_files=5):
    """Capture a managed native process; the receipt identifies the actual child.

    No shell or command strings are evaluated. Environment and output never enter
    the process receipt. The service manager owns the child, and the relay exits
    after that child stops; this helper does not create another listening server.
    """
    name = config.get('name', '')
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,40}', name):
        raise ValueError('Invalid managed service name.')
    executable = Path(config.get('executable', ''))
    working_directory = Path(config.get('working_directory', ''))
    arguments = config.get('arguments', [])
    if (not executable.is_absolute() or not executable.is_file() or not working_directory.is_absolute()
            or not working_directory.is_dir() or not isinstance(arguments, list)
            or not all(isinstance(value, str) for value in arguments)):
        raise ValueError('Managed process requires an existing executable/directory and argument list.')
    receipt = _check_path(log_root, receipt)
    if receipt.suffix != '.json':
        raise ValueError('Managed process receipt must be JSON.')
    paths = [Path(log_root) / (name + '.' + stream + '.log') for stream in ('stdout', 'stderr')]
    for path in paths:
        append_bytes(path, b'', log_root=log_root, max_bytes=max_bytes, max_files=max_files)
    child = subprocess.Popen([str(executable), *arguments], cwd=working_directory, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    state = {'name': name, 'nonce': config.get('nonce'), 'relay_pid': os.getpid(),
             'child_pid': child.pid, 'status': 'running'}

    def save():
        temporary = _check_path(log_root, receipt.with_name(receipt.name + '.tmp'))
        temporary.write_text(json.dumps(state), encoding='utf-8')
        temporary.replace(receipt)

    failures = []

    def drain(stream, path):
        try:
            while chunk := stream.read1(16384):
                append_bytes(path, chunk, log_root=log_root, max_bytes=max_bytes, max_files=max_files)
        except Exception as error:
            failures.append(type(error).__name__)
            # A broken capture must not leave an unbounded, unregistered child.
            _stop_child(child)
        finally:
            stream.close()

    try:
        save()
        readers = [threading.Thread(target=drain, args=(stream, path), daemon=True)
                   for stream, path in zip((child.stdout, child.stderr), paths)]
        for reader in readers:
            reader.start()
        code = child.wait()
        for reader in readers:
            reader.join(timeout=3)
        state.update(status='capture_failed' if failures else 'exited', exit_code=code)
        if failures:
            state['error_types'] = failures
        save()
        return 1 if failures else code
    finally:
        _stop_child(child)


def _check_path(root, path):
    root = Path(root).absolute()
    path = Path(os.path.abspath(path))
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        raise ValueError('Technical logs must stay inside the configured log directory.') from None
    for current in (*root.parents, root, *(root.joinpath(*parts[:index]) for index in range(1, len(parts) + 1))):
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError('Technical log paths and archives cannot be links.')
        if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
            raise ValueError('Technical logs cannot overwrite hard-linked files.')
    return path


def append_jsonl(path, record, *, log_root=DEFAULT_LOG_ROOT, max_bytes=5 * 1024 * 1024, max_files=5):
    """Append one UTF-8 JSON line, rotating whole files under a process-wide lock.

    max_files includes the current file. Invalid/oversized records and unsafe
    paths fail before mutation. Only this logger's numbered archives are pruned.
    """
    if type(max_bytes) is not int or max_bytes < 32 or type(max_files) is not int or not 1 <= max_files <= 20:
        raise ValueError('max_bytes must be >=32 and max_files must be 1–20.')
    if not isinstance(record, dict):
        raise ValueError('Technical log records must be JSON objects.')
    line = (json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
    if len(line) > max_bytes:
        raise ValueError('A single technical log record exceeds the file size limit.')
    path = Path(path)
    if not path.is_absolute():
        path = Path(log_root) / path
    if path.suffix.lower() != '.jsonl':
        raise ValueError('Only plain .jsonl technical logs are supported.')
    with _LOCK:
        path = _check_path(log_root, path)
        archives = [_check_path(log_root, path.with_name(path.name + '.' + str(index)))
                    for index in range(1, max_files)]
        for existing in (path, *archives):
            if existing.exists() and (not existing.is_file() or existing.stat().st_size > max_bytes):
                raise ValueError('Existing log exceeds the bound or is not a regular file; explicit migration is required.')
        if path.exists() and path.stat().st_size:
            with path.open('rb') as current:
                current.seek(-1, os.SEEK_END)
                if current.read(1) != b'\n':
                    raise ValueError('Existing log has an incomplete final line; explicit recovery is required.')
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size + len(line) > max_bytes:
            _rotate(path, archives)
        with path.open('ab') as target:
            target.write(line)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Bound stdout/stderr for a managed native process.')
    parser.add_argument('--relay-config', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--log-root', type=Path, default=DEFAULT_LOG_ROOT)
    args = parser.parse_args()
    configuration = _check_path(args.log_root, args.relay_config)
    raise SystemExit(relay_process(json.loads(configuration.read_text('utf-8-sig')), args.receipt, log_root=args.log_root))
