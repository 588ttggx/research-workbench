"""Reopen search artifacts and keep human screening in the existing SQLite ledger."""
import json
import re
import tempfile
from pathlib import Path
import workflow as w
from research_store import Store,encode,now

RUN_ID=re.compile(r'\d{8}T\d{6}-[a-f0-9]{8}')


def artifact_json(path, name):
    from storage_budget import read_search_artifact
    return json.loads(read_search_artifact(path, name))


def folder(run_id):
    if not isinstance(run_id,str) or not RUN_ID.fullmatch(run_id):raise ValueError('检索编号无效。')
    root=(w.ROOT/'output/文献检索').resolve();path=(root/run_id).resolve()
    if not path.is_relative_to(root):raise ValueError('检索结果不存在或尚未完成。')
    artifact_json(path, 'papers/index.json')
    return path


def screening(run_id):
    value=Store().cursor('scholarly:screen:'+run_id,{})
    return {'screening':value,'screening_revision':w.digest(encode(value))}


def public_results(papers):
    import scholarly_search as search
    import journal_ranks
    library=w.read_json(w.LIBRARY,{}).get('records',[])
    results=[]
    for paper in sorted(papers,key=lambda paper:paper.get('metadata_rank') or 9999):
        item={key:paper.get(key) for key in ('paper_id','title','authors','year','venue','doi','abstract','wos_id','arxiv_id','openalex_id','semantic_scholar_id','citation_counts','query_matches','context_matches','concept_match')}
        item['workspace_matches']=search.library_matches(paper,library)
        item['sources']=list(dict.fromkeys(record['source'] for record in paper.get('source_records',[])))
        item['abstract']=re.sub(r'<[^>]*>',' ',item.get('abstract') or '')[:6000]
        item['title']=re.sub(r'<[^>]*>',' ',item.get('title') or '')
        item['url']=('https://doi.org/'+item['doi'] if item.get('doi') else
            'https://arxiv.org/abs/'+item['arxiv_id'] if item.get('arxiv_id') else
            item['openalex_id'] if item.get('openalex_id') else
            'https://www.semanticscholar.org/paper/'+item['semantic_scholar_id'] if item.get('semantic_scholar_id') else
            'https://www.webofscience.com/wos/woscc/full-record/'+item['wos_id'] if item.get('wos_id') else '')
        codes=[]
        for source in paper.get('source_records',[]):
            raw=source.get('raw') or {}
            value=raw.get('issn') or ((raw.get('record') or {}).get('identifiers') or {}).get('issn') or []
            if isinstance(value,str):value=re.split(r'[,;\s]+',value)
            if isinstance(value,list):codes.extend(value)
        item['issn']=list(dict.fromkeys(codes));results.append(item)
    ranks=journal_ranks.resolve_many([{**item,'id':item['paper_id']} for item in results]) if results else {}
    for item in results:item['journal_ranks']=ranks.get(item['paper_id'],{})
    return results


def load_result(run_id):
    path=folder(run_id);receipt=artifact_json(path,'search-log.json');index=artifact_json(path,'papers/index.json')
    import scholarly_search as search
    papers=public_results(index.get('papers',[]))
    return {'run_id':run_id,'plan':receipt.get('plan') or {'query':index.get('query',''),'sources':index.get('sources_requested',[]),'max_results':15},
        'status':search.result_status(receipt.get('providers',{})),
        'providers':search.provider_details(receipt.get('providers',{}),receipt.get('requests',[]),receipt.get('warnings',[])),
        'warnings':receipt.get('warnings',[]),'papers':papers,'count':len(papers),'generated_at':receipt.get('generated_at'),
        'reading_scope':'本次仅检索题录与可得摘要；未下载、未核查全文。',**screening(run_id)}


def history():
    root=w.ROOT/'output/文献检索';records=[]
    if root.is_dir():
        paths=sorted((p for p in root.iterdir() if p.is_dir() and RUN_ID.fullmatch(p.name)),key=lambda p:p.name,reverse=True)
        for path in paths:
            if not (path/'papers/index.json').is_file() and not (path/'search-history.zip').is_file():continue
            try:receipt=artifact_json(path,'search-log.json')
            except (ValueError,OSError):continue
            if receipt.get('purpose')=='connection_check':continue
            plan=receipt.get('plan') or {};providers=receipt.get('providers',{})
            records.append({'run_id':path.name,'query':plan.get('query') or receipt.get('query',''),
                'generated_at':receipt.get('generated_at'),'sources':plan.get('sources',list(providers)),
                'retrieved':sum(int(p.get('retrieved') or 0) for p in providers.values())})
            if len(records)>=30:break
    return {'records':records}


def screen(data):
    run_id=data.get('run_id');path=folder(run_id);paper_id=data.get('paper_id');decision=data.get('decision');reason=data.get('reason','')
    index=artifact_json(path,'papers/index.json')
    if decision not in ('include','exclude','reset') or paper_id not in {p['paper_id'] for p in index.get('papers',[])}:raise ValueError('请选择本次结果中的论文和有效筛选操作。')
    if not isinstance(reason,str) or len(reason)>500:raise ValueError('筛选说明最多 500 字。')
    store=Store();key='scholarly:screen:'+run_id
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT value FROM cursors WHERE key=?',(key,)).fetchone();value=json.loads(row['value']) if row else {}
        if data.get('revision')!=w.digest(encode(value)):raise ValueError('筛选记录已变化，请重新打开这次检索。')
        if decision=='reset':value.pop(paper_id,None)
        else:value[paper_id]={'decision':decision,'reason':reason.strip(),'updated':now()}
        db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)',(key,encode(value),now()))
        Store.log(db,'scholarly-screen',run_id,{'paper_id':paper_id,'decision':decision})
    return {'screening':value,'screening_revision':w.digest(encode(value))}


def export(run_id,kind,*,selected=False):
    if kind not in ('bibtex','json'):raise ValueError('导出格式无效。')
    path=folder(run_id)
    mime='application/x-bibtex; charset=utf-8' if kind=='bibtex' else 'application/json; charset=utf-8'
    if not selected:
        from storage_budget import read_search_artifact
        return read_search_artifact(path,'papers/bibtex.bib' if kind=='bibtex' else 'papers/index.json'),mime
    index=artifact_json(path,'papers/index.json');state=screening(run_id)['screening']
    papers=[p for p in index.get('papers',[]) if state.get(p['paper_id'],{}).get('decision')=='include']
    if not papers:raise ValueError('请先保留至少一篇论文。')
    if kind=='json':return json.dumps({**index,'papers':papers,'export_scope':'human_included'},ensure_ascii=False,indent=2).encode('utf-8'),mime
    import scholarly_search
    temporary=w.HERE/'_临时';temporary.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temporary) as directory:
        target=Path(directory)/'selection.bib';scholarly_search.collector().write_bibtex(target,papers);return target.read_bytes(),mime


def subscribe(data):
    import scholarly_search as search
    import research_radar as radar
    plan=search.validate_plan(data.get('plan'));name=data.get('name','');project=data.get('project') or '共享'
    if not isinstance(name,str):raise ValueError('关注名称格式无效。')
    name=name.strip()
    if not 1<=len(name)<=100:raise ValueError('请为持续关注填写 1–100 字名称。')
    sources=[s for s in plan['sources'] if s in ('wos','openalex','crossref')]
    if not sources or len(sources)!=len(plan['sources']):raise ValueError('持续提醒目前支持 WoS、OpenAlex 与 Crossref；请在查询中明确选择这些来源后再添加。')
    if project!='共享':__import__('knowledge').lines(project)
    queries={key:value for key,value in plan['provider_queries'].items() if key in sources and key in ('openalex','crossref')}
    current=radar.settings()
    if data.get('revision')!=current['revision']:raise ValueError('关注规则已变化，请重新打开添加关注。')
    rule={'id':'search-'+w.digest(encode([plan['query'],plan['wos_query'],plan['include_groups'],queries,sources,project]))[:16],
        'name':name,'type':'topic','query':plan['query'],'wos_query':plan['wos_query'],'project':project,
        'enabled':True,'sources':sources,'relevance_mode':'watch','relevance_tier':'direct',
        'include_groups':plan['include_groups'],'provider_queries':queries,'origin_search':data.get('run_id'),
        'original_intent':plan.get('original_intent') or plan['query'],
        'criteria':plan.get('criteria') or {'required':plan['include_groups'],'priority':[],
            'optional':plan['optional_groups'],'exclusion':[]}}
    existing=next((r for r in current['rules'] if r['id']==rule['id']),None)
    if existing:return {'reused':True,'rule':existing}
    result=radar.save({'revision':current['revision'],'rules':[*current['rules'],rule]})
    return {'reused':False,'rule':rule,'revision':result['revision']}
