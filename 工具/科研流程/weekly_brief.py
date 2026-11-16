"""One editable weekly brief, with bounded, quoted and source-validated candidates."""
import json
import re
import workflow as w
from research_store import Store,RADAR_HANDLED_DECISIONS
from radar_inbox import clean, decorate, merged,candidate_identity

SCHEMA = 2
SECTIONS = {'methods': '新方法与可借鉴做法', 'emerging': '热点与新主题线索',
            'teams': '关注团队动态', 'gaps': '潜在研究问题与 Gap 候选'}


def reviewable(rows,rules):
    store=Store();decisions=store.radar_decisions()
    return [row for row in decorate(merged(rows),rules,relevance=store.radar_relevance())
            if row['priority']['tier'] in ('direct','adjacent','background') and not row.get('selected')
            and decisions.get(candidate_identity(row),{}).get('decision') not in RADAR_HANDLED_DECISIONS]


def content_rules(rules):
    return [{key:value for key,value in rule.items() if key!='reading_enabled'} for rule in rules]


def input_signature(rules,local,store=None):
    """Cheap invalidation only; no corpus read or model call on scheduling ticks."""
    store=store or Store();path=w.DATA/'candidates.json'
    legacy={'mtime':path.stat().st_mtime_ns,'size':path.stat().st_size} if path.exists() else None
    with store.connection() as db:
        alerts=dict(db.execute("SELECT COUNT(*) AS n,COALESCE(MAX(created),'') AS updated FROM radar_alerts").fetchone())
    return w.digest(json.dumps({'version':1,'day':local.date().isoformat(),'rules':content_rules(rules),
        'source':store.radar_source_signature(),'legacy':legacy,'alerts':alerts},sort_keys=True,ensure_ascii=False))


def schedule_state(local,store=None):
    import research_radar
    store=store or Store();receipt=store.cursor('radar:weekly',{})
    week=local.strftime('%G-W%V');signature=input_signature(research_radar.settings()['rules'],local,store)
    refresh=receipt.get('week')==week and receipt.get('schema')==SCHEMA
    return {'due':not refresh or receipt.get('input_signature')!=signature,
            'refresh':refresh,'signature':signature,'week':week}


def status(store=None):
    import research_radar
    store=store or Store();receipt=store.cursor('radar:weekly',{})
    if not receipt:return receipt
    state=schedule_state(research_radar.datetime.now(research_radar.TZ),store)
    proposal=w.read_json(w.DATA/'AI修改'/(receipt.get('proposal_id','')+'.json'),{}) if receipt.get('proposal_id') else {}
    return {**receipt,'stale':state['due'],'proposal_pending':proposal.get('status')=='待确认'}


def materials(rows, rules):
    """Metadata and local reading excerpts remain distinct evidence scopes."""
    focused = [row for row in reviewable(rows,rules) if row['priority']['band'] == 'focus']
    sources = []
    for row in focused[:16]:
        ref = 'RADAR-' + w.digest((row.get('doi') or row.get('openalex_id') or row['source']+':'+row['external_id']))[:16]
        sources.append({'ref': ref, 'title': clean(row['title']), 'url': row['url'],
                        'scope': '来源摘要，未核查原文' if row.get('abstract') else '仅题录',
                        'kind': 'abstract' if row.get('abstract') else 'metadata',
                        'text': clean(row.get('abstract') or row['title'])[:4500]})
    projects = sorted({r.get('project') for r in rules if r.get('enabled', True) and r.get('project') not in (None, '', '共享')})
    import organization
    seen = set()
    for project in projects[:4]:
        try: inputs, _ = organization.paper_inputs(project)
        except ValueError: continue
        for paper in inputs:
            if paper['id'] in seen: continue
            same = next((r for r in focused if r.get('doi') and w.normalize_doi(r['doi']) == w.normalize_doi(paper.get('doi'))), None)
            if not same: continue
            seen.add(paper['id'])
            for part in paper['sources'][:2]:
                sources.append({'ref': paper['id']+':'+part['ref'], 'title': paper['title'],
                                'url': 'http://127.0.0.1:8503/#paper?id='+paper['id'],
                                'scope': part['location'], 'kind': 'excerpt', 'text': part['text'][:4500]})
            if len(sources) >= 20: break
    return sources[:20]


def validate(plan, sources):
    known = {s['ref']: s for s in sources}; result = {key: [] for key in SECTIONS}; quoted = {}
    if not isinstance(plan, dict) or set(plan) != set(SECTIONS): raise ValueError('周报候选必须包含四类内容')
    for section in SECTIONS:
        rows = plan[section]
        if not isinstance(rows, list) or len(rows) > 3: raise ValueError('每类周报候选最多三条')
        for row in rows:
            if not isinstance(row, dict): raise ValueError('周报候选格式无效')
            text = row.get('text'); conditions = row.get('conditions'); limitation = row.get('limitation')
            if any(not isinstance(v, str) or not v.strip() or len(v) > maximum for v, maximum in
                   ((text, 900), (conditions, 400), (limitation, 400))): raise ValueError('周报候选缺少说明、条件或证据限制')
            evidence = row.get('evidence')
            if not isinstance(evidence, list) or not 1 <= len(evidence) <= 3: raise ValueError('周报候选需要真实证据')
            refs = set()
            for entry in evidence:
                if not isinstance(entry, dict) or entry.get('ref') not in known: raise ValueError('周报引用了未提供的来源')
                ref = entry['ref']; source = known[ref]; quote = entry.get('quote'); refs.add(ref)
                if not isinstance(quote, str) or not 8 <= len(quote) <= 120 or clean(quote).casefold() not in clean(source['text']).casefold():
                    raise ValueError('周报引文必须与提供片段精确对应')
                if section in ('methods', 'gaps') and source['kind'] == 'metadata': raise ValueError('题录不能支持方法或 Gap 判断')
                quoted.setdefault(ref, set()).add(quote)
            if section == 'gaps' and re.search(r'首次提出|从未研究|没有任何研究|全球空白|no prior studies|first ever|has never been',text,re.I):
                raise ValueError('现有片段不能证明全球空白或首次性；请改写为待查新的具体问题')
            result[section].append({key: row[key] for key in ('text', 'conditions', 'limitation', 'evidence')})
    for quotes in quoted.values():
        if sum(len(re.findall(r'\b[\w-]+\b', q)) for q in quotes) > 25 or sum(len(re.findall(r'[\u4e00-\u9fff]', q)) for q in quotes) > 100:
            raise ValueError('同一来源的直接引文过长，请缩短引文')
    return result


def verified_candidates(plan,sources):
    """Quarantine individual invalid drafts; retain independently validated evidence."""
    if not isinstance(plan,dict) or set(plan)!=set(SECTIONS):raise ValueError('周报候选必须包含四类内容')
    accepted={key:[] for key in SECTIONS};rejected=[]
    for section in SECTIONS:
        if not isinstance(plan[section],list) or len(plan[section])>3:raise ValueError('每类周报候选最多三条')
        for index,row in enumerate(plan[section]):
            trial={key:list(rows) for key,rows in accepted.items()};trial[section].append(row)
            try:accepted=validate(trial,sources)
            except ValueError as error:rejected.append({'section':section,'index':index,'reason':str(error)})
    return accepted,rejected


def synthesis(rows, rules, week, *, allow_model=True):
    sources = materials(rows, rules)
    # Titles can classify a topic, but cannot invent a method, result or research gap.
    if not any(s['kind'] != 'metadata' for s in sources):
        return {'status': 'insufficient_evidence', 'sources': sources, 'sections': {}, 'message': '目前只有题录，等待摘要或阅读片段。'}
    signature = w.digest(json.dumps({'schema': SCHEMA, 'validation_schema':2, 'sources': sources, 'rules': content_rules(rules)}, ensure_ascii=False, sort_keys=True))
    key = 'radar:weekly-synthesis:'+week; store = Store(); previous = store.cursor(key, {})
    if previous.get('signature') == signature and previous.get('status') == 'ready': return {**previous, 'reused': True}
    if not allow_model:
        return {'status':'pending_refresh','sources':sources,'sections':{},
                'message':'题录与统计已按当前规则更新；需要时可手动整理新版证据候选。'}
    import automation_controls
    if not automation_controls.effective().get('ai_enabled', True):
        return {'status': 'disabled', 'sources': sources, 'sections': {}, 'message': 'AI 自动整理已暂停；题录与统计仍正常更新。'}
    from model_gateway import model_status
    if not model_status().get('configured'):
        return {'status': 'needs_configuration', 'sources': sources, 'sections': {}, 'message': 'DeepSeek 尚未连接，保留来源等待整理。'}
    import organization, structured_response
    example = {key: [{'text': '带条件的候选，不能声称已查明事实或全球空白', 'conditions': '适用范围',
                     'limitation': '材料与核查限制', 'evidence': [{'ref': '输入 ref', 'quote': '输入片段中的原句，简短引用'}]}] for key in SECTIONS}
    rules_bundle=__import__('research_prompts').bundle('weekly')
    payload = {'model': 'deepseek-flash', 'response_format': {'type': 'json_object'}, 'thinking': {'type': 'disabled'}, 'max_tokens': 6500,
               'messages': [{'role': 'system', 'content': rules_bundle['text']+'\n只输出 JSON：'+json.dumps(example, ensure_ascii=False)},
                            {'role': 'user', 'content': json.dumps({'week': week, 'sources': sources}, ensure_ascii=False)}]}
    try:
        plan = structured_response.request(payload, '周报证据整理', lambda p: verified_candidates(p, sources))
        sections,rejected=verified_candidates(plan,sources)
        result = {'status': 'ready', 'rule_versions':rules_bundle['versions'], 'signature': signature, 'sources': sources, 'sections':sections,'rejected':rejected,
                  'message':('已自动排除 '+str(len(rejected))+' 条未通过来源校验的草稿；其余候选仍需核对。') if rejected else '', 'created': w.now()}
        store.commit_page(key, [], result)
        return result
    except ValueError as exc:
        # The model request ledger owns paid-call reuse and unknown-outcome protection.
        kept={key:previous[key] for key in ('sources','sections') if key in previous} if previous.get('status')=='ready' else {}
        return {'status': 'needs_attention', 'sources': sources, 'sections': {}, **kept,
                'retained_previous':bool(kept),'message': str(exc)}


def md(text):
    return clean(text).replace('[', '\\[').replace(']', '\\]')


def render(rows, rules, alerts, week, since, previous_rows=(), *, allow_model=True):
    all_rows = reviewable(rows,rules); focus = [r for r in all_rows if r['priority']['band'] == 'focus']
    extra = [r for r in all_rows if r['priority']['band'] != 'focus']
    ai = synthesis(all_rows, rules, week,allow_model=allow_model)
    body = '# Weekly Research Brief · '+week+'\n\n'
    body += '范围：最近七天本系统首次发现、当前仍未处理的资料；发表日期与首次发现日期分开。已浏览、略过、稍后及已选择收录的资料保留在雷达历史与相应清单，不重复列为阅读待办。题录、摘要和 AI 候选不代表核查全文或正式科研结论。\n\n'
    body += '## 本周概览\n\n重点线索 '+str(len(focus))+' 篇；补充线索 '+str(len(extra))+' 篇；引用与出版变化 '+str(len(alerts))+' 条。\n\n'
    body += '## 重点论文与项目关联\n\n'
    body += '\n'.join('- ['+md(r['title'])+']('+r['url']+') · '+', '.join(r['sources'])+' · '+md(r.get('project', '共享'))+' · '+md(r['priority']['reason']) for r in focus[:30]) or '本周没有命中重点范围的新论文。'
    if len(focus) > 30: body += '\n\n其余 '+str(len(focus)-30)+' 篇在[雷达重点线索](http://127.0.0.1:8503/#discover?radar=focus)查看。'
    body += '\n\n## 关注对象与团队动态\n\n'
    names = {'topic': '主题', 'project': '项目', 'paper': '论文', 'author': '作者', 'institution': '机构', 'lab': '团队/PI', 'citation': '引用', 'retraction': '出版更新'}
    groups = []
    previous_focus=[row for row in reviewable(previous_rows,rules) if row['priority']['band']=='focus']
    for rule in rules:
        if rule.get('enabled') is False: continue
        count = sum(rule['id'] in r.get('watch_ids', []) for r in focus)
        old = sum(rule['id'] in r.get('watch_ids', []) for r in previous_focus)
        if count or old:
            groups.append('- '+names[rule['type']]+' · '+md(rule.get('query') or rule.get('author_id') or rule.get('institution_id') or rule.get('work_id') or rule.get('doi') or rule['id'])+'：本周首次发现 '+str(count)+' 篇；前七天 '+str(old)+' 篇。')
    body += '\n'.join(groups) or '本周没有对应关注对象的新线索。'
    body += '\n\n以上只统计本地发现范围；检索词、回查和索引延迟会影响数量，不能用来证明领域热度升降。\n'
    body += '\n## 引用与撤稿／更正\n\n'
    labels = {'citation': '引用数量变化', 'retraction': '撤稿标记变化', 'metadata': '题录变化', 'publication_update': '出版更新线索'}
    for a in alerts:
        detail = (' · '+str((a.get('before') or {}).get('citation_count', '未记录'))+' → '+str((a.get('after') or {}).get('citation_count', '未提供'))) if a['kind'] == 'citation' else ''
        body += '- ['+md(a.get('title') or a['external_id'])+']('+a['url']+') · '+labels.get(a['kind'], a['kind'])+detail+' · '+a['source']+'\n'
    if not alerts: body += '本周没有首次发现的更新线索；不代表上游没有更新。\n'
    known = {s['ref']: s for s in ai['sources']}
    if ai.get('retained_previous'):body += '\n本轮 AI 整理未成功。下面保留上次成功候选及其原证据，尚未依据最新资料更新。\n'
    for section, title in SECTIONS.items():
        body += '\n## '+title+'\n\n'
        entries = ai.get('sections', {}).get(section, [])
        if not entries: body += '当前来源尚未形成可核查候选；可补充相关摘要、原文或阅读记录。\n'; continue
        for entry in entries:
            body += '- **AI 候选 · 待核对**：'+entry['text']+'\n\n  适用条件：'+entry['conditions']+'\n\n  证据限制：'+entry['limitation']+'\n\n'
            for evidence in entry['evidence']:
                source = known[evidence['ref']]
                body += '  来源：['+md(source['title'])+']('+source['url']+') · '+md(source['scope'])+' · “'+md(evidence['quote'])+'”\n\n'
    body += '\n## 补充线索与下一步\n\n'
    body += '补充 '+str(len(extra))+' 篇均保留在[雷达补充线索](http://127.0.0.1:8503/#discover?radar=supplementary)，不混入重点论文数量。优先核查相关原文，再决定是否收录及调整项目判断。\n'
    if len(extra) <= 5:
        body += '\n'+'\n'.join('- ['+md(r['title'])+']('+r['url']+') · '+', '.join(r['sources'])+' · '+md(r['priority']['reason']) for r in extra)+'\n'
    candidate_count=sum(len(v) for v in ai.get('sections',{}).values())
    ready_message='已生成 '+str(candidate_count)+' 条带证据候选，等待核对' if candidate_count else '已检查现有证据，本周暂无可靠候选'
    body += '\n自动整理状态：'+{'ready': ready_message, 'insufficient_evidence': '等待更多证据', 'disabled': '已暂停', 'needs_configuration': '等待模型连接', 'needs_attention': '需要检查','pending_refresh':'题录已更新，证据候选按需整理'}.get(ai['status'], ai['status'])+'。'+ai.get('message', '')+'\n'
    return body, {'records': len(all_rows), 'focus': len(focus), 'supplementary': len(extra), 'alerts': len(alerts),
                  'synthesis_status': ai['status'], 'candidate_count':candidate_count, 'schema': SCHEMA}
