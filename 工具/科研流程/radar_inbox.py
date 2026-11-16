"""Rebuildable watch relevance: retain every discovery, explain the inbox priority."""
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
from filelock import FileLock
import json
import re
import workflow as w


DEFAULT_SCOPES = {
    'topic-1': [['terahertz', 'thz', '太赫兹'], ['yam', 'dioscorea', 'starch', '淀粉', '山药']],
    'topic-2': [['yam', 'dioscorea', '山药'], ['cultivar', 'variety', 'varieties', 'identification', '品种', '鉴别']],
    'topic-3': [['terahertz', 'thz', '太赫兹'], ['powder', 'pellet', 'particle', 'sample preparation', '粉末', '压片', '粒径', '制样']],
}
AI_FOCUS_MIN_SCORE = 20
TIERS = ('noise', 'pending', 'background', 'adjacent', 'direct')
TIER_LABELS = {
    'direct': '主题相关',
    'adjacent': '方法相关',
    'background': '拓展阅读',
    'noise': '噪声档案',
    'pending': '题录待判断',
}
THZ_TERMS = ('terahertz', 'thz', '太赫兹', '太赫兹光谱')
YAM_TERMS = ('yam', 'dioscorea', 'chinese yam', '山药', '薯蓣')
STARCH_TERMS = ('starch', '淀粉')
IDENTIFICATION_TERMS = (
    'cultivar', 'variety', 'varieties', 'identification', 'discrimination',
    'authentication', 'classification', '品种', '鉴别', '识别', '分类',
)
PREPARATION_TERMS = (
    'powder', 'pellet', 'particle', 'sample preparation', 'tablet',
    'pressed pellet', '粉末', '压片', '粒径', '制样',
)
FOOD_MATERIAL_TERMS = (
    'food', 'flour', 'biomass', 'plant', 'seed', 'tea', 'protein',
    'carbohydrate', 'lactose', 'glucose', 'sugar', '食品', '面粉', '植物',
    '种子', '蛋白', '糖',
)
SPECTRAL_TERMS = (
    'spectroscopy', 'spectroscopic', 'spectrum', 'spectra', 'spectral', 'ftir', 'raman',
    'hyperspectral', 'near-infrared', 'nir', '光谱', '红外', '拉曼',
)


def clean(value):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]*>', ' ', str(value or ''))).strip()


def contains(text, term):
    if re.search(r'[\u4e00-\u9fff]', term):
        return term.casefold() in text.casefold()
    return re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', text, re.I) is not None


def _matched(text, terms):
    return [term for term in terms if contains(text, term)]


def group_hits(text, terms):
    """Respect the sense of a physical-particle group, without changing queries."""
    physical=bool({term.casefold() for term in terms}&{'powder','pellet','sample preparation','粉末','压片','粒径','制样'})
    if physical:
        text=re.sub(r'\bparticles?\s+swarm\b','swarm',text,flags=re.I)
    return [term for term in terms if contains(text,term)
            or physical and term.casefold() in {'powder','pellet','particle'} and contains(text,term+'s')]


def semantic_axes(row):
    """Return interpretable content axes before assigning a research tier."""
    title = clean(row.get('title'))
    abstract = clean(row.get('abstract'))
    text = title + ' ' + abstract+' '+' '.join(str(value) for value in row.get('keywords',[]) if isinstance(value,str))
    # "YAM" is also a common bone-density abbreviation ("young adult mean").
    # Do not turn that acronym into the food crop.
    crop_text = re.sub(r'young adult mean\s*\(?\s*yam\s*\)?', ' ', text, flags=re.I)
    axes = {
        'terahertz': _matched(text, THZ_TERMS),
        'yam': _matched(crop_text, YAM_TERMS),
        'starch': _matched(text, STARCH_TERMS),
        'identification': _matched(text, IDENTIFICATION_TERMS),
        'preparation': _matched(text, PREPARATION_TERMS),
        'food_material': _matched(text, FOOD_MATERIAL_TERMS),
        'spectroscopy': _matched(text, SPECTRAL_TERMS),
    }
    axes['project_object'] = sorted(set(axes['yam'] + axes['starch']))
    axes['method'] = axes['terahertz'] or axes['spectroscopy']
    return axes


def nonresearch_title(row):
    return re.match(r'^\s*(?:review for|author response for|decision letter for)\b',
                    clean(row.get('title')), re.I) is not None


def content_tier(row, axes=None):
    """Legacy project classification for retained unscoped historical records."""
    if nonresearch_title(row):
        return 'noise', '同行评审材料，不是可收录的研究论文'
    axes = axes or semantic_axes(row)
    if axes['terahertz'] and axes['yam']:
        return 'direct', '太赫兹与山药/薯蓣对象同时出现'
    if axes['terahertz'] and axes['starch']:
        return 'adjacent', '太赫兹与淀粉对象同时出现，需判断是否服务品种分类'
    if axes['terahertz'] and axes['preparation'] and axes['food_material']:
        return 'adjacent', '太赫兹食品/生物样品制样方法，可迁移但对象并非山药'
    if (axes['yam'] or axes['starch']) and (axes['identification'] or axes['spectroscopy']):
        return 'background', '山药/淀粉鉴别或光谱背景，但不是太赫兹直接证据'
    if axes['terahertz']:
        return 'noise', '只命中太赫兹，未出现山药、淀粉或可迁移的食品样品任务'
    return 'noise', '未形成对象、方法和任务的可用交集'


def rule_groups(rule):
    criteria=rule.get('criteria') or {}
    groups=criteria.get('required') or rule.get('include_groups')
    if groups:return groups
    from research_radar import DEFAULT_QUERIES
    if rule.get('id') in DEFAULT_SCOPES:
        index=int(rule['id'][-1])-1
        if rule.get('query')==DEFAULT_QUERIES[index]:return DEFAULT_SCOPES[rule['id']]
    return [[term] for term in re.findall(r'[\w-]+',rule.get('query',''))
            if term.casefold() not in ('and','or','not','the','of','in','a')]


def rule_tier(row, rule, axes=None):
    """Use the saved watch conditions; project labels never add hidden gates."""
    if nonresearch_title(row):return 'noise','同行评审材料，不作为研究论文提醒'
    text=clean(row.get('title'))+' '+clean(row.get('abstract'))+' '+' '.join(
        str(value) for value in row.get('keywords',[]) if isinstance(value,str))
    criteria=rule.get('criteria') or {}
    if any(group_hits(text,group) for group in criteria.get('exclusion',[])):
        return 'noise','命中本人设置的排除条件'
    groups=rule_groups(rule)
    hits=[group_hits(text,group) for group in groups]
    if groups and all(hits):
        preferred=criteria.get('priority') or []
        count=sum(bool(group_hits(text,group)) for group in preferred)
        preference=('；优先条件 '+str(count)+'/'+str(len(preferred))) if preferred else ''
        return rule.get('relevance_tier') or 'direct','命中该关注的全部必须概念'+preference+'；依据为题录与可得摘要'
    methods=[term for group in criteria.get('optional',[]) for term in group_hits(text,group)]
    if methods:
        return 'adjacent','命中本人指定的方法参考：'+'、'.join(methods)+'；未同时满足主题全部必须条件'
    native_match=(row.get('source')=='WoS' and
                  ((bool(row.get('query')) and row.get('query')==rule.get('query')) or not criteria))
    if not row.get('abstract') and (any(hits) or native_match):
        return 'pending','检索返回的题录缺摘要，无法核对全部必须条件；保留题录待判断'
    return 'noise','未同时命中本关注的全部必须概念'


def candidate_identity(row):
    key = row.get('doi') or row.get('openalex_id') or row.get('wos_id')
    if not key and row.get('source') and row.get('external_id'):
        key = str(row['source']) + ':' + str(row['external_id'])
    return 'RADAR-' + w.digest(str(key))[:16] if key else None


def priority(row, rules, axes=None):
    text = clean(row.get('title')) + ' ' + clean(row.get('abstract'))+' '+' '.join(
        value for value in row.get('keywords',[]) if isinstance(value,str))
    axes = axes or semantic_axes(row)
    ids = set(row.get('watch_ids', []) + ([row['watch_id']] if row.get('watch_id') else []))
    if not ids and row.get('query'):
        ids.update(rule['id'] for rule in rules if rule.get('query') == row['query'])
    matches = []
    for rule in rules:
        if rule.get('enabled') is False or rule['id'] not in ids:
            continue
        kind = rule['type']
        if kind in ('author', 'institution', 'lab', 'citation', 'paper', 'retraction'):
            matches.append({'id': rule['id'], 'score': 100, 'focused': True,
                            'tier': rule.get('relevance_tier') or 'direct',
                            'reason': '来源标识匹配关注对象', 'terms': []})
            continue
        groups = rule_groups(rule)
        if groups:
            hits = [group_hits(text,group) for group in groups]
            focused = all(hits)
            terms = [term for group in hits for term in group]
            score = round(100 * sum(bool(group) for group in hits) / len(hits))
        else:
            # A transparent lexical aid, never an AI score or scientific judgement.
            terms = [word for word in re.findall(r'[\w-]+', rule.get('query', ''))
                     if word.casefold() not in ('and', 'or', 'not', 'the', 'of', 'in', 'a')]
            hits = [term for term in terms if contains(text, term)]
            score = round(100 * len(hits) / len(terms)) if terms else 0
            focused = bool(terms) and score >= 60
            terms = hits
        preferred=(rule.get('criteria') or {}).get('priority') or []
        if preferred:
            ratio=sum(bool(group_hits(text,group)) for group in preferred)/len(preferred)
            score=round(score*.8+20*ratio)
        tier, tier_reason = rule_tier(row, rule, axes)
        matches.append({'id': rule['id'], 'score': score, 'focused': tier == 'direct',
                        'tier': tier,
                        'reason': tier_reason + ('；命中：' + '、'.join(terms) if terms else ''),
                        'terms': terms})
    best = max(matches, key=lambda item: (TIERS.index(item.get('tier', 'noise')), item['score']), default={})
    disabled={rule['id'] for rule in rules if rule.get('enabled') is False}
    detected_tier, detected_reason = ('noise','关注已关闭，保留历史题录') if ids and ids<=disabled else content_tier(row, axes)
    tier = best.get('tier', detected_tier)
    return {'band': 'focus' if tier in ('direct', 'adjacent') else 'supplementary',
            'tier': tier, 'tier_label': TIER_LABELS[tier],
            'score': best.get('score', 0),
            'reason': best.get('reason', detected_reason + '；尚未对应当前关注规则'),
            'matches': matches,
            'recommendable':tier in ('direct','adjacent','background'),
            'basis': '对象 / 方法 / 任务分层，科研相关性待核查'}


def relevance_fingerprint(row,rules):
    rules=[{key:value for key,value in rule.items() if key!='reading_enabled'} for rule in rules]
    return w.digest(__import__('json').dumps({'title':clean(row.get('title')),'abstract':clean(row.get('abstract')),
            'doi':w.normalize_doi(row.get('doi')),'openalex_id':row.get('openalex_id'),
            'watch_ids':sorted(row.get('watch_ids',[])),'rules':rules,'policy':'watch-criteria-v2'},sort_keys=True,ensure_ascii=False))


class CandidateSnapshot(dict):
    """One operation's material, with a file identity checked again at commit."""
    def __init__(self, data, stamp):
        super().__init__(data)
        self.stamp = stamp


class SnapshotBusy(ValueError):
    """The source changed between two reads; a bounded caller retry is safe."""


def _source_stamp():
    path = w.DATA/'candidates.json'
    if path.exists():
        value = path.stat()
        return ('legacy',str(path.resolve()),value.st_ino,value.st_size,value.st_mtime_ns)
    from research_store import Store
    return ('sqlite',w.digest(json.dumps(Store().radar_source_signature(),sort_keys=True)))


def snapshot():
    path=w.DATA/'candidates.json'
    if not path.exists():
        from research_store import Store
        store=Store()
        for _ in range(2):
            before=store.radar_source_signature()
            # Cold noise remains in Seen for duplicate suppression but is not
            # material for browsing, AI ranking, acquisition or weekly briefs.
            rows=store.seen(include_cold=False)
            states=store.radar_candidate_states()
            after=store.radar_source_signature()
            if before==after:break
        else:
            raise SnapshotBusy('候选资料正在更新，请稍后重试；原选用保留。')
        records=merged(rows)
        indexed={candidate_identity(row):row for row in records}
        for identity,state in states.items():
            legacy=state.get('legacy_record')
            row=indexed.get(identity)
            if row is None and isinstance(legacy,dict):
                row={**legacy}
                records.append(row);indexed[identity]=row
            if row is not None:
                row.update({key:value for key,value in state.items()
                            if key in ('selected','collection','acquisition','workspace_id',
                                       'workspace_record','evidence_status','project')})
        stamp=('sqlite',w.digest(json.dumps(after,sort_keys=True)))
        return CandidateSnapshot({'records':records,'checked':w.now()},stamp)
    for _ in range(2):
        before = _source_stamp()
        data = w.read_json(w.DATA/'candidates.json', {'records': []})
        after = _source_stamp()
        if before == after:return CandidateSnapshot(data, after)
    raise SnapshotBusy('候选资料正在更新，请稍后重试；原选用保留。')


def _content_digest(text):
    import hashlib
    digest=hashlib.sha256()
    for start in range(0,len(text),65536):digest.update(text[start:start+65536].encode('utf-8'))
    return digest.digest()


@contextmanager
def candidate_edit(material=None):
    w.DATA.mkdir(parents=True,exist_ok=True)
    with FileLock(str(w.DATA/'.radar-candidates.lock'),timeout=30):
        data=material if isinstance(material,CandidateSnapshot) and material.stamp==_source_stamp() else snapshot()
        if not (w.DATA/'candidates.json').exists():
            from research_store import Store
            fields=('selected','collection','acquisition','workspace_id',
                    'workspace_record','evidence_status','project','candidate_id','legacy_record')
            known_identities={candidate_identity(row) for row in data['records'] if candidate_identity(row)}
            before={candidate_identity(row):{key:row[key] for key in fields if key in row}
                    for row in data['records'] if candidate_identity(row)}
            yield data
            store=Store()
            for row in data['records']:
                identity=candidate_identity(row)
                if not identity:continue
                current={key:row[key] for key in fields if key in row}
                if current!=before.get(identity,{}):
                    if identity not in known_identities:
                        current['legacy_record']=dict(row)
                    store.update_radar_candidate_state(
                        identity,{key:current.get(key) for key in current})
            data.stamp=_source_stamp()
            return
        before=_content_digest(json.dumps(data,ensure_ascii=False,separators=(',',':'),sort_keys=True))
        yield data
        serialized=json.dumps(data,ensure_ascii=False,separators=(',',':'),sort_keys=True)
        if _content_digest(serialized)!=before:w.atomic_text(w.DATA/'candidates.json',serialized)
        data.stamp=_source_stamp()


def update_candidate(identifier,changes):
    with candidate_edit() as data:
        row=next((r for r in data['records'] if identifier in (r.get('doi'),r.get('openalex_id'),r.get('external_id'))),None)
        if row is None:return False
        if not (w.DATA/'candidates.json').exists():
            allowed={'selected','collection','acquisition','workspace_id',
                     'workspace_record','evidence_status','project','candidate_id','legacy_record'}
            if set(changes)-allowed:raise ValueError('SQLite 候选状态不支持修改该元数据字段')
        row.update(changes)
        return True


def decorate(rows, rules, *, relevance=None):
    decorated=[]
    for row in rows:
        row=dict(row)
        if relevance is not None:
            row.pop('ai_relevance',None)
            ai=relevance.get(candidate_identity(row))
            if ai:row['ai_relevance']=ai
        axes=semantic_axes(row)
        row={**row,'priority':priority(row,rules,axes)}
        if row.get('ai_relevance',{}).get('signature')!=relevance_fingerprint(row,rules):row.pop('ai_relevance',None)
        ai=row.get('ai_relevance',{})
        ai_tier=ai.get('tier')
        if ai_tier not in TIERS and isinstance(ai.get('score'),(int,float)) and not isinstance(ai.get('score'),bool):
            score=ai['score']
            ai_tier='direct' if score>=70 else 'adjacent' if score>=45 else 'background' if score>=30 else 'noise'
        current=row['priority'].get('tier','noise')
        if ai.get('status')=='ready' and ai_tier in TIERS and TIERS.index(ai_tier)<TIERS.index(current):
            row['priority']={**row['priority'],'tier':ai_tier,'tier_label':TIER_LABELS[ai_tier],
                             'band':'focus' if ai_tier in ('direct','adjacent') else 'supplementary',
                             'ai_demoted':True,
                             'reason':row['priority']['reason']+'；AI 研判为'+TIER_LABELS[ai_tier]}
        decorated.append(row)
    confidence={'high':2,'medium':1,'low':0}
    return sorted(decorated,key=lambda row:(
        TIERS.index(row['priority'].get('tier','noise')),
        confidence.get(row.get('ai_relevance',{}).get('confidence'),0),
        row.get('first_seen') or row.get('discovered') or '',
        row['priority']['score']),reverse=True)


def reviewable(rows, rules, decisions=None, *, recent_days=90, background_days=90, relevance=None):
    """Return only records that may occupy the user-facing reminder inbox."""
    decisions=decisions or {}
    result=[]
    now=datetime.now(timezone.utc)
    recent_cutoff=now-timedelta(days=recent_days)
    background_cutoff=now-timedelta(days=background_days)
    for row in decorate(rows,rules,relevance=relevance):
        identity=candidate_identity(row)
        tier=row['priority'].get('tier')
        cutoff=background_cutoff if tier=='background' else recent_cutoff
        try:
            recent=datetime.fromisoformat(row.get('first_seen') or row.get('discovered'))>=cutoff
        except (TypeError,ValueError):
            recent=True
        if (row.get('selected') or identity in decisions
                or (recent and tier in ('direct','adjacent','background','pending'))):
            result.append(row)
    return result


def merged(rows):
    """DOI, native IDs and aliases join observations without losing source metadata."""
    records = []; aliases = {}
    for row in rows:
        doi = w.normalize_doi(row.get('doi'))
        keys = [key for key in (doi, row.get('openalex_id'),row.get('wos_id'),
                row.get('external_id') if row.get('source')=='OpenAlex' else None,
                row.get('source', '') + ':' + str(row.get('external_id') or '')) if key and key != ':']
        previous = next((aliases[key] for key in keys if key in aliases), None)
        if previous is None:
            previous = {}; records.append(previous)
        # A DOI arriving later can bridge two observations that were previously
        # separate. Collapse their aliases without losing either source/history.
        for key in keys:
            other=aliases.get(key)
            if other is None or other is previous:continue
            # They may not yet share a native ID; merge their metadata explicitly.
            watches=set(previous.get('watch_ids',[]))|set(other.get('watch_ids',[]))
            sources=set(previous.get('sources',[]))|set(other.get('sources',[]))
            earliest=min(v for v in (previous.get('first_seen'),other.get('first_seen')) if v) if previous.get('first_seen') or other.get('first_seen') else None
            previous.update({k:v for k,v in other.items() if k not in previous or not previous[k]})
            previous.update(watch_ids=sorted(watches),sources=sorted(sources))
            if earliest:previous['first_seen']=earliest
            if other.get('selected'):previous['selected']=True
            records[:]=[record for record in records if record is not other]
            for alias,record in list(aliases.items()):
                if record is other:aliases[alias]=previous
        sources = set(previous.get('sources', [])) | set(row.get('sources', []))
        if row.get('source'): sources.add(row['source'])
        watches = set(previous.get('watch_ids', [])) | set(row.get('watch_ids', []))
        if row.get('watch_id'): watches.add(row['watch_id'])
        selected = {key: previous[key] for key in ('selected', 'collection', 'acquisition') if key in previous}
        first = min(v for v in (previous.get('first_seen'), row.get('first_seen')) if v) if previous.get('first_seen') or row.get('first_seen') else None
        # Do not erase an abstract/authorship/topic from the other metadata source.
        previous.update({key: value for key, value in row.items() if value not in (None, '', [], {})})
        previous.update(selected, sources=sorted(sources), watch_ids=sorted(watches))
        if first: previous['first_seen'] = first
        if doi: previous['doi'] = doi
        for key in keys: aliases[key] = previous
    return records
