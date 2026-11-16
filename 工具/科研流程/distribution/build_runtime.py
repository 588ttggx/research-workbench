"""Build reviewed, relocatable runtime payloads without copying live state.

Only the caller-selected installed runtimes are read. Environment creation and
entrypoint generation happen at installation time, never in the source tree.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import tomllib
from urllib.parse import urlsplit, urlunsplit
import zipfile

from distribution.publish_source import _real_path, _relative


CORE_COMPONENTS = ('python313', 'python312', 'open-notebook', 'node', 'surreal')
MAX_ARCHIVE_BYTES = 2 * 1024**3
WORKFLOW = PurePosixPath('工具/科研流程')
NOTEBOOK = PurePosixPath('工具/OpenNotebook/open-notebook-1.15.0')
REPORT_FORMAT = 'workbench-runtime-inventory-v1'
SKIP_DIRS = {'.git', '__pycache__', '.pytest_cache'}
SOURCE_DIRS = ('api', 'open_notebook', 'commands', 'prompts')


@dataclass(frozen=True)
class Entry:
    source: Path
    destination: str
    fingerprint: tuple


def _stamp(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('Runtime source contains a link: ' + path.name)
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _skip(name):
    return (name.lower() in SKIP_DIRS or name.lower().startswith('.env')
            or name.lower() == 'direct_url.json'
            or name.endswith(('.pyc', '.pyo', '.dpapi', '.sqlite', '.sqlite3', '.sqlite-wal', '.sqlite-shm'))
            or name.startswith('__editable__') and name.endswith(('.py', '.pth')))


def _tree(source, destination, *, excluded=()):
    """Do not follow links, swallow enumeration failures, or open excluded files."""
    source = _real_path(source)
    if not source.is_dir():
        raise FileNotFoundError('Required runtime directory missing: ' + source.name)
    destination = _relative(str(destination))
    pending = [(source, PurePosixPath())]
    entries = []
    while pending:
        folder, relative = pending.pop()
        _stamp(folder)
        with os.scandir(folder) as children:
            for child in sorted(children, key=lambda item: item.name.casefold()):
                tail = relative / child.name
                if _skip(child.name) or any(tail == x or x in tail.parents for x in excluded):
                    continue
                path = Path(child.path)
                fingerprint = _stamp(path)
                if child.is_dir(follow_symlinks=False):
                    pending.append((path, tail))
                elif child.is_file(follow_symlinks=False):
                    target = _relative(str(destination / tail)).as_posix()
                    entries.append(Entry(path, target, fingerprint))
                else:
                    raise ValueError('Unsupported runtime file type: ' + child.name)
    return entries


def _file(source, destination):
    source = _real_path(source)
    if not source.is_file():
        raise FileNotFoundError('Required runtime file missing: ' + source.name)
    if _skip(source.name):
        raise ValueError('Excluded runtime file requested: ' + source.name)
    return Entry(source, _relative(str(destination)).as_posix(), _stamp(source))


def _venv_config(app, expected):
    config = _real_path(app / '.venv/pyvenv.cfg')
    values = {}
    for line in config.read_text('utf-8-sig').splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            if key.strip() in ('home', 'version_info', 'version'):
                if key.strip() in values:
                    raise ValueError('Duplicate Python environment configuration field.')
                values[key.strip()] = value.strip()
    home = Path(values.get('home', ''))
    version = values.get('version_info', values.get('version', ''))
    if not home.is_absolute() or not re.fullmatch(re.escape(expected) + r'\.\d+', version):
        raise ValueError('Python environment requires an absolute base and the matching version.')
    home = _real_path(home)
    if not (home/'python.exe').is_file() or not (home/'LICENSE.txt').is_file():
        raise ValueError('Python base interpreter or license is missing.')
    return home, version


def _notebook(root):
    registry = root/'工具/工具版本.json'
    relative = NOTEBOOK
    if registry.is_file():
        _real_path(registry)
        registered = json.loads(registry.read_text('utf-8-sig')).get('open_notebook', {}).get('runtime')
        if registered:
            relative = _relative(registered)
            if relative.parts[:2] != ('工具', 'OpenNotebook'):
                raise ValueError('Open Notebook runtime must be inside its registered tool directory.')
    return _real_path(root/relative), relative


def _license_path(root, executable, component, overrides):
    selected = overrides.get(component+'_license')
    if selected:
        return _real_path(selected)
    candidates = (executable.parent/'LICENSE', executable.parent/'LICENSE.txt',
                  root/'output/工作台发布与安装/_临时/许可'/(component+'-LICENSE.txt'))
    for candidate in candidates:
        _real_path(candidate)
        if candidate.is_file():
            return candidate
    raise FileNotFoundError('Required third-party license missing: ' + component)


def _plans(root, components, overrides, versions):
    notebook, notebook_target = _notebook(root)
    plans, packages = {}, []
    for component in components:
        if component in ('python313', 'python312'):
            app, target, expected = ((root/WORKFLOW, WORKFLOW, '3.13') if component=='python313'
                                     else (notebook, notebook_target, '3.12'))
            base, version = _venv_config(app, expected)
            excluded = tuple(PurePosixPath(p) for p in ('Lib/site-packages', 'Scripts', 'Doc', 'share'))
            entries = _tree(base, 'runtime/'+component, excluded=excluded)
            entries += _tree(app/'.venv/Lib/site-packages', target/'.venv/Lib/site-packages')
            packages.append({'name': 'CPython', 'version': version, 'license': 'PSF-2.0',
                             'source': 'https://www.python.org/'})
        elif component == 'open-notebook':
            entries = []
            for directory in SOURCE_DIRS:
                entries += _tree(notebook/directory, notebook_target/directory)
            for optional in ('migrations',):
                if (notebook/optional).exists():
                    entries += _tree(notebook/optional, notebook_target/optional)
            for filename in ('LICENSE', 'pyproject.toml'):
                entries.append(_file(notebook/filename, notebook_target/filename))
            for filename in ('uv.lock', 'run_api.py', 'CONFIGURATION.md'):
                if (notebook/filename).exists():
                    entries.append(_file(notebook/filename, notebook_target/filename))
            frontend = _real_path(overrides.get('notebook_frontend') or notebook/'frontend')
            if not _real_path(frontend/'.next/standalone/server.js').is_file():
                raise FileNotFoundError('Open Notebook standalone server.js is missing.')
            entries += _tree(frontend/'.next/standalone', notebook_target/'frontend',
                             excluded=(PurePosixPath('.next/static'), PurePosixPath('public')))
            entries += _tree(frontend/'.next/static', notebook_target/'frontend/.next/static')
            entries += _tree(frontend/'public', notebook_target/'frontend/public')
            version = tomllib.loads((notebook/'pyproject.toml').read_text('utf-8')).get('project', {}).get('version', 'unknown')
            packages.append({'name': 'Open Notebook', 'version': version, 'license': 'MIT',
                             'source': 'https://github.com/lfnovo/open-notebook'})
        else:
            default = (shutil.which('node.exe') or shutil.which('node')) if component=='node' else root/'工具/OpenNotebook/bin/surreal.exe'
            executable = overrides.get(component) or default
            if not executable:
                raise FileNotFoundError('Runtime executable not found: ' + component)
            executable = _real_path(executable)
            destination = PurePosixPath('runtime/node/node.exe' if component=='node' else '工具/OpenNotebook/bin/surreal.exe')
            license_file = _license_path(root, executable, component, overrides)
            entries = [_file(executable, destination),
                       _file(license_file, destination.parent/(component+'-LICENSE.txt'))]
            packages.append({'name': 'Node.js' if component=='node' else 'SurrealDB',
                             'version': versions.get(component, 'unknown'),
                             'license': 'MIT with third-party notices' if component=='node' else 'See bundled license',
                             'source': 'https://nodejs.org/' if component=='node' else 'https://github.com/surrealdb/surrealdb'})
        if not entries:
            raise ValueError('Runtime component contains no files: ' + component)
        plans[component] = sorted(entries, key=lambda item: item.destination)
    names = set()
    for entries in plans.values():
        for entry in entries:
            key = entry.destination.casefold()
            if key in names:
                raise ValueError('Duplicate runtime destination: ' + entry.destination)
            names.add(key)
    return plans, packages


def _safe_url(value):
    parsed = urlsplit(value.strip())
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))


def _package_inventory(plans, packages):
    warnings = set()
    for entries in plans.values():
        for entry in entries:
            if entry.source.name != 'METADATA' or not entry.source.parent.name.endswith('.dist-info'):
                continue
            metadata = Parser().parsestr(entry.source.read_text('utf-8', errors='replace'))
            name, version = metadata.get('Name'), metadata.get('Version')
            if not name or not version:
                raise ValueError('Dependency METADATA lacks package name or version.')
            license_text = metadata.get('License-Expression') or metadata.get('License') or ''
            if not license_text:
                license_text = '; '.join(x.removeprefix('License :: ') for x in metadata.get_all('Classifier', []) if x.startswith('License :: '))
            project_urls = metadata.get_all('Project-URL', [])
            source_urls = [value.split(',', 1)[-1] for value in project_urls
                           if value.split(',', 1)[0].strip().lower() in ('source', 'source code', 'repository', 'code')]
            candidates = source_urls + [metadata.get('Home-page', '')]
            candidates += [value.split(',', 1)[-1] for value in project_urls]
            source = next((url for value in candidates if (url := _safe_url(value))), None)
            packages.append({'name': name, 'version': version,
                             'license': ' '.join(license_text.split())[:400] or 'unknown', 'source': source})
    unique = {json.dumps(x, sort_keys=True): x for x in packages}
    for item in unique.values():
        if item['version']=='unknown' or item['license']=='unknown':
            warnings.add('Metadata review required: '+item['name'])
        if any(term in item['license'].upper() for term in ('AGPL', 'AFFERO', 'COMMERCIAL', 'BUSINESS', 'SUSTAINABLE')):
            warnings.add('Distribution license review required: '+item['name'])
    return sorted(unique.values(), key=lambda item: (item['name'].lower(), item['version'])), sorted(warnings)


def _digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def _zip(entries, path, limit):
    expanded = 0
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
        for entry in entries:
            _real_path(entry.source)
            if _stamp(entry.source) != entry.fingerprint:
                raise ValueError('Runtime source changed during build: '+entry.destination)
            archive.write(entry.source, entry.destination)
            if _stamp(entry.source) != entry.fingerprint:
                raise ValueError('Runtime source changed during build: '+entry.destination)
            expanded += entry.fingerprint[2]
            if path.stat().st_size >= limit:
                raise ValueError('Runtime archive exceeds the Release asset limit.')
    if path.stat().st_size >= limit:
        raise ValueError('Runtime archive exceeds the Release asset limit.')
    return expanded


def build_runtime(root, output, components=CORE_COMPONENTS, *, source_overrides=None,
                  component_versions=None, max_archive_bytes=MAX_ARCHIVE_BYTES, progress=None,
                  replace_existing=False):
    """Return installer manifest items; the release owner supplies their URLs.

    Source overrides select already-reviewed executable/license files. No network
    access, package execution, environment mutation or live database read occurs.
    """
    root, output = _real_path(root), _real_path(output)
    components = tuple(components)
    if not components or len(set(components)) != len(components) or any(c not in CORE_COMPONENTS for c in components):
        raise ValueError('Select unique supported runtime components.')
    if not output.is_relative_to(root/'output') or output == root/'output':
        raise ValueError('Runtime output must be a task directory below project output/.')
    if not 0 < max_archive_bytes <= MAX_ARCHIVE_BYTES:
        raise ValueError('Invalid runtime archive limit.')
    overrides = source_overrides or {}
    if set(overrides)-{'node', 'surreal', 'node_license', 'surreal_license', 'notebook_frontend'}:
        raise ValueError('Unknown runtime source override.')
    report_path = output/'runtime_inventory.json'
    previous = {'packages': [], 'components': []}
    if report_path.exists():
        previous = json.loads(report_path.read_text('utf-8'))
        if previous.get('format') != REPORT_FORMAT:
            raise FileExistsError('Existing inventory is not owned by this builder.')
    previous_components = {item['id']: item for item in previous['components']}
    replacements = {}
    for component in components:
        archive = output/('runtime-'+component+'.zip')
        if archive.exists():
            if not replace_existing:
                raise FileExistsError('Existing runtime archive retained: '+component)
            _real_path(archive)
            saved = previous_components.get(component)
            if not saved or saved['archive'] != archive.name or _digest(archive) != saved['sha256']:
                raise ValueError('Changed or unowned runtime archive retained: '+component)
            replacements[archive] = _stamp(archive)
    plans, packages = _plans(root, components, overrides, component_versions or {})
    packages, warnings = _package_inventory(plans, previous['packages']+packages)
    output.mkdir(parents=True, exist_ok=True)
    pending, manifest = [], []
    try:
        for component, entries in plans.items():
            if progress:
                progress({'component': component, 'stage': 'compressing', 'files': len(entries)})
            descriptor, filename = tempfile.mkstemp(prefix='runtime-'+component+'-', suffix='.partial', dir=output)
            os.close(descriptor)
            temporary = Path(filename)
            final = output/('runtime-'+component+'.zip')
            pending.append((temporary, final))
            expanded = _zip(entries, temporary, max_archive_bytes)
            manifest.append({'id': component, 'archive': final.name, 'sha256': _digest(temporary),
                             'size_bytes': temporary.stat().st_size, 'required': True, 'extract_to': '.',
                             'expanded_size_bytes': expanded, 'file_count': len(entries)})
        for temporary, final in pending:
            if final in replacements:
                _real_path(final)
                if _stamp(final) != replacements[final]:
                    raise ValueError('Runtime archive changed during replacement: '+final.name)
                temporary.replace(final)
            elif final.exists():
                raise FileExistsError('Runtime archive appeared during build: '+final.name)
            else:
                temporary.rename(final)
        previous_components.update({item['id']: item for item in manifest})
        report = {'format': REPORT_FORMAT, 'packages': packages, 'warnings': warnings,
                  'components': list(previous_components.values())}
        descriptor, filename = tempfile.mkstemp(prefix='runtime-inventory-', suffix='.partial', dir=output)
        os.close(descriptor)
        temporary = Path(filename)
        pending.append((temporary, report_path))
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        temporary.replace(report_path)
        return manifest
    finally:
        for temporary, _ in pending:
            if temporary.exists():
                temporary.unlink()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--components', nargs='+', default=CORE_COMPONENTS, choices=CORE_COMPONENTS)
    parser.add_argument('--node-license', type=Path)
    parser.add_argument('--surreal-license', type=Path)
    args = parser.parse_args()
    overrides = {key: value for key, value in {'node_license': args.node_license, 'surreal_license': args.surreal_license}.items() if value}
    result = build_runtime(args.root, args.output, args.components, source_overrides=overrides,
                           progress=lambda value: print(json.dumps(value), flush=True))
    print(json.dumps(result, ensure_ascii=False, indent=2))
