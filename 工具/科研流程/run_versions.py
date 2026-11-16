"""Seal an existing reproducible RUN without changing its research approval.

Git owns the captured code, strict lock and DVC definition. The lightweight
run tag points at that exact commit; neither the user's index nor HEAD moves.
The seal is additive. Editing an analysis continues to create a new RUN.
"""
from pathlib import Path
import re
import tomllib
import zipfile
from filelock import FileLock
import workflow as w
from research_store import Store, encode
import dataset_store as data


def _run(identifier):
    if not isinstance(identifier,str) or not re.fullmatch(r'RUN-\d{4,}',identifier):
        raise ValueError('运行身份无效')
    node=Store().node(identifier)
    if not node or node['kind']!='RUN' or node['owner']!='Pipeline' or node['status']!='COMPLETED':
        raise ValueError('只有已完成登记的分析运行可以冻结')
    folder=(w.ROOT/node['uri']).resolve()
    folder.relative_to((w.ROOT/'数据/分析运行').resolve())
    return node,folder


def _committed(repository,commit,path):
    relative=Path(path).resolve().relative_to(repository).as_posix()
    # Native Git applies the repository's actual line-ending/attribute rules.
    # Comparing raw show bytes incorrectly rejects Windows CRLF worktrees.
    expected=data.command(['git','rev-parse','--verify',commit+':'+relative],repository).strip()
    actual=data.command(['git','hash-object','--path='+relative,'--',str(path)],repository).strip()
    if actual!=expected:
        raise ValueError('运行文件与已保存的 Git 版本不一致：'+Path(path).name)


def freeze(identifier,revision):
    node,folder=_run(identifier)
    with FileLock(str(folder/'.version-freeze.lock'),timeout=45):
        node,folder=_run(identifier)
        if node['revision']!=revision:
            raise ValueError('运行记录已变化，请刷新来源详情后重试')
        info=w.read_json(folder/'run.json');pipeline=info.get('pipeline')
        if not pipeline or not pipeline.get('git_commit'):
            raise ValueError('这次运行尚未提交完整的 Git / DVC 版本；请先处理数据仓库的待提交状态')
        repository=data.repository();commit=pipeline['git_commit']
        if not re.fullmatch(r'[0-9a-f]{40,64}',commit):raise ValueError('保存的 Git 版本无效')
        definition=(w.ROOT/pipeline['uri']).resolve();definition.relative_to(repository/'runs'/identifier)
        code=info['code'];archive=(w.ROOT/code['archive']).resolve();archive.relative_to(folder)
        if w.digest(archive.read_bytes())!=code['archive_sha256']:
            raise ValueError('代码快照校验失败，未冻结')
        with zipfile.ZipFile(archive) as saved:
            lock=saved.read('uv.lock');project=saved.read('pyproject.toml')
        parsed=tomllib.loads(lock.decode('utf-8'))
        if parsed.get('version')!=1 or not parsed.get('package') or not parsed.get('requires-python'):
            raise ValueError('这次运行没有可用的严格环境锁，未冻结')
        if (definition.parent/'uv.lock').read_bytes()!=lock or (definition.parent/'pyproject.toml').read_bytes()!=project:
            raise ValueError('运行环境锁与代码快照不一致，未冻结')
        env=w.read_json(folder/'environment.json')
        if 'ENV-'+w.digest(encode(env))[:16]!=info['outputs']['environment_id']:
            raise ValueError('实际运行环境记录校验失败，未冻结')
        source=(w.ROOT/info['inputs']['uri']).resolve() if info['inputs'].get('uri') else folder/'input.csv'
        source.relative_to(repository/'datasets')
        if not source.is_file() or w.digest(source.read_bytes())!=info['inputs']['csv_sha256']:
            raise ValueError('输入版本校验失败，未冻结')
        parameters=w.read_json(definition.parent/'parameters.json')
        if (info.get('id')!=identifier or parameters.get('run_id')!=identifier
            or parameters.get('input_sha256')!=info['inputs']['csv_sha256']
            or parameters.get('code_archive_sha256')!=code['archive_sha256']
            or (definition.parent/parameters.get('input','')).resolve()!=source):
            raise ValueError('运行身份、输入或代码与原生计算定义不一致，未冻结')
        # Recover a missing output through native DVC; changed files are rejected.
        __import__('analysis_runs')._check_pipeline(pipeline)
        files=['code.zip','frozen_replay.py','pyproject.toml','uv.lock','parameters.json','dvc.yaml','dvc.lock','metrics.json']
        if (definition.parent/'method.md').is_file():files.append('method.md')
        for name in files:_committed(repository,commit,definition.parent/name)
        if (definition.parent/'code.zip').read_bytes()!=archive.read_bytes():
            raise ValueError('Git 中的代码与本次运行不一致，未冻结')
        _committed(repository,commit,source.with_suffix(source.suffix+'.dvc'))
        if encode(w.read_json(definition.parent/'metrics.json'))!=encode(w.read_json(folder/'metrics.json')):
            raise ValueError('保存的运行指标不一致，未冻结')
        tag='run/'+identifier;ref='refs/tags/'+tag
        matching=data.command(['git','for-each-ref','--format=%(objectname)',ref],repository).strip()
        if matching and matching!=commit:
            raise ValueError('同名冻结版本已指向其他提交，旧版本保留，请核查')
        hashes={name:w.digest((definition.parent/name).read_bytes()) for name in files}
        values={'schema':1,'run_id':identifier,'git_commit':commit,'git_tag':tag,
            'git_repository':repository.relative_to(w.ROOT.resolve()).as_posix(),
            'input_sha256':info['inputs']['csv_sha256'],'code_archive_sha256':code['archive_sha256'],
            'environment_id':info['outputs']['environment_id'],'environment_sha256':w.digest((folder/'environment.json').read_bytes()),
            'lock_sha256':w.digest(lock),'files':hashes,'artifacts':pipeline['artifacts'],
            'method_version':info['outputs'].get('method_version'),
            'scope':'已冻结计算版本；科研判断、QC 和成果审核仍以各自原记录为准。输入、方法或图表修改时保存新运行。'}
        seal=folder/'version-seal.json'
        if seal.exists():
            receipt=w.read_json(seal)
            if any(receipt.get(key)!=value for key,value in values.items()):
                raise ValueError('冻结清单与当前运行不一致，未覆盖旧版')
        else:
            receipt={**values,'created':w.now()};w.write_json(seal,receipt)
        # Compare-and-swap never replaces an existing tag. A crash before/after
        # tag creation resumes from the same durable seal on the next request.
        if not matching:
            data.command(['git','update-ref',ref,commit,'0'*len(commit)],repository)
        record={**receipt,'uri':seal.relative_to(w.ROOT.resolve()).as_posix(),'sha256':w.digest(seal.read_bytes())}
        updated=Store().put_node(identifier,node['kind'],node['owner'],project=node['project'],
            external_id=node['external_id'],uri=node['uri'],status=node['status'],
            data={**node['data'],'version_freeze':record},expected=revision)
        __import__('research_records').export_snapshot()
        return {'id':identifier,'revision':updated['revision'],'version_freeze':record}


def artifact(identifier):
    node,folder=_run(identifier);record=node['data'].get('version_freeze')
    path=folder/'version-seal.json'
    if not record or not path.is_file() or w.digest(path.read_bytes())!=record['sha256']:
        raise ValueError('冻结清单尚未生成或校验失败')
    return path
