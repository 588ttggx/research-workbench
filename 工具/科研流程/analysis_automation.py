"""Approved, explicit RSpace-to-CSV analysis profiles; one existing event bus."""
from pathlib import Path
import json
import math
import re
from urllib.parse import urlsplit,unquote
from filelock import FileLock
import workflow as w
from research_store import Store,encode
import method_registry as methods
import project_profiles as lifecycle

KEY='analysis:auto:'


def _path(uri):
    parsed=urlsplit(uri);local=unquote(parsed.path) if parsed.scheme=='file' else uri
    if parsed.scheme=='file':local='\\\\'+parsed.netloc+local.replace('/','\\') if parsed.netloc not in ('','localhost') else local[1:] if re.match(r'^/[A-Za-z]:/',local) else local
    return Path(local)


def _dependencies(node,nodes):
    fields=node['data'].get('metadata',{});related={fields[k] for k in ('sample','batch','instrument','calibration','sop') if fields.get(k)}
    return [{'id':n['id'],'data':n['data']} for n in nodes.values() if n['owner']=='RSpace' and (n['id'] in related or n['data'].get('global_id') in related) and n.get('external_id','').split('#')[0]==node['external_id'].split('#')[0]]


def code_version():
    return w.digest(b''.join((w.HERE/name).read_bytes() for name in ('thz_domain.py','data_analysis.py','qc_records.py','analysis_automation.py')))


def profiles():
    values=[]
    for method in methods.listing()['records']:
        value=Store().cursor(KEY+method['id'],{'enabled':False,'revision':0,'method_id':method['id']})
        value={**value,'method_title':method['data']['title'],'method_current':not method['archived'] and method['status']=='VERIFIED' and value.get('method_fingerprint')==method['fingerprint'],'code_current':value.get('code_version')==code_version()}
        value['progress']=Store().cursor(KEY+method['id']+':progress',{})
        with Store().connection() as db:value['items']=[json.loads(row['value']) for row in db.execute('SELECT value FROM cursors WHERE key LIKE ? ORDER BY updated DESC',(KEY+method['id']+':progress:%',))]
        values.append(value)
    return {'records':values,'scope':'只处理原生实验明确指定的方法、完成状态和本机 CSV。目录、列对应与方法变更由同一入口维护；条件不足保留等待原因，不补造事实。'}


def configure(body):
    key=KEY+str(body.get('method_id',''))
    with FileLock(str(w.DATA/'analysis-auto-config.lock'),timeout=30):
        old=Store().cursor(key,{'revision':0})
        if body.get('revision')!=old['revision']:raise ValueError('自动接续设置已变化，请重新打开')
        if type(body.get('enabled')) is not bool:raise ValueError('自动接续状态无效')
        if not body['enabled'] and old.get('root') and not any(name in body for name in ('root','columns','project','native_project','noise_indices')):
            value={**old,'revision':old['revision']+1,'enabled':False};Store().commit_page(key,[],value);return value
        method=methods.approved(body.get('method_id'),body.get('method_fingerprint'))
        root=Path(body.get('root',''))
        if not root.is_absolute() or not root.is_dir():raise ValueError('请选择实际存在的实验 CSV 目录')
        root=root.resolve();columns=body.get('columns',{})
        required=[columns.get(k) for k in ('time','sample','reference')]
        if any(not isinstance(v,str) or not 1<=len(v)<=120 for v in required) or len(set(required))!=3:raise ValueError('请明确三个不同的时间、样品和参考列名')
        if set(columns)-{'time','sample','reference','reference_after'} or any(not isinstance(v,str) or len(v)>120 for v in columns.values()):raise ValueError('波形列对应无效')
        project=body.get('project');native_project=body.get('native_project')
        __import__('knowledge').lines(project)
        if not isinstance(native_project,str) or not native_project.strip() or len(native_project)>120:raise ValueError('请指定原生记录中实际填写的项目 ID')
        noise=body.get('noise_indices')
        if noise is not None and (not isinstance(noise,list) or len(noise)!=2 or any(type(v) is not int for v in noise) or not 0<=noise[0]<noise[1]<=10000 or noise[1]-noise[0]<4):raise ValueError('噪声窗口需为至少四点的有效起止序号')
        value={'revision':old['revision']+1,'enabled':body['enabled'],'root':str(root),'columns':columns,'noise_indices':noise,
               'project':project,'native_project':native_project.strip(),'method_id':method['id'],'method_fingerprint':method['fingerprint'],'code_version':code_version()}
        aliases=Store().cursor('rspace:project-map',{})
        if aliases.get(native_project.strip(),project)!=project:
            others=[p for p in profiles()['records'] if p['method_id']!=method['id'] and p.get('enabled') and p.get('native_project')==native_project.strip()]
            if others or old.get('native_project')!=native_project.strip() or old.get('project')!=aliases[native_project.strip()]:raise ValueError('此原生项目由其他接续配置关联，请先核对并暂停冲突配置')
        mapping_changed=aliases.get(native_project.strip())!=project
        aliases[native_project.strip()]=project;Store().commit_page('rspace:project-map',[],aliases)
        if mapping_changed:
            upstream=Store().cursor('connector:rspace',{})
            if upstream:Store().commit_page('connector:rspace',[],{**upstream,'revision':upstream.get('revision',0)+1})
        Store().commit_page(key,[],value);return value


def _metadata(node,nodes):
    fields=node['data'].get('metadata',{});result={key:fields[key] for key in ('independent_sample_id','preparation_id','scan_id','measurement_date','time_unit','signal_unit','instrument_state') if fields.get(key)}
    def identity(value):
        return value if value in nodes else next((n['id'] for n in nodes.values() if n['owner']=='RSpace' and n['data'].get('global_id')==value and n.get('external_id','').split('#')[0]==node['external_id'].split('#')[0]),value)
    result.update(experiment_id=node['id'],batch_id=identity(fields.get('batch','')),instrument_id=identity(fields.get('instrument','')),calibration_id=identity(fields.get('calibration','')))
    if fields.get('sop'):
        result['sop_id']=identity(fields['sop']);sop=nodes.get(result['sop_id']);result['sop_record_version']=sop['data'].get('source_modified') if sop else None
    if not result.get('independent_sample_id'):result['independent_sample_id']=identity(fields.get('sample',''))
    calibration=nodes.get(result['calibration_id']);result['calibration_valid_until']=calibration['data'].get('metadata',{}).get('valid_until') if calibration else None
    result['rspace_record_version']=node['data'].get('source_modified');result['calibration_record_version']=calibration['data'].get('source_modified') if calibration else None
    for key in ('thickness_mm','temperature_celsius','humidity_percent','dynamic_range_db','water_vapor_metric'):
        if fields.get(key):
            try:value=float(fields[key])
            except ValueError:raise ValueError('原生测量条件 '+key+' 不是实际数值') from None
            if not math.isfinite(value):raise ValueError('原生测量条件包含非有限数值')
            result[key]=value
    result['reference_pairing_confirmed']=fields.get('reference_pairing_confirmed') in ('true','已确认')
    result['geometry_confirmed']=fields.get('geometry_confirmed') in ('true','已确认')
    for key in __import__('thz_domain').ASSUMPTIONS:result[key]=result['geometry_confirmed']
    return result


def synchronize(progress=None):
    with FileLock(str(w.DATA/'analysis-auto.lock'),timeout=30):
        if not __import__('rspace_connector').status()['enabled']:return {'status':'paused','message':'原生实验同步已暂停，不接续缓存事实的分析'}
        store=Store();nodes={n['id']:n for n in store.nodes()};summary=[]
        for profile in profiles()['records']:
            if not profile['enabled']:continue
            try:revision=lifecycle.capture_automatic(profile['project'])
            except lifecycle.AutomaticStopped:
                summary.append({'status':'paused','reason':'项目已归档，保留接续偏好；恢复后继续。'});continue
            key=KEY+profile['method_id']+':progress';previous=store.cursor(key,{});state={**previous,'status':'waiting_experiment','reason':'等待原生实验完成并明确选择此方法、CSV 与实际条件','checked':w.now()}
            if not profile['method_current'] or not profile['code_current']:
                state.update(status='needs_review',reason='方法内容或计算实现已变化，请重新核对并保存自动接续设置')
                try:
                    with lifecycle.automatic_commit(profile['project'],revision):store.commit_page(key,[],state)
                except lifecycle.AutomaticStopped:state.update(status='paused',reason='项目状态已变化，保留原接续偏好。')
                summary.append(state);continue
            for node in nodes.values():
                latest=store.cursor(KEY+profile['method_id'],{})
                if not latest.get('enabled') or latest.get('revision')!=profile['revision']:break
                fields=node['data'].get('metadata',{})
                if node['owner']!='RSpace' or node['kind']!='ExperimentIndex' or node['data'].get('source_project',node['project'])!=profile['native_project'] or fields.get('method_id')!=profile['method_id'] or node['status'] not in ('COMPLETED','完成'):continue
                event_key=key+':'+node['id'];saved=store.cursor(event_key,{});fingerprint=None
                try:
                    path=_path(fields.get('raw_uri',''))
                    if not path.is_absolute() or path.suffix.lower()!='.csv':raise ValueError('正式记录需要明确的本机 CSV 位置')
                    path=path.resolve();root=Path(profile['root']).resolve()
                    if not path.is_relative_to(root):raise ValueError('CSV 不在已批准目录内')
                    source_identity=w.digest(encode([profile['revision'],node['data'].get('source_modified'),fields]))
                    read_path=path
                    if not path.is_file():
                        snapshot=saved.get('dataset_snapshot')
                        if saved.get('source_identity')!=source_identity or not snapshot:raise ValueError('CSV 文件尚未到达，或来源版本已变化')
                        read_path=(w.ROOT/snapshot['uri']).resolve()
                        if not read_path.is_relative_to((w.ROOT/'数据/数据版本/datasets').resolve()) or not read_path.is_file():raise ValueError('已保存的数据版本缺失，请从备份恢复')
                    if read_path.stat().st_size>2_000_000:raise ValueError('CSV 超过当前配对分析支持的大小，需采用对应批量方法')
                    before=read_path.stat();raw=read_path.read_bytes();after=read_path.stat()
                    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('文件仍在写入，保留等待，不分析半份数据')
                    checksum=w.digest(raw)
                    if read_path!=path and checksum!=saved['dataset_snapshot']['sha256']:raise ValueError('已保存输入的校验值变化，未重建或覆盖')
                    dependencies=_dependencies(node,nodes)
                    versions={node['id']:node['data'].get('source_modified'),**{item['id']:item['data'].get('source_modified') for item in dependencies}}
                    fingerprint=w.digest(encode([profile['revision'],checksum,node['data'].get('source_modified'),fields,dependencies]))
                    if saved.get('fingerprint')==fingerprint and saved.get('status') in ('completed','waiting_conditions','source_changed'):
                        state.update(status=saved['status'],reason=saved.get('reason','此实验已接续，沿用保存的运行与结果'));continue
                    if fields.get('checksum') and fields['checksum'].lower()!=checksum:raise ValueError('原生登记的校验值与到达文件不同，需先核对来源')
                    # Freeze arrived bytes before computation. A failed model
                    # precondition never removes the raw data version.
                    with lifecycle.automatic_commit(profile['project'],revision):
                        dataset=__import__('dataset_store').store_input(raw.decode('utf-8'),profile['project'],path.name)
                        producers=[r['target'] for r in store.relations('VERIFIED') if r['source']==dataset['id'] and r['kind']=='ProducedBy']
                        if any(identity!=node['id'] for identity in producers):raise ValueError('同一数据已登记到其他实验，需要核对其归属；未自动合并来源')
                        existing=store.node(dataset['id'])
                        if existing and existing['project'] not in (profile['project'],'共享'):raise ValueError('数据已在另一项目登记，请先核对共享范围')
                        evidence=[{'source_system':'RSpace','source':node['uri'],'location':'Raw Data URI','sha256':checksum}]
                        if not existing:store.put_node(dataset['id'],'Dataset','DataStorage+DVC',project=profile['project'],uri=dataset['uri'],status='CAPTURED',data={**dataset,'title':path.name,'experiment_id':node['id'],'source_uri':node['uri']})
                        store.relation(dataset['id'],node['id'],'ProducedBy',evidence,mechanical=True)
                        store.commit_page(event_key,[],{'status':'captured','fingerprint':fingerprint,'source_identity':source_identity,'source_versions':versions,'dataset_snapshot':dataset,'experiment_id':node['id'],'source_uri':node['uri'],'checked':w.now()})
                        metadata=_metadata(node,nodes);options={'method_id':profile['method_id'],'method_fingerprint':profile['method_fingerprint'],'metadata':metadata,'columns':profile['columns']}
                        if profile.get('noise_indices') is not None:options['noise_indices']=profile['noise_indices']
                        scientific={k:v for k,v in metadata.items() if k not in ('rspace_record_version','calibration_record_version','sop_record_version')}
                        computation=w.digest(encode([checksum,profile['method_fingerprint'],profile['code_version'],profile['columns'],profile.get('noise_indices'),scientific]))
                        if saved.get('computation_signature')==computation and saved.get('analysis_id'):
                            changes=[{'id':identity,'before':saved.get('source_versions',{}).get(identity),'after':version} for identity,version in versions.items() if saved.get('source_versions',{}).get(identity)!=version]
                            notice={**saved,'status':'source_changed','fingerprint':fingerprint,'source_identity':source_identity,'source_changes':changes,'pending_source_versions':versions,'reason':'正式记录版本已更新，计算输入未变；原运行保留，请核对说明，不重复生成分析报告','checked':w.now()}
                            store.commit_page(event_key,[],notice);state.update(status='source_changed',reason=node['id']+'：'+notice['reason']);continue
                        store.commit_page(event_key,[],{**store.cursor(event_key,{}),'computation_signature':computation,'source_uri':node['uri']})
                    if progress:progress('正在接续 '+node['id']+' 的已核对方法')
                    latest=store.cursor(KEY+profile['method_id'],{})
                    if not latest.get('enabled') or latest.get('revision')!=profile['revision']:break
                    result=__import__('data_analysis').save({'project':profile['project'],'kind':'thz','filename':path.name,'csv':raw.decode('utf-8'),'options':options,'lifecycle_revision':revision})
                    with lifecycle.automatic_commit(profile['project'],revision):store.commit_page(event_key,[],{**store.cursor(event_key,{}),'status':'completed','analysis_id':result['id'],'run_id':result['provenance']['run_id'],'dataset_id':dataset['id'],'qc_status':result['metrics']['qc']['status'],'checked':w.now()})
                    state.update(status='completed',reason='符合条件的实验已接续；结果和来源保存在所属运行',last_success=w.now())
                except lifecycle.AutomaticStopped:
                    state.update(status='paused',reason='项目状态已变化，本次接续停止；原始数据与原运行保留。');break
                except (ValueError,OSError,UnicodeError) as exc:
                    outcome={**store.cursor(event_key,{}),'status':'waiting_conditions','reason':str(exc),'fingerprint':fingerprint,'experiment_id':node['id'],'source_uri':node['uri'],'checked':w.now()}
                    try:
                        with lifecycle.automatic_commit(profile['project'],revision):store.commit_page(event_key,[],outcome)
                        state.update(status='waiting_conditions',reason=node['id']+'：'+str(exc))
                    except lifecycle.AutomaticStopped:
                        state.update(status='paused',reason='项目状态已变化，本次接续停止。');break
            try:
                with lifecycle.automatic_commit(profile['project'],revision):store.commit_page(key,[],state)
            except lifecycle.AutomaticStopped:state.update(status='paused',reason='项目状态已变化，保留接续偏好与已有结果。')
            summary.append(state)
        return {'profiles':summary,'scope':'自动登记计算产物，不自动确认科研解释或根因。'}


def dispatch(start_job):
    if any(p['enabled'] and not lifecycle.archived(p.get('project')) for p in profiles()['records']):return start_job('formal_analysis_update',{})
    return {'status':'disabled'}


def acknowledge(body):
    with FileLock(str(w.DATA/'analysis-auto.lock'),timeout=30):
        store=Store();profile=store.cursor(KEY+str(body.get('method_id')),{});key=KEY+str(body.get('method_id'))+':progress:'+str(body.get('experiment_id'));saved=store.cursor(key,{})
        if saved.get('status')!='source_changed' or saved.get('fingerprint')!=body.get('fingerprint'):raise ValueError('接续记录已变化，请重新核对')
        nodes={n['id']:n for n in store.nodes()};node=nodes.get(body.get('experiment_id'))
        if not node:raise ValueError('正式实验索引已变化')
        fields=node['data'].get('metadata',{});path=_path(fields.get('raw_uri','')).resolve()
        if not path.is_relative_to(Path(profile['root']).resolve()):raise ValueError('来源目录已变化')
        read=path if path.is_file() else (w.ROOT/saved['dataset_snapshot']['uri']).resolve()
        if read!=path and not read.is_relative_to((w.ROOT/'数据/数据版本/datasets').resolve()):raise ValueError('保存的数据位置不符')
        checksum=__import__('backup_crypto').file_digest(read)
        fingerprint=w.digest(encode([profile['revision'],checksum,node['data'].get('source_modified'),fields,_dependencies(node,nodes)]))
        if fingerprint!=saved['fingerprint']:raise ValueError('来源、数据或依赖版本已变化，请先重新同步核对')
        result={**saved,'status':'completed','source_versions':saved.get('pending_source_versions',saved.get('source_versions',{})),'reason':'已核对更新记录，保留原运行与原方法版本','reviewed':w.now()};store.commit_page(key,[],result)
        prefix=KEY+str(body.get('method_id'))+':progress'
        with store.connection() as db:
            pending=[json.loads(row['value']) for row in db.execute('SELECT value FROM cursors WHERE key LIKE ?',(prefix+':%',)) if json.loads(row['value']).get('status') in ('source_changed','waiting_conditions')]
        summary=store.cursor(prefix,{});summary.update(status=pending[0]['status'] if pending else 'completed',reason=pending[0]['reason'] if pending else result['reason'],checked=w.now());store.commit_page(prefix,[],summary)
        with store.connection() as db:store.log(db,'analysis.source_reviewed',key,{'fingerprint':fingerprint})
        return result
