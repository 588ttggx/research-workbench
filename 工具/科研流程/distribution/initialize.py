"""Initialize a released workspace and rebuild path-bound Python entry points."""
from __future__ import annotations
import argparse
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import stat
import subprocess
import sys
import tempfile
import venv

# The installer invokes this file with Python's isolated mode. Add only the
# release's own integration package so optional components use the same code.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from distribution.prepare_model import prepare_model

MARKER = '.research-workbench-release.json'
_ANY_CONTENT = object()


def _check_entry(path: Path, *, writable: bool = False):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if (stat.S_ISLNK(info.st_mode)
            or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)):
        raise ValueError('Installation paths cannot traverse links, including broken links.')
    if writable and stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
        raise ValueError('Installation write targets cannot be hard links.')
    return info


def _safe_path(path: Path, *, writable: bool = False) -> Path:
    path = Path(os.path.abspath(path))
    for current in (*reversed(path.parents), path):
        _check_entry(current, writable=writable)
    return path


def _safe_environment_tree(path: Path):
    _safe_path(path, writable=True)
    def fail(error):
        raise error
    for base, directories, files in os.walk(path, followlinks=False, onerror=fail):
        for name in (*directories, *files):
            _check_entry(Path(base)/name, writable=True)


def contained(root: Path, relative: str, *, writable: bool = False) -> Path:
    parts = PurePosixPath(relative.replace('\\', '/')).parts
    if not parts or any(p in ('.', '..') or ':' in p for p in parts) or relative.startswith(('/', '\\')):
        raise ValueError('Invalid installation-relative path.')
    return _safe_path(root.joinpath(*parts), writable=writable)


def release_root(root: Path) -> Path:
    root = _safe_path(root)
    marker = contained(root, MARKER)
    metadata = json.loads(marker.read_text('utf-8-sig')) if marker.is_file() else {}
    if not isinstance(metadata, dict) or metadata.get('schema_version') != 1 or not metadata.get('release_id'):
        raise ValueError('Select a verified Research Workbench release directory.')
    return root


def write_new(path: Path, text: str) -> bool:
    path = _safe_path(path, writable=True)
    if path.exists() and not path.is_file():
        raise ValueError('An installation file path is occupied by a directory.')
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('x', encoding='utf-8', newline='\n') as stream: stream.write(text)
        return True
    except FileExistsError:
        return False


def _receipt_snapshot(root: Path, release_id: str):
    path = contained(root, 'installation.json', writable=True)
    if not path.exists():
        return path, None
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError('Existing installation receipt is not owned by this release.')
    before = path.read_bytes()
    try:
        value = json.loads(before)
    except ValueError:
        raise ValueError('Existing installation receipt is not owned by this release.') from None
    if (not isinstance(value, dict) or value.get('schema_version') != 1
            or value.get('release_id') != release_id or value.get('status') != 'initialized'
            or not isinstance(value.get('environments'), list) or not isinstance(value.get('created'), list)
            or value.get('existing_files_preserved') is not True):
        raise ValueError('Existing installation receipt is not owned by this release.')
    return path, before


def _atomic_text(path: Path, text: str, *, expected=_ANY_CONTENT):
    path = _safe_path(path, writable=True)
    def unchanged():
        _safe_path(path, writable=True)
        if expected is not _ANY_CONTENT and (path.read_bytes() if path.exists() else None) != expected:
            raise ValueError('Installation receipt changed during initialization; preserving it.')
    unchanged()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix='.'+path.name+'.', suffix='.tmp', dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        unchanged()
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def create_workspace(root: Path) -> dict:
    root = release_root(root)
    template = json.loads(contained(root, '工具/科研流程/distribution/versions.template.json').read_text('utf-8-sig'))
    app = contained(root, template['open_notebook']['runtime'])
    for relative in ('科研知识库/项目', '科研知识库/文献/条目', '科研知识库/知识', '科研知识库/背景',
                     '科研知识库/方向', '科研知识库/笔记', '科研知识库/周报', '科研知识库/主题综述',
                     '工具/科研流程/数据', '工具/日志', '工具/OpenNotebook/data', '工具/n8n/data', 'output'):
        contained(root, relative, writable=True).mkdir(parents=True, exist_ok=True)
    defaults = {
        '科研知识库/文献/library.json': {'schema': 1, 'records': []},
        '工具/科研流程/数据/state.json': {},
        '工具/科研流程/数据/科研管理员.json': {'enabled': False, 'project': '', 'projects': {}},
        '工具/科研流程/数据/流程设置.json': {'values': {
            'daily_time': '08:30', 'sync_enabled': False, 'daily_enabled': False,
            'ai_enabled': False, 'discover_enabled': False, 'acquire_enabled': False,
            'sync_minutes': 1, 'radar_source_limit': 200, 'radar_recent_days': 90,
            'radar_background_days': 90}, 'ready': False, 'message': '首次安装：请在设置中配置并主动启用后台任务。'},
        '工具/工具版本.json': template,
    }
    created = []
    for relative, value in defaults.items():
        if write_new(contained(root, relative, writable=True), json.dumps(value, ensure_ascii=False, indent=2)+'\n'): created.append(relative)
    write_new(contained(root, '科研知识库/README.md', writable=True), '# 我的科研工作区\n\n从工作台创建项目、导入自己的文献，并在连接与设置中配置所需服务。\n')
    write_new(app/'.env', '\n'.join([
        'SURREAL_URL=ws://127.0.0.1:8000/rpc', 'SURREAL_USER=root',
        'SURREAL_PASSWORD='+secrets.token_urlsafe(32),
        'SURREAL_NAMESPACE=open_notebook', 'SURREAL_DATABASE=open_notebook',
        'OPEN_NOTEBOOK_ENCRYPTION_KEY='+secrets.token_urlsafe(48),
        'API_URL=http://127.0.0.1:5055', 'NEXT_PUBLIC_API_URL=http://127.0.0.1:5055',
        'NO_PROXY=localhost,127.0.0.1,.local', 'PYTHONUTF8=1',
        'PYTHONIOENCODING=utf-8', 'OPEN_NOTEBOOK_WORKER_MAX_TASKS=1', '',
    ]))
    return {'created': created, 'existing_files_preserved': True}


def repair_environment(root: Path, kind: str) -> dict:
    root = release_root(root)
    if kind not in ('workflow', 'open-notebook'): raise ValueError('Unknown environment.')
    app = contained(root, '工具/科研流程' if kind == 'workflow' else '工具/OpenNotebook/open-notebook-1.15.0', writable=True)
    target = _safe_path(app/'.venv', writable=True)
    if not (target/'Lib/site-packages').is_dir(): raise ValueError('Bundled Python dependencies are missing.')
    _safe_environment_tree(target)
    venv.EnvBuilder(with_pip=False, symlinks=False).create(target)
    _safe_environment_tree(target)
    site = _safe_path(target/'Lib/site-packages', writable=True)
    if kind == 'open-notebook': _atomic_text(site/'research_workbench_source.pth', str(app)+'\n')
    pip_wheels = sorted((Path(sys.base_prefix)/'Lib/ensurepip/_bundled').glob('pip-*.whl'))
    if not pip_wheels: raise ValueError('Bundled Python ensurepip wheel is missing.')
    sys.path.insert(0, str(pip_wheels[-1]))
    from pip._vendor.distlib.scripts import ScriptMaker
    maker = ScriptMaker(None, str(_safe_path(target/'Scripts', writable=True)))
    maker.executable = str(target/'Scripts/python.exe')
    maker.variants = {''}; maker.clobber = True
    count = 0
    for distribution in importlib.metadata.distributions(path=[str(site)]):
        for entry in distribution.entry_points:
            if entry.group in ('console_scripts', 'gui_scripts'):
                if not entry.name or any(c in entry.name for c in '/\\:'):
                    raise ValueError('Unsafe Python entry point.')
                maker.make(entry.name+' = '+entry.value, options={'gui': entry.group == 'gui_scripts'})
                count += 1
    return {'environment': kind, 'entry_points': count}


def initialize(root: Path) -> dict:
    root = release_root(root)
    release_id = json.loads(contained(root, MARKER).read_text('utf-8-sig'))['release_id']
    receipt_path, before = _receipt_snapshot(root, release_id)
    created = create_workspace(root)
    model = prepare_model(root)
    script = contained(root, '工具/科研流程/distribution/initialize.py')
    environment = os.environ.copy()
    for name in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV'): environment.pop(name, None)
    environment.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    repaired = []
    for kind, version in (('workflow', 'python313'), ('open-notebook', 'python312')):
        interpreter = contained(root, 'runtime/'+version+'/python.exe')
        result = subprocess.run([str(interpreter), '-I', str(script), '--workspace-root', str(root), '--repair-env', kind],
                                env=environment, capture_output=True, text=True, encoding='utf-8', timeout=180)
        if result.returncode:
            raise RuntimeError('Environment initialization failed: '+kind+'; '+result.stderr[-2000:])
        repaired.append(json.loads(result.stdout))
    workflow = contained(root, '工具/科研流程')
    subprocess.run([str(contained(root, '工具/科研流程/.venv/Scripts/python.exe')), '-B', '-c',
                    'import numpy, yaml, win32crypt, pymupdf; from research_store import Store; Store()'],
                   cwd=workflow, env=environment, check=True, timeout=90)
    receipt = {'schema_version': 1, 'release_id': release_id,
               'status': 'initialized', 'environments': repaired, 'embedding_model': model, **created}
    _atomic_text(receipt_path, json.dumps(receipt, ensure_ascii=False, indent=2)+'\n', expected=before)
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace-root', type=Path, required=True)
    parser.add_argument('--repair-env', choices=('workflow', 'open-notebook'))
    parser.add_argument('--no-shortcut', action='store_true')
    parser.add_argument('--no-launch', action='store_true')
    args = parser.parse_args()
    result = repair_environment(args.workspace_root, args.repair_env) if args.repair_env else initialize(args.workspace_root)
    if not args.repair_env:
        launcher = contained(release_root(args.workspace_root), '工具/科研流程/distribution/Launch.ps1')
        powershell = Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
        if not args.no_shortcut:
            subprocess.run([str(powershell), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(launcher),
                            '-Action', 'none', '-CreateShortcut'], check=True, timeout=30)
        if not args.no_launch:
            subprocess.Popen([str(powershell), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(launcher)],
                             cwd=args.workspace_root, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__': main()
