"""Capture actual inputs/code/environment and multi-source output lineage per RUN."""
import importlib.metadata
import json
import platform
from pathlib import Path
import subprocess
import sys
import zipfile
import uuid
from filelock import FileLock
import workflow as w
from research_store import Store, encode


def environment():
    packages={p.metadata['Name']:p.version for p in importlib.metadata.distributions() if p.metadata['Name']}
    return {'python':sys.version,'executable':sys.executable,'os':platform.platform(),
            'architecture':platform.machine(),'packages':dict(sorted(packages.items())),
            'gpu_driver':None,'cuda':None,'scope':'实际 CPU 运行环境快照；GPU / CUDA 未采集，不能用于 GPU 正式复现'}


def code_snapshot(folder,extra_files=()):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    contents={p.name:p.read_bytes() for p in w.HERE.glob('*.py')}
    contents.update({p.name:p.read_bytes() for p in extra_files})
    for name in ('pyproject.toml','uv.lock'):
        if (w.HERE/name).is_file():contents[name]=(w.HERE/name).read_bytes()
    files={name:w.digest(raw) for name,raw in contents.items()}
    identity=w.digest(encode(files))
    archive=folder/('code-'+identity[:16]+'.zip')
    if not archive.exists():
        temporary=archive.with_suffix('.tmp')
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as z:
            for name,raw in contents.items():z.writestr(name,raw)
        temporary.replace(archive)
    command=['git','-C',str(w.HERE)]
    def git(args):
        r=subprocess.run(command+args,env=__import__('git_support').environment(),capture_output=True,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
        return r.stdout.strip() if r.returncode==0 else None
    commit=git(['rev-parse','HEAD']);dirty=git(['status','--porcelain'])
    return {'sha256':identity,'archive':archive.resolve().relative_to(w.ROOT.resolve()).as_posix(),'archive_sha256':w.digest(archive.read_bytes()),
            'git_commit':commit,'dirty':bool(dirty) if commit else None,'scope':'探索运行代码快照；正式成果需已提交代码、严格环境锁和批准的方法'}


def _key(result):
    return 'run_registration:'+w.digest(encode([result['project'],result['id']]))


def _lock(result):
    folder=w.DATA/'分析登记';folder.mkdir(parents=True,exist_ok=True)
    return FileLock(str(folder/(_key(result).split(':')[1]+'.lock')),timeout=240)


def _reserve(store,result,options):
    """Reserve the job and all output IDs in one durable SQLite transaction."""
    request={'result':result,'options':options}
    fingerprint=w.digest(encode(request));key=_key(result)
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        old=db.execute('SELECT * FROM jobs WHERE idem=?',(key,)).fetchone()
        if old:
            payload=json.loads(old['payload'])
            if payload['fingerprint']!=fingerprint:raise ValueError('同一分析身份的输入或参数已变化，未覆盖原运行')
            return old['id'],payload
        identifiers={}
        for name,prefix in [('run_id','RUN'),('result_id','R'),('figure_id','FIG')]:
            sequence='sequence:'+prefix;row=db.execute('SELECT value FROM meta WHERE key=?',(sequence,)).fetchone()
            number=int(row['value'])+1 if row else 1
            db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(sequence,str(number)))
            identifiers[name]=f'{prefix}-{number:04d}'
        payload={**request,'fingerprint':fingerprint,'outputs':identifiers,'created':w.now(),'state':{}}
        job_id=uuid.uuid4().hex;stamp=w.now()
        db.execute('INSERT INTO jobs(id,kind,payload,idem,status,phase,safe_retry,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                   (job_id,'run_registration',encode(payload),key,'queued','已保留运行身份',1,stamp,stamp))
        store.log(db,'run.reserved',identifiers['run_id'],{'job_id':job_id,'analysis_id':result['id']})
    return job_id,payload


def _phase(store,job_id,payload,label):
    with store.connection() as db:
        db.execute('UPDATE jobs SET payload=?,phase=?,updated=? WHERE id=?',(encode(payload),label,w.now(),job_id))
        store.log(db,'run.phase',payload['outputs']['run_id'],{'phase':label})


def _write_once(path,value):
    if path.exists():
        if encode(w.read_json(path))!=encode(value):raise ValueError('已保存的运行文件发生变化，未覆盖原版本')
    else:w.write_json(path,value)


def _save_analysis(result,outputs):
    import re
    if not re.fullmatch('[A-Za-z0-9_-]{1,100}',result['id']):raise ValueError('分析身份无效')
    w.write_json(w.DATA/'数据分析'/(result['id']+'.json'),{**result,'provenance':outputs})


def _check_pipeline(pipeline):
    definition=(w.ROOT/pipeline['uri']).resolve()
    definition.relative_to((w.ROOT/'数据/数据版本/runs').resolve())
    if not definition.is_file() or w.digest(definition.with_name('dvc.lock').read_bytes())!=pipeline['lock_sha256']:
        raise ValueError('已保存的 DVC 运行定义发生变化，未重建或覆盖')
    missing=[item for item in pipeline['artifacts'] if not (w.ROOT/item['uri']).is_file()]
    if missing:
        import dataset_store as data
        with data.writer():data.command([sys.executable,'-m','dvc','checkout'],definition.parent)
    for item in pipeline['artifacts']:
        path=(w.ROOT/item['uri']).resolve();path.relative_to(definition.parent)
        if not path.is_file() or w.digest(path.read_bytes())!=item['sha256']:
            raise ValueError('已生成的运行产物校验失败，未覆盖原版本')


def register(result,options):
    store=Store()
    with _lock(result):
        # Existing pre-journal RUNs remain readable and retain their original IDs.
        existing=next((n for n in store.nodes(result['project'],'RUN') if n['data'].get('analysis_id')==result['id'] and n['status']=='COMPLETED'),None)
        with store.connection() as db:journal=db.execute('SELECT id FROM jobs WHERE idem=?',(_key(result),)).fetchone()
        if existing and not journal:return existing['data']['outputs']
        job_id,payload=_reserve(store,result,options)
        job=store.job(job_id)
        if job['status']=='completed':return job['result']['outputs']
        if job['status'] in ('failed','needs_review'):store.retry(job_id)
        store.claim(job_id)
        try:
            outputs=_execute(store,job_id,payload)
            store.finish(job_id,result={'outputs':outputs})
            return outputs
        except Exception as exc:
            store.finish(job_id,error=str(exc) if isinstance(exc,ValueError) else '运行登记未完成：'+type(exc).__name__)
            raise


def resume(job_id,*,managed=False):
    store=Store();job=store.job(job_id,private=True)
    if not job or job['kind']!='run_registration':raise ValueError('运行接续任务不存在')
    payload=job['payload']
    if not managed:return {'outputs':register(payload['result'],payload['options'])}
    with _lock(payload['result']):
        latest=store.job(job_id,private=True)
        if latest['status']=='completed':return latest['result']
        return {'outputs':_execute(store,job_id,latest['payload'])}


def _execute(store,job_id,payload):
    result=payload['result'];options=payload['options'];state=payload['state']
    identifier=payload['outputs']['run_id'];result_id=payload['outputs']['result_id'];figure_id=payload['outputs']['figure_id']
    folder=w.ROOT/'数据/分析运行'/identifier;folder.mkdir(parents=True,exist_ok=True)
    from dataset_store import source_file
    source=source_file(result);raw=source.read_bytes()
    if w.digest(raw)!=result['source_sha256']:raise ValueError('输入校验值变化，未登记不一致的运行')
    if 'prepared' not in state:
        state['prepared']={'environment':environment(),'code':code_snapshot(folder)}
        _phase(store,job_id,payload,'已保存代码与环境')
    env=state['prepared']['environment'];code=state['prepared']['code']
    if w.digest((w.ROOT/code['archive']).read_bytes())!=code['archive_sha256']:raise ValueError('代码快照校验失败，未覆盖运行')
    env_id='ENV-'+w.digest(encode(env))[:16];code_id='CODE-'+code['sha256'][:16]
    dataset_id='DATA-'+result['source_sha256'][:16];common={'project':result['project']}
    store.put_node(identifier,'RUN','Pipeline',uri=str(folder.relative_to(w.ROOT)),status='REGISTERING',
                   data={'analysis_id':result['id'],'kind':result['kind'],'parameters':options,'formal':False,'title':identifier+' · 登记中'},**common)
    figure=folder/(figure_id+'.plotly.json');_write_once(figure,result['figure'])
    _write_once(folder/'environment.json',env);_write_once(folder/'parameters.json',options)
    _write_once(folder/'metrics.json',result['metrics'])
    # New datasets have one immutable file in Data Storage; RUN stores its link.
    # Legacy runs keep their original input copy for compatibility and recovery.
    if result.get('source_root')=='workspace':
        _write_once(folder/'input.json',{'uri':result['source'],'sha256':result['source_sha256']})
    elif (folder/'input.csv').exists():
        if (folder/'input.csv').read_bytes()!=raw:raise ValueError('旧运行输入已改变，未覆盖')
    else:(folder/'input.csv').write_bytes(raw)
    if 'pipeline' not in state:
        state['pipeline']=prepare_pipeline(result,identifier,code) if result.get('dataset') else None
        _phase(store,job_id,payload,'已生成并核验计算产物')
    pipeline=state['pipeline']
    if pipeline:_check_pipeline(pipeline)
    outputs={'run_id':identifier,'result_id':result_id,'figure_id':figure_id,'dataset_id':dataset_id,'environment_id':env_id,'code_id':code_id,
             'artifacts':pipeline.get('artifacts',[]) if pipeline else [],
             'missing':['EXP / Sample / Batch / Calibration 未关联','正式代码版本与环境锁待冻结','领域方法与单位待确认']}
    store.put_node(dataset_id,'Dataset','DataStorage+DVC',uri=result['source'],status='EXPLORATORY',data={**result.get('dataset',{}),'sha256':result['source_sha256'],'version':result['source_sha256'],'dvc_tracked':bool(result.get('dataset',{}).get('dvc_tracked')),'title':'输入 CSV'},**common)
    store.put_node(env_id,'Environment','Pipeline',uri=str((folder/'environment.json').relative_to(w.ROOT)),status='CAPTURED',data=env,**common)
    store.put_node(code_id,'Code','Git',uri=code['archive'],status='SNAPSHOT',data=code,**common)
    store.put_node(result_id,'Result','Pipeline',uri=result['path'],status='COMPUTED',data={'metrics':result['metrics'],'title':result['filename'],'run_id':identifier},**common)
    store.put_node(figure_id,'Figure','Pipeline',uri=str(figure.relative_to(w.ROOT)),status='EXPORTED' if pipeline else 'SPECIFICATION',data={'title':figure_id+' · 分析图','sha256':w.digest(figure.read_bytes()),'format':'Plotly JSON / SVG / PNG / PDF' if pipeline else 'Plotly JSON','run_id':identifier,'exported_image':bool(pipeline),'artifacts':pipeline.get('artifacts',[]) if pipeline else []},**common)
    for a,b,kind in [(identifier,dataset_id,'Uses'),(identifier,env_id,'Uses'),(identifier,code_id,'Uses'),(result_id,identifier,'ProducedBy'),(figure_id,result_id,'DerivedFrom')]:
        store.relation(a,b,kind,[{'source':'Pipeline','run_id':identifier,'location':str(folder.relative_to(w.ROOT))}],mechanical=True)
    if result['kind']=='thz':
        outputs.update(__import__('qc_records').register(result,identifier,dataset_id,pipeline))
        outputs['missing']=['正式代码与环境待冻结']+([] if len(outputs['native_records'])==4 else ['部分正式实验、样品、仪器或校准原生索引尚未接入'])
    _write_once(folder/'run.json',{'id':identifier,'created':payload['created'],'inputs':{'csv_sha256':result['source_sha256'],'uri':result['source'] if result.get('source_root')=='workspace' else None},'code':code,'outputs':outputs,'pipeline':pipeline,'formal':False})
    _save_analysis(result,outputs)
    store.put_node(identifier,'RUN','Pipeline',uri=str(folder.relative_to(w.ROOT)),status='COMPLETED',data={'analysis_id':result['id'],'kind':result['kind'],'parameters':options,'inputs':[dataset_id],'outputs':outputs,'pipeline':pipeline,'formal':False,'title':identifier+' · 探索分析'},**common)
    from research_records import export_snapshot
    export_snapshot()
    return outputs


def reproduce(identifier):
    import data_analysis
    node=Store().node(identifier)
    if not node or node['kind']!='RUN':raise ValueError('运行不存在')
    folder=(w.ROOT/node['uri']).resolve()
    if not folder.is_relative_to((w.ROOT/'数据/分析运行').resolve()):raise ValueError('运行路径无效')
    info=w.read_json(folder/'run.json')
    source=(w.ROOT/info['inputs']['uri']).resolve() if info['inputs'].get('uri') else folder/'input.csv'
    source.relative_to(w.ROOT.resolve());text=source.read_bytes().decode('utf-8')
    if w.digest(text)!=info['inputs']['csv_sha256']:raise ValueError('输入校验失败')
    # This checks deterministic calculations using installed code; frozen replay requires the saved environment/code.
    actual=data_analysis.compute(text,node['data']['kind'],node['data']['parameters'])
    expected=w.read_json(folder/'metrics.json')
    return {'id':identifier,'metrics_match':encode(actual['metrics'])==encode(expected),'scope':'当前环境中的确定性复跑检查；不等同于独立环境恢复验收'}


def prepare_pipeline(result,identifier,code):
    import dataset_store as data
    import yaml
    repository=data.repository();folder=repository/'runs'/identifier
    with data.writer():
        folder.mkdir(parents=True,exist_ok=True)
        archive=w.ROOT/code['archive']
        with zipfile.ZipFile(archive) as saved:
            originals={folder/'code.zip':archive.read_bytes(),**{folder/name:saved.read(name) for name in ['frozen_replay.py','pyproject.toml','uv.lock']}}
        if result.get('method_document'):originals[folder/'method.md']=result['method_document']['text'].encode('utf-8')
        for target,content in originals.items():
            if target.exists() and target.read_bytes()!=content:
                raise ValueError('冻结运行文件已改变，未覆盖原版本')
            if not target.exists():target.write_bytes(content)
        parameters={'run_id':identifier,'kind':result['kind'],'options':result.get('options') or w.read_json(w.ROOT/'数据/分析运行'/identifier/'parameters.json'),
                    'input':__import__('os').path.relpath(data.source_file(result),folder).replace('\\','/'),
                    'input_sha256':result['source_sha256'],'code_archive_sha256':code['archive_sha256']}
        _write_once(folder/'parameters.json',parameters)
        definition={'stages':{'analysis':{'cmd':'python frozen_replay.py','deps':[parameters['input'],'code.zip','frozen_replay.py','parameters.json','pyproject.toml','uv.lock'],
                      'outs':['computed'],'metrics':[{'metrics.json':{'cache':False}}]}}}
        if result.get('method_document'):definition['stages']['analysis']['deps'].append('method.md')
        definition_file=folder/'dvc.yaml'
        if definition_file.exists():
            if encode(yaml.safe_load(definition_file.read_text('utf-8')))!=encode(definition):
                raise ValueError('冻结计算定义已改变，未覆盖原版本')
        else:w.atomic_text(definition_file,yaml.safe_dump(definition,allow_unicode=True,sort_keys=False))
        data.command([sys.executable,'-m','dvc','repro','dvc.yaml'],folder,timeout=180)
        actual=w.read_json(folder/'metrics.json')
        if encode(actual)!=encode(result['metrics']):raise ValueError('冻结代码复跑指标不一致，未登记成功运行')
        files=[*originals,folder/'parameters.json',folder/'dvc.yaml',folder/'dvc.lock',folder/'metrics.json',folder/'.gitignore']
        git=data.commit_paths(repository,files,identifier+' reproducible exploratory pipeline')
        artifacts=[{'name':p.name,'uri':p.relative_to(w.ROOT.resolve()).as_posix(),'sha256':w.digest(p.read_bytes()),'bytes':p.stat().st_size} for p in (folder/'computed').iterdir() if p.is_file()]
        return {'uri':(folder/'dvc.yaml').relative_to(w.ROOT.resolve()).as_posix(),'lock_sha256':w.digest((folder/'dvc.lock').read_bytes()),
                'git_commit':git.get('commit'),'git_status':git['status'],'artifacts':artifacts,
                'scope':'使用保存的代码和输入执行 DVC stage；正式科研审核与独立环境恢复另行验收'}


def artifact(identifier,filename):
    if filename not in ('figure.svg','figure.png','figure.pdf','figure.plotly.json','metrics.json','dvc.yaml','dvc.lock','uv.lock','method.md'):
        raise ValueError('运行产物不存在')
    node=Store().node(identifier)
    if not node or node['kind']!='RUN' or not node['data'].get('pipeline'):
        raise ValueError('该运行尚无已保存的专业图')
    definition=(w.ROOT/node['data']['pipeline']['uri']).resolve()
    definition.relative_to((w.ROOT/'数据/数据版本/runs').resolve())
    path=definition.parent/('computed/'+filename if filename.startswith('figure.') else filename)
    if not path.is_file():raise ValueError('运行产物缺失，请从数据备份恢复')
    expected=next((r['sha256'] for r in node['data']['pipeline']['artifacts'] if r['name']==filename),None)
    if expected and w.digest(path.read_bytes())!=expected:raise ValueError('运行产物校验失败，未展示已改变的文件')
    if filename=='metrics.json':
        result=Store().node(node['data']['outputs']['result_id'])
        if not result or encode(w.read_json(path))!=encode(result['data']['metrics']):raise ValueError('运行指标已变化，未展示已改变的记录')
    if filename=='method.md':
        method=Store().node(node['data']['outputs'].get('method_version'))
        if not method or w.digest(path.read_bytes())!=method['data'].get('source_sha256'):raise ValueError('冻结方法校验失败，未展示已改变的记录')
    return path
