"""Bounded daily reading from existing discoveries; no model or source calls."""
from datetime import datetime,timedelta,timezone
import json
import hashlib
import re
from radar_inbox import clean,group_hits,rule_groups,rule_tier,nonresearch_title,TIERS,relevance_fingerprint

KEY='radar:daily-reading'
TZ=timezone(timedelta(hours=8))
DEFAULTS={'daily_limit':8,'method_limit':5,'background_limit':2,'include_older':True,
          'recent_days':90,'allow_repeat':True}


def validate_preferences(value=None):
    if value is None:value={}
    if not isinstance(value,dict) or set(value)-set(DEFAULTS):raise ValueError('每日阅读设置格式无效。')
    result={**DEFAULTS,**value}
    for key,low,high in [('daily_limit',1,30),('method_limit',0,30),('background_limit',0,30),('recent_days',7,365)]:
        if type(result[key]) is not int or not low<=result[key]<=high:
            raise ValueError('每日阅读数量须为1–30，方法和背景上限为0–30，近期范围为7–365天。')
    if any(type(result[key]) is not bool for key in ('include_older','allow_repeat')):
        raise ValueError('较早论文和重复推荐设置须为开关。')
    return result


def basis(row,rules=None):
    """Explain this title against the current watches, without a hidden field taxonomy."""
    if not clean(row.get('title')) or nonresearch_title(row):return None
    text=clean(row.get('title'))+' '+clean(row.get('abstract'))
    ids=set(row.get('watch_ids',[])+([row['watch_id']] if row.get('watch_id') else []))
    ids.update(m['id'] for m in (row.get('priority') or {}).get('matches',[]) if m.get('id'))
    matches=[]
    for rule in rules or []:
        if rule.get('enabled') is False or rule.get('reading_enabled') is False:continue
        if rule.get('type') in ('topic','project'):
            tier,reason=rule_tier(row,rule)
        elif rule['id'] in ids:
            tier,reason=rule.get('relevance_tier') or 'direct','来源标识匹配本人关注对象'
        else:continue
        if tier not in ('direct','adjacent','background'):continue
        criteria=rule.get('criteria') or {}
        terms=[term for group in rule_groups(rule)+criteria.get('optional',[]) for term in group_hits(text,group)]
        priority=sum(bool(group_hits(text,group)) for group in criteria.get('priority',[]))
        matches.append((TIERS.index(tier),priority,rule,tier,reason,terms))
    if not matches:return None
    _,_,rule,tier,reason,terms=max(matches,key=lambda m:m[:2])
    ai=row.get('ai_relevance') or {}
    if ai.get('status')=='ready' and ai.get('signature')==relevance_fingerprint(row,rules):
        ai_tier=ai.get('tier')
        if ai_tier not in TIERS and type(ai.get('score')) in (int,float):
            score=ai['score'];ai_tier='direct' if score>=70 else 'adjacent' if score>=45 else 'background' if score>=30 else 'noise'
        if ai_tier in TIERS and TIERS.index(ai_tier)<TIERS.index(tier):tier=ai_tier
    category={'direct':'主题相关','adjacent':'方法拓展','background':'课题背景'}.get(tier)
    if not category:return None
    name=rule.get('name') or rule.get('query') or rule['id']
    return {'category':category,'reason':'关注「'+name+'」：'+reason+('；命中：'+'、'.join(dict.fromkeys(terms)) if terms else ''),
            'watch_id':rule['id'],'watch_name':name,'priority':max(m[1] for m in matches),
            'evidence':'题名与来源摘要' if row.get('abstract') else '题名与关键词' if row.get('keywords') else '题名'}


def publication_order(row):
    value=str(row.get('publication_date') or row.get('year') or '')
    return value if re.fullmatch(r'\d{4}(?:-\d{2}){0,2}',value) else ''


def select(rows,state,*,excluded=(),now=None,rules=None,preferences=None):
    now=now or datetime.now(timezone.utc);day=now.astimezone(TZ).date().isoformat()
    preferences=validate_preferences(preferences)
    excluded=set(excluded)
    pool={r['id']:r for r in state.get('pool',[]) if isinstance(r,dict) and r.get('id')}
    pool.update({r['id']:r for r in rows if r.get('id')})
    def recent(row):
        value=publication_order(row)
        try:return datetime.fromisoformat(value+'-01'*(2-value.count('-'))).date()>=(now-timedelta(days=preferences['recent_days'])).date()
        except ValueError:return False
    explanations={key:basis(row,rules) for key,row in pool.items()}
    pool={key:row for key,row in pool.items() if key not in excluded and not row.get('selected') and explanations[key]
          and (preferences['include_older'] or recent(row))}
    # Metadata is a rebuildable cache in the existing ledger, never a second library.
    pool=dict(sorted(pool.items(),key=lambda item:publication_order(item[1]),reverse=True)[:240])
    history=[h for h in state.get('history',[]) if h.get('day') and 0<=(now.astimezone(TZ).date()-datetime.fromisoformat(h['day']).date()).days<7]
    seen={identifier for h in history if h['day']!=day for identifier in h.get('ids',[])}
    today=next((h.get('ids',[]) for h in history if h['day']==day),[])
    ranked=sorted((r for r in pool.values() if preferences['allow_repeat'] or r['id'] not in seen),
                  key=lambda r:(r['id'] not in seen,r['id'] in today,explanations[r['id']]['priority'],publication_order(r),r.get('first_seen') or '',r['id']),reverse=True)
    categories={'主题相关':[],'方法拓展':[],'课题背景':[]}
    for row in ranked:categories[explanations[row['id']]['category']].append(row)
    chosen=[]
    # Balance the feed; background never displaces a suitable direct/method paper.
    for category,limit in [('主题相关',preferences['daily_limit']),('方法拓展',preferences['method_limit']),('课题背景',preferences['background_limit'])]:
        chosen.extend(categories[category][:limit])
    chosen=chosen[:preferences['daily_limit']]
    result=[]
    for row in chosen:
        first=row.get('first_seen') or ''
        try:new=datetime.fromisoformat(first).astimezone(TZ).date().isoformat()==day
        except (ValueError,TypeError):new=False
        freshness='今日首次发现' if new else '再次推荐' if row['id'] in seen else '阅读补充'
        result.append({**row,'reading':{**explanations[row['id']],'freshness':freshness}})
    history=[h for h in history if h['day']!=day]+[{'day':day,'ids':[r['id'] for r in chosen]}]
    return result,{'day':day,'history':history[-7:],'pool':list(pool.values())}


def page(*,offset,limit,q,source,rank_system,rank_quartile):
    import radar_browse
    import research_radar
    import journal_ranks
    from research_store import Store
    store=Store();settings=research_radar.settings();rules=settings['rules'];preferences=validate_preferences(settings.get('reading'))
    base=radar_browse.page(scope='recent',limit=1)
    with radar_browse.LOCK,radar_browse.connection() as db:
        rows=[{**json.loads(r['data']),'id':r['identity']} for r in db.execute(
            "SELECT identity,data FROM candidates ORDER BY position LIMIT 1000")]
    # Rule/AI versions invalidate cached recommendations along with the browse index.
    signature=hashlib.sha256(json.dumps({'rules':rules,'reading':preferences,'version':2},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    state=store.cursor(KEY,{}) or {}
    if state.get('signature')!=signature:state={'history':state.get('history',[])}
    ai_checked=store.cursor('radar:relevance',{}).get('checked')
    if state.get('ai_checked')!=ai_checked:state={**state,'pool':[]}
    excluded=set(store.radar_decisions())
    excluded.update(key for key,value in store.radar_candidate_states().items() if value.get('selected'))
    candidates,saved=select(rows,state,excluded=excluded,rules=rules,preferences=preferences)
    saved['signature']=signature
    saved['ai_checked']=ai_checked
    if saved!=state:store.commit_page(KEY,[],saved)
    count=len(candidates)
    ranks=journal_ranks.resolve_many(candidates)
    candidates=[{**r,'journal_ranks':ranks.get(r['id'])} for r in candidates
        if (not q or q.casefold() in ' '.join(str(r.get(k) or '') for k in ('title','abstract','doi','source')).casefold())
        and (not source or source in (r.get('sources') or [r.get('source')]))
        and (not rank_quartile or journal_ranks.matches_filter(ranks.get(r['id']),rank_system,rank_quartile))]
    return {**base,'candidates':candidates[offset:offset+limit],
        'total':len(candidates),'offset':offset,'limit':limit,'has_more':offset+limit<len(candidates),
        'counts':{**base['counts'],'reading':count},'reading':{
            'day':saved['day'],'target':preferences['daily_limit'],'preferences':preferences,'available':count,'basis':'题录与可得摘要，未核查全文',
            'first_seen_today':sum(r['reading']['freshness']=='今日首次发现' for r in candidates),
            'message':'优先未推荐的近期材料；阅读补充和再次推荐保留原发表日期，不计入今日首次发现。'}}
