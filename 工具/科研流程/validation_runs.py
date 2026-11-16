"""Exercise actual files through native Git/DVC and the existing isolated ledger."""
import json
import os
from pathlib import Path
import re
import sys
import zipfile
from filelock import FileLock
import workflow as w
from research_store import encode
import raw_data
import dataset_store as data
from analysis_runs import code_snapshot,environment


def _write(path,raw):
    raw=raw.encode('utf-8') if isinstance(raw,str) else raw
    if path.exists():
        if path.read_bytes()!=raw:raise ValueError('演练的已存版本发生变化，未覆盖')
    else:path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)


def _node(identifier):
    node=raw_data.ledger().node(identifier) if isinstance(identifier,str) and re.fullmatch(r'RUN-V-[a-f0-9]{20}',identifier) else None
    if not node or node['kind']!='RUN' or node['data'].get('purpose')!=raw_data.PURPOSE:raise ValueError('实战演练运行不存在')
    return node


def _folder(node):
    folder=(w.ROOT/node['uri']).resolve();folder.relative_to((w.ROOT/'数据/软件验证/数据版本/runs').resolve())
    return folder


def _check(node):
    folder=_folder(node)
    for entry in node['data'].get('artifacts',[]):
        path=(folder/entry['path']).resolve();path.relative_to(folder)
        if not path.is_file() or w.digest(path.read_bytes())!=entry['sha256']:raise ValueError('演练文件缺失或校验失败，保留旧记录，请先恢复备份')


def run(identifiers=None,options=None,progress=None):
    identifiers=identifiers or [n['id'] for n in raw_data.listing()]
    if not isinstance(identifiers,list) or not 1<=len(identifiers)<=10 or len(set(identifiers))!=len(identifiers):raise ValueError('请选择 1–10 组已登记的演练资料')
    datasets=[raw_data.detail(i) for i in sorted(identifiers)]
    if sum(n['data']['bytes'] for n in datasets)>256*1024**2:raise ValueError('本轮演练最多 256 MB，请分批选择数据')
    options=options or {};defaults={'title':'File intake rehearsal · verification data','waveform_title':'Decoded waveforms · rehearsal data','spectrum_title':'Fourier inspection · no material classification'}
    if set(options)-set(defaults) or any(not isinstance(t,str) or not 1<=len(t.strip())<=200 for t in options.values()):raise ValueError('图标题无效')
    options={**defaults,**{k:v.strip() for k,v in options.items()}};version_signature=w.digest(encode([[(n['id'],n['data']['version']) for n in datasets],options]))
    with FileLock(str(w.DATA/'实战演练.lock'),timeout=180):
        store=raw_data.ledger()
        pending=next((n for n in store.nodes(kind='RUN') if n['status']=='REGISTERING' and n['data'].get('version_signature')==version_signature),None)
        if pending:node=pending;request=node['data']['request']
        else:
            if progress:progress('正在冻结输入版本、实际代码和环境')
            code=code_snapshot(w.ROOT/'数据/软件验证/代码快照',[w.HERE/'cct_decode.ps1']);env=environment()
            if all(f.get('header_hex','').startswith('c3c3d4c6') for dataset in datasets for f in dataset['files']):
                env['native_decoder']=__import__('cct_bridge').runtime()
            request={'dataset_versions':[(n['id'],n['data']['version']) for n in datasets],'options':options,'code':code,'environment':env}
            identifier='RUN-V-'+w.digest(encode(request))[:20];node=store.node(identifier)
            if node and node['status']=='COMPLETED':_check(node);return {**detail(identifier),'reused':True}
            folder=data.repository(validation=True)/'runs'/identifier
            node=store.put_node(identifier,'RUN','Python',project='软件验证',uri=folder.relative_to(w.ROOT).as_posix(),status='REGISTERING',
                                data={'purpose':raw_data.PURPOSE,'formal':False,'title':'文件接收实战演练','version_signature':version_signature,'request':request,'parameters':options})
        identifier=node['id'];folder=_folder(node);folder.mkdir(parents=True,exist_ok=True)
        expected=dict(request['dataset_versions'])
        if any(n['data']['version']!=expected.get(n['id']) for n in datasets):raise ValueError('演练输入已变化，原运行保留，请重新选择当前版本')
        archive=w.ROOT/request['code']['archive']
        if w.digest(archive.read_bytes())!=request['code']['archive_sha256']:raise ValueError('保存的代码快照校验失败')
        with zipfile.ZipFile(archive) as saved:
            frozen={name:saved.read(name) for name in ('validation_replay.py','uv.lock')}
        inputs=[{'id':n['id'],'title':n['data']['title'],'version':n['data']['version'],
                 'snapshot':os.path.relpath(w.ROOT/n['data']['snapshot_uri'],folder).replace('\\','/'),'files':n['files']} for n in datasets]
        _write(folder/'code.zip',archive.read_bytes())
        for name,raw in frozen.items():_write(folder/name,raw)
        _write(folder/'inputs.json',encode(inputs));_write(folder/'environment.json',encode(request['environment']))
        _write(folder/'parameters.json',encode({'run_id':identifier,'code_archive_sha256':request['code']['archive_sha256'],'options':request['options']}))
        import yaml
        definition={'stages':{'intake_validation':{'cmd':'python validation_replay.py',
            'deps':['validation_replay.py','inputs.json','code.zip','parameters.json','environment.json','uv.lock',*[n['snapshot'] for n in inputs]],
            'outs':['computed'],'metrics':[{'metrics.json':{'cache':False}}]}}}
        _write(folder/'dvc.yaml',yaml.safe_dump(definition,allow_unicode=True,sort_keys=False))
        if progress:progress('正在执行原生 DVC 流水线、逐文件核对与专业绘图')
        with data.writer():
            data.command([sys.executable,'-m','dvc','repro','dvc.yaml'],folder,timeout=180)
            repository=data.repository(validation=True)
            owned=[folder/name for name in ['validation_replay.py','inputs.json','code.zip','parameters.json','environment.json','uv.lock','dvc.yaml','dvc.lock','metrics.json','.gitignore']]
            git=data.commit_paths(repository,owned,identifier+' software rehearsal')
        metrics=w.read_json(folder/'metrics.json')
        if metrics.get('signal_analysis')=='DECODED_CCT_V0':
            for dataset in datasets:
                current=raw_data._node(dataset['id'])
                if current['data']['version']!=dataset['data']['version']:raise ValueError('登记解码范围时输入版本已变化，旧运行保留')
                store.put_node(current['id'],current['kind'],current['owner'],project=current['project'],external_id=current['external_id'],uri=current['uri'],status=current['status'],expected=current['revision'],
                               data={**current['data'],'format_status':'decoded_structure','format_observation':{'version':current['data']['version'],'format':'CCTF v0 / NRBF Int32','run':identifier,'samples':metrics['sample_counts'],'scope':'结构与数值已核对；物理标尺、实际材料和参考配对仍未核实'}})
        result_id='R-V-'+identifier[6:];figure_id='FIG-V-'+identifier[6:];env_id='ENV-V-'+w.digest(encode(request['environment']))[:20];code_id='CODE-V-'+request['code']['sha256'][:20]
        common={'purpose':raw_data.PURPOSE,'formal':False}
        for i,kind,owner,content in [(result_id,'Result','Python',{'title':'文件接收验证结果','metrics':metrics}),
                                    (figure_id,'Figure','Python',{'title':request['options']['title']}),
                                    (env_id,'Environment','Python',request['environment']),(code_id,'Code','Git',request['code'])]:
            store.put_node(i,kind,owner,project='软件验证',status='VALIDATION_ONLY',data={**content,**common})
        evidence=[{'location':'原生 DVC lock 与逐文件 SHA256','scope':'软件演练；不表示 THz 科学 QC 通过'}]
        for target in [*identifiers,env_id,code_id]:store.relation(identifier,target,'Uses',evidence,mechanical=True)
        store.relation(result_id,identifier,'ProducedBy',evidence,mechanical=True);store.relation(figure_id,result_id,'DerivedFrom',evidence,mechanical=True)
        figures=[figure_id]
        if metrics.get('signal_analysis')=='DECODED_CCT_V0':
            for name in ('waveform','spectrum'):
                extra_id=figure_id+'-'+name
                store.put_node(extra_id,'Figure','Python',project='软件验证',status='VALIDATION_ONLY',data={**common,'title':request['options'][name+'_title'],'artifact':name+'.svg'})
                store.relation(extra_id,result_id,'DerivedFrom',evidence,mechanical=True);figures.append(extra_id)
        graph=__import__('graph_exports').export(figure_id,store=store)
        if graph.get('status')=='exported':_write(folder/'provenance.svg',(w.ROOT/graph['path']).read_bytes())
        owned=[p for p in folder.rglob('*') if p.is_file() and p.name not in {'.lock'} and '.dvc' not in p.parts and not p.name.endswith('.tmp')]
        artifacts=[{'path':p.relative_to(folder).as_posix(),'sha256':w.digest(p.read_bytes()),'bytes':p.stat().st_size} for p in owned if p.name!='.gitignore']
        row=store.put_node(identifier,'RUN','Python',project='软件验证',uri=node['uri'],status='COMPLETED',expected=node['revision'],
                           data={**node['data'],'outputs':{'result':result_id,'figure':figure_id,'figures':figures,'environment':env_id,'code':code_id},'metrics':metrics,
                                 'git_commit':git.get('commit'),'git_status':git['status'],'artifacts':artifacts,'graph_status':graph['status']})
        if progress:progress('实战演练完成，结果、图和来源已关联')
        return {**detail(row['id']),'reused':False}


def history():
    return [{'id':n['id'],'title':n['data']['title'],'status':n['status'],'created':n['created'],
             'files':n['data'].get('metrics',{}).get('files'),'datasets':n['data']['request']['dataset_versions']} for n in raw_data.ledger().nodes(kind='RUN')]


def detail(identifier):
    node=_node(identifier);_check(node) if node['status']=='COMPLETED' else None
    return {**node,'scope':'使用原文件的端到端软件实战演练；不是材料识别或 THz 物理分析',
            'trace':__import__('research_records').trace(identifier,store=raw_data.ledger())}


def artifact(identifier,filename):
    node=_node(identifier);folder=_folder(node)
    allowed={'computed/'+name+suffix for name in ('figure','waveform','spectrum') for suffix in ('.svg','.png','.pdf','.plotly.json')}
    allowed|={'computed/inventory.csv','computed/waveforms.npz','computed/waveform_sources.json','provenance.svg','metrics.json','dvc.yaml','dvc.lock'}
    names={Path(item['path']).name:item for item in node['data'].get('artifacts',[]) if item['path'] in allowed}
    if filename not in names:raise ValueError('演练产物不存在')
    item=names[filename];path=folder/item['path']
    if not path.is_file() or w.digest(path.read_bytes())!=item['sha256']:raise ValueError('演练产物校验失败')
    return path


def reproduce(identifier,progress=None):
    node=_node(identifier);_check(node);folder=_folder(node);expected=node['data']['metrics']
    if progress:progress('正在使用保存的代码、参数和输入复跑')
    with data.writer():data.command([sys.executable,'-m','dvc','repro','--force','dvc.yaml'],folder,timeout=180)
    actual=w.read_json(folder/'metrics.json')
    if encode(actual)!=encode(expected):raise ValueError('复跑指标不一致；原登记结果保留，请核查')
    _check(node)
    return {'id':identifier,'metrics_match':True,'files':actual['files'],'scope':'保存代码与输入下的确定性复跑；不是独立设备或 THz 科学验证'}
