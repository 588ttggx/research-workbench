"""Assemble only manifest-verified Qwen 4B parts inside a new installation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from distribution.publish_source import _real_path, _relative


MANIFEST = 'runtime/model-parts/qwen3-embedding-4b.json'
MODEL_MANIFEST = '工具/模型/weights/manifests/registry.ollama.ai/library/qwen3-embedding/4b'
FORMAT = 'workbench-qwen4b-parts-v1'
SHA = re.compile(r'[a-f0-9]{64}')
PART = re.compile(r'runtime/model-parts/[a-f0-9]{64}-[0-9]{4}\.part')
CHUNK_LIMIT = 1024**3


def _file(root, relative, *, missing=False):
    path = _real_path(root/_relative(relative))
    if not path.exists():
        if missing:
            return path
        raise FileNotFoundError('Missing model component: '+relative)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('Model files must be regular files without hard links: '+relative)
    return path


def _hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _valid_digest(value):
    return isinstance(value, str) and SHA.fullmatch(value)


def _size(value, maximum):
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value <= maximum


def _plan(root):
    path = _file(root, MANIFEST, missing=True)
    if not path.exists():
        return None
    if path.stat().st_size > 1024*1024:
        raise ValueError('Model manifest is too large.')
    config = json.loads(path.read_text('utf-8'))
    if config.get('format') != FORMAT or config.get('model') != 'qwen3-embedding:4b':
        raise ValueError('Unsupported model parts manifest.')
    if config.get('model_manifest') != MODEL_MANIFEST or not _valid_digest(config.get('model_manifest_sha256')):
        raise ValueError('Invalid Ollama model manifest reference.')
    model_path = _file(root, MODEL_MANIFEST)
    if model_path.stat().st_size > 1024*1024:
        raise ValueError('Ollama model manifest is too large.')
    if _hash(model_path) != config['model_manifest_sha256']:
        raise ValueError('Ollama model manifest hash mismatch.')
    native = json.loads(model_path.read_text('utf-8'))
    expected = {x['digest'].removeprefix('sha256:'): x['size'] for x in [native['config'], *native['layers']]}
    blobs = config.get('blobs')
    if not isinstance(blobs, list) or not 1 <= len(blobs) <= 20:
        raise ValueError('Invalid model blob list.')
    seen_blobs, seen_parts, plans = set(), set(), []
    for blob in blobs:
        sha, size = blob.get('sha256'), blob.get('size_bytes')
        if not _valid_digest(sha) or not _size(size, 32*1024**3) or sha in seen_blobs or expected.get(sha) != size:
            raise ValueError('Invalid model blob identity or size.')
        seen_blobs.add(sha)
        relative = '工具/模型/weights/blobs/sha256-'+sha
        target = _file(root, relative, missing=True)
        reuse = target.exists()
        if reuse and (target.stat().st_size != size or _hash(target) != sha):
            raise ValueError('Existing model blob has a different hash; retained: '+relative)
        parts = blob.get('parts')
        if not isinstance(parts, list) or not 1 <= len(parts) <= 100:
            raise ValueError('Invalid model chunk list.')
        total, checked = 0, []
        for part in parts:
            rel, part_sha, part_size = part.get('path'), part.get('sha256'), part.get('size_bytes')
            if not isinstance(rel, str) or not PART.fullmatch(rel) or not rel.startswith('runtime/model-parts/'+sha+'-'):
                raise ValueError('Invalid model part path.')
            if rel in seen_parts or not _valid_digest(part_sha) or not _size(part_size, CHUNK_LIMIT):
                raise ValueError('Invalid model part identity or size.')
            seen_parts.add(rel)
            source = _file(root, rel, missing=reuse)
            total += part_size
            if source.exists() and (source.stat().st_size != part_size or _hash(source) != part_sha):
                raise ValueError('Model part size or hash mismatch: '+rel)
            checked.append((source, part_sha, part_size, rel))
        if total != size:
            raise ValueError('Model part sizes do not equal the blob size.')
        plans.append((target, sha, size, reuse, checked))
    if seen_blobs != set(expected):
        raise ValueError('Model parts do not cover the complete Ollama manifest.')
    return plans


def prepare_model(workspace_root):
    """Verify every input before writing; preserve existing differing blobs.

    Missing manifests mean the optional component was not selected. Successful
    runs can be repeated after chunks have been removed, using verified blobs.
    """
    root = _real_path(workspace_root)
    plans = _plan(root)
    if plans is None:
        return {'status': 'not_installed', 'model': 'qwen3-embedding:4b'}
    assembled = reused = 0
    for target, expected, size, reuse, parts in plans:
        if reuse:
            reused += 1
            continue
        _real_path(target.parent).mkdir(parents=True, exist_ok=True)
        descriptor, filename = tempfile.mkstemp(prefix='.qwen-', suffix='.partial', dir=target.parent)
        temporary = Path(filename)
        try:
            digest, written = hashlib.sha256(), 0
            with os.fdopen(descriptor, 'wb') as output:
                for _, part_sha, part_size, relative in parts:
                    source = _file(root, relative)
                    part_digest, count = hashlib.sha256(), 0
                    with source.open('rb') as stream:
                        for block in iter(lambda: stream.read(1024*1024), b''):
                            count += len(block)
                            if count > part_size:
                                raise ValueError('Model part size changed during assembly.')
                            output.write(block)
                            digest.update(block)
                            part_digest.update(block)
                    _file(root, relative)
                    if count != part_size or part_digest.hexdigest() != part_sha:
                        raise ValueError('Model part hash changed during assembly.')
                    written += count
                output.flush()
                os.fsync(output.fileno())
            if written != size or digest.hexdigest() != expected:
                raise ValueError('Assembled model hash mismatch.')
            _real_path(target)
            if target.exists():
                raise ValueError('Model destination appeared during assembly; retained.')
            # Windows rename refuses existing destinations. POSIX link provides
            # the same no-replacement publication, then drops our temporary name.
            if os.name == 'nt':
                temporary.rename(target)
            else:
                os.link(temporary, target)
                temporary.unlink()
            assembled += 1
        finally:
            if temporary.exists():
                temporary.unlink()
    removed = 0
    for _, _, _, _, parts in plans:
        for _, sha, size, relative in parts:
            source = _file(root, relative, missing=True)
            if source.exists():
                if source.stat().st_size != size or _hash(source) != sha:
                    raise ValueError('Changed model part was retained during cleanup: '+relative)
                source.unlink()
                removed += 1
    return {'status': 'ready', 'model': 'qwen3-embedding:4b', 'assembled': assembled,
            'reused': reused, 'removed_verified_parts': removed}
