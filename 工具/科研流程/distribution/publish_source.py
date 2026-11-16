"""Export a reviewed source allowlist without touching the live workspace.

No Git history, private knowledge, runtime database or credential store is read.
The scanners are release gates for recognizable patterns, not a privacy audit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Mapping


MODULE = PurePosixPath('工具/科研流程')
MARKER_NAME = '.workbench-source-staging.json'
FORMAT = 'workbench-source-staging-v1'
RULES = {'common', 'chat', 'project', 'knowledge', 'organize', 'directions',
         'reading', 'radar', 'weekly', 'extraction', 'comparison'}
SKILLS = {'idea-evaluator', 'tech-paper-template', 'figure-designer',
          'pre-submission-reviewer', 'deep-research', 'benchmark-paper-template',
          'paper-polish', 'intro-drafter', 'paper-writer', 'rebuttal-guidance',
          'research-organizer', 'scholarly-paper-collector'}
TOP_FILES = {'pyproject.toml', 'uv.lock', 'requirements.txt',
             'document-parser-requirements.in', 'document-parser-requirements.lock',
             'document-vllm-requirements.in', 'document-vllm-requirements.lock'}
PUBLIC_REGRESSION_TESTS = {'test_fulltext_quality.py', 'test_portable_backup.py'}
LOCAL_MAINTENANCE = {'verify_locked_environment.py', 'provision_science_tools.py'}
TOP_SUFFIXES = {'.py', '.js', '.css', '.html'}
TEXT_SUFFIXES = {'.py', '.js', '.mjs', '.cjs', '.jsx', '.ts', '.tsx', '.css',
                 '.html', '.json', '.toml', '.lock', '.in', '.txt', '.md', '.r',
                 '.ps1', '.cmd', '.iss', '.yaml', '.yml', '.svg', '.env'}
ASSET_SUFFIXES = TEXT_SUFFIXES | {'.otf', '.ttf', '.woff', '.woff2', '.png', '.jpg', '.jpeg', '.ico'}
BLOCKED_PARTS = {'.git', '.venv', 'node_modules', '__pycache__', 'legacy',
                 'browser-profile', 'data', '数据', '_临时', 'output'}
BLOCKED_SUFFIXES = {'.sqlite', '.sqlite3', '.db', '.dpapi', '.pem', '.key',
                    '.log', '.pyc', '.zip', '.pdf', '.csv', '.xlsx'}
TOKEN_PATTERNS = (
    ('github-token', re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,})\b')),
    ('provider-api-key', re.compile(r'\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}\b')),
    ('slack-token', re.compile(r'\bxox[baprs]-[A-Za-z0-9-]{12,}\b')),
    ('aws-access-key', re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b')),
    ('private-key', re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----')),
)
CREDENTIAL = re.compile(
    r'''(?i)(?:^|(?<=[{,;]))[ \t]*(?:(?:const|let|var)\s+)?["']?(?:api[_-]?key|api[_-]?token|access[_-]?token|auth[_-]?token|password|passwd|client[_-]?secret)["']?\s*[:=]\s*["']([^"'\r\n]{8,})["']''')
FRONTEND_LOCALE = re.compile(r'third_party/open-notebook/frontend/src/lib/locales/[a-z]{2}-[A-Za-z]{2,4}/index\.ts\Z')
PERSONAL_PATH = re.compile(
    r'(?i:(?<![^\s"\'`(])[A-Z]:[\\/]+(?!Program\s+Files(?:\s*\(x86\))?[\\/]|Windows[\\/]|ProgramData[\\/])[^\s"\'`<>|]+)'
    r'|(?<![A-Za-z0-9])/(?:Users|home)/[^/\s"\']+')
PLACEHOLDERS = {'fixture-credential', 'example-password', 'example-token',
                'example-api-key', 'your-api-key', 'your_api_key',
                'replace-me', 'change-me', 'changeme', 'placeholder',
                'redacted', '<redacted>', 'test-token', 'test-password'}
RESERVED_NAMES = {'con', 'prn', 'aux', 'nul',
                  *(name + str(i) for name in ('com', 'lpt') for i in range(1, 10))}


class PublicationBlocked(ValueError):
    """Only paths, line numbers and rule names are safe to display."""
    def __init__(self, findings):
        self.findings = findings
        super().__init__(json.dumps({'publication_blocked': findings}, ensure_ascii=False))


def _is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _real_path(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    for current in (*reversed(path.parents), path):
        if _is_link(current):
            raise ValueError('Source and destination must not traverse directory links.')
    return path


def _relative(value: str) -> PurePosixPath:
    if not isinstance(value, str) or '\\' in value or ':' in value:
        raise ValueError('Invalid relative publication path.')
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {'', '.', '..'} for part in value.split('/')):
        raise ValueError('Invalid relative publication path.')
    for part in path.parts:
        if (part.endswith((' ', '.')) or part.split('.', 1)[0].lower() in RESERVED_NAMES
                or any(ord(char) < 32 or char in '<>"|?*' for char in part)):
            raise ValueError('Invalid Windows publication filename.')
    return path


def _allowed(relative: PurePosixPath) -> bool:
    parts = relative.parts
    if any(part.lower() in BLOCKED_PARTS or part.lower().startswith('.env') for part in parts):
        return False
    if relative.suffix.lower() in BLOCKED_SUFFIXES:
        return False
    if parts[:2] == MODULE.parts:
        tail = parts[2:]
        if len(tail) == 1:
            return tail[0] not in LOCAL_MAINTENANCE and (tail[0] in TOP_FILES or relative.suffix in TOP_SUFFIXES)
        if not tail:
            return False
        category = tail[0]
        if category == 'frontend':
            return (len(tail) == 2 and tail[1] in {'package.json', 'package-lock.json', 'build.mjs', 'knowledge-build.mjs'}
                    or len(tail) > 2 and tail[1] in {'src', 'assets', 'dist'} and relative.suffix.lower() in ASSET_SUFFIXES)
        if category == 'vendor':
            return relative.suffix.lower() in ASSET_SUFFIXES or relative.name in {'LICENSE', 'NOTICE'}
        if category == 'r':
            return relative.suffix.lower() == '.r'
        if category == 'zotero-addon':
            return relative.suffix.lower() in {'.js', '.json'}
        if category == 'distribution':
            return relative.suffix.lower() in {'.py', '.ps1', '.cmd', '.iss', '.json', '.toml', '.md', '.txt'}
        if category == 'tests':
            return len(tail) == 2 and (tail[1] in PUBLIC_REGRESSION_TESTS or
                                      tail[1].startswith('test_distribution_') and relative.suffix == '.py')
    if len(parts) == 4 and parts[:3] == ('.agents', 'rules', 'research'):
        return relative.stem in RULES and relative.suffix == '.md'
    if len(parts) >= 4 and parts[:2] == ('.agents', 'skills') and parts[2] in SKILLS:
        tail = parts[3:]
        if tail == ('SKILL.md',) or tail == ('SKILL.disabled.md',):
            return True
        if tail[0] == 'references':
            return relative.suffix == '.md'
        if parts[2] == 'scholarly-paper-collector':
            return (tail == ('LICENSE',)
                    or tail[0] == 'scripts' and 'tests' not in tail and relative.suffix == '.py'
                    or tail[0] == 'assets' and relative.suffix in {'.html', '.css'})
    return False


def _walk(folder: Path, *, prune_private=True, skip_git=False):
    """Do not enumerate production data, dependency trees or junction targets."""
    for base, directories, files in os.walk(folder, followlinks=False):
        base = Path(base)
        kept = []
        for name in sorted(directories):
            if (prune_private and (name.lower() in BLOCKED_PARTS or name.lower().startswith('.env'))
                    or skip_git and name.lower() == '.git'):
                continue
            if _is_link(base / name):
                raise ValueError('A selected source or destination contains a directory link.')
            kept.append(name)
        directories[:] = kept
        for name in sorted(files):
            yield base / name


def source_manifest(root: Path) -> list[str]:
    root = _real_path(root)
    module = _real_path(root / Path(MODULE))
    if not module.is_dir():
        raise ValueError('The selected source is not a research workbench workspace.')
    selected = []
    candidates = [path for path in module.iterdir() if path.is_file()]
    for name in ('frontend', 'vendor', 'r', 'zotero-addon', 'distribution', 'tests'):
        folder = _real_path(module / name)
        if folder.is_dir():
            candidates.extend(_walk(folder))
    rules = _real_path(root / '.agents/rules/research')
    if rules.is_dir():
        candidates.extend(rules.iterdir())
    for name in sorted(SKILLS):
        folder = _real_path(root / '.agents/skills' / name)
        if folder.is_dir():
            candidates.extend(_walk(folder))
    for path in candidates:
        relative = path.relative_to(root)
        if _allowed(PurePosixPath(relative.as_posix())):
            _real_path(path)
            if not path.is_file():
                raise ValueError('A selected source is not a regular file.')
            selected.append(relative.as_posix())
    return sorted(set(selected))


def default_replacements(root: Path) -> dict[str, dict[str, str]]:
    """Strict, copy-only path adaptation for the known workspace source layout.

    Match fixed statement shapes exactly once. The original personal path is
    read from that statement, never copied into the public release tooling or
    logged. A changed upstream shape requires review instead of a broad rewrite.
    """
    root = _real_path(root)
    recipes = [
        ('工具/科研流程/dataset_store.py',
         r"env\.setdefault\('DVC_SITE_CACHE_DIR','[^'\r\n]+'\)",
         "env.setdefault('DVC_SITE_CACHE_DIR',str(w.ROOT/'runtime/cache/DVC'))"),
        ('工具/科研流程/document_parser.py',
         r"cache = Path\(config\.get\('cache', '[^'\r\n]+'\)\)",
         "cache = Path(config.get('cache', str(w.ROOT/'runtime/cache/document-parser')))"),
        ('工具/科研流程/professional_tools.py',
         r"temporary = Path\('[^'\r\n]+'\)",
         "temporary = w.ROOT/'runtime/cache/Cytoscape/tmp'"),
        ('工具/科研流程/rspace_runtime.py',
         r"allowed=Path\('[^'\r\n]+'\)\.absolute\(\)",
         "allowed=(w.ROOT/'runtime/RSpace').absolute()"),
        ('工具/科研流程/scientific_figures.py',
         r"os\.environ\.setdefault\('MPLCONFIGDIR','[^'\r\n]+'\)",
         "os.environ.setdefault('MPLCONFIGDIR',str(w.ROOT/'runtime/cache/Matplotlib'))"),
        ('.agents/skills/scholarly-paper-collector/scripts/scholarly_collector/config.py',
         r'    configured_root = Path\("[^"\r\n]+"\)\r?\n'
         r'    return configured_root / "[^"\r\n]+" if os.name == "nt" and configured_root.is_dir\(\) else run_dir / "\.spc_cache"',
         '    configured_root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ResearchWorkbench/Cache"\n'
         '    return configured_root / "scholarly"'),
        ('.agents/skills/scholarly-paper-collector/references/workspace-workflow.md',
         r'^- `SPC_CACHE_DIR`[^\r\n]*',
         '- `SPC_CACHE_DIR` 可指定缓存；默认使用当前用户的 `LOCALAPPDATA`（未设置时为用户主目录）下的 `ResearchWorkbench/Cache/scholarly`。'),
    ]
    replacements = {}
    for relative, pattern, replacement in recipes:
        path = _real_path(root / Path(_relative(relative)))
        source = path.read_bytes().decode('utf-8-sig')
        matches = list(re.finditer(pattern, source, flags=re.MULTILINE))
        if len(matches) != 1 or source.count(matches[0].group(0)) != 1:
            raise ValueError('Expected exactly one unchanged distribution statement: ' + relative)
        replacements[relative] = {matches[0].group(0): replacement}
    return replacements


def scan_text(text: str, path: str) -> list[dict]:
    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        matched = {name for name, pattern in TOKEN_PATTERNS if pattern.search(line)}
        if PERSONAL_PATH.search(line):
            matched.add('personal-absolute-path')
        if not matched.intersection({'github-token', 'provider-api-key', 'slack-token', 'aws-access-key'}):
            for match in CREDENTIAL.finditer(line):
                value = match.group(1).strip()
                # This upstream translation field names the API-key input. It
                # is UI copy, while provider token patterns above still apply.
                if (FRONTEND_LOCALE.fullmatch(path.replace('\\', '/'))
                        and re.fullmatch(r'''\s*apiKey:\s*(["'])(.*?)\1,?\s*''', line)):
                    continue
                if value.lower() not in PLACEHOLDERS and not value.startswith(('${', '%', '<YOUR_', 'os.environ', 'process.env')):
                    matched.add('credential-literal')
        findings.extend({'path': path, 'line': number, 'rule': rule} for rule in sorted(matched))
    return findings


def _text(path: PurePosixPath, data: bytes):
    if path.suffix.lower() in TEXT_SUFFIXES or path.name in {'LICENSE', 'NOTICE', '.gitignore'}:
        try:
            return data.decode('utf-8-sig')
        except UnicodeDecodeError as error:
            raise ValueError('A selected text file is not valid UTF-8: ' + path.as_posix()) from error
    return None


def _prepared(root: Path, replacements: Mapping | None):
    paths = source_manifest(root)
    replacements = replacements or {}
    if not isinstance(replacements, Mapping):
        raise ValueError('Replacements must map selected relative paths to exact text replacements.')
    for path in replacements:
        _relative(path)
        if path not in paths:
            raise ValueError('A replacement targets a file outside the publication allowlist.')
    payload, findings = {}, []
    for relative in paths:
        path = _real_path(root / Path(relative))
        data = path.read_bytes()
        text = _text(PurePosixPath(relative), data)
        if relative in replacements:
            changes = replacements[relative]
            if text is None or not isinstance(changes, Mapping):
                raise ValueError('Only selected UTF-8 text supports publication replacements.')
            for before, after in changes.items():
                if not isinstance(before, str) or not before or not isinstance(after, str) or before not in text:
                    raise ValueError('An expected publication replacement no longer matches: ' + relative)
                text = text.replace(before, after)
            data = text.encode('utf-8')
        if text is not None:
            findings.extend(scan_text(text, relative))
        payload[relative] = data
    return payload, findings


def scan_source(root: Path, *, replacements: Mapping | None = None) -> dict:
    root = _real_path(root)
    payload, findings = _prepared(root, replacements)
    return {'ready': not findings, 'file_count': len(payload),
            'total_bytes': sum(map(len, payload.values())), 'findings': findings,
            'files': {path: hashlib.sha256(data).hexdigest() for path, data in payload.items()}}


def scan_tree(root: Path) -> list[dict]:
    """Scan all final published text, including caller-authored launchers/docs."""
    root = _real_path(root)
    findings = []
    for path in _walk(root, prune_private=False, skip_git=True):
        _real_path(path)
        if path.name == MARKER_NAME:
            continue
        relative = PurePosixPath(path.relative_to(root).as_posix())
        if (any(part.lower() in BLOCKED_PARTS or part.lower().startswith('.env') for part in relative.parts)
                or relative.suffix.lower() in BLOCKED_SUFFIXES):
            findings.append({'path': relative.as_posix(), 'line': 0, 'rule': 'forbidden-published-file'})
            continue
        value = _text(relative, path.read_bytes())
        if value is not None:
            findings.extend(scan_text(value, relative.as_posix()))
    return findings


def _target_state(root: Path, target: Path) -> dict:
    # Publishing is an output operation. Source directories can never be targets.
    if '..' in Path(target).parts:
        raise ValueError('Destination must not contain parent traversal.')
    target = _real_path(target)
    output = _real_path(root / 'output')
    if target == output or not target.is_relative_to(output):
        raise ValueError('Destination must be a task staging directory below workspace/output.')
    if not target.exists():
        return {}
    if not target.is_dir():
        raise ValueError('Destination must be a directory.')
    entries = list(target.iterdir())
    if not entries:
        return {}
    marker = target / MARKER_NAME
    _real_path(marker)
    if marker.exists() and marker.stat().st_nlink > 1:
        raise ValueError('Existing publication marker must not be a hard link.')
    try:
        saved = json.loads(marker.read_text('utf-8'))
    except (OSError, ValueError) as error:
        raise ValueError('Existing destination is not an owned publication staging directory.') from error
    root_id = hashlib.sha256(str(root).encode('utf-8')).hexdigest()
    if (not isinstance(saved, dict) or saved.get('format') != FORMAT or saved.get('source_id') != root_id
            or not isinstance(saved.get('files'), dict)):
        raise ValueError('Existing publication marker does not match this workspace.')
    expected = saved['files']
    for relative, digest in expected.items():
        path = _real_path(target / Path(_relative(relative)))
        if (not path.is_file() or path.stat().st_nlink > 1 or not isinstance(digest, str)
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
            raise ValueError('A previously published file was changed; preserving the destination.')
    actual = {path.relative_to(target).as_posix() for path in _walk(target, prune_private=False) if path.name != MARKER_NAME}
    if actual != set(expected):
        raise ValueError('Destination contains unowned files; preserving the destination.')
    return expected


def publish_source(root: Path, target: Path, *, replacements: Mapping | None = None) -> dict:
    """Publish only after every selected text and every existing target passes.

    Exact replacements affect only copied bytes; originals are never rewritten.
    Repeated publication requires unchanged owned contents. A changed or unknown
    destination is left untouched instead of silently deleting user work.
    """
    root = _real_path(root)
    old_files = _target_state(root, target)
    target = _real_path(target)
    payload, findings = _prepared(root, replacements)
    if findings:
        raise PublicationBlocked(findings)
    # Recheck ownership immediately before the first mutation.
    if old_files != _target_state(root, target):
        raise ValueError('Destination changed while preparing publication.')
    hashes = {path: hashlib.sha256(data).hexdigest() for path, data in payload.items()}
    target.mkdir(parents=True, exist_ok=True)
    for relative, data in payload.items():
        destination = _real_path(target / Path(_relative(relative)))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    for relative in sorted(set(old_files) - set(payload)):
        destination = _real_path(target / Path(_relative(relative)))
        if not destination.is_relative_to(target):
            raise ValueError('A stale publication path escaped its destination.')
        destination.unlink()
    marker = {'format': FORMAT, 'source_id': hashlib.sha256(str(root).encode('utf-8')).hexdigest(), 'files': hashes}
    (target / MARKER_NAME).write_text(json.dumps(marker, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'ready': True, 'file_count': len(payload), 'total_bytes': sum(map(len, payload.values())),
            'findings': [], 'files': hashes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--target', type=Path)
    parser.add_argument('--replacements', type=Path, help='Private JSON map; values are never logged.')
    parser.add_argument('--write', action='store_true', help='Copy to a new or owned staging directory.')
    args = parser.parse_args()
    if args.write and args.target is None:
        parser.error('--write requires --target')
    replacements = json.loads(args.replacements.read_text('utf-8-sig')) if args.replacements else None
    try:
        report = (publish_source(args.root, args.target, replacements=replacements) if args.write
                  else scan_source(args.root, replacements=replacements))
    except PublicationBlocked as error:
        print(str(error))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ready'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
