"""Bounded AI relevance suggestions, separate from lexical matches and research facts."""
from datetime import datetime,timezone,timedelta
import json
from filelock import FileLock
import workflow as w
from research_store import Store,RADAR_HANDLED_DECISIONS
from radar_inbox import TIERS,clean,decorate,relevance_fingerprint,candidate_identity,snapshot


def identity(row):
    return candidate_identity(row)


def validate(plan,inputs):
    if not isinstance(plan,dict) or set(plan)!={'rankings'} or not isinstance(plan['rankings'],list):
        raise ValueError('相关性整理需要完整的 rankings 列表')
    known={row['ref']:row for row in inputs};accepted={};rejected=[]
    for row in plan['rankings']:
        ref=row.get('ref') if isinstance(row,dict) else None
        if ref not in known or ref in accepted:raise ValueError('相关性整理引用了未知或重复对象')
        tier=row.get('tier');confidence=row.get('confidence');score=row.get('score');reason=row.get('reason');quote=row.get('quote')
        if tier not in TIERS and type(score) is int and 0<=score<=100:
            tier='direct' if score>=70 else 'adjacent' if score>=45 else 'background' if score>=30 else 'noise'
            confidence='medium'
        if (tier not in TIERS or confidence not in ('high','medium','low')
                or not isinstance(reason,str) or not 1<=len(reason)<=350
                or not isinstance(quote,str) or not 8<=len(quote)<=120
                or clean(quote).casefold() not in known[ref]['text'].casefold()):
            rejected.append(ref);continue
        accepted[ref]={'tier':tier,'confidence':confidence,'reason':reason,
                       'quote':quote,'scope':known[ref]['scope']}
        if type(score) is int and 0<=score<=100:accepted[ref]['score']=score
    if len(plan['rankings'])!=len(known) or set(accepted)|set(rejected)!=set(known):
        raise ValueError('相关性整理遗漏了输入对象')
    return accepted,rejected


def run(progress=None):
    w.DATA.mkdir(parents=True,exist_ok=True)
    with FileLock(str(w.DATA/'.radar-relevance-generation.lock'),timeout=30):
        return _run(progress)


def _run(progress=None):
    import research_radar,automation_controls
    from model_gateway import model_status
    rules=research_radar.settings()['rules'];store=Store()
    initial=snapshot();rows=decorate(initial['records'],rules)
    if not automation_controls.effective().get('ai_enabled',True):return {'status':'disabled','message':'AI 相关性建议已暂停，来源候选继续保留。'}
    if not model_status().get('configured'):return {'status':'needs_configuration','message':'等待现有 DeepSeek 连接，保留关键词命中排序。'}
    pending=[];updates={};cached=0;decisions=store.radar_decisions();processed=set()
    recent_since=datetime.now(timezone.utc)-timedelta(days=7)
    for row in rows:
        if row.get('selected') or row['priority'].get('tier','noise') not in ('direct','adjacent'):continue
        try:
            if datetime.fromisoformat(row.get('first_seen') or row.get('discovered'))<recent_since:continue
        except (TypeError,ValueError):continue
        ref=identity(row)
        if not ref:continue
        if (decisions.get(ref) or {}).get('decision') in RADAR_HANDLED_DECISIONS:continue
        signature=relevance_fingerprint(row,rules);old=store.cursor('radar:relevance:'+ref,{})
        if old.get('signature')==signature:
            processed.add(ref)
            if old.get('status')=='ready':updates[ref]=old;cached+=1
            continue # An invalid AI draft for the same version is not repeatedly paid for.
        if len(pending)<10:
            pending.append({'ref':ref,'signature':signature,'title':clean(row.get('title') or row.get('doi') or ''),
                'text':clean(row.get('abstract') or row.get('title'))[:4500],
                'scope':'来源摘要，未核查全文' if row.get('abstract') else '仅题录，未核查全文'})
    rejected=[];batch=store.cursor('radar:relevance:active-batch',{})
    if batch.get('status') in ('running','needs_attention'):
        if isinstance(batch.get('inputs'),list):pending=batch['inputs'] # Resume exactly this paid request, including after restart.
        else:batch={}
    if pending:
        if progress:progress('AI 正在按关注规则整理 '+str(len(pending))+' 条重点线索')
        import organization,structured_response
        payload={'model':'deepseek-flash','response_format':{'type':'json_object'},'thinking':{'type':'disabled'},'max_tokens':3500,
             'messages':[{'role':'system','content':organization.skill_text('radar')+'\n只返回JSON {"rankings":[{"ref":"输入ref","tier":"direct|adjacent|background|noise","confidence":"high|medium|low","reason":"简短理由与限制","quote":"输入原句"}]}。'},
                         {'role':'user','content':json.dumps({'watch_rules':rules,'inputs':pending},ensure_ascii=False)}]}
        if batch.get('status') in ('running','needs_attention'):payload=batch['payload']
        store.commit_page('radar:relevance:active-batch',[],{'status':'running','inputs':pending,'payload':payload,'created':batch.get('created') or w.now()})
        try:
            plan=structured_response.request(payload,'雷达相关性',lambda value:validate(value,pending))
            valid,rejected=validate(plan,pending)
            for row in pending:
                if (store.radar_decision(row['ref']) or {}).get('decision') in RADAR_HANDLED_DECISIONS:continue
                result={'signature':row['signature'],'created':w.now(),'status':'ready' if row['ref'] in valid else 'invalid_draft',
                        'model':'deepseek-flash',**valid.get(row['ref'],{})}
                store.commit_page('radar:relevance:'+row['ref'],[],result)
                processed.add(row['ref'])
                if row['ref'] in valid:updates[row['ref']]=result
            store.commit_page('radar:relevance:active-batch',[],{'status':'completed','inputs':pending,'created':w.now()})
        except ValueError as error:
            store.commit_page('radar:relevance:active-batch',[],{'status':'needs_attention','inputs':pending,'payload':payload,'created':w.now()})
            return {'status':'needs_attention','message':str(error),'cached':cached,'source_candidates_preserved':True}
    # AI results live in the small SQLite overlay. Rebuilding the 200+ MB
    # candidate corpus for every ten classifications made ordinary use fragile.
    remaining=0;decisions=store.radar_decisions()
    for row in rows:
        if (row['priority'].get('tier') in ('direct','adjacent')
                and not row.get('ai_relevance') and not row.get('selected')
                and identity(row) not in updates and identity(row) not in processed
                and (decisions.get(identity(row)) or {}).get('decision') not in RADAR_HANDLED_DECISIONS):
            try:
                if datetime.fromisoformat(row.get('first_seen') or row.get('discovered'))>=recent_since:
                    remaining+=1
            except (TypeError,ValueError):
                pass
    result={'status':'completed','ranked':len(updates),'cached':cached,'excluded':len(rejected),
            'remaining':max(0,remaining),
            'scope':'AI 只做直接证据/方法邻近/背景对照/噪声分层；题录/摘要未核查全文，收录仍由用户选择。','checked':w.now()}
    store.commit_page('radar:relevance',[],result)
    return result
