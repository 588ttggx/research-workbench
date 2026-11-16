"""Assemble reviewed source and prebuilt runtime components into one release."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import zipfile

from publish_source import default_replacements, publish_source, scan_tree, _real_path, _relative, _walk

REPOSITORY_FORMAT = 'research-workbench-repository-v1'
GENERATED_NAMES = {'manifest.json', 'Install.ps1', 'Install.cmd', 'SHA256SUMS.txt'}


def digest(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def _file(path):
    path = _real_path(path)
    if path.exists() and (not path.is_file() or path.stat().st_nlink > 1):
        raise ValueError('Release files must be regular files without hard links.')
    return path


def _current_hash(path):
    path = _file(path)
    return digest(path) if path.exists() else None


def _hashes(value):
    if not isinstance(value, dict): raise ValueError('Invalid build ownership file list.')
    for name, sha in value.items():
        _relative(name)
        if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha):
            raise ValueError('Invalid build ownership digest.')
    return value


def _repository_state(prepared, ownership):
    prepared = _real_path(prepared); ownership = _file(ownership)
    saved = json.loads(ownership.read_text('utf-8')) if ownership.exists() else None
    if saved is not None and (not isinstance(saved, dict) or saved.get('format') != REPOSITORY_FORMAT):
        raise ValueError('Existing repository has no recognized ownership receipt.')
    expected = _hashes(saved['files']) if saved is not None else {}
    actual = {}
    if prepared.exists():
        if not prepared.is_dir(): raise ValueError('Repository staging must be a directory.')
        for entry in prepared.iterdir():
            _real_path(entry)
            if entry.name == '.git':
                if entry.is_file(): _file(entry)
                continue  # Preserve existing Git state without opening or traversing it.
            candidates = _walk(entry, prune_private=False) if entry.is_dir() else (entry,)
            for path in candidates:
                path = _file(path)
                actual[path.relative_to(prepared).as_posix()] = digest(path)
    if actual != expected:
        raise ValueError('Repository contains changed, missing or unowned files; preserving it.')
    return expected, _current_hash(ownership)


def _release_state(output):
    receipt = _file(output/'core-build.json'); core = _file(output/'core.zip')
    saved = json.loads(receipt.read_text('utf-8')) if receipt.exists() else None
    if saved is None:
        if core.exists() or any(_file(output/name).exists() for name in GENERATED_NAMES):
            raise ValueError('Existing release output has no ownership receipt.')
        return {}, None
    if (not isinstance(saved, dict) or saved.get('id') != 'core' or saved.get('archive') != 'core.zip'
            or not isinstance(saved.get('generated_files'), dict)):
        raise ValueError('Invalid core build receipt.')
    expected = _hashes(saved['generated_files'])
    if set(expected) != GENERATED_NAMES:
        raise ValueError('Core build receipt has an unexpected generated file set.')
    expected = {**expected, 'core.zip': saved.get('sha256')}
    _hashes(expected)
    for name, sha in expected.items():
        if _current_hash(output/name) != sha:
            raise ValueError('Release output differs from its owned build: '+name)
    if core.stat().st_size != saved.get('size_bytes'):
        raise ValueError('Core ZIP size differs from its owned build.')
    return expected, digest(receipt)


def _unchanged(path, expected):
    if _current_hash(path) != expected:
        raise ValueError('A build destination changed during assembly; preserving it.')


def _atomic_bytes(destination, content, expected):
    destination = _file(destination)
    _unchanged(destination, expected)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.'+destination.name+'.', suffix='.partial', dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content); stream.flush(); os.fsync(stream.fileno())
        _unchanged(destination, expected)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def release_url(repository, tag, archive):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) or '..' in repository:
        raise ValueError('Invalid GitHub repository.')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', tag) or '..' in tag:
        raise ValueError('Invalid release tag.')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.zip', archive):
        raise ValueError('Invalid component filename.')
    return f'https://github.com/{repository}/releases/download/{tag}/{archive}'


def verify_components(folder, components):
    for item in components:
        release_url('owner/repository','v1',item['archive'])
        path=_file(folder/item['archive'])
        if path.stat().st_size != item['size_bytes'] or digest(path) != item['sha256']:
            raise ValueError('Runtime component differs from its build inventory: '+item['archive'])


def versions_template():
    return {'schema':1,
            'open_notebook':{'version':'1.15.0','runtime':'工具/OpenNotebook/open-notebook-1.15.0','data':'工具/OpenNotebook/data'},
            'integration':{'schema':2,'entry':'工具/科研流程/dashboard.py','data':'工具/科研流程/数据'},
            'n8n':{'version':'2.42.4','runtime':'工具/n8n/runtime-2.42.4','data':'工具/n8n/data','installed':False},
            'document_parser':{'enabled':False,'version':'PaddleOCR-VL-1.6','runtime':'runtime/PaddleOCR-VL',
                               'cache':'runtime/cache/document-parser','inference_runtime':'WSL Ubuntu-24.04:/opt/thz-document-vlm'},
            'graphviz':{'version':'16.1.0','executable':'工具/Graphviz/16.1.0/Graphviz-16.1.0-win64/bin/dot.exe'},
            'r':{'version':'4.6.1','runtime':'工具/R/4.6.1'},
            'powershell':{'version':'7.6.9','runtime':'工具/PowerShell/7.6.9','executable':'工具/PowerShell/7.6.9/pwsh.exe'}}


def release_manager(text):
    expression=r"\$allowed = \[IO.Path\]::GetFullPath\('[^']+'\)"
    text,count=re.subn(expression,"$allowed = [IO.Path]::GetFullPath((Join-Path $workspaceRoot 'runtime/RSpace'))",text)
    if count != 1: raise ValueError('Service manager release adapter no longer matches source.')
    return text


def _json(value): return json.dumps(value,ensure_ascii=False,indent=2)+'\n'


def frontend_files(folder, component):
    """Ship the reviewed patched source alongside the exact standalone binary."""
    folder=_real_path(folder)
    names={'package.json','package-lock.json','next.config.ts','next-env.d.ts','tsconfig.json',
           'postcss.config.mjs','components.json','eslint.config.mjs','start-server.js','vitest.config.ts','LICENSE'}
    selected={name:_file(folder/name).read_bytes() for name in names}
    extensions={'.ts','.tsx','.js','.jsx','.mjs','.css','.json','.md','.svg','.ico','.png','.jpg','.jpeg','.woff','.woff2','.otf','.ttf'}
    for directory in ('src','public'):
        tree=_real_path(folder/directory)
        if not tree.is_dir():raise ValueError('Corresponding frontend source is incomplete.')
        for path in _walk(tree,prune_private=False):
            relative=path.relative_to(folder)
            if any(part.lower() in {'.git','.next','node_modules','__pycache__'} or part.lower().startswith('.env') for part in relative.parts):continue
            if path.suffix.lower() not in extensions:raise ValueError('Unexpected file in corresponding frontend source: '+relative.as_posix())
            selected[relative.as_posix()]=_file(path).read_bytes()
    package=json.loads(selected['package.json']);lock=json.loads(selected['package-lock.json'])
    pins={'next':'16.4.1','zod':'4.6.6','follow-redirects':'1.16.2'}
    actual={name:package.get('dependencies',{}).get(name) for name in ('next','zod')}
    actual['follow-redirects']=package.get('overrides',{}).get('follow-redirects')
    if actual!=pins or any(lock.get('packages',{}).get('node_modules/'+name,{}).get('version')!=version for name,version in pins.items()):
        raise ValueError('Corresponding frontend package pins and lockfile must match the reviewed build.')
    prefix='third_party/open-notebook/'
    files={prefix+'frontend/'+name:content for name,content in selected.items()}
    source={'format':'open-notebook-corresponding-frontend-v1','upstream_version':'1.15.0',
            'upstream':'https://github.com/lfnovo/open-notebook/tree/v1.15.0/frontend',
            'license':'MIT','dependency_pins':pins,'binary_sha256':component['sha256'],
            'files':{name:hashlib.sha256(content).hexdigest() for name,content in selected.items()}}
    files[prefix+'frontend-source-manifest.json']=_json(source).encode('utf-8')
    files[prefix+'README.md']=('# Open Notebook frontend source\n\n'
        'Upstream: [Open Notebook v1.15.0](https://github.com/lfnovo/open-notebook/tree/v1.15.0/frontend), MIT. '
        'The adjacent frontend/LICENSE retains the upstream copyright and license.\n\n'
        'This source corresponds to the standalone frontend bundled in runtime-open-notebook.zip. '
        'Only package.json and package-lock.json were changed for the reviewed Next.js, Zod and follow-redirects pins. '
        'The source manifest records their exact versions, all source file hashes and the matching binary ZIP hash.\n\n'
        'Build inside frontend with npm ci --ignore-scripts, then npm run build. '
        'The release uses the generated .next/standalone server and copies .next/static and public beside it.\n').encode('utf-8')
    return files


def build(root, output, *, repository='588ttggx/research-workbench', tag='v0.1.0-preview.1', frontend_source=None):
    if '..' in root.parts or '..' in output.parts: raise ValueError('Build paths cannot contain parent traversal.')
    root=_real_path(root); output=_real_path(output)
    release_url(repository,tag,'core.zip')
    if not output.is_relative_to(root/'output') or output == root/'output': raise ValueError('Use a task output directory.')
    module=_real_path(root/'工具/科研流程/distribution')
    source=_real_path(output.parent/'source-stage')
    report=publish_source(root,source,replacements=default_replacements(root))
    inventory=json.loads(_file(output/'runtime_inventory.json').read_text('utf-8'))
    components=list(inventory['components'])
    optional=_file(output/'optional_runtime_inventory.json')
    optional_inventory=json.loads(optional.read_text('utf-8')) if optional.exists() else None
    if optional_inventory is not None:
        for component in optional_inventory['components']:
            if component.get('required') is not False:raise ValueError('Optional runtime components must remain optional.')
            selected=dict(component)
            if selected['id']=='ollama':selected['group']='qwen4b'
            components.append(selected)
    verify_components(output,components)
    files={name:_file(source/name).read_bytes() for name in report['files']}
    files.update({
        'README.md':_file(module/'release_readme.md').read_bytes(),
        'LICENSE':_file(module/'AGPL-3.0.txt').read_bytes(),
        '.research-workbench-release.json':_json({'schema_version':1,'release_id':tag}).encode('utf-8'),
        '.gitignore':'.venv/\nnode_modules/\nruntime/\n数据/\n.env\n.env.*\n*.dpapi\n*.sqlite*\n*.db\n__pycache__/\n*.pyc\noutput/\n科研知识库/\n工具/日志/\n工具/OpenNotebook/data/\n工具/n8n/data/\n进程.json\ninstallation*.json\n'.encode(),
        '工具/科研流程/distribution/versions.template.json':_json(versions_template()).encode('utf-8'),
        '工具/OpenNotebook/管理服务.ps1':b'\xef\xbb\xbf'+release_manager(_file(root/'工具/OpenNotebook/管理服务.ps1').read_text('utf-8-sig')).encode('utf-8'),
        'runtime_inventory.json':_json(inventory).encode('utf-8'),
    })
    if optional_inventory is not None:files['optional_runtime_inventory.json']=_json(optional_inventory).encode('utf-8')
    for name, action in [('打开科研区.cmd','start'),('停止科研区.cmd','stop')]:
        files[name]=('@echo off\r\nchcp 65001 >nul\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0工具\\科研流程\\distribution\\Launch.ps1" -Action '+action+' %*\r\nif errorlevel 1 pause\r\n').encode('utf-8')
    notices='# Third-party components\n\nSelf-authored integration code: AGPL-3.0-only. Each bundled dependency retains its own license.\n\n'
    notices+='Python: https://www.python.org/psf/license/\n\nNode.js: https://github.com/nodejs/node\n\nOpen Notebook: https://github.com/lfnovo/open-notebook (MIT)\n\nSurrealDB 2.7.0: https://github.com/surrealdb/surrealdb/tree/v2.7.0 (see bundled LICENSE)\n\n'
    notices+='PyMuPDF 1.28.2: AGPL/commercial dual license; this release follows AGPL.\n\n'
    notices+=f'For corresponding PyMuPDF/MuPDF, R and native-library source archives, consult the source-index records in this [Release](https://github.com/{repository}/releases/tag/{tag}). Use each index\'s exact version, availability status and SHA-256 digest. The R source bundle uses source-index.json and SHA256SUMS.txt internally; native-library coverage is recorded separately from package source availability.\n\n'
    notices+='Installed Python package versions and source URLs: runtime_inventory.json. Original package license and metadata files remain inside each environment package. Frontend licenses and font notices remain beside the built assets.\n'
    files['THIRD_PARTY_NOTICES.md']=notices.encode('utf-8')
    notebook=next((component for component in components if component['id']=='open-notebook'),None)
    if notebook:
        frontend_source=frontend_source or output.parent/'_临时/notebook-frontend-release'
        files.update(frontend_files(frontend_source,notebook))
        with zipfile.ZipFile(_file(output/notebook['archive'])) as binary:
            name='工具/OpenNotebook/open-notebook-1.15.0/frontend/node_modules/next/package.json'
            if binary.getinfo(name).file_size>65536 or json.loads(binary.read(name)).get('version')!='16.4.1':
                raise ValueError('Standalone Next.js binary does not match its published source pins.')
    prepared=_real_path(output.parent/'repository')
    ownership=_file(output.parent/'repository-build.json')
    temporary_root=_real_path(output.parent/'_临时');temporary_root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='release-assembly-',dir=temporary_root) as temporary_name:
        assembly=Path(temporary_name); tree=assembly/'tree';tree.mkdir()
        for name,data in files.items():
            destination=_real_path(tree/Path(_relative(name)))
            destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(data)
        findings=scan_tree(tree)
        if findings:raise ValueError('Prepared repository scan failed: '+json.dumps(findings,ensure_ascii=False))
        old,ownership_hash=_repository_state(prepared,ownership)
        previous_release,receipt_hash=_release_state(output)
        hashes={name:hashlib.sha256(data).hexdigest() for name,data in files.items()}
        staged_core=assembly/'core.zip'
        with zipfile.ZipFile(staged_core,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
            for name,data in sorted(files.items()):archive.writestr(name,data)
        if staged_core.stat().st_size>=2**31:raise ValueError('Core ZIP exceeds the release limit.')
        item={'id':'core','archive':'core.zip','sha256':digest(staged_core),'size_bytes':staged_core.stat().st_size,'required':True,'extract_to':'.'}
        components.insert(0,item)
        for component in components:component['url']=release_url(repository,tag,component['archive'])
        manifest={'schema_version':1,'repository':repository,'release_id':tag,
                  'installation':{'python':'runtime/python313/python.exe','initializer':'工具/科研流程/distribution/initialize.py'},
                  'components':components}
        generated={'manifest.json':_json(manifest).encode('utf-8'),
                   'SHA256SUMS.txt':''.join(f"{component['sha256']}  {component['archive']}\n" for component in components).encode('utf-8'),
                   **{name:files['工具/科研流程/distribution/'+name] for name in ('Install.ps1','Install.cmd')}}
        # Complete every preflight before touching the reviewed repository or release outputs.
        verify_components(output,components[1:])
        if (old,ownership_hash)!=_repository_state(prepared,ownership) or (previous_release,receipt_hash)!=_release_state(output):
            raise ValueError('Build ownership changed during assembly.')
        prepared.mkdir(parents=True,exist_ok=True)
        for name,data in sorted(files.items()):
            if hashes[name]!=old.get(name):_atomic_bytes(prepared/Path(_relative(name)),data,old.get(name))
        for name in sorted(set(old)-set(files)):
            destination=_file(prepared/Path(_relative(name)));_unchanged(destination,old[name]);destination.unlink()
        _atomic_bytes(ownership,_json({'format':REPOSITORY_FORMAT,'files':hashes}).encode('utf-8'),ownership_hash)
        _unchanged(output/'core.zip',previous_release.get('core.zip'))
        os.replace(staged_core,output/'core.zip')
        for name,data in generated.items():_atomic_bytes(output/name,data,previous_release.get(name))
        build_receipt={**item,'generated_files':{name:hashlib.sha256(data).hexdigest() for name,data in generated.items()}}
        _atomic_bytes(output/'core-build.json',_json(build_receipt).encode('utf-8'),receipt_hash)
    return {'repository_files':len(files),'core_bytes':item['size_bytes'],'components':len(components),'manifest':str(output/'manifest.json')}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[3])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--repository',default='588ttggx/research-workbench')
    parser.add_argument('--tag',default='v0.1.0-preview.1')
    parser.add_argument('--frontend-source',type=Path,help='Reviewed frontend source matching the runtime inventory.')
    args=parser.parse_args()
    print(_json(build(args.root,args.output,repository=args.repository,tag=args.tag,frontend_source=args.frontend_source)))
