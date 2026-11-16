"""Edit and publish existing n8n schedules without replacing their other nodes."""
from __future__ import annotations
import copy
import json
import re
import sqlite3
import sys
import threading
from contextlib import closing
from datetime import datetime,timezone,timedelta
import workflow as w

BASE = 'http://127.0.0.1:5678'
LOCK = threading.Lock()
REMOVED_DATA_TASKS={'raw_data_scan','validation_run','validation_update','validation_reproduce'}
RETIRED_BACKGROUND = {'生成背景候选','等待 生成背景候选','结果 生成背景候选',
                      '完成 生成背景候选','失败 生成背景候选','停止 生成背景候选'}
POLL_OUTCOMES = {'completed':('completed','skipped'),
                 'failed':('failed','needs_review','partial','waiting')}
POLL_ERROR = '={{ $json.error || ($json.result && $json.result.message) || "任务未完成，请检查科研首页" }}'


def user_jobs():
    from research_store import Store
    return [job for job in Store().jobs() if job['kind'] not in REMOVED_DATA_TASKS]

FIELDS = {'daily_time','sync_enabled','daily_enabled','ai_enabled','discover_enabled','acquire_enabled',
          'sync_minutes','radar_source_limit','radar_recent_days','radar_background_days'}
DEFAULTS = {'daily_time':'08:30','sync_enabled':True,'daily_enabled':True,'ai_enabled':True,
            'discover_enabled':True,'acquire_enabled':True,'sync_minutes':1,
            'radar_source_limit':200,'radar_recent_days':90,'radar_background_days':90}


def client():
    sys.path.insert(0, str(w.ROOT/'工具/n8n'))
    from setup_flows import session
    return session()


def validate(values):
    if not isinstance(values, dict) or set(values)-FIELDS: raise ValueError('流程仅支持时间、间隔与已提供步骤的开关。')
    result = {**DEFAULTS, **values}
    if not isinstance(result['daily_time'], str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', result['daily_time']): raise ValueError('请选择有效的每日运行时间。')
    numeric={'sync_minutes','radar_source_limit','radar_recent_days','radar_background_days'}
    if any(type(result[key]) is not bool for key in FIELDS-{'daily_time'}-numeric): raise ValueError('流程开关格式无效。')
    if type(result['sync_minutes']) is not int or not 1 <= result['sync_minutes'] <= 60: raise ValueError('同步间隔为 1–60 分钟。')
    if type(result['radar_source_limit']) is not int or not 10 <= result['radar_source_limit'] <= 200: raise ValueError('每个来源每日上限为 10–200 条。')
    for key,label in (('radar_recent_days','直接证据和方法邻近'),('radar_background_days','背景对照')):
        if type(result[key]) is not int or not 7 <= result[key] <= 365: raise ValueError(label+'保留期限为 7–365 天。')
    return result


def registered():
    flows = w.read_json(w.ROOT/'工具/n8n/流程登记.json', {}).get('flows', [])
    if len(flows) != 2: raise ValueError('未找到两个已登记的本机流程。')
    return flows


def fetch(c):
    result = []
    for item in registered():
        response = c.get(BASE+'/rest/workflows/'+item['id'], timeout=15); response.raise_for_status()
        result.append(response.json()['data'])
    return result


def snapshot(flows):
    values = dict(DEFAULTS)
    explicit_radar_ai=None
    for flow in flows:
        daily = any(n['name'] == '每日更新' for n in flow['nodes'])
        values['daily_enabled' if daily else 'sync_enabled'] = bool(flow.get('active'))
        for node in flow['nodes']:
            p = node.get('parameters', {})
            if node['name'] == '每日更新':
                expression = p.get('rule', {}).get('interval', [{}])[0].get('expression', '')
                match = re.fullmatch(r'0 (\d{1,2}) (\d{1,2}) \* \* \*', expression)
                if match: values['daily_time'] = f'{int(match[2]):02}:{int(match[1]):02}'
            if node['name'] == '每分钟同步': values['sync_minutes'] = p.get('rule', {}).get('interval', [{}])[0].get('minutesInterval', 1)
            if daily and node['name'] in ('生成背景候选', '发现新论文候选', '获取相关开放全文'):
                try: body = json.loads(p.get('jsonBody', '{}'))
                except (ValueError, TypeError): body = {}
                key = {'生成背景候选': 'ai_enabled', '发现新论文候选': 'discover_enabled', '获取相关开放全文': 'acquire_enabled'}[node['name']]
                values[key] = body.get('enabled', True) is not False and not node.get('disabled')
                if node['name']=='发现新论文候选':
                    if type(body.get('ai_enabled')) is bool:explicit_radar_ai=body['ai_enabled']
                    for field in ('radar_source_limit','radar_recent_days','radar_background_days'):
                        if type(body.get(field)) is int:values[field]=body[field]
    if explicit_radar_ai is not None:values['ai_enabled']=explicit_radar_ai
    fingerprint = w.digest(json.dumps([{'id': f['id'], 'version': f['versionId'], 'active': f.get('active'), 'published': f.get('activeVersionId')} for f in flows], sort_keys=True))
    return {'values': values, 'fingerprint': fingerprint, 'ready': True, 'timezone': 'Asia/Shanghai', 'published': all(not f.get('active') or f.get('activeVersionId') == f['versionId'] for f in flows), 'updated': w.now()}


def settings():
    with client() as c:
        result = snapshot(fetch(c))
    w.write_json(w.DATA/'流程设置.json', result)
    return result


def cached():
    return w.read_json(w.DATA/'流程设置.json', {'values': dict(DEFAULTS), 'ready': False, 'message': '打开流程设置可读取实际运行配置。'})


def native_schedule():
    """Read published local workflow metadata; never open the database for writing."""
    path = w.ROOT/'工具/n8n/data/.n8n/database.sqlite'
    if not path.is_file():
        return {}
    try:
        registrations = registered()
        ids = [item['id'] for item in registrations]
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                'SELECT w.id,w.name,w.active,w.isArchived,w.versionId,w.activeVersionId,h.nodes '
                'FROM workflow_entity w LEFT JOIN workflow_history h '
                'ON h.versionId=w.activeVersionId AND h.workflowId=w.id '
                'WHERE w.id IN (?,?)', ids).fetchall()
        result = {}
        for row in rows:
            flow = dict(row)
            registered_name = next(item['name'] for item in registrations if item['id']==flow['id'])
            action = 'discover' if '每日' in registered_name else 'sync'
            flow['nodes'] = json.loads(flow['nodes']) if flow['nodes'] else []
            flow['active'] = bool(flow['active'] and not flow['isArchived'])
            trigger = '每日更新' if action=='discover' else '每分钟同步'
            present = any(node.get('name')==trigger and not node.get('disabled') for node in flow['nodes'])
            result[action] = {'active':bool(flow['active']),'configured':present,'flow':flow}
        return result
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
        return {}


def effective(native=None):
    values = dict(cached()['values'])
    for action, entry in (native_schedule() if native is None else native).items():
        enabled = 'daily_enabled' if action=='discover' else 'sync_enabled'
        values[enabled] = entry['active']
        if entry['configured']:
            live = snapshot([entry['flow']])['values']
            fields = (FIELDS-{'sync_enabled','sync_minutes'} if action=='discover' else {'sync_minutes'})
            values.update({field:live[field] for field in fields})
    return values


def permitted(action,values=None):
    values=effective() if values is None else values
    if action=='sync':return bool(values.get('sync_enabled',True))
    # Installed workflows still poll their old step to completion. Its only
    # effect is now a skipped receipt; manual previews use their own route.
    if action in ('ai_update','background'):return False
    fields={'discover':'discover_enabled','acquire_candidates':'acquire_enabled'}
    if action in fields:return bool(values.get('daily_enabled') and values.get(fields[action]))
    if action=='weekly':return bool(values.get('daily_enabled'))
    return bool(values.get('sync_enabled') or values.get('daily_enabled'))


def schedule_key(action,local=None, *, values=None):
    local=local or datetime.now(timezone(timedelta(hours=8)))
    if action in ('sync','versions'):
        interval=max(1,min(60,int((effective() if values is None else values).get('sync_minutes',1))))
        minute=int(local.timestamp()//60)
        local=datetime.fromtimestamp((minute-minute%interval)*60,local.tzinfo)
    slot=local.strftime('%Y-%m-%d:%H:%M') if action in ('sync','discover','versions') else local.date().isoformat()
    return 'schedule:'+action+':'+slot


def continue_daily(start_job,local, *, values=None):
    """Resume the same enabled daily children when the native clock is absent."""
    values=effective() if values is None else values
    if not values.get('daily_enabled') or local.strftime('%H:%M')<values.get('daily_time','08:30'):return {}
    return {action:start_job(action,{'action':action,'_scheduled':True,
            'idempotency_key':schedule_key(action,local,values=values)})['job_id']
            for action in ('acquire_candidates','versions') if permitted(action,values)}


def dispatch_independent(start_job):
    """Check each owner's existing switch and retry state outside paper sync."""
    from research_store import Store
    store=Store();results={};failures=[]
    owners=(('canvas_organize','canvas_organization','scheduled_dispatch'),
            ('rspace_sync','rspace_connector','dispatch'),
            ('data_remote_sync','data_remote','dispatch'),
            ('formal_analysis_update','analysis_automation','dispatch'))
    def enqueue(kind,data=None,**kwargs):
        body=dict(data or {})
        if not kwargs.get('resume_id'):
            body.setdefault('idempotency_key','independent:'+kind+':'+datetime.now(timezone.utc).strftime('%Y-%m-%d:%H:%M'))
        return start_job(kind,body,**kwargs)
    for kind,module,function in owners:
        try:
            with store.connection() as db:
                active=db.execute("SELECT id,status FROM jobs WHERE kind=? AND status IN ('queued','running') LIMIT 1",(kind,)).fetchone()
            if active:
                results[kind]={'status':active['status'],'job_id':active['id']}
                continue
            results[kind]=getattr(__import__(module),function)(enqueue)
        except Exception as error:
            results[kind]={'status':'deferred','error_type':type(error).__name__}
            failures.append(kind)
    return {'status':'partial' if failures else 'checked','checks':results,'failures':failures}


def payload(flow):
    return {key: copy.deepcopy(flow[key]) for key in ('name', 'nodes', 'connections', 'settings')}


def poll_outcome(status):
    accepted = json.dumps(POLL_OUTCOMES[status], ensure_ascii=False)
    return '={{ '+accepted+'.includes($json.status) ? "'+status+'" : $json.status }}'


def migrate_runtime_definition(definition):
    """Remove the generated background branch and keep unrelated custom nodes."""
    nodes = definition['nodes']
    connections = definition['connections']
    present = {node['name'] for node in nodes} & RETIRED_BACKGROUND
    if present:
        if present != RETIRED_BACKGROUND:
            raise ValueError('旧背景节点不完整，请先核对原生流程。')
        retired_done = connections.get('完成 生成背景候选',{}).get('main',[])
        if not retired_done or not retired_done[0] or any(edge['node'] in present for edge in retired_done[0]):
            raise ValueError('旧背景成功分支无法安全接续，请先核对原生流程。')
        downstream = copy.deepcopy(retired_done[0])
        for name, connection in connections.items():
            for output, branches in connection.items():
                if name in present:
                    retained = branches[1:] if name=='完成 生成背景候选' and output=='main' else branches
                    if any(edge['node'] not in present for branch in retained for edge in branch):
                        raise ValueError('旧背景节点有自定义出边，请先核对原生流程。')
                if name not in present:
                    for index, branch in enumerate(branches):
                        remapped = []
                        for edge in branch:
                            if edge['node']=='生成背景候选' and output=='main':
                                remapped.extend(item for item in downstream if item not in remapped)
                            elif edge['node'] in present:
                                raise ValueError('旧背景节点有自定义入边，请先核对原生流程。')
                            else:
                                remapped.append(edge)
                        branches[index] = remapped
        for name in present:
            connections.pop(name,None)
        definition['nodes'] = nodes = [node for node in nodes if node['name'] not in present]
    for node in nodes:
        name = node['name']
        parameters = node.get('parameters',{})
        if name.startswith(('完成 ','失败 ')) and node['type']=='n8n-nodes-base.if':
            expected = 'completed' if name.startswith('完成 ') else 'failed'
            checks = parameters.get('conditions',{}).get('conditions',[])
            for check in checks:
                if check.get('leftValue')=='={{ $json.status }}' and check.get('rightValue')==expected:
                    check['leftValue'] = poll_outcome(expected)
        if name.startswith('停止 ') and node['type']=='n8n-nodes-base.stopAndError':
            if parameters.get('errorMessage')=='={{ $json.error || "任务未完成，请检查科研首页" }}':
                parameters['errorMessage'] = POLL_ERROR
    return definition


def publish(c, identifier, definition, enabled):
    response = c.patch(BASE+'/rest/workflows/'+identifier, json=definition, timeout=25); response.raise_for_status()
    saved = response.json()['data']
    if enabled:
        response = c.post(BASE+'/rest/workflows/'+identifier+'/activate', json={'versionId': saved['versionId'], 'name': '科研区页面确认的运行设置', 'description': '保留原节点，更新运行时间与步骤开关'}, timeout=30)
    else:
        response = c.post(BASE+'/rest/workflows/'+identifier+'/deactivate', json={}, timeout=30)
    response.raise_for_status()


def save(values, fingerprint):
    values = validate(values)
    with LOCK, client() as c:
        flows = fetch(c)
        if snapshot(flows)['fingerprint'] != fingerprint: raise ValueError('流程已在其他窗口修改，请重新打开设置。')
        backup = w.DATA/'流程备份'/w.now().replace(':', '-').replace('.', '-')
        changed = []
        try:
            for flow in flows:
                definition = migrate_runtime_definition(payload(flow))
                daily = any(n['name'] == '每日更新' for n in definition['nodes'])
                definition['settings']['timezone'] = 'Asia/Shanghai'
                for node in definition['nodes']:
                    p = node.get('parameters', {})
                    if node['name'] == '每日更新':
                        hour, minute = map(int, values['daily_time'].split(':'))
                        p['rule'] = {'interval': [{'field': 'cronExpression', 'expression': f'0 {minute} {hour} * * *'}]}
                    elif node['name'] == '每分钟同步':
                        p['rule'] = {'interval': [{'field': 'minutes', 'minutesInterval': values['sync_minutes']}]}
                    if daily and node['name'] in ('发现新论文候选', '获取相关开放全文'):
                        action, key = {'发现新论文候选': ('discover', 'discover_enabled'), '获取相关开放全文': ('acquire_candidates', 'acquire_enabled')}[node['name']]
                        body={'action':action,'enabled':values[key]}
                        if node['name']=='发现新论文候选':
                            body.update(ai_enabled=values['ai_enabled'],radar_source_limit=values['radar_source_limit'],
                                        radar_recent_days=values['radar_recent_days'],
                                        radar_background_days=values['radar_background_days'])
                        p['jsonBody']=json.dumps(body,ensure_ascii=False)
                w.write_json(backup/(flow['id']+'.json'), payload(flow))
                changed.append(flow)
                publish(c, flow['id'], definition, values['daily_enabled' if daily else 'sync_enabled'])
        except Exception:
            recovered = True
            for flow in reversed(changed):
                try: publish(c, flow['id'], payload(flow), bool(flow.get('active')))
                except Exception: recovered = False
            raise ValueError('流程设置未完成；'+('已恢复修改前的配置，请重试。' if recovered else '原配置已备份，请检查自动流程的运行状态。')) from None
        current = fetch(c)
        for flow in current: w.write_json(w.ROOT/'工具/n8n/flows'/(flow['id']+'.json'), {**payload(flow), 'id': flow['id']})
        registration = w.ROOT/'工具/n8n/流程登记.json'
        saved = w.read_json(registration,{})
        versions = {flow['id']:flow['versionId'] for flow in current}
        for item in saved.get('flows',[]):
            if item['id'] in versions:
                item['versionId'] = versions[item['id']]
        if saved.get('flows'):
            w.write_json(registration,saved)
        result = snapshot(current); w.write_json(w.DATA/'流程设置.json', result)
        return result


def migrate_published_runtime():
    """Use the existing version-bound save and rollback for the installed flows."""
    with client() as c:
        flows = fetch(c)
    current = snapshot(flows)
    if not current['published']:
        raise ValueError('有尚未发布的原生流程修改，请先处理这些修改。')
    if not any(payload(flow)!=migrate_runtime_definition(payload(flow)) for flow in flows):
        return {'status':'unchanged','flows':len(flows)}
    result = save(current['values'],current['fingerprint'])
    return {'status':'completed','flows':len(flows),'published':result['published']}


def diagram():
    cfg = cached()['values']
    admin = __import__('administrator_state').settings(effective=False)
    daily = ('每日 '+cfg['daily_time']) if cfg['daily_enabled'] else '每日积累流程已暂停'
    daily += '<br/>'+('发现新论文候选' if cfg['discover_enabled'] else '候选发现已跳过')
    daily += '<br/>'+('获取相关开放全文' if cfg['acquire_enabled'] else '全文获取已跳过')
    daily += '<br/>'+('AI 整理雷达线索' if cfg['ai_enabled'] else 'AI 整理已暂停')
    return '\n'.join(['flowchart LR', 'subgraph IN["01 · 资料积累"]', 'direction TB',
        'A["Zotero · 论文与附件"] --> B["'+('每 '+str(cfg['sync_minutes'])+' 分钟同步' if cfg['sync_enabled'] else '定时同步已暂停')+'"]', 'B --> C["全文检索 · 原页阅读"]', 'C -.-> T["'+daily+'"]', 'end',
        'subgraph AI["02 · 整理与分析"]', 'direction TB', 'D["'+('管理员检查新增资料' if admin.get('enabled') else '管理员自动任务已暂停')+'"] --> E["分类 · 摘要 · 关联草稿"]', 'E --> F["技能分析 · 方向候选"]', 'end',
        'subgraph SAVE["03 · 核查后持续积累"]', 'direction TB', 'G["核查来源与阅读范围"] --> H["确认正式修改"]', 'H --> I["背景 · 项目 · 研究主线"]', 'I --> J["视图刷新 · 版本记录"]', 'end',
        'IN --> AI', 'AI --> SAVE',
        'style IN fill:#f5f8ff,stroke:#bac9e5,color:#304567', 'style AI fill:#fffaf1,stroke:#e0d0aa,color:#756038', 'style SAVE fill:#f3faf6,stroke:#b6d5c3,color:#365b4e',
        'classDef sources fill:#edf2ff,stroke:#a4b8dd,color:#304567,rx:8,ry:8', 'classDef drafts fill:#fff6e4,stroke:#dac394,color:#756038,rx:8,ry:8',
        'classDef saved fill:#edf7f3,stroke:#a1c8b5,color:#365b4e,rx:8,ry:8', 'class A,B,C sources', 'class D,E,F,T drafts', 'class G,H,I,J saved'])
