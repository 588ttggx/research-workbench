"""Read-only RSpace ELN/Inventory API projection; native records keep authority.

Official schemas: /resources/rspace_api_specs_2_23_0.yaml and
/resources/rspace_api_inventory_specs_2_24_0.yaml. No native database is read.
The API key is protected locally and never enters jobs, snapshots or responses.
"""
from datetime import datetime,timezone,timedelta
import html
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from filelock import FileLock
import requests
import win32crypt
import workflow as w
from research_store import Store,encode

KEY='connector:rspace'
KINDS={'ExperimentIndex':'EXP','InstrumentIndex':'INST','CalibrationIndex':'CAL','BatchIndex':'B','SOP':'SOP'}
DEFAULT_FIELDS={'id':'Unified ID','project':'Project ID','status':'Status','sample':'Sample ID',
 'batch':'Batch ID','instrument':'Instrument ID','calibration':'Calibration ID','sop':'SOP ID',
 'dataset':'Dataset ID','raw_uri':'Raw Data URI','checksum':'Raw Data SHA256',
 'start':'Start Time','end':'End Time','valid_until':'Valid Until'}
DEFAULT_FIELDS.update(independent_sample_id='Independent Sample ID',preparation_id='Preparation ID',scan_id='Scan ID',
 measurement_date='Measurement Date',time_unit='Time Unit',signal_unit='Signal Unit',thickness_mm='Thickness mm',
 temperature_celsius='Temperature Celsius',humidity_percent='Humidity Percent',instrument_state='Instrument State')
DEFAULT_FIELDS.update(method_id='Method ID',dynamic_range_db='Dynamic Range dB',water_vapor_metric='Water Vapor Metric',
 reference_pairing_confirmed='样品参考配对已确认',geometry_confirmed='方法适用条件已确认')
STREAMS={'documents':('/api/v1','documents'),'samples':('/api/inventory/v1','samples'),
 'containers':('/api/inventory/v1','containers')}
FACT_RELATIONS={'sample':'Uses','batch':'PreparedFrom','instrument':'MeasuredWith',
 'calibration':'CalibratedBy','sop':'FollowsSOP','dataset':'ProducedBy'}


def _lock():
    w.DATA.mkdir(parents=True,exist_ok=True)
    return FileLock(str(w.DATA/'rspace.lock'),timeout=30)


def _secret(value=None):
    path=w.DATA/'rspace-local.dpapi'
    if value is not None:
        w.DATA.mkdir(parents=True,exist_ok=True)
        path.write_bytes(win32crypt.CryptProtectData(value.encode(),'RSpace Connector',None,None,None,4))
        return value
    return win32crypt.CryptUnprotectData(path.read_bytes(),None,None,None,0)[1].decode() if path.is_file() else ''


def _base(value):
    if not isinstance(value,str):raise ValueError('请输入 RSpace 实例地址')
    parsed=urlsplit(value.strip())
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('实例地址需为 http(s) 地址，不包含账号、密钥或查询参数')
    if parsed.scheme=='http' and parsed.hostname not in ('127.0.0.1','localhost','::1'):
        raise ValueError('远程 RSpace 使用 HTTPS；本机实例可以使用 HTTP')
    return value.strip().rstrip('/')


def status():
    config=Store().cursor(KEY,{'enabled':False,'revision':0,'base':'','forms':{},'fields':DEFAULT_FIELDS,'inventory':True})
    config['fields']={**DEFAULT_FIELDS,**config.get('fields',{})}
    progress={**Store().cursor(KEY+':sync',{}),**Store().cursor(KEY+':retry',{})}
    return {**config,'deployment':__import__('rspace_runtime').deployment(),'has_key':(w.DATA/'rspace-local.dpapi').is_file(),'progress':progress,
            'status':'configured' if config['enabled'] else 'paused' if config.get('base') else 'not_connected',
            'message':'正式正文在 RSpace 修改，工作区自动同步索引、状态与明确的关系。',
            'kinds':list(KINDS),'field_defaults':DEFAULT_FIELDS,'records':len([n for n in Store().nodes() if n['owner']=='RSpace'])}


def configure(body):
    with _lock():
        old=status()
        if body.get('revision')!=old['revision']:raise ValueError('连接设置已变化，请刷新后再保存')
        if type(body.get('enabled')) is not bool:raise ValueError('连接状态无效')
        base=_base(body.get('base',old['base']));forms=body.get('forms',old['forms']);fields=body.get('fields',old['fields'])
        if not isinstance(forms,dict) or len(forms)>50 or any(not re.fullmatch(r'\d+',key) or kind not in KINDS for key,kind in forms.items()):raise ValueError('请选择明确的 RSpace 表单 ID 和科研索引类型')
        if not isinstance(fields,dict) or set(fields)-set(DEFAULT_FIELDS) or any(not isinstance(v,str) or not 1<=len(v.strip())<=100 for v in fields.values()):raise ValueError('字段名称无效')
        secret=body.get('api_key')
        if secret is not None and (not isinstance(secret,str) or not 1<=len(secret.strip())<=1000):raise ValueError('API Key 无效；留空时沿用本机已保存的密钥')
        if base!=old.get('base') and not secret:raise ValueError('更换实例需要填写该实例的 API Key')
        if body['enabled'] and not secret and not _secret():raise ValueError('请在本机填写 RSpace API Key')
        if type(body.get('inventory',old['inventory'])) is not bool:raise ValueError('Inventory 设置无效')
        if secret:_secret(secret.strip())
        config={'enabled':body['enabled'],'revision':old['revision']+1,'base':base,'forms':forms,
                'fields':{**DEFAULT_FIELDS,**fields},'inventory':body.get('inventory',old['inventory']),'updated':w.now()}
        Store().commit_page(KEY,[],config)
        if any(old.get(key)!=config[key] for key in ('base','forms','fields','inventory')):Store().commit_page(KEY+':sync',[],{})
        Store().commit_page(KEY+':retry',[],{})
        return status()


def _get(config,path,params=None):
    try:
        response=requests.get(config['base']+path,params=params,headers={'apiKey':_secret(),'Accept':'application/json'},timeout=(10,40),allow_redirects=False)
    except requests.RequestException:raise ValueError('RSpace 暂不可访问；保留现有索引与同步进度') from None
    if response.status_code in (401,403):raise ValueError('RSpace 访问未获允许，请核对 API Key 与原生账户权限')
    if response.status_code==429:raise ValueError('RSpace 暂时限流；保留进度，稍后接续')
    if not response.ok:raise ValueError('RSpace 接口暂未完成（HTTP '+str(response.status_code)+'）')
    try:value=response.json()
    except ValueError:raise ValueError('RSpace 没有返回有效 API 数据，请核对实例地址') from None
    if not isinstance(value,dict):raise ValueError('RSpace API 返回结构不符，未推进同步')
    return value


def inspect():
    config=status()
    if not config['base'] or not config['has_key']:raise ValueError('请先保存实例地址和 API Key')
    data=_get(config,'/api/v1/forms',{'pageSize':50,'pageNumber':0})
    forms=data.get('forms')
    if not isinstance(forms,list):raise ValueError('当前实例没有返回可用表单列表，请核对版本与权限')
    cache=Store().cursor(KEY+':forms',{})
    for form in forms:
        if form.get('stableId'):cache[config['base']+'#'+str(form['id'])]=str(form['stableId'])
    Store().commit_page(KEY+':forms',[],cache)
    return {'forms':[{'id':str(f['id']),'name':f.get('name','未命名表单')} for f in forms if type(f.get('id')) is int],
            'message':'已连接原生 API。选择实验、仪器、校准或 SOP 对应的正式表单后保存；其他表单不会被当成实验。'}


def _fields(record):
    result={}
    for field in [*record.get('fields',[]),*record.get('extraFields',[])]:
        if isinstance(field,dict) and isinstance(field.get('name'),str):
            text=re.sub('<[^>]*>',' ',str(field.get('content') or ''))
            result[field['name']]=html.unescape(text).strip()
    return result


def _project(value):
    if not value:return '共享'
    if len(value)>120 or re.search(r'[\x00-\x1f/\\]',value):raise ValueError('RSpace 项目字段包含无效内容，请在原生记录中更正')
    return value


def _form_kind(config,form):
    identity=str(form.get('id',''));stable=form.get('stableId');cache=Store().cursor(KEY+':forms',{})
    direct=config['forms'].get(identity)
    if direct:
        if stable and cache.get(config['base']+'#'+identity)!=str(stable):
            cache[config['base']+'#'+identity]=str(stable);Store().commit_page(KEY+':forms',[],cache)
        return direct
    if stable:
        matches={kind for identifier,kind in config['forms'].items() if cache.get(config['base']+'#'+identifier)==str(stable)}
        if len(matches)>1:raise ValueError('同一原生表单被映射成多个类型，请核对设置')
        if matches:return matches.pop()
    return None


def _import(config,stream,record):
    if type(record.get('id')) is not int or not re.fullmatch(r'[A-Z]{2}\d+',str(record.get('globalId',''))):raise ValueError('原生对象缺少有效 External ID，未生成科研对象')
    if stream=='documents':
        kind=_form_kind(config,record.get('form') or {})
        if not kind:return None
        prefix=KINDS[kind]
    else:kind,prefix=('SampleIndex','S') if stream=='samples' else ('Container','CONT')
    values=_fields(record);mapping=config['fields'];facts={k:values.get(name,'') for k,name in mapping.items()}
    store=Store();external=config['base']+'#'+record['globalId'];old=next((n for n in store.nodes() if n['owner']=='RSpace' and n['external_id']==external),None)
    unified=facts.pop('id')
    if unified and (len(unified)>120 or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]+',unified)):raise ValueError('原生统一 ID 字段无效，请更正后同步')
    if old and unified and old['id']!=unified:raise ValueError('同一原生对象的统一 ID 发生变化，原身份保留；请先核查映射')
    identifier=old['id'] if old else unified or store.allocate(prefix)
    existing=store.node(identifier)
    if existing and (existing['owner']!='RSpace' or existing['external_id']!=external):raise ValueError('统一 ID 已属于其他对象，未覆盖现有记录')
    native_project=_project(facts.pop('project'));project=store.cursor('rspace:project-map',{}).get(native_project,native_project);status='DELETED_AT_SOURCE' if record.get('deleted') else facts.pop('status') or 'RECORDED'
    content={'title':record.get('name') or record['globalId'],'source_system':'RSpace','global_id':record['globalId'],
             'api_uri':config['base']+STREAMS[stream][0]+'/'+stream+'/'+str(record['id']),
             'source_modified':record.get('lastModified'),'source_version':record.get('version'),
             'signed':record.get('signed'),'metadata':facts,'index_only':True,
             'source_project':native_project,'scope':'原生实验事实索引；不复制 ELN 正文，不表示科学结论已通过审核。'}
    node=store.put_node(identifier,kind,'RSpace',external_id=external,project=project,
                        uri=config['base']+'/globalId/'+record['globalId'],status=status,data=content,
                        expected=old['revision'] if old else None)
    return node


def _relations(config):
    store=Store();nodes={n['id']:n for n in store.nodes()};unresolved=[];desired=set();uris=set()
    for node in nodes.values():
        if node['owner']!='RSpace' or not node['external_id'].startswith(config['base']+'#'):continue
        uris.add(node['uri'])
        if node['status']=='DELETED_AT_SOURCE':continue
        for field,kind in FACT_RELATIONS.items():
            value=node['data']['metadata'].get(field)
            if not value:continue
            targets=[x.strip() for x in re.split('[,;\n]',value) if x.strip()]
            for target in targets:
                if target not in nodes:
                    mapped=[n['id'] for n in nodes.values() if n['owner']=='RSpace' and n.get('external_id','').startswith(config['base']+'#') and n['data'].get('global_id')==target]
                    if len(mapped)==1:target=mapped[0]
                if target not in nodes:unresolved.append({'source':node['id'],'field':field,'target':target});continue
                source,destination=(target,node['id']) if field=='dataset' else (node['id'],target)
                evidence=[{'source_system':'RSpace','source':node['uri'],'location':config['fields'][field],
                           'version':node['data']['source_modified'],'authority_field':True}]
                # Facts from explicitly mapped native fields, never AI inference.
                identity='REL-'+__import__('hashlib').sha256(encode([source,destination,kind]).encode()).hexdigest()[:20]
                desired.add(identity)
                with store.connection() as db:
                    previous=db.execute('SELECT * FROM relations WHERE id=?',(identity,)).fetchone()
                    if previous and not any(e.get('authority_field') and e.get('source')==node['uri'] for e in json.loads(previous['evidence'])):
                        unresolved.append({'source':node['id'],'field':field,'target':target,'reason':'保留已有人工关系，待核对'});continue
                    if previous and previous['evidence']==encode(evidence) and previous['status']=='VERIFIED':continue
                    if previous:db.execute('UPDATE relations SET evidence=?,status=\'VERIFIED\',revision=revision+1,updated=? WHERE id=?',(encode(evidence),w.now(),identity))
                    else:db.execute('INSERT INTO relations(id,source,target,kind,status,evidence,conditions,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',(identity,source,destination,kind,'VERIFIED',encode(evidence),'原生字段记录的机械关系；不代表科研支持关系',w.now(),w.now()))
                    Store.log(db,'rspace.relation',identity,{'field':field,'authority':'RSpace'})
    with store.connection() as db:
        for edge in db.execute('SELECT * FROM relations').fetchall():
            if edge['id'] not in desired and edge['status']!='REJECTED' and any(e.get('authority_field') and e.get('source') in uris for e in json.loads(edge['evidence'])):
                db.execute("UPDATE relations SET status='REJECTED',revision=revision+1,updated=? WHERE id=?",(w.now(),edge['id']))
                Store.log(db,'rspace.relation_withdrawn',edge['id'],{'reason':'原生字段已移除或对象已在来源删除','previous_evidence':json.loads(edge['evidence'])})
    return unresolved


def _synchronize(progress=None):
    with _lock():
        config=status()
        if not config['enabled']:return {'status':'skipped','message':'RSpace 尚未连接或自动同步已暂停'}
        store=Store();cursor=store.cursor(KEY+':sync',{})
        if cursor.get('revision')!=config['revision']:cursor={'revision':config['revision'],'cycle_started':w.now(),'streams':{},'completed':[]}
        if cursor.get('finished'):cursor={'revision':config['revision'],'cycle_started':w.now(),'streams':{},'completed':[],**{k:cursor[k] for k in ('last_success','last_full_check') if k in cursor}}
        full=not cursor.get('last_full_check') or datetime.now(timezone.utc)-datetime.fromisoformat(cursor['last_full_check'])>timedelta(days=7)
        threshold=None if full or not cursor.get('last_success') else datetime.fromisoformat(cursor['last_success'])-timedelta(minutes=10)
        count=0
        for stream,(base,key) in STREAMS.items():
            if stream in cursor['completed'] or stream!='documents' and not config['inventory']:continue
            page=cursor['streams'].get(stream,0)
            for _ in range(10):
                if progress:progress('正在同步 RSpace '+{'documents':'正式记录','samples':'样品','containers':'容器'}[stream]+' · 第 '+str(page+1)+' 页')
                params={'pageNumber':page,'pageSize':50,'orderBy':'lastModified desc' if stream=='documents' else 'modificationDate desc'}
                if stream!='documents':params['deletedItems']='INCLUDE'
                data=_get(config,base+'/'+stream,params)
                rows=data.get(key)
                if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):raise ValueError('RSpace 分页结构不符，当前页未记为完成')
                reached=False
                for summary in rows:
                    if type(summary.get('id')) is not int:raise ValueError('原生分页项缺少有效 ID，当前页未推进')
                    if threshold and summary.get('lastModified'):
                        try:modified=datetime.fromisoformat(summary['lastModified'].replace('Z','+00:00'))
                        except (ValueError,TypeError):raise ValueError('原生修改时间无效，未推进同步游标') from None
                        if modified<threshold:reached=True;break
                    if stream=='documents' and not _form_kind(config,summary.get('form') or {}):continue
                    detail=_get(config,base+'/'+stream+'/'+str(summary['id']))
                    node=_import(config,stream,detail);count+=bool(node)
                page+=1;cursor['streams'][stream]=page
                if reached or len(rows)<50 or page*50>=data.get('totalHits',float('inf')):
                    cursor['completed'].append(stream);store.commit_page(KEY+':sync',[],cursor);break
                store.commit_page(KEY+':sync',[],cursor)
            else:return {'status':'partial','records':count,'message':'已保存分页进度，后续同步事件继续；尚未推进成功时间'}
        unresolved=_relations(config)
        cursor.update(finished=True,last_success=cursor['cycle_started'],unresolved=unresolved)
        if full:cursor['last_full_check']=cursor['cycle_started']
        store.commit_page(KEY+':sync',[],cursor)
        return {'status':'completed','records':count,'unresolved':unresolved,'last_success':cursor['last_success']}


def synchronize(progress=None):
    try:
        result=_synchronize(progress);Store().commit_page(KEY+':retry',[],{});return result
    except ValueError as exc:
        before=Store().cursor(KEY+':retry',{});failures=before.get('failures',0)+1
        Store().commit_page(KEY+':retry',[],{'last_error':str(exc),'failures':failures,'retry_after':(datetime.now(timezone.utc)+timedelta(minutes=min(60,2**min(failures,5)))).isoformat()})
        raise


def dispatch(start_job):
    config=status()
    if not config['enabled']:return {'status':'not_connected'}
    retry=config['progress'].get('retry_after')
    if retry and datetime.now(timezone.utc)<datetime.fromisoformat(retry):return {'status':'waiting','message':'来源暂不可用，等待退避后自动接续'}
    return start_job('rspace_sync',{'idempotency_key':'rspace:'+str(config['revision'])+':'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M')})
