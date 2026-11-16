"""Register measured QC outputs and root-cause candidates, preserving prose."""
import knowledge as k
import workflow as w
from research_store import Store


def register(result,run_id,dataset_id,pipeline):
    store=Store();method=result['method_document'];version='METHODV-'+w.digest(method['fingerprint']+method['text'])[:20]
    relative=str(__import__('pathlib').Path(pipeline['uri']).parent/'method.md')
    if not store.node(version):store.put_node(version,'Method','Pipeline',uri=relative,status='CAPTURED_SOURCE_VERSION',project=result['project'],
                   data={'title':'方法版本 · '+method['title'],'source_method_id':method['id'],'source_uri':method['uri'],
                         'fingerprint':method['fingerprint'],'source_sha256':w.digest(method['text']),
                         'policy':result['options']['method_snapshot'],'scope':'运行时保存的只读方法版本；当前知识主稿仍在原方法记录编辑。'})
    evidence=[{'source':'Pipeline','run_id':run_id,'location':relative,'method_fingerprint':method['fingerprint']}]
    store.relation(run_id,version,'Uses',evidence,mechanical=True)
    store.relation(version,method['id'],'DerivedFrom',evidence,mechanical=True)
    qc=result['metrics']['qc'];identifier='QC-'+w.digest(run_id)[:16]
    store.put_node(identifier,'QC','Pipeline',project=result['project'],status=qc['status'],uri=pipeline['uri'],
                   data={'title':'质量检查 · '+result['filename'],'run_id':run_id,'method_version':version,**qc})
    store.relation(identifier,run_id,'ProducedBy',evidence,mechanical=True)
    store.relation(dataset_id,identifier,'CheckedBy',evidence,mechanical=True)
    candidates=[]
    if qc['status']=='FAIL':
        for kind,prefix,label in [('Issue','ISSUE','质量检查问题'),('Failure','FAIL','质量异常待核查')]:
            candidate=prefix+'-'+w.digest(run_id)[:16];old=store.node(candidate)
            if old:candidates.append(candidate);continue
            path=w.KB/'笔记'/result['project']/label/(candidate+'.md')
            facts='\n'.join('- '+row['metric']+'：'+str(row.get('value')) for row in qc['checks'] if row['status']=='FAIL')
            body='# '+label+'\n\n'+facts+'\n\n来源：'+run_id+'；QC：'+identifier+'。\n\n## 待人工核查\n\n这是质量阈值触发的候选，尚未认定实验失败或根因。请核对原始数据、方法条件和处理过程；实际尝试、原因、解决与教训由人确认。\n'
            text=k.properties('',{'id':candidate,'type':'research_record','record_type':kind,'project':result['project'],'title':label,'source_run':run_id})+body
            if path.exists():
                current=path.read_text('utf-8-sig');meta,body,_=k.split(current)
                if meta.get('id')!=candidate or meta.get('source_run')!=run_id:raise ValueError('同名候选不属于当前运行，未覆盖')
            else:w.atomic_text(path,text)
            store.put_node(candidate,kind,'Markdown',project=result['project'],uri=path.relative_to(w.KB).as_posix(),status='CANDIDATE',
                           data={'title':label,'source':'qc-candidate','run_id':run_id,'document_sha256':w.digest(body.rstrip())})
            store.relation(candidate,identifier,'Uses',evidence,mechanical=True);candidates.append(candidate)
    native=[]
    for field in ('experiment_id','independent_sample_id','instrument_id','calibration_id'):
        identity=result['options']['metadata'].get(field);node=store.node(identity) if isinstance(identity,str) else None
        if node and node['owner']=='RSpace':
            store.relation(run_id,identity,'Uses',[{'source':'User-declared measured metadata','location':field,'run_id':run_id}],mechanical=True);native.append(identity)
    return {'qc_id':identifier,'method_version':version,'qc_candidates':candidates,'native_records':native}
