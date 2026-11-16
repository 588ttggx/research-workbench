"""Project-scoped projections of existing area owners, without native fact writes."""
import json
from filelock import FileLock
import workflow as w
import workspace_catalog as catalog
import project_profiles as profiles
from research_store import Store, encode

WATCH_FIELDS={'query','criteria','include_groups','provider_queries','wos_query','original_intent','name'}


def watch(identifier,project):
    import research_radar
    rule=next((r for r in research_radar.settings()['rules'] if r['id']==identifier and r.get('project')==project),None)
    if not rule:raise ValueError('关注规则已移除或退出本项目。')
    return rule


def fingerprint(value):return w.digest(encode(value))


def validate_watch_sources(project,rule):
    import project_materials
    documents={d['id']:d for d in catalog.rows(reconcile_records=False)}
    selected=project_materials.selected_document_ids(project)
    for identifier in rule.get('source_document_ids',[]):
        doc=documents.get(identifier)
        if not doc or doc.get('archived') or doc.get('visibility')=='system' or (doc.get('project')!=project and identifier not in selected):
            raise ValueError('关注依据已退出本项目范围或已归档，请重新核对依据关联；原设置保留。')


def bind_watch(data):
    project=data.get('project') or '山药'
    with profiles.lifecycle_lock(project):
        if profiles.archived(project):raise ValueError('项目已归档，请先恢复。')
        import research_radar,project_materials
        current=research_radar.settings()
        if data.get('revision')!=current['revision']:raise ValueError('关注设置已变化，请重新打开。')
        rule=watch(data.get('rule_id'),project)
        if data.get('action')=='remove':
            identifier=data.get('source_id')
            updated={**rule,'source_document_ids':[i for i in rule.get('source_document_ids',[]) if i!=identifier],
                     'source_versions':{i:v for i,v in rule.get('source_versions',{}).items() if i!=identifier}}
            return research_radar.save({'revision':current['revision'],'rules':[updated if r['id']==rule['id'] else r for r in current['rules']]})
        if data.get('action') not in (None,'add'):raise ValueError('请选择关联或移除依据。')
        source=catalog.detail(data.get('source_id'))
        if source.get('project')!=project and source['id'] not in project_materials.selected_document_ids(project):
            raise ValueError('请先选用这份资料，再绑定本项目关注。')
        if source.get('archived') or source.get('visibility')=='system':raise ValueError('请选择当前可用的科研资料。')
        ids=list(dict.fromkeys([*rule.get('source_document_ids',[]),source['id']]))
        if len(ids)>8:raise ValueError('每条关注最多绑定8份依据资料。')
        updated={**rule,'source_document_ids':ids,'source_versions':{
            **rule.get('source_versions',{}),source['id']:catalog.document_version(source)}}
        return research_radar.save({'revision':current['revision'],'rules':[updated if r['id']==rule['id'] else r for r in current['rules']]})


def apply_watch(project,identifier,fields,expected,versions):
    import research_radar
    current=research_radar.settings();rule=watch(identifier,project)
    validate_watch_sources(project,rule)
    if fingerprint(rule)!=expected:raise ValueError('关注规则已变化，请重新准备；原设置保留。')
    if not isinstance(fields,dict) or not fields or set(fields)-WATCH_FIELDS:raise ValueError('关注建议不能改变身份、项目或启停开关。')
    updated={**rule,**fields,'source_versions':{**rule.get('source_versions',{}),**versions}}
    return research_radar.save({'revision':current['revision'],'rules':[updated if r['id']==identifier else r for r in current['rules']]})


def listing(project,documents,allowed):
    if profiles.archived(project):return {'groups':[],'connections':[],'watch_bindings':{'rules':[],'sources':[]}}
    by_id={d['id']:d for d in documents};groups={};connections=[];store=Store()
    def add(source,target):
        group=groups.setdefault(source['id'],{'id':fingerprint([project,source['id'],source['version']])[:24],
            'source':source,'targets':[],'status':'pending'})
        group['targets'].append(target)
    def document_source(doc):
        return {'id':doc['id'],'title':doc.get('display_title') or doc['title'],
                'version':catalog.document_version(doc),'path':doc['path']}
    def connection(area,status,message):connections.append({'area':area,'status':status,'message':message})
    rules=[]
    try:
        import research_radar
        settings=research_radar.settings();rules=[r for r in settings['rules'] if r.get('project')==project]
        for rule in rules:
            for identifier in rule.get('source_document_ids',[]):
                doc=by_id.get(identifier)
                if identifier not in allowed or not doc or doc.get('archived'):continue
                if rule.get('source_versions',{}).get(identifier)==catalog.document_version(doc):continue
                add(document_source(doc),{'id':'watch:'+rule['id'],'kind':'watch_rule','area':'discover',
                    'dependency_ids':rule.get('source_document_ids',[]),
                    'rule_id':rule['id'],'label':rule.get('name') or rule['query'],'owner_project':project,
                    'fingerprint':fingerprint(rule),'status':'pending','reason':'明确绑定的关注依据已变化，可核对检索范围；启停开关保持原设置。'})
        bound=sum(bool(r.get('source_document_ids')) for r in rules)
        connection('discover','connected' if bound else 'unbound',f'{len(rules)}条关注，{bound}条已绑定依据资料；绑定后按来源版本定位变化。')
    except (ValueError,OSError) as error:
        settings={'revision':0};connection('discover','unavailable',str(error))
    nodes=[n for n in store.nodes(project) if n['owner']=='RSpace' and n['project']==project]
    key='change-impact:native-observed:'+project
    # This receipt observes versions only; native facts remain owned by RSpace.
    with FileLock(str(w.DATA/'.change-impact-native.lock'),timeout=20):
        baseline=store.cursor(key,{});observed=dict(baseline.get('records',{}));new=False
        for node in nodes:
            version=fingerprint([node['revision'],node['data'],node['status']])
            if node['id'] not in observed:observed[node['id']]={'version':version,'revision':node['revision']};new=True;continue
            if observed[node['id']]['version']==version:continue
            add({'id':node['id'],'title':node['data'].get('title') or node['id'],'version':version,
                 'open_action':'lab','native_id':node['id']},
                {'id':'native:'+node['id'],'kind':'native_review','area':'lab','open_action':'lab',
                 'native_id':node['id'],'version':version,'label':node['data'].get('title') or node['id'],
                 'status':'pending','reason':f'正式记录版本 {observed[node["id"]]["revision"]} → {node["revision"]}；在原生入口核对事实与依赖。'})
        if new:store.commit_page(key,[],{'records':observed})
    connection('lab','connected' if nodes else 'empty',f'{len(nodes)}条原生记录；同步后的版本变化进入本清单，正式事实沿原平台核对。')
    try:
        with store.connection() as db:
            configured_analysis=db.execute(
                "SELECT 1 FROM cursors WHERE key LIKE 'analysis:auto:%' "
                "AND key NOT LIKE '%:progress' LIMIT 1").fetchone()
        values=[]
        if configured_analysis:
            import analysis_automation
            values=[p for p in analysis_automation.profiles()['records'] if p.get('project')==project]
        for profile in values:
            candidates=[profile.get('progress',{}),*profile.get('items',[])]
            if (profile.get('method_current') is False or profile.get('code_current') is False) and candidates[0].get('status')!='needs_review':
                candidates[0]={'status':'needs_review','reason':'方法内容或计算实现已变化，请重新核对原自动接续配置；历史运行保留。'}
            for index,item in enumerate(candidates):
                if item.get('status') not in ('source_changed','waiting_conditions','needs_review'):continue
                identifier='analysis:'+profile['method_id']+':'+str(item.get('experiment_id',index))
                add({'id':identifier,'title':profile['method_title'],'version':fingerprint(item),
                     'open_action':'method','method_id':profile['method_id']},
                    {'id':identifier,'kind':'native_review','area':'analyze','open_action':'method',
                     'method_id':profile['method_id'],'status':'pending','label':profile['method_title'],
                     'review_level':'observation' if item.get('status') in ('source_changed','waiting_conditions') else 'decision',
                     'reason':item.get('reason') or '核对分析方法、输入与来源版本；计算沿已批准配置接续。'})
        connection('analyze','connected' if values else 'not_configured',f'{len(values)}份方法接续配置；'+('来源变更、缺失条件和方法变化在此接续。' if values else '尚未配置自动计算，不会因正文修改自行重算。'))
    except (ValueError,OSError) as error:connection('analyze','unavailable',str(error))
    try:
        import project_closure
        saved_closure=store.cursor('project-closure:'+project,{})
        closure=project_closure.overview(project) if saved_closure.get('checks') or saved_closure.get('closed') else {'checks':[]}
        for item in closure['checks']:
            if not item.get('stale'):continue
            identifier='closure:'+item['id']
            add({'id':identifier,'title':item['label'],'version':fingerprint([closure['revision'],item]),'open_action':'closure'},
                {'id':identifier,'kind':'native_review','area':'outputs','open_action':'closure','status':'pending',
                 'label':item['label'],'reason':'结项依据已变化，原确认历史保留；请从结项入口重新核对当前证据。'})
        connection('outputs','connected','交付正文沿明确引用接续；结项依据沿原版本检查，冻结结果保留。')
    except (ValueError,OSError) as error:connection('outputs','unavailable',str(error))
    connection('knowledge','connected','知识正文和明确引用按当前版本定位；自动索引不提高人工核查等级。')
    connection('projects','connected','方案、总览和有明确资料引用的工作/计划接续，身份、完成状态和当前节点保留。')
    return {'groups':list(groups.values()),'connections':connections,'watch_bindings':{
        'revision':settings['revision'],'rules':[{'id':r['id'],'title':r.get('name') or r['query'],'sources':r.get('source_document_ids',[])} for r in rules],
        'sources':[{'id':d['id'],'title':d.get('display_title') or d['title']} for d in documents
                   if d['id'] in allowed and not d.get('archived') and d.get('visibility')!='system']}}


def acknowledge_native(data):
    project=data.get('project') or '山药'
    with profiles.lifecycle_lock(project),FileLock(str(w.DATA/'.change-impact-native.lock'),timeout=20):
        if profiles.archived(project):raise ValueError('项目已归档，请先恢复。')
        node=Store().node(data.get('id'))
        if not node or node['project']!=project or node['owner']!='RSpace':raise ValueError('原生记录不属于本项目。')
        version=fingerprint([node['revision'],node['data'],node['status']])
        if data.get('version')!=version:raise ValueError('原生版本已再次变化，请重新核对。')
        key='change-impact:native-observed:'+project;baseline=Store().cursor(key,{'records':{}})
        baseline['records'][node['id']]={'version':version,'revision':node['revision']}
        Store().commit_page(key,[],baseline)
    return {'status':'reviewed','id':node['id']}
