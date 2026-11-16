"""Frozen file-intake replay; binary content is hashed, never guessed as spectra."""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
import sys


def execute(folder):
    folder=Path(folder).resolve();repository=folder.parents[1]
    parameters=json.loads((folder/'parameters.json').read_text('utf-8'))
    archive=folder/'code.zip'
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=parameters['code_archive_sha256']:raise ValueError('Saved code checksum mismatch')
    inputs=json.loads((folder/'inputs.json').read_text('utf-8'))
    inventory=[];summaries=[]
    for dataset in inputs:
        snapshot=(folder/dataset['snapshot']).resolve();snapshot.relative_to((repository/'datasets').resolve())
        hashes=Counter();extensions=Counter();binary=0;headers=Counter()
        for item in dataset['files']:
            source=(snapshot/item['path']).resolve();source.relative_to(snapshot)
            raw=source.read_bytes();checksum=hashlib.sha256(raw).hexdigest()
            if len(raw)!=item['bytes'] or checksum!=item['sha256']:raise ValueError('Input file checksum mismatch: '+item['path'])
            hashes[checksum]+=1;extensions[item['extension']]+=1;binary+=int(b'\0' in raw[:4096]);headers[raw[:4].hex()]+=1
            inventory.append({'dataset_id':dataset['id'],'dataset':dataset['title'],'file_id':item['id'],'path':item['path'],'bytes':len(raw),'sha256':checksum})
        if {p.relative_to(snapshot).as_posix() for p in snapshot.rglob('*') if p.is_file()}!={f['path'] for f in dataset['files']}:raise ValueError('Input snapshot contains unregistered files')
        summaries.append({'id':dataset['id'],'title':dataset['title'],'version':dataset['version'],'files':len(dataset['files']),
                          'bytes':sum(f['bytes'] for f in dataset['files']),'extensions':dict(sorted(extensions.items())),
                          'binary_files':binary,'headers':dict(sorted(headers.items())),'duplicate_content_groups':sum(n>1 for n in hashes.values())})
    metrics={'method':'native-file-intake-v1','scope':'文件接收与版本演练；不是真实实验或光谱分析',
             'file_integrity':'PASS','scientific_qc':'UNASSESSED','signal_analysis':'BLOCKED_UNVERIFIED_FORMAT',
             'files':len(inventory),'bytes':sum(r['bytes'] for r in inventory),'datasets':summaries,
             'unknown_conditions':['材料身份','独立样品与重复层级','仪器与导出格式','坐标与单位','参考配对','校准和环境条件']}
    output=folder/'computed';output.mkdir(exist_ok=True)
    with (output/'inventory.csv').open('w',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(inventory[0]));writer.writeheader();writer.writerows(inventory)
    (folder/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    categories=[];counts=[]
    for dataset in summaries:
        for extension,count in dataset['extensions'].items():categories.append(dataset['title']+'\n'+(extension or 'no extension'));counts.append(count)
    figure={'data':[{'type':'bar','x':categories,'y':counts,'name':'Registered files'}],
            'layout':{'title':{'text':parameters['options']['title']},'xaxis':{'title':{'text':'Dataset / file extension'}},'yaxis':{'title':{'text':'File count (not independent samples)'}}}}
    (output/'figure.plotly.json').write_text(json.dumps(figure,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    sys.path.insert(0,str(archive))
    from scientific_figures import export
    export(figure,output,parameters['run_id'])
    if all(item.get('header_hex','').startswith('c3c3d4c6') for dataset in inputs for item in dataset['files']):
        from cct_bridge import decode,NATIVE_SCALE,runtime
        expected_runtime=json.loads((folder/'environment.json').read_text('utf-8')).get('native_decoder')
        if expected_runtime and runtime()!=expected_runtime:raise ValueError('NRBF 读取环境与保存版本不同，请恢复对应组件或创建新运行；旧结果保留')
        import numpy as np
        from scipy.fft import rfft,rfftfreq
        records,arrays=decode(inputs,output,archive);waveforms=[];spectra=[];point_counts=[]
        for dataset in inputs:
            selected=[r for r in records if r['dataset']==dataset['id'] and r['extension']=='.sigtds']
            if not selected:continue
            lengths={r['points'] for r in selected}
            if len(lengths)!=1:raise ValueError('同组样点长度不一致，保留已解码数据，不自动重采样')
            matrix=np.stack([arrays[r['array_key']] for r in selected]).astype(float)*NATIVE_SCALE
            count=matrix.shape[1];point_counts.append(count)
            waveforms.append({'type':'scatter','mode':'lines','x':list(range(count)),'y':np.median(matrix,axis=0).tolist(),'name':dataset['title']+' · file median'})
            # General Fourier inspection only. No calibrated THz axis or pairing is implied.
            amplitudes=np.abs(rfft(matrix-matrix.mean(axis=1,keepdims=True),axis=1))/count
            frequencies=rfftfreq(count);median=np.median(amplitudes,axis=0);positive=(frequencies>0)&(median>0)
            spectra.append({'type':'scatter','mode':'lines','x':frequencies[positive].tolist(),'y':median[positive].tolist(),'name':dataset['title']+' · file median'})
            for reference in [r for r in records if r['dataset']==dataset['id'] and r['extension']=='.reftds']:
                values=arrays[reference['array_key']].astype(float)*NATIVE_SCALE
                waveforms.append({'type':'scatter','mode':'lines','x':list(range(len(values))),'y':values.tolist(),'name':dataset['title']+' · reference file (unpaired)'})
        specifications={
            'waveform':{'data':waveforms,'layout':{'title':{'text':parameters['options']['waveform_title']},'xaxis':{'title':{'text':'Sample index (optical delay not verified)'}},'yaxis':{'title':{'text':'Amplitude (software native scale)'}}}},
            'spectrum':{'data':spectra,'layout':{'title':{'text':parameters['options']['spectrum_title']},'xaxis':{'type':'log','dtick':1,'tickformat':'.0e','title':{'text':'Normalized frequency (cycles / sample, not THz)'}},'yaxis':{'type':'log','dtick':1,'tickformat':'.0e','title':{'text':'Fourier amplitude (native scale)'}}}}
        }
        palette=['#357C74','#637FA7','#C38758','#A48DAB']
        for spec in specifications.values():
            for index,trace in enumerate(spec['data']):trace['line']={'color':palette[index%len(palette)],'width':1.8}
        for name,spec in specifications.items():
            sub=output/name;export(spec,sub,parameters['run_id']+'-'+name)
            for suffix in ('svg','png','pdf'):(sub/('figure.'+suffix)).replace(output/(name+'.'+suffix))
            sub.rmdir()
            (output/(name+'.plotly.json')).write_text(json.dumps(spec,ensure_ascii=False,sort_keys=True),encoding='utf-8')
        metrics.update(signal_analysis='DECODED_CCT_V0',waveforms_decoded=len(records),sample_counts=sorted(set(point_counts)),
                       signal_scope='依据配套软件读取规则解码；通用 FFT 仅作归一化检查。时延/THz 标尺、真实配对、材料身份与科学 QC 未核实')
        (folder/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    return metrics


if __name__=='__main__':execute(Path(__file__).parent)
