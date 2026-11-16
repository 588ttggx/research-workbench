"""Package selected native tools and model bytes without personal runtime state."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import zipfile

from distribution.build_runtime import (_digest, _file, _safe_url, _stamp, _tree,
                                        _zip, MAX_ARCHIVE_BYTES)
from distribution.publish_source import _real_path
from distribution import prepare_model


COMPONENTS = ('r', 'graphviz', 'powershell', 'ollama', 'qwen4b')
FORMAT = 'workbench-optional-runtime-inventory-v1'
TOOLS = {
    'r': ('工具/R/4.6.1', 'bin/x64/Rscript.exe', '4.6.1', 'GPL-2.0-or-later', 'https://cran.r-project.org/'),
    'graphviz': ('工具/Graphviz/16.1.0', 'Graphviz-16.1.0-win64/bin/dot.exe', '16.1.0', 'EPL-2.0', 'https://gitlab.com/graphviz/graphviz/-/tree/16.1.0'),
    'powershell': ('工具/PowerShell/7.6.9', 'pwsh.exe', '7.6.9', 'MIT and third-party notices', 'https://github.com/PowerShell/PowerShell/releases/tag/v7.6.9'),
    'ollama': ('工具/模型/Ollama', 'ollama.exe', '0.40.0', 'MIT and bundled runtime licenses', 'https://github.com/ollama/ollama/releases/tag/v0.40.0'),
}


def _license(root, component, overrides):
    source = overrides.get(component) or root/'output/工作台发布与安装/_临时'/(component+'-LICENSE.txt')
    source = _real_path(source)
    if not source.is_file():
        raise FileNotFoundError('Optional runtime license missing: '+component)
    if source.stat().st_nlink != 1:
        raise ValueError('Optional runtime license must not be hardlinked.')
    return source


def _description(path):
    fields, last = {}, None
    for line in path.read_text('utf-8', errors='replace').splitlines():
        if line[:1].isspace() and last:
            fields[last] += ' '+line.strip()
        elif ':' in line:
            key, value = line.split(':', 1)
            fields[key], last = value.strip(), key
    name = fields.get('Package')
    if not name or not fields.get('Version'):
        raise ValueError('R package DESCRIPTION lacks identity.')
    source = next((_safe_url(x) for x in re.split(r'[,\s]+', fields.get('URL', '')) if _safe_url(x)), None)
    if source is None and fields.get('Repository') == 'CRAN':
        source = 'https://cran.r-project.org/package='+name
    return {'name': 'R package '+name, 'version': fields['Version'],
            'license': fields.get('License', 'unknown'), 'source': source}


def _native_plan(root, component, overrides):
    relative, executable, version, license_name, source = TOOLS[component]
    folder = _real_path(root/relative)
    _file(folder/executable, PurePosixPath(relative)/executable)
    entries = _tree(folder, relative)
    packages = [{'name': component, 'version': version, 'license': license_name, 'source': source}]
    if component == 'r':
        _file(folder/'COPYING', PurePosixPath(relative)/'COPYING')
        library = _tree(root/'工具/R/library', '工具/R/library')
        entries += library
        for entry in library:
            if entry.source.name == 'DESCRIPTION' and len(PurePosixPath(entry.destination).parts) == 5:
                packages.append(_description(entry.source))
    elif component == 'powershell':
        for name in ('LICENSE.txt', 'ThirdPartyNotices.txt'):
            _file(folder/name, PurePosixPath(relative)/name)
    else:
        license_file = _license(root, component, overrides)
        target = PurePosixPath(relative)/'DISTRIBUTION-LICENSE.txt'
        entries.append(_file(license_file, target))
    if any(entry.source.stat().st_nlink != 1 for entry in entries):
        raise ValueError('Optional native sources must not contain hardlinked files.')
    return sorted(entries, key=lambda e: e.destination), packages


def _new_zip(output, name, pending):
    final = output/name
    if final.exists():
        raise FileExistsError('Existing optional archive retained: '+name)
    descriptor, filename = tempfile.mkstemp(prefix=name+'-', suffix='.partial', dir=output)
    os.close(descriptor)
    temporary = Path(filename)
    pending.append((temporary, final))
    return temporary, final


def _item(identifier, path, expanded, count, group=None):
    if path.stat().st_size >= MAX_ARCHIVE_BYTES:
        raise ValueError('Optional runtime archive exceeds the Release limit.')
    return {'id': identifier, 'archive': 'runtime-'+identifier+'.zip', 'required': False,
            'extract_to': '.', 'group': group or identifier, 'size_bytes': path.stat().st_size,
            'sha256': _digest(path), 'expanded_size_bytes': expanded, 'file_count': count}


def _model_sources(root):
    source = _real_path(root/prepare_model.MODEL_MANIFEST)
    if not source.is_file() or source.stat().st_nlink != 1:
        raise ValueError('Model source manifest must be an ordinary non-hardlinked file.')
    raw = source.read_bytes()
    manifest = json.loads(raw)
    descriptors = [manifest['config'], *manifest['layers']]
    if not 1 <= len(descriptors) <= 20:
        raise ValueError('Invalid Ollama model source descriptors.')
    seen, sources = set(), []
    for entry in descriptors:
        digest, size = entry.get('digest'), entry.get('size')
        if not isinstance(digest, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
            raise ValueError('Invalid model source digest.')
        if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= 32*1024**3:
            raise ValueError('Invalid model source size.')
        if digest in seen:
            continue
        seen.add(digest)
        blob = _real_path(root/'工具/模型/weights/blobs'/digest.replace(':', '-'))
        stamp = _stamp(blob)
        if blob.stat().st_nlink != 1:
            raise ValueError('Hardlinked model source is not accepted.')
        if stamp[2] != size or _digest(blob) != digest[7:]:
            raise ValueError('Model source size or hash does not match its Ollama manifest.')
        sources.append((blob, digest[7:], size, stamp))
    return source, raw, sources


def _model_archives(root, output, overrides, chunk_bytes, pending, progress):
    license_file = _license(root, 'qwen4b', overrides)
    manifest_path, manifest_raw, sources = _model_sources(root)
    config = {'format': prepare_model.FORMAT, 'model': 'qwen3-embedding:4b',
              'model_manifest': prepare_model.MODEL_MANIFEST,
              'model_manifest_sha256': hashlib.sha256(manifest_raw).hexdigest(), 'blobs': []}
    items, sequence = [], 1
    for source, digest, size, stamp in sources:
        blob = {'sha256': digest, 'size_bytes': size, 'parts': []}
        complete_digest = hashlib.sha256()
        with source.open('rb') as stream:
            for index in range(math.ceil(size/chunk_bytes)):
                identifier = f'qwen4b-part{sequence:03d}'
                part_path = f'runtime/model-parts/{digest}-{index:04d}.part'
                temporary, _ = _new_zip(output, 'runtime-'+identifier+'.zip', pending)
                wanted, count, hasher = min(chunk_bytes, size-index*chunk_bytes), 0, hashlib.sha256()
                if progress:
                    progress({'component': identifier, 'stage': 'compressing', 'size_bytes': wanted})
                with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
                    with archive.open(part_path, 'w', force_zip64=True) as output_stream:
                        while count < wanted:
                            block = stream.read(min(1024*1024, wanted-count))
                            if not block:
                                raise ValueError('Model source ended during chunk creation.')
                            output_stream.write(block)
                            hasher.update(block)
                            complete_digest.update(block)
                            count += len(block)
                blob['parts'].append({'path': part_path, 'size_bytes': count, 'sha256': hasher.hexdigest()})
                items.append(_item(identifier, temporary, count, 1, 'qwen4b'))
                sequence += 1
        _real_path(source)
        if _stamp(source) != stamp or source.stat().st_nlink != 1 or complete_digest.hexdigest() != digest:
            raise ValueError('Model source changed during packaging.')
        config['blobs'].append(blob)
    temporary, _ = _new_zip(output, 'runtime-qwen4b.zip', pending)
    data = json.dumps(config, ensure_ascii=False, indent=2).encode('utf-8')
    source_notice = ('Model: qwen3-embedding:4b\n'
                     'Model card: https://huggingface.co/Qwen/Qwen3-Embedding-4B\n'
                     'Ollama package: https://ollama.com/library/qwen3-embedding:4b\n'
                     'License: Apache-2.0; the original 0.6B model and account configuration are not included.\n')
    with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        archive.writestr(prepare_model.MANIFEST, data)
        archive.writestr(prepare_model.MODEL_MANIFEST, manifest_raw)
        archive.write(license_file, '工具/模型/weights/QWEN4B-LICENSE.txt')
        archive.writestr('工具/模型/weights/QWEN4B-SOURCE.txt', source_notice)
    expanded = len(data)+len(manifest_raw)+license_file.stat().st_size+len(source_notice.encode('utf-8'))
    items.insert(0, _item('qwen4b', temporary, expanded, 4, 'qwen4b'))
    package = {'name': 'Qwen3 Embedding 4B (Ollama)', 'version': 'manifest-sha256:'+config['model_manifest_sha256'],
               'license': 'Apache-2.0', 'source': 'https://huggingface.co/Qwen/Qwen3-Embedding-4B'}
    return items, [package]


def build_optional(root, output, components=('r', 'graphviz', 'powershell'), *,
                   license_overrides=None, chunk_bytes=1024**3, progress=None):
    root, output = _real_path(root), _real_path(output)
    components = tuple(components)
    if not components or len(set(components)) != len(components) or any(c not in COMPONENTS for c in components):
        raise ValueError('Select unique supported optional components.')
    if not output.is_relative_to(root/'output') or output == root/'output':
        raise ValueError('Optional output must remain under project output/.')
    if not isinstance(chunk_bytes, int) or not 0 < chunk_bytes <= prepare_model.CHUNK_LIMIT:
        raise ValueError('Model chunks must be at most 1 GiB.')
    overrides = license_overrides or {}
    if set(overrides)-{'graphviz', 'ollama', 'qwen4b'}:
        raise ValueError('Unknown optional license override.')
    report_path = output/'optional_runtime_inventory.json'
    previous = {'packages': [], 'components': []}
    if report_path.exists():
        previous = json.loads(report_path.read_text('utf-8'))
        if previous.get('format') != FORMAT:
            raise FileExistsError('Existing optional inventory is not owned by this builder.')
    plans, packages = {}, []
    for component in components:
        if (output/('runtime-'+component+'.zip')).exists():
            raise FileExistsError('Existing optional archive retained: '+component)
        if component != 'qwen4b':
            plans[component], found = _native_plan(root, component, overrides)
            packages += found
    destinations = [entry.destination.casefold() for plan in plans.values() for entry in plan]
    if len(destinations) != len(set(destinations)):
        raise ValueError('Optional archive destinations collide.')
    output.mkdir(parents=True, exist_ok=True)
    pending, items = [], []
    try:
        for component, entries in plans.items():
            if progress:
                progress({'component': component, 'stage': 'compressing', 'files': len(entries)})
            temporary, _ = _new_zip(output, 'runtime-'+component+'.zip', pending)
            expanded = _zip(entries, temporary, MAX_ARCHIVE_BYTES)
            items.append(_item(component, temporary, expanded, len(entries)))
        if 'qwen4b' in components:
            added, found = _model_archives(root, output, overrides, chunk_bytes, pending, progress)
            items += added
            packages += found
        for temporary, final in pending:
            if final.exists():
                raise FileExistsError('Optional archive appeared during build: '+final.name)
            temporary.rename(final)
        unique = {json.dumps(p, sort_keys=True): p for p in previous['packages']+packages}
        report = {'format': FORMAT, 'packages': sorted(unique.values(), key=lambda p:p['name']),
                  'components': previous['components']+items, 'native_acceptance': 'not_tested',
                  'notes': ['Native functionality requires separate installation validation.',
                            'OCR WSL, host drivers, Linux distributions and personal accounts are not included.']}
        descriptor, filename = tempfile.mkstemp(prefix='optional-inventory-', suffix='.partial', dir=output)
        os.close(descriptor)
        temporary = Path(filename)
        pending.append((temporary, report_path))
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        temporary.replace(report_path)
        return items
    finally:
        for temporary, _ in pending:
            if temporary.exists():
                temporary.unlink()
