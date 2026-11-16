"""Overlapping discovery windows, durable Seen and page-level transactional cursors."""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import json
import re
import time
from urllib.parse import quote
import requests
from filelock import FileLock
import workflow as w
from research_store import Store, encode, RADAR_HANDLED_DECISIONS

TZ=timezone(timedelta(hours=8))
WATCH_TYPES=('topic','project','paper','author','institution','lab','citation','retraction')
DEFAULT_QUERIES=['terahertz spectroscopy yam cultivar','Dioscorea cultivar identification spectroscopy','terahertz powder sample preparation']
DEFAULT_WOS_QUERIES=[
    'TS=(terahertz OR "terahertz spectroscopy" OR THz) AND TS=(yam OR Dioscorea OR starch OR "Chinese yam")',
    'TS=(yam OR Dioscorea OR "Chinese yam") AND TS=(cultivar OR variety OR varieties OR identification OR discrimination OR authentication)',
    'TS=(terahertz OR THz) AND TS=(powder OR pellet OR particle OR "sample preparation")',
]
WOS_RECENT_DAYS=90
WOS_PAGE_SIZE=50
WOS_PAGE_LIMIT=4
WOS_SCAN_VERSION=5
CROSSREF_SCAN_VERSION=2
CROSSREF_TOP_N=200
OPENALEX_SCAN_VERSION=4


def reminder_policy():
    """Read the editable reminder bounds from the existing automation panel."""
    try:
        import automation_controls
        values=automation_controls.effective()
    except Exception:
        values={}
    def bounded(key,default,low,high):
        value=values.get(key,default)
        return value if type(value) is int and low<=value<=high else default
    return {
        'source_limit':bounded('radar_source_limit',200,10,200),
        'recent_days':bounded('radar_recent_days',90,7,365),
        'background_days':bounded('radar_background_days',90,7,365),
    }
WOS_FIELD_QUERY=re.compile(r'\b(?:TS|TI|IS|SO|VL|PG|CS|PY|FPY|DOP|AU|AI|UT|DO|DT|PMID|OG|SUR)\s*=',re.I)


class WoSNotConfigured(RuntimeError):
    pass


def _exception_state(exc):
    response=getattr(exc,'response',None)
    value={'status':'failed','error_type':type(exc).__name__}
    if isinstance(exc,requests.exceptions.ProxyError):value['message']='本机代理连接失败，请检查代理是否运行；已保留上次结果。'
    elif isinstance(exc,requests.exceptions.Timeout):value['message']='来源响应超时，稍后由后台重试。'
    status=getattr(response,'status_code',None)
    if isinstance(status,int):value['http_status']=status
    headers=getattr(response,'headers',{}) or {}
    retry=headers.get('Retry-After') if hasattr(headers,'get') else None
    if retry:value['retry_after']=str(retry)[:100]
    return value


def rule_fingerprint(rule):
    # A durable API cursor belongs to its exact query, never to a reused label alone.
    fields = {k:rule.get(k) for k in ('type','query','project','author_id','coauthor_ids','institution_id','work_id','doi')}
    for key in ('sources','relevance_mode','provider_queries','criteria'):
        if rule.get(key) is not None:fields[key]=rule[key]
    if rule.get('type') in ('topic', 'project') and rule.get('include_groups') is not None:
        fields['include_groups'] = rule['include_groups']
    if rule.get('type') in ('topic', 'project') and rule.get('wos_query') is not None:
        fields['wos_query'] = rule['wos_query']
    return w.digest(encode(fields))


def settings():
    from radar_inbox import DEFAULT_SCOPES
    value=w.read_json(w.DATA/'watch-rules.json',None)
    if value is None:
        value={'revision':1,'timezone':'Asia/Shanghai','daily':'08:30','weekly':'MON',
               'rules':[{'id':'topic-'+str(i+1),'type':'topic','query':q,'project':'山药','enabled':True,
                         'relevance_tier':('direct','background','adjacent')[i],
                         'include_groups':DEFAULT_SCOPES['topic-'+str(i+1)]} for i,q in enumerate(DEFAULT_QUERIES)]}
    rules=[]
    for original in value.get('rules',[]):
        rule=dict(original)
        if (rule.get('type') in ('topic','project') and 'wos_query' not in rule
                and rule.get('id') in ('topic-1','topic-2','topic-3')):
            index=int(rule['id'].split('-')[-1])-1
            if 0<=index<len(DEFAULT_WOS_QUERIES) and rule.get('query')==DEFAULT_QUERIES[index]:
                rule['wos_query']=DEFAULT_WOS_QUERIES[index]
        if (rule.get('type') in ('topic','project') and 'relevance_tier' not in rule
                and rule.get('id') in ('topic-1','topic-2','topic-3')):
            index=int(rule['id'].split('-')[-1])-1
            if rule.get('query')==DEFAULT_QUERIES[index]:
                rule['relevance_tier']=('direct','background','adjacent')[index]
        rules.append(rule)
    value={**value,'rules':rules}
    return {**value,'reading':__import__('radar_reading').validate_preferences(value.get('reading')),'available_types':list(WATCH_TYPES)}


def save(data):
    w.DATA.mkdir(parents=True,exist_ok=True)
    with FileLock(str(w.DATA/'.watch-rules.lock'),timeout=10):return _save(data)


def _save(data):
    current=settings()
    if data.get('revision')!=current['revision']:raise ValueError('关注规则已变化，请刷新')
    reading=__import__('radar_reading').validate_preferences(data.get('reading',current.get('reading')))
    rules=data.get('rules')
    if not isinstance(rules,list) or len(rules)>100:raise ValueError('关注规则最多 100 条')
    ids=set()
    for r in rules:
        if not isinstance(r,dict):raise ValueError('关注规则格式无效')
        if 'source_document_ids' in r:
            source_ids=r['source_document_ids'];versions=r.get('source_versions',{})
            if not isinstance(source_ids,list) or len(source_ids)>8 or any(not isinstance(i,str) or not re.fullmatch(r'DOC-[a-f0-9]{20}',i) for i in source_ids) or len(set(source_ids))!=len(source_ids):
                raise ValueError('关注依据最多8份已登记资料。')
            if not isinstance(versions,dict) or set(versions)-set(source_ids) or any(not isinstance(v,str) or len(v)>128 for v in versions.values()):
                raise ValueError('关注依据版本无效。')
        if 'reading_enabled' in r and type(r['reading_enabled']) is not bool:raise ValueError('是否参与每日阅读须为开关。')
        if r.get('type') not in WATCH_TYPES or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',r.get('id','')) or r['id'] in ids:raise ValueError('关注类型或 ID 无效')
        ids.add(r['id'])
        if 'criteria' in r:r['criteria']=__import__('scholarly_search').validate_criteria(r['criteria'])
        required=(r.get('criteria') or {}).get('required')
        old=next((old for old in current['rules'] if old['id']==r['id']),None)
        if required:
            r['include_groups']=required
            if not old or required!=__import__('radar_inbox').rule_groups(old):
                queries,wos_query=__import__('scholarly_search').concept_queries(required,r.get('sources') or ['wos','openalex','crossref'])
                if not r.get('query') or old and r.get('query')==old.get('query'):r['query']=' '.join(group[0] for group in required)[:500]
                if not r.get('wos_query') or old and r.get('wos_query')==old.get('wos_query'):r['wos_query']=wos_query
                previous=(old or {}).get('provider_queries') or {};provided=r.get('provider_queries') or {}
                r['provider_queries']={key:provided.get(key) if provided.get(key)!=previous.get(key) else value for key,value in queries.items()}
        if not isinstance(r.get('query',''),str) or len(r.get('query',''))>500:raise ValueError('查询内容无效')
        for key,prefix in [('author_id','A'),('institution_id','I'),('work_id','W')]:
            if r.get(key) and not re.fullmatch(prefix+r'\d+',r[key]):raise ValueError('OpenAlex ID 格式错误')
        if r['type'] in ('author','lab') and not r.get('author_id'):raise ValueError('作者或实验室关注需要可解析的 PI Author ID；不会猜测实验室身份')
        if r['type']=='institution' and not r.get('institution_id'):raise ValueError('机构关注需要 Institution ID')
        if r['type']=='citation' and not r.get('work_id'):raise ValueError('引用关注需要 Work ID')
        if r['type']=='paper' and not (r.get('work_id') or r.get('doi')):raise ValueError('论文关注需要 DOI 或 Work ID')
        if r['type'] in ('topic','project') and not r.get('query','').strip():raise ValueError('主题或项目关注需要检索词，避免抓取整个数据库')
        if r.get('relevance_tier') not in (None,'direct','adjacent','background','noise'):
            raise ValueError('关注研判层级无效')
        if r.get('relevance_mode') not in (None,'watch'):raise ValueError('关注相关性模式无效')
        if not isinstance(r.get('original_intent',''),str) or len(r.get('original_intent',''))>2000:raise ValueError('原始关注需求最多 2000 字')
        if 'sources' in r and (not isinstance(r['sources'],list) or not r['sources'] or any(s not in ('wos','openalex','crossref') for s in r['sources'])):raise ValueError('持续关注来源只能选择 WoS、OpenAlex 或 Crossref')
        if not isinstance(r.get('name',''),str) or len(r.get('name',''))>100:raise ValueError('关注名称最多 100 字')
        queries=r.get('provider_queries',{})
        if not isinstance(queries,dict) or any(key not in ('crossref','openalex') or not isinstance(value,str) or not 1<=len(value.strip())<=2000 for key,value in queries.items()):raise ValueError('持续关注的来源检索词无效')
        if not isinstance(r.get('wos_query',''),str) or len(r.get('wos_query',''))>4000:raise ValueError('WoS 检索式过长或格式无效')
        if r.get('wos_query','').strip() and not WOS_FIELD_QUERY.search(r['wos_query']):raise ValueError('WoS 需要字段式检索，例如 TS=(terahertz AND starch)')
        if r.get('doi') and not re.fullmatch(r'10\.\d{4,9}/\S+',w.normalize_doi(r['doi'])):raise ValueError('请填写有效 DOI')
        coauthors=r.get('coauthor_ids',[])
        if not isinstance(coauthors,list) or len(coauthors)>20 or any(not isinstance(a,str) or not re.fullmatch(r'A\d+',a) for a in coauthors):raise ValueError('合作作者最多 20 个有效 Author ID')
        groups=r.get('include_groups')
        if groups is not None and (not isinstance(groups,list) or len(groups)>8 or any(not isinstance(g,list) or not 1<=len(g)<=12 or any(not isinstance(term,str) or not term.strip() or len(term)>80 for term in g) for g in groups)):raise ValueError('重点词组格式无效')
    value={k:v for k,v in current.items() if k!='available_types'}
    value.update(revision=current['revision']+1,rules=rules,reading=reading)
    w.write_json(w.DATA/'watch-rules.json',value)
    return settings()


def get(url,params=None):
    response=requests.get(url,params=params,headers={'User-Agent':'ResearchWorkspace/3.0 (local scholarly metadata watcher)'},timeout=(10,45))
    response.raise_for_status()
    return response.json()


def get_openalex(url,params=None):
    import scholarly_search
    values=dict(params or {})
    try:api_key,email=scholarly_search.openalex_credentials()
    except (ValueError,OSError):api_key,email='',''
    if api_key:values['api_key']=api_key
    elif email:values['mailto']=email
    return get(url,values)


def get_wos(api,params,api_key):
    url=('https://api.clarivate.com/apis/wos-starter/v1/documents' if api=='starter'
         else 'https://api.clarivate.com/api/wos/')
    response=requests.get(url,params=params,headers={'X-ApiKey':api_key,'Accept':'application/json'},
                          timeout=(10,45))
    response.raise_for_status()
    return response.json()


def wos_credentials():
    import scholarly_search
    return scholarly_search.wos_credentials()


@lru_cache(maxsize=1)
def wos_provider():
    import scholarly_search
    return scholarly_search.collector().wos


def normalize(item,source,rule,*,wos_api='starter'):
    if source=='Crossref':
        doi=w.normalize_doi(item.get('DOI'));external=doi
        title=' '.join(item.get('title',[]));journal=' '.join(item.get('container-title',[]))
        updates=item.get('update-to',[]);year=(item.get('published',{}).get('date-parts') or [[]])[0]
        creators=[{'creatorType':'author','firstName':a.get('given',''),'lastName':a.get('family','')} if a.get('family') else {'creatorType':'author','name':a['name']} for a in item.get('author',[]) if a.get('family') or a.get('name')]
        extra={'updates':updates,'relation':item.get('relation',{}),'issn':item.get('ISSN',[]),'links':item.get('link',[]),'creators':creators,
               'publication_date':'-'.join(str(v).zfill(2) if i else str(v) for i,v in enumerate(year)) if year else None,
               'abstract':re.sub('<[^>]+>','',item.get('abstract') or '')}
    elif source=='WoS':
        paper=wos_provider().normalize(item,wos_api)
        external=paper.get('wos_id')
        doi=w.normalize_doi(paper.get('doi'))
        title=paper.get('title') or ''
        journal=paper.get('venue') or ''
        year=[paper.get('year')]
        raw=next(((source.get('raw') or {}).get('record') or {} for source in paper.get('source_records',[])
                  if source.get('source')=='wos'),{})
        record_link=((raw.get('links') or {}).get('record'))
        url=record_link or ('https://www.webofscience.com/wos/woscc/full-record/'+external if external else '')
        types=raw.get('types') or []
        identifiers=raw.get('identifiers') or {}
        issn=[]
        for field in ('issn','eissn'):
            value=identifiers.get(field) or []
            issn.extend(value if isinstance(value,list) else re.split(r'[,;\s]+',str(value)))
        issn=list(dict.fromkeys(value for value in issn if value))
        extra={'wos_id':external,'citation_count':paper.get('citation_count'),
               'authors':[{'display_name':name} for name in paper.get('authors',[]) if name],
               'creators':[{'creatorType':'author','name':name} for name in paper.get('authors',[]) if name],
               'abstract':paper.get('abstract') or '',
               'issn':issn,
                'wos_types':types,'keywords':(raw.get('keywords') or {}).get('authorKeywords') or []}
    else:
        doi=w.normalize_doi(item.get('doi'));external=item.get('id','').rsplit('/',1)[-1]
        title=item.get('title') or '';journal=((item.get('primary_location') or {}).get('source') or {}).get('display_name') or ''
        location=(item.get('primary_location') or {}).get('source') or {}
        creators=[{'creatorType':'author','name':a['author']['display_name']} for a in item.get('authorships',[]) if (a.get('author') or {}).get('display_name')]
        index=item.get('abstract_inverted_index') or {};words={position:word for word,positions in index.items() for position in positions if isinstance(position,int) and 0<=position<10000}
        abstract=' '.join(words[position] for position in sorted(words))
        year=[item.get('publication_year')];extra={'citation_count':item.get('cited_by_count'),'openalex_id':external,'retracted':item.get('is_retracted',False),
             'abstract':abstract,'topics':[{'id':t.get('id'),'name':t.get('display_name')} for t in item.get('topics',[])],
             'authors':[a['author'] for a in item.get('authorships',[]) if a.get('author')],
             'institutions':[i for a in item.get('authorships',[]) for i in a.get('institutions',[])],
             'issn':location.get('issn') or ([location['issn_l']] if location.get('issn_l') else []),'creators':creators,'publication_date':item.get('publication_date')}
    if not external or not title:return None
    return {'source':source,'external_id':external,'doi':doi or None,'title':title,'journal':journal,'year':year[0] if year else None,
            'watch_id':rule['id'],'watch_type':rule['type'],'query':rule.get('query'),
            'project':rule.get('project') or '共享','status':'candidate_unverified',
            'discovered':w.now(),'type':((extra.get('wos_types') or ['journal-article'])[0].lower()
                if source=='WoS' else 'journal-article'),
            'url':('https://doi.org/'+doi if source!='WoS' and doi else
                   (url if source=='WoS' else 'https://openalex.org/'+external)),**extra}


def scan_key(source,rule):
    return 'radar:'+source.lower()+':'+rule['id']+(':latest' if rule.get('_manual_latest') or rule.get('_latest_scan') else '')


def daily_remaining(source,rule,store):
    """Both cursors consume the same source/watch allowance; no parallel quota."""
    base='radar:'+source.lower()+':'+rule['id'];day=datetime.now(TZ).date().isoformat()
    used=sum(int(value.get('day_scanned') or 0) for key in (base,base+':latest')
             if (value:=store.cursor(key,{})).get('scan_day')==day)
    return max(0,reminder_policy()['source_limit']-used)


def admit_page(items, source, rule, state, *, wos_api='starter',store=None):
    """Advance over broad source matches without retaining unrelated topic noise."""
    from radar_inbox import priority
    from radar_inbox import nonresearch_title
    rows = [row for item in items if (row := normalize(item, source, rule, wos_api=wos_api))]
    # An explicit WoS field query is already the source-level admission gate.
    # Starter records normally omit abstracts, so applying a second title-only
    # group filter here would discard valid WoS hits.
    admitted = [row for row in rows if not nonresearch_title(row)
                and (source=='WoS' or rule['type'] not in ('topic', 'project')
                or not rule.get('include_groups') or priority(row, [rule])['tier'] != 'noise')]
    state['scanned'] = state.get('scanned', 0) + len(items)
    state['excluded'] = state.get('excluded', 0) + len(rows) - len(admitted)
    day = datetime.now(TZ).date().isoformat()
    state['day_scanned'] = (state.get('day_scanned', 0) if state.get('scan_day') == day else 0) + len(items)
    state['scan_day'] = day
    counts=state.setdefault('last_counts',dict(scanned=0,duplicate=0,new=0,matched=0,pending=0,failed=0,excluded=0))
    counts['scanned']+=len(items);counts['failed']+=len(items)-len(rows)
    counts['excluded']+=len(rows)-len(admitted)
    seen=set()
    for row in admitted:
        marker=row.get('doi') or (row['source'],row['external_id'])
        duplicate=marker in seen
        if store and not duplicate:
            with store.connection() as db:
                duplicate=db.execute('SELECT 1 FROM seen WHERE (source=? AND external_id=?) OR (doi IS NOT NULL AND doi=?) LIMIT 1',
                    (source,row['external_id'],row.get('doi'))).fetchone() is not None
        seen.add(marker);counts['duplicate' if duplicate else 'new']+=1
        tier=priority(row,[rule])['tier']
        if tier=='pending':counts['pending']+=1
        elif tier in ('direct','adjacent','background'):counts['matched']+=1
    return admitted


def wos(rule,store):
    """Continue a bounded WoS scan instead of treating page one as complete."""
    if not rule.get('wos_query'):
        return {'status':'not_configured','message':'此关注未填写 WoS 检索式'}
    try:api_key,api,database=wos_credentials()
    except (ValueError,OSError):raise WoSNotConfigured('WoS 本机凭证无法读取') from None
    if not api_key:raise WoSNotConfigured('WoS API 密钥尚未配置')
    if api not in ('starter','expanded'):raise ValueError('WoS 接口类型无效')
    key=scan_key('wos',rule);state=store.cursor(key,{})
    if rule.get('_latest_scan') and not rule.get('_manual_latest') and not state:
        previous=store.cursor('radar:wos:'+rule['id'],{})
        if previous.get('status')=='completed' and previous.get('window_until')==datetime.now(TZ).date().isoformat():state=previous
    fingerprint=rule_fingerprint(rule)
    if (state.get('rule_sha256')!=fingerprint or state.get('wos_api')!=api
            or state.get('wos_database')!=database or state.get('scan_version')!=WOS_SCAN_VERSION):
        state={k:state[k] for k in ('scan_day','day_scanned') if k in state}
    local=datetime.now(TZ);day=local.date().isoformat()
    source_limit=reminder_policy()['source_limit']
    if not rule.get('_manual_latest') and state.get('window_until')==day and state.get('status')=='completed':
        return {'status':'not_due','scanned':state.get('scanned',0),
                'upstream_total':state.get('upstream_total'),'truncated':False,
                'day_scanned':state.get('day_scanned',0),'limit':source_limit,
                'window_complete':True,'coverage':'cursor_window',
                'message':'今日此关注已检查完成，复用结果；明日检查新入索引论文。'}
    query=rule['wos_query'].strip()

    def fresh_window(previous):
        return {**{k:previous[k] for k in ('scan_day','day_scanned','last_counts') if k in previous},
                'rule_sha256':fingerprint,'wos_api':api,'wos_database':database,
                'scan_version':WOS_SCAN_VERSION,
                'window_since':(local.date()-timedelta(days=WOS_RECENT_DAYS)).isoformat(),
                'window_until':day,'wos_page':1,'scanned':0,'excluded':0,
                'page_size':min(WOS_PAGE_SIZE,source_limit,daily_remaining('wos',rule,store) or source_limit),
                'status':'pending','truncated':True}

    if not state.get('window_until') or state.get('status')=='completed' or rule.get('_manual_latest') or (rule.get('_latest_scan') and state.get('window_until')!=day):
        state=fresh_window(state)
    state['last_counts']=dict(scanned=0,duplicate=0,new=0,matched=0,pending=0,failed=0,excluded=0)
    if state.get('page_size',WOS_PAGE_SIZE)>source_limit:
        # Numbered pagination cannot change size at page N. Replay the fixed
        # window; Seen preserves identities and today's allowance is retained.
        state.update(wos_page=1,page_size=min(WOS_PAGE_SIZE,source_limit),scanned=0,excluded=0)
    state.setdefault('page_size',min(WOS_PAGE_SIZE,source_limit))
    pages_this_run=0
    while pages_this_run<WOS_PAGE_LIMIT:
        remaining=min(daily_remaining('wos',rule,store),rule.get('_run_limit',50)-state['last_counts']['scanned'])
        expected=state['page_size']
        if isinstance(state.get('upstream_total'),int):expected=min(expected,max(1,state['upstream_total']-state.get('scanned',0)))
        if remaining<expected:
            state.update(budget_deferred=True,checked=w.now())
            store.commit_page(key,[],state)
            return {'status':'completed','coverage':'daily_limit','window_complete':False,
                    'scanned':state.get('scanned',0),'day_scanned':state.get('day_scanned',0),
                    'upstream_total':state.get('upstream_total'),'truncated':True,
                    'limit':source_limit,'pages_checked':pages_this_run,
                    'message':'已达到本机每日扫描上限，分页进度保留，明日接续；这不是 API 账户额度。'}
        state['budget_deferred']=False
        # A continuation belongs to a fixed window, even after midnight.
        since=state['window_since'];until=state['window_until']
        page=max(1,int(state.get('wos_page',1)))
        if api=='starter':
            params={'db':database,'q':query,'page':page,'limit':state['page_size'],
                    'sortField':'LD+D','publishTimeSpan':since+' '+until}
        else:
            params={'databaseId':database,
                    'usrQuery':'('+query+') AND LD=('+since+' '+until+')',
                    'firstRecord':(page-1)*state['page_size']+1,
                    'count':state['page_size'],'sortField':'LD+D'}
        data=get_wos(api,params,api_key)
        if api=='starter':
            items=data.get('hits') or []
            total=(data.get('metadata') or {}).get('total')
        else:
            records=(((data.get('Data') or {}).get('Records') or {}).get('records') or {})
            items=records.get('REC') or []
            if isinstance(items,dict):items=[items]
            total=(data.get('QueryResult') or {}).get('RecordsFound')
        rows=admit_page(items,'WoS',rule,state,wos_api=api,store=store)
        total=int(total) if isinstance(total,(int,float)) else max(
            int(state.get('upstream_total') or 0),len(items))
        if not items and int(state.get('scanned',0))<total:
            raise ValueError('WoS 分页提前返回空页，来源总数与当前扫描范围不一致')
        complete=int(state.get('scanned',0))>=total
        state.update(checked=w.now(),upstream_total=total,
                     wos_limit=state['page_size'],wos_pages_scanned=page,
                     status='completed' if complete else 'pending',
                     wos_page=1 if complete else page+1,truncated=not complete)
        # Rows and their NEXT page commit together, so an interrupted request
        # cannot replay a committed page and count it toward completion twice.
        store.commit_page(key,rows,state)
        pages_this_run+=1
        if complete and until<day:
            state=fresh_window(state)
            store.commit_page(key,[],state)
        elif complete:
            break
        if state['last_counts']['scanned']>=rule.get('_run_limit',50):break
    scanned=int(state.get('scanned',0))
    complete=state.get('status')=='completed'
    return {'status':'completed' if complete else 'pending','scanned':scanned,
            'upstream_total':state.get('upstream_total'),
            'truncated':not complete,'pages_checked':pages_this_run,
            'window_complete':complete,'day_scanned':state.get('day_scanned',0),
            'limit':source_limit,'counts':state['last_counts']}


def crossref(rule,store):
    key=scan_key('crossref',rule);state=store.cursor(key,{})
    fingerprint=rule_fingerprint(rule)
    if state.get('rule_sha256')!=fingerprint or state.get('scan_version')!=CROSSREF_SCAN_VERSION:
        state={k:state[k] for k in ('scan_day','day_scanned') if k in state}
    if rule.get('_manual_latest') or (rule.get('_latest_scan') and state.get('scan_day')!=datetime.now(TZ).date().isoformat()):
        state={'since':(datetime.now(timezone.utc)-timedelta(days=90)).isoformat(),'until':w.now(),'cursor':'*','done':False,
               **{k:state[k] for k in ('scan_day','day_scanned') if k in state}}
    if state.get('done'):
        state={'since':(datetime.now(timezone.utc)-timedelta(days=14)).isoformat(),
               'until':w.now(),'cursor':'*','done':False,
               'scan_version':CROSSREF_SCAN_VERSION,
               **{k:state[k] for k in ('scan_day','day_scanned') if k in state}}
    if not state.get('since'):
        state={'since':(datetime.now(timezone.utc)-timedelta(days=14)).isoformat(),'until':w.now(),'cursor':'*',
               **{k:state[k] for k in ('scan_day','day_scanned') if k in state}}
    state['rule_sha256']=fingerprint
    state['scan_version']=CROSSREF_SCAN_VERSION
    source_limit=reminder_policy()['source_limit']
    top=min(source_limit,int(CROSSREF_TOP_N),600)
    state['top_n']=top
    state['scanned_this_window']=int(state.get('scanned_this_window') or 0)
    state['last_counts']=dict(scanned=0,duplicate=0,new=0,matched=0,pending=0,failed=0,excluded=0)
    for _ in range(8):
        remaining = min(daily_remaining('crossref',rule,store),rule.get('_run_limit',50)-state['last_counts']['scanned']) if rule['type'] in ('topic', 'project') else 50
        if remaining <= 0:
            state['budget_deferred']=daily_remaining('crossref',rule,store)<=0;store.commit_page(key,[],state);return False
        needed=top-state['scanned_this_window']
        if needed<=0:
            state.update(done=True,status='completed',checked=w.now())
            store.commit_page(key,[],state)
            return True
        page_size = min(50, remaining, needed)
        params={'rows':page_size,'cursor':state['cursor'],
                'filter':f"from-index-date:{state['since'][:10]},until-index-date:{state['until'][:10]}",
                'sort':'indexed' if rule.get('_manual_latest') or rule.get('_latest_scan') else 'relevance','order':'desc','select':'DOI,title,author,container-title,published,published-print,published-online,type,abstract,ISSN,URL,link,relation,update-to'}
        if rule.get('query'):params['query.bibliographic']=rule['query']
        result=get('https://api.crossref.org/works',params)['message']
        items=result.get('items',[]);rows=admit_page(items,'Crossref',rule,state,store=store)
        cursor=result.get('next-cursor')
        state['scanned_this_window']+=len(items)
        state['upstream_total']=int(result.get('total-results') or 0)
        state.update(cursor=cursor or state['cursor'],
                     done=not items or len(items)<page_size or not cursor or state['scanned_this_window']>=top)
        store.commit_page(key,rows,state)
        if state['done']:return True
    return False


def openalex(rule,store):
    key=scan_key('openalex',rule);state=store.cursor(key,{})
    fingerprint=rule_fingerprint(rule)
    if state.get('rule_sha256')!=fingerprint or state.get('scan_version')!=OPENALEX_SCAN_VERSION:
        state={k:state[k] for k in ('scan_day','day_scanned') if k in state}
    # Weekly backfill catches delayed ingestion beyond the daily 14-day overlap.
    if rule.get('_manual_latest') or (rule.get('_latest_scan') and state.get('scan_day')!=datetime.now(TZ).date().isoformat()):
        state={'since':(datetime.now(timezone.utc)-timedelta(days=90)).date().isoformat(),
               'until':datetime.now(timezone.utc).date().isoformat(),'cursor':'*','page':1,
               **{k:state[k] for k in ('scan_day','day_scanned') if k in state}}
    if not state.get('since') or state.get('done'):
        previous=state.get('backfill_at','')
        backfill=not previous or (datetime.now(timezone.utc)-datetime.fromisoformat(previous)).days>=7
        state={'since':(datetime.now(timezone.utc)-timedelta(days=30 if backfill else 14)).date().isoformat(),
               'until':datetime.now(timezone.utc).date().isoformat(),'cursor':'*','backfill_at':w.now() if backfill else previous,
               **{k:state[k] for k in ('scan_day','day_scanned') if k in state}}
    state['rule_sha256']=fingerprint
    state['scan_version']=OPENALEX_SCAN_VERSION
    filters=[f"from_publication_date:{state['since']}",f"to_publication_date:{state['until']}"]
    authors=list(dict.fromkeys(([rule['author_id']] if rule.get('author_id') else [])+rule.get('coauthor_ids',[])))
    if authors:filters.append('authorships.author.id:'+'|'.join(authors))
    if rule.get('institution_id'):filters.append('authorships.institutions.id:'+rule['institution_id'])
    if rule['type']=='citation':filters.append('cites:'+rule['work_id'])
    try:
        import scholarly_search
        api_key,_=scholarly_search.openalex_credentials()
    except (ValueError,OSError):
        api_key=''
    keyless=not bool(api_key)
    source_limit=reminder_policy()['source_limit']
    if keyless:
        # Numbered pages require a fixed size; shrinking the last page to the
        # remaining daily allowance would shift offsets and repeat/skip rows.
        state.setdefault('page_size',min(50,source_limit,daily_remaining('openalex',rule,store) or source_limit) if rule['type'] in ('topic','project') else 50)
        if rule['type'] in ('topic','project') and state['page_size']>source_limit:
            # A smaller configured allowance cannot fit the saved page. Replay
            # the fixed window with smaller pages; Seen preserves identities.
            state.update(page=1,page_size=min(50,source_limit),scanned=0,excluded=0)
    state['pagination_mode']='page' if keyless else 'cursor'
    state['budget_deferred']=False
    state['last_counts']=dict(scanned=0,duplicate=0,new=0,matched=0,pending=0,failed=0,excluded=0)
    for _ in range(3):
        remaining = min(daily_remaining('openalex',rule,store),rule.get('_run_limit',50)-state['last_counts']['scanned']) if rule['type'] in ('topic', 'project') else 50
        if remaining <= 0 or (keyless and remaining<state['page_size']):
            daily_left=daily_remaining('openalex',rule,store)
            state['budget_deferred']=daily_left<=0 or (keyless and daily_left<state['page_size'])
            store.commit_page(key,[],state)
            return False
        params={'filter':','.join(filters),'per-page':state['page_size'] if keyless else min(50, remaining)}
        if rule.get('_manual_latest') or rule.get('_latest_scan'):params['sort']='publication_date:desc'
        if keyless:
            params['page']=int(state.get('page') or 1)
        else:
            params['cursor']=state.get('cursor') or '*'
        if rule.get('query'):params['search']=rule['query']
        result=get_openalex('https://api.openalex.org/works',params)
        items=result.get('results',[]);rows=admit_page(items,'OpenAlex',rule,state,store=store)
        meta=result.get('meta',{})
        state['upstream_total']=int(meta.get('count') or 0)
        if keyless:
            count=int(state['upstream_total'])
            scanned=int(state.get('scanned') or 0)
            state.update(page=int(params['page'])+1,
                         done=not items or len(items)<params['per-page'] or scanned>=count)
        else:
            cursor=meta.get('next_cursor')
            state.update(cursor=cursor or state.get('cursor') or '*',done=not cursor or not items)
        store.commit_page(key,rows,state)
        if state['done']:return True
    return False


def metadata_watch(rule,store):
    # An individual Paper Watch observes metadata/citation/retraction changes.
    key='radar:paper:'+rule['id'];old=store.cursor(key,{})
    fingerprint=rule_fingerprint(rule)
    if old.get('rule_sha256')!=fingerprint:old={}
    target=rule.get('work_id') or 'https://doi.org/'+w.normalize_doi(rule.get('doi'))
    item=get_openalex('https://api.openalex.org/works/'+quote(target,safe='/:'))
    row=normalize(item,'OpenAlex',rule)
    if row is None:raise ValueError('论文来源没有返回可识别题录，未推进同步状态')
    values={k:row.get(k) for k in ('citation_count','retracted','title')}
    alerts=[]
    paper=next((p for p in w.read_json(w.LIBRARY,{'records':[]})['records']
                if (row.get('doi') and w.normalize_doi(p.get('doi'))==row['doi']) or p.get('openalex_id')==row['external_id']),{})
    base={'source':'OpenAlex','external_id':row['external_id'],'paper_id':paper.get('id'),'doi':row.get('doi'),
          'title':row['title'],'url':row['url'],'project':rule.get('project'),'watch_id':rule['id']}
    if old and old.get('values')!=values:
        row['metadata_change']={'before':old.get('values'),'after':values}
        for field,kind in [('citation_count','citation'),('retracted','retraction'),('title','metadata')]:
            if old['values'].get(field)!=values.get(field):
                alerts.append({**base,'kind':kind,'before':{field:old['values'].get(field)},'after':{field:values.get(field)}})
    elif not old and values['retracted']:
        alerts.append({**base,'kind':'retraction','before':None,'after':{'retracted':True}})
    store.commit_page(key,[row],{'values':values,'checked':w.now(),'rule_sha256':fingerprint},alerts=alerts)


def corrections(store):
    # Inspect each saved DOI for deposited update relations, including notices citing it.
    errors=[];checked=0;pending=[];unavailable=[]
    clock = datetime.now(timezone.utc)
    papers=list(w.read_json(w.LIBRARY,{'records':[]})['records'])
    papers.extend({'id':None,'doi':r['doi'],'title':r.get('query') or r['doi'],'project':r.get('project')} for r in settings()['rules']
                  if r.get('enabled',True) and r['type'] in ('paper','retraction') and r.get('doi'))
    visited=set()
    for paper in papers:
        doi=w.normalize_doi(paper.get('doi'))
        if not doi or doi in visited:continue
        visited.add(doi)
        key='radar:updates:'+doi;previous=store.cursor(key,{})
        if previous.get('checked','')[:10]==clock.date().isoformat():continue
        if previous.get('status')=='not_indexed' and previous.get('next_check','')>clock.isoformat():
            unavailable.append({'doi':doi,'reason':'Crossref 尚无该 DOI 的记录','next_check':previous['next_check']});continue
        scan_key=key+':scan';scan=store.cursor(scan_key,{})
        try:
            if not scan or scan.get('done'):
                item=get('https://api.crossref.org/works/'+quote(doi,safe=''))['message']
                scan={'updates':item.get('update-to',[]),'relations':item.get('relation',{}),'notices':[],
                      'cursor':'*','started':w.now(),'done':False}
            for _ in range(3):
                message=get('https://api.crossref.org/works',{'filter':'updates:'+doi,'rows':100,'cursor':scan['cursor']})['message']
                items=message.get('items',[]);notices={w.normalize_doi(n.get('doi')):n for n in scan['notices']}
                notices.update({w.normalize_doi(n.get('DOI')):{'doi':n.get('DOI'),'title':n.get('title'),'updates':n.get('update-to')} for n in items})
                scan={**scan,'notices':list(notices.values()),'cursor':message.get('next-cursor') or scan['cursor'],
                      'done':len(items)<100 or not message.get('next-cursor')}
                store.commit_page(scan_key,[],scan)
                if scan['done']:break
            if not scan['done']:
                pending.append('Crossref:updates:'+doi);continue
            updates=scan['updates'];relations=scan['relations'];notices=sorted(scan['notices'],key=lambda n:w.normalize_doi(n.get('doi')))
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code==404:
                next_check=(clock+timedelta(days=7)).isoformat()
                store.commit_page(key,[],{**previous,'status':'not_indexed','attempted':w.now(),'next_check':next_check})
                unavailable.append({'doi':doi,'reason':'Crossref 尚无该 DOI 的记录','next_check':next_check})
            else:errors.append('Crossref:updates:'+doi)
            continue
        except (requests.RequestException,ValueError,KeyError,TypeError):
            errors.append('Crossref:updates:'+doi)
            continue
        value={'checked':clock.isoformat(),'status':'completed','paper_id':paper['id'],'updates':updates,'relations':relations,'notices':notices}
        before={k:previous.get(k,[] if k!='relations' else {}) for k in ('updates','relations','notices')}
        after={k:value[k] for k in before}
        alerts=[]
        had_observation=bool(previous.get('checked'))
        if (had_observation and before!=after) or (not had_observation and any(after.values())):
            alerts.append({'source':'Crossref','external_id':doi,'paper_id':paper['id'],'doi':doi,'kind':'publication_update',
                           'title':paper.get('title') or doi,'url':'https://doi.org/'+doi,'project':paper.get('project'),
                           'before':before if had_observation else None,'after':after})
        store.commit_page(key,[],value,alerts=alerts);checked+=1
    return {'checked':checked,'errors':errors,'pending_pages':pending,'unavailable':unavailable}


def export_candidates(store):
    from radar_inbox import merged,reviewable,candidate_edit
    rules = settings()['rules'];relevance=store.radar_relevance()
    policy=reminder_policy()
    library={w.normalize_doi(p.get('doi')) for p in w.read_json(w.LIBRARY)['records'] if p.get('doi')}
    if not (w.DATA/'candidates.json').exists():
        material=__import__('radar_inbox').snapshot()
        rows=[row for row in material['records']
              if w.normalize_doi(row.get('doi')) not in library]
        result=dict(material)
        result.update(checked=w.now(),queries=[r.get('query') for r in rules if r.get('query')],
                      records=reviewable(rows,rules,store.radar_decisions(),
                                         recent_days=policy['recent_days'],
                                         background_days=policy['background_days'],relevance=relevance))
        return result
    signature = w.digest(encode({'rules': rules, 'library': sorted(library), 'view':store.radar_source_signature(),'policy':policy}))
    previous = store.cursor('radar:candidate-export', {})
    observed = w.now()
    incremental = previous.get('signature') == signature and (w.DATA/'candidates.json').is_file()
    incoming = store.seen(since=previous.get('observed_until'),include_cold=False) if incremental else store.seen(include_cold=False)
    if incremental and not incoming:
        material=__import__('radar_inbox').snapshot()
        legacy=any(isinstance(row.get('priority'),dict) and 'axes' in row['priority']
                   for row in material['records'])
        if not legacy:return material
        with candidate_edit(material) as result:
            for row in result['records']:
                if isinstance(row.get('priority'),dict):row['priority'].pop('axes',None)
            result['records']=reviewable(result['records'],rules,store.radar_decisions(),
                                         recent_days=policy['recent_days'],
                                         background_days=policy['background_days'],relevance=relevance)
        return result
    with candidate_edit() as result:
        rows=[r for r in merged(result['records']+list(reversed(incoming))) if w.normalize_doi(r.get('doi')) not in library]
        result.update(checked=observed,queries=[r.get('query') for r in rules if r.get('query')],
                      records=reviewable(rows,rules,store.radar_decisions(),
                                         recent_days=policy['recent_days'],
                                         background_days=policy['background_days'],relevance=relevance))
    store.commit_page('radar:candidate-export', [], {'signature': signature, 'observed_until': observed})
    return result


def _export_with_retry(store, attempts=3):
    """A concurrent writer can make the candidate read unstable; retry briefly."""
    from radar_inbox import SnapshotBusy
    for attempt in range(attempts):
        try:
            return export_candidates(store)
        except SnapshotBusy:
            if attempt+1>=attempts:raise
            time.sleep(0.5*(attempt+1))


def discover(progress=None,*,manual=False):
    """Always persist a terminal receipt so one crash cannot trigger a retry storm."""
    try:
        return _discover(progress,manual=manual)
    except Exception as exc:
        store=Store()
        previous=store.cursor('radar:last_attempt',{})
        failures=int(previous.get('consecutive_failures') or 0)+1
        retry_minutes=min(360,30*(2**min(failures-1,3)))
        observed=datetime.now(TZ)
        receipt={
            **(previous if isinstance(previous,dict) else {}),
            'checked':w.now(),'status':'failed','errors':['pipeline:'+type(exc).__name__],
            'pending_pages':[],'budget_deferred':[],
            'consecutive_failures':failures,
            'next_retry_at':(observed+timedelta(minutes=retry_minutes)).isoformat(),
            'coverage':'本轮在形成完整回执前异常结束；未声明来源完整，旧候选和游标保留。',
        }
        store.commit_page('radar:last_attempt',[],receipt)
        raise


def _discover(progress=None,*,manual=False):
    store=Store();errors=[];pending=[];budget_deferred=[];skipped=[];source_status={}
    def history_after(source,rule,action,scanned=0):
        if manual or rule['type'] not in ('topic','project') or scanned>=50:return
        historic={key:value for key,value in rule.items() if key not in ('_latest_scan','_manual_latest')}
        clock=store.cursor(scan_key(source,historic),{})
        if not clock or clock.get('done') or clock.get('status')=='completed' or clock.get('rule_sha256')!=rule_fingerprint(historic):return
        remaining=min(50-scanned,daily_remaining(source,historic,store))
        if remaining<=0:return
        # Numbered pages cannot be resized after page one. If the old page
        # does not fit this run, preserve it for a later continuation.
        if source=='WoS' or clock.get('pagination_mode')=='page':
            if clock.get('page_size',50)>remaining:return
        identifier=source+':'+rule['id']+':history'
        try:
            action({**historic,'_run_limit':remaining},store)
            state=store.cursor(scan_key(source,historic),{})
            source_status[identifier]={'status':'completed' if state.get('done') or state.get('status')=='completed' else 'pending',
                'counts':state.get('last_counts',{}),'coverage':'history_continuation','window_complete':bool(state.get('done') or state.get('status')=='completed'),
                'message':'已先检查最新题录；历史补漏仅使用本轮剩余扫描量。'}
            if source_status[identifier]['status']=='pending':pending.append(identifier)
        except (requests.RequestException,ValueError,KeyError,TypeError) as exc:
            source_status[identifier]=_exception_state(exc);errors.append(identifier)
    for rule in settings()['rules']:
        if not rule.get('enabled',True):continue
        if rule['type'] in ('topic','project'):rule={**rule,'_latest_scan':True}
        if manual:rule={**rule,'_manual_latest':True}
        allowed=rule.get('sources') or ['wos','openalex','crossref']
        if 'wos' in allowed and rule['type'] in ('topic','project') and rule.get('wos_query'):
            identifier='WoS:'+rule['id']
            try:
                if progress:progress('检查 WoS · '+rule['id'])
                outcome=wos(rule,store)
                if outcome.get('status')!='not_due':outcome['counts']=store.cursor(scan_key('wos',rule),{}).get('last_counts',{})
                source_status[identifier]=outcome
                history_after('WoS',rule,wos,int(outcome.get('counts',{}).get('scanned') or 0))
                if outcome.get('coverage')=='daily_limit':budget_deferred.append(identifier)
                if outcome.get('status') not in ('completed','not_due'):
                    pending.append(identifier)
            except WoSNotConfigured as exc:
                source_status[identifier]={'status':'needs_configuration','message':str(exc)}
                skipped.append(identifier)
            except (requests.RequestException,ValueError,KeyError,TypeError) as exc:
                source_status[identifier]=_exception_state(exc)
                errors.append(identifier)
        for source,action in [('OpenAlex',metadata_watch if rule['type']=='paper' else openalex),('Crossref',crossref)]:
            if source.lower() not in allowed:continue
            if source=='Crossref' and rule['type'] not in ('topic','project'):continue
            if rule['type']=='retraction' and not (rule.get('work_id') or rule.get('doi')):continue
            effective={**rule,'query':(rule.get('provider_queries') or {}).get(source.lower(),rule.get('query',''))}
            clock = store.cursor(scan_key(source,rule), {})
            if not clock and not manual:
                previous=store.cursor('radar:'+source.lower()+':'+rule['id'],{})
                if previous.get('scan_day')==datetime.now(TZ).date().isoformat() and previous.get('done'):clock=previous
            scan_version=(CROSSREF_SCAN_VERSION if source=='Crossref' else OPENALEX_SCAN_VERSION)
            current_window=(rule['type'] in ('topic', 'project')
                and clock.get('rule_sha256') == rule_fingerprint(effective)
                and clock.get('scan_version') == scan_version
                and clock.get('scan_day') == datetime.now(TZ).date().isoformat())
            if not manual and current_window and clock.get('done'):
                top=clock.get('top_n',CROSSREF_TOP_N)
                source_status[source+':'+rule['id']]={
                    'status':'not_due','coverage':'bounded_top_n' if source=='Crossref' else 'cursor_window',
                    'scanned':int(clock.get('scanned') or 0),
                    'day_scanned':int(clock.get('day_scanned') or 0),
                    'limit':reminder_policy()['source_limit'],
                    'upstream_total':clock.get('upstream_total'),'window_complete':True,
                    **({'top_n':top} if source=='Crossref' else {}),
                    'message':('今日相关性前 '+str(top)+' 条的设定范围已检查，复用结果；不代表覆盖全部命中。'
                        if source=='Crossref' else '今日此关注已检查完成，复用结果；明日检查新入索引论文。')}
                history_after(source,effective,action)
                continue
            if (not manual and current_window
                    and (clock.get('day_scanned', 0) >= reminder_policy()['source_limit']
                         or (clock.get('pagination_mode')=='page' and clock.get('budget_deferred')
                             and reminder_policy()['source_limit']-clock.get('day_scanned',0)<clock.get('page_size',50)))):
                budget_deferred.append(source+':'+rule['id'])
                source_status[source+':'+rule['id']]={
                    'status':'completed','coverage':'daily_limit',
                    'scanned':int(clock.get('scanned') or 0),
                    'day_scanned':int(clock.get('day_scanned') or 0),
                    'limit':reminder_policy()['source_limit'],
                    'upstream_total':clock.get('upstream_total'),
                    'window_complete':bool(clock.get('done')),
                    'message':'已达到本机每日扫描上限，分页进度保留，明日接续；这不是 API 账户额度。',
                }
                continue
            try:
                if progress:progress('检查 '+source+' · '+rule['id'])
                if rule['type']=='retraction':action=metadata_watch
                outcome=action(effective,store)
                cursor=store.cursor(scan_key(source,rule),{})
                deferred=outcome is False and cursor.get('budget_deferred',False)
                detail={'status':'completed' if outcome is not False or deferred else 'pending',
                        'scanned':int(cursor.get('scanned') or 0),
                        'day_scanned':int(cursor.get('day_scanned') or 0),
                        'limit':reminder_policy()['source_limit'],
                        'counts':cursor.get('last_counts',{}),
                        'upstream_total':cursor.get('upstream_total'),
                        'window_complete':bool(cursor.get('done')),
                        'coverage':('daily_limit' if deferred else 'latest_window' if rule.get('_latest_scan') else 'bounded_top_n' if source=='Crossref' and rule['type'] in ('topic','project')
                                    else 'cursor_window')}
                if source=='Crossref' and not manual and not rule.get('_latest_scan'):
                    detail['top_n']=cursor.get('top_n',CROSSREF_TOP_N)
                    detail['message']='本次检查相关性前 '+str(detail['top_n'])+' 条范围，不代表全量覆盖。'
                if manual or rule.get('_latest_scan'):detail['message']='本次按最新日期检查最近 90 天题录，每来源/关注单轮最多 50 条；历史分页只使用本轮剩余扫描量。'
                if deferred:detail['message']='已达到本机每日扫描上限，分页进度保留，明日接续；这不是 API 账户额度。'
                source_status[source+':'+rule['id']]=detail
                history_after(source,effective,action,int(detail['counts'].get('scanned') or 0))
                if deferred:budget_deferred.append(source+':'+rule['id'])
                elif outcome is False:pending.append(source+':'+rule['id'])
            except (requests.RequestException,ValueError,KeyError,TypeError) as exc:
                source_status[source+':'+rule['id']]=_exception_state(exc)
                errors.append(source+':'+rule['id'])
    unavailable=[]
    if progress:progress('检查收藏论文的撤稿与更正')
    try:
        update_check=corrections(store);errors.extend(update_check['errors']);pending.extend(update_check['pending_pages']);unavailable=update_check['unavailable']
    except (requests.RequestException,ValueError,KeyError):errors.append('Crossref:updates')
    candidates=_export_with_retry(store)
    observed=datetime.now(TZ)
    retry_minutes=30 if errors else 15 if pending else None
    counts={key:sum(int(item.get('counts',{}).get(key) or 0) for item in source_status.values())
            for key in ('scanned','duplicate','new','matched','pending','failed','excluded')}
    counts['failed']+=len(errors)
    # Latest checks and historical catch-up share one daily allowance. Report
    # their sum instead of the last cursor's count (which may still be zero).
    rule_map={rule['id']:rule for rule in settings()['rules']}
    for identifier,detail in source_status.items():
        source,_,rule_id=identifier.partition(':')
        if rule_id in rule_map and source in ('WoS','OpenAlex','Crossref') and 'limit' in detail:
            left=daily_remaining(source.lower(),rule_map[rule_id],store)
            detail['day_scanned']=detail['limit']-left
            if detail.get('coverage')=='daily_limit' and left>0:
                detail['message']='受本机每日扫描上限约束，今日已用 '+str(detail['day_scanned'])+'/'+str(detail['limit'])+' 条，剩余 '+str(left)+' 条不足当前固定分页；保留进度，明日接续。这不是 API 账户额度。'
    from radar_inbox import candidate_identity
    decisions=store.radar_decisions()
    focused=[row for row in candidates['records'] if row['priority']['band']=='focus' and not row.get('selected')
             and (decisions.get(candidate_identity(row)) or {}).get('decision') not in RADAR_HANDLED_DECISIONS]
    result={'checked':w.now(),'manual':manual,'counts':counts,'candidates':len(candidates['records']),'pending_pages':pending,'errors':errors,'budget_deferred':budget_deferred,
            'skipped':skipped,'source_status':source_status,
            'unavailable':unavailable,'focus':len(focused),
            'status':'partial' if errors or pending else 'completed',
            'consecutive_failures':0 if not errors else int(store.cursor('radar:last_attempt',{}).get('consecutive_failures') or 0)+1,
            'next_retry_at':(observed+timedelta(minutes=retry_minutes)).isoformat() if retry_minutes else '',
            'coverage':'上游覆盖与索引延迟可能造成漏报；不声称零漏检。'}
    store.commit_page('radar:last_attempt',[],result)
    if not errors and not pending:store.commit_page('radar:last_success',[],result)
    w.atomic_text(w.KB/'文献/新论文候选.md','# 新论文提醒\n\n'+result['coverage']+'\n\n近期重点提醒 '+str(len(focused))+' 条；未入选记录不会进入知识区文献库。\n\n'+'\n'.join('- ['+r['title']+']('+r.get('url','')+') · '+r['priority']['reason']+' · 待核查 / 待选择收录' for r in focused)+'\n')
    return result


def collect(data):
    from radar_inbox import candidate_edit
    with candidate_edit() as candidates:
        key=data.get('id') or data.get('doi')
        record=next((r for r in candidates['records'] if key in (r.get('doi'),r.get('external_id'),r.get('openalex_id'),r.get('wos_id'))),None)
        if not record:raise ValueError('候选不存在')
        record['selected']=True;record['collection']={'selected_at':w.now(),'status':'selected'}
        return {'selected':True,'doi':record.get('doi'),'id':record.get('external_id'),
                'message':'已选择收录，后台接续获取与同步；无 DOI 的条目先保留来源稳定 ID。'}


def collect_many(data):
    """Select several existing candidates in one decision and retain per-item receipts."""
    from radar_inbox import candidate_edit
    items=data.get('items')
    if not isinstance(items,list) or not 1<=len(items)<=100:
        raise ValueError('每批请选择 1–100 篇论文。')
    results=[]
    with candidate_edit() as candidates:
        records=candidates['records']
        for item in items:
            key=item if isinstance(item,str) else (
                item.get('id') or item.get('doi') or item.get('external_id') or item.get('openalex_id')
                or item.get('wos_id'))
            if not key:
                results.append({'key':key,'status':'invalid','message':'候选缺少稳定身份。'})
                continue
            record=next((r for r in records if key in (
                r.get('doi'),r.get('external_id'),r.get('openalex_id'),r.get('wos_id'))),None)
            if not record:
                results.append({'key':key,'status':'not_found','message':'候选不存在或已退出当前范围。'})
                continue
            already=bool(record.get('selected'))
            record['selected']=True
            record['collection']=record.get('collection') or {'selected_at':w.now(),'status':'selected'}
            results.append({'key':key,'status':'already_selected' if already else 'selected',
                            'doi':record.get('doi'),'id':record.get('external_id')})
    selected=sum(item['status'] in ('selected','already_selected') for item in results)
    return {'selected':selected,'not_found':len(results)-selected,'items':results,
            'message':'已加入后台获取队列；每篇的全文、仅题录或失败状态继续单独保留。'}


def weekly(*, refresh=False, allow_model=True):
    local=datetime.now(TZ);week=local.strftime('%G-W%V');store=Store()
    path=w.KB/'笔记/共享/每周研究简报'/(week+'.md')
    relative=path.relative_to(w.KB).as_posix()
    w.DATA.mkdir(parents=True,exist_ok=True)
    # Serialize schedulers, including the crash between file creation and cursor commit.
    with FileLock(str(w.DATA/'.weekly-generation.lock'),timeout=30):
        import knowledge
        import weekly_brief
        rules=settings()['rules'];signature=weekly_brief.input_signature(rules,local,store)
        previous=store.cursor('radar:weekly',{})
        if path.exists() and not refresh and previous.get('week')==week and previous.get('schema')==2 and previous.get('input_signature')==signature:
            receipt={**(previous if previous.get('week')==week else {}),
                     'week':week,'path':relative,'observed_sha256':w.digest(path.read_bytes()),'preserved':True,
                     'records':previous.get('records') if previous.get('week')==week else None}
            store.commit_page('radar:weekly',[],receipt)
            return {'status':'already_saved',**receipt}
        since=(datetime.now(timezone.utc)-timedelta(days=7)).isoformat()
        before=(datetime.now(timezone.utc)-timedelta(days=14)).isoformat()
        seen=store.seen(include_cold=False);rows=[r for r in seen if r['first_seen']>=since]
        earlier=[r for r in seen if before<=r['first_seen']<since]
        alerts=[a for a in store.radar_alerts() if a['created']>=since]
        body,counts=weekly_brief.render(rows,rules,alerts,week,since,earlier,
                                       allow_model=allow_model and (refresh or not path.exists()))
        counts['input_signature']=signature
        if path.exists():
            # A refresh is always a preview against the same editable main draft.
            # Even a crash with no receipt must preserve the existing file.
            import ai_updates
            target=ai_updates.target_for({'target':'document','path':relative,'project':'共享'})
            body_signature=w.digest(body)
            if previous.get('week')==week and previous.get('proposed_sha256')==body_signature:
                receipt={**previous,'input_signature':signature}
                store.commit_page('radar:weekly',[],receipt)
                return {'status':'already_saved',**receipt,'preserved':True}
            proposal=ai_updates.store_proposal(target,{'kind':'document','summary':'本周新增线索与带证据候选；原周报保留，核对后更新。','body':body},
                                               '按当前关注范围刷新同一份周报，保留人工正文并核对证据','共享',automatic=True)
            receipt={**previous,**counts,'week':week,'path':relative,'preserved':True,'observed_sha256':w.digest(path.read_bytes()),
                     'proposed_sha256':body_signature,'proposal_id':proposal['id'],'updated':w.now(),
                     'auto_status':'observed','auto_reason':'本周更新待人工采纳'}
            store.commit_page('radar:weekly',[],receipt)
            return {'status':'already_saved',**receipt}
        with knowledge.editing():
            if path.exists():raise ValueError('周报在生成期间已创建，原稿保留；重新读取后可继续核对更新')
            raw=knowledge.properties('',{'type':'weekly_brief','project':'共享','status':'AI 整理 · 待核查',
                                         'maintenance_owner':'ai','managed_hash':w.digest(body.rstrip())})+body
            w.atomic_text(path,raw)
        receipt={**counts,'week':week,'path':relative,'generated_sha256':w.digest(raw),'created':w.now()}
        store.commit_page('radar:weekly',[],receipt)
        return {'status':'saved',**receipt}


def weekly_schedule_started(local):
    return local.weekday()>0 or (local.hour,local.minute)>=(8,30)


def weekly_if_due():
    local=datetime.now(TZ)
    if not weekly_schedule_started(local):return {'status':'not_due','message':'周报在北京时间每周一 08:30 后生成，错过后开机补上本周'}
    import weekly_brief
    state=weekly_brief.schedule_state(local)
    if not state['due']:return {'status':'already_saved'}
    return weekly(refresh=state['refresh'],allow_model=not state['refresh'])


def due(daily_time='08:30'):
    local=datetime.now(TZ);last=Store().cursor('radar:last_attempt',{})
    stamp=datetime.fromisoformat(last['checked']).astimezone(TZ) if last.get('checked') else None
    retry_at=last.get('next_retry_at')
    if retry_at:
        try:
            if local<datetime.fromisoformat(retry_at).astimezone(TZ):return False
        except ValueError:
            pass
    if stamp and stamp.date()==local.date() and last.get('budget_deferred') and not last.get('errors') and all(p.startswith('budget:') for p in last.get('pending_pages', [])):
        return False
    hour,minute=map(int,daily_time.split(':'))
    retry=timedelta(minutes=30) if last.get('errors') else timedelta(seconds=45)
    # A whole-pipeline exception records 'failed', not 'partial'. It must retry
    # after the same backoff, otherwise one transient error ends the day.
    retryable=bool(stamp) and last.get('status') in ('partial','failed') and local-stamp>=retry
    return (local.hour,local.minute)>=(hour,minute) and (not stamp or stamp.date()<local.date() or retryable)
