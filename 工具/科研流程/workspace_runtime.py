"""Dependency-free paths, UTC timestamps, hashing and atomic local file writes.

New modules use this foundation instead of importing the synchronization engine.
An already loaded workflow module may override the legacy path attributes; this
keeps existing embedding and isolated test callers compatible without importing it.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[1]
_DEFAULTS = {
    'HERE': _HERE, 'ROOT': _ROOT, 'DATA': _HERE/'数据',
    'KB': _ROOT/'科研知识库', 'LIBRARY': _ROOT/'科研知识库/文献/library.json',
    'STATE': _HERE/'数据/state.json', 'API': 'http://127.0.0.1:5055/api',
    'ZOTERO': 'http://127.0.0.1:23119/api/users/0',
}


def __getattr__(name):
    if name not in _DEFAULTS:
        raise AttributeError(name)
    legacy = sys.modules.get('workflow')
    return vars(legacy).get(name, _DEFAULTS[name]) if legacy else _DEFAULTS[name]


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode('utf-8')).hexdigest()


def read_json(path, default=None):
    return json.loads(path.read_text('utf-8-sig')) if path.exists() else default


def atomic_text(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=path.name+'.', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='') as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(5):
            try:
                temporary.replace(path)
                break
            except PermissionError as error:
                if attempt == 4 or getattr(error, 'winerror', None) not in (5, 32, 33):
                    raise
                time.sleep(.05*(2**attempt))
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2))
