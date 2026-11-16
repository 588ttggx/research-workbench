"""Targeted, read-only pages for source-bound extracted knowledge identities.

No graph projection, catalog reconciliation, model request or manuscript creation
belongs on this route. Historical identity survives unavailable or excluded text.
"""
import json
import re

import knowledge_extraction as extraction
from knowledge_comparison import evidence_matches_claim
from research_store import Store

LABELS={'About':'涉及概念','AssociatedWith':'主题相关','DerivedFrom':'提取出处',
        'Supports':'支持','Contradicts':'反驳','Inconclusive':'证据未定','MethodSimilar':'方法相近'}
REASONS={'source_out_of_scope':'来源已退出全局知识范围，提取正文不再展示。',
         'non_knowledge_projection':'此内容属于项目判断或阅读维护记录，已退出知识图；原身份和历史记录保留。',
         'missing_original':'来源原文暂时缺失，以下为保存的历史提取投影。',
         'stale_cache':'原文与解析缓存版本不一致，请更新来源后重新核查。',
         'low_quality_text':'原文文字包含乱码或 OCR 质量不足，已暂停使用；原 PDF、原身份与历史提取保留。',
         'source_text_changed':'原文已重新解析，保存的提取对应旧文字版本，等待定向重新核查。',
         'partial_parse':'原文解析不完整，暂不能核查此提取对象。',
         'unparsed':'来源正文尚未完成解析。',
         'source_changed':'来源正文版本已变化，以下投影需要重新提取核查。',
         'extractor_changed':'提取规则版本已变化，当前结果等待重新核查。',
         'source_excerpt_changed':'来源片段位置已变化，当前结果等待重新核查。',
         'invalid_evidence':'保存的出处或原文偏移无法通过当前版本校验。',
         'invalid_numbers':'保存的主张数字不能在所列原文片段中核实。',
         'rejected':'本人已拒绝此提取对象，身份及来源记录保留。',
         'aliased':'此对象已合并到另一知识对象，原身份及出处保留。'}


def _extracted(node):
    return node and node['owner']==extraction.OWNER and node['kind'] in extraction.KINDS


def _merged_sources(store, identifier, kind):
    # This traverses only incoming merge identities, never arbitrary graph edges.
    # UNION (rather than UNION ALL) also terminates corrupt historical cycles.
    with store.connection() as db:
        rows=db.execute('''WITH RECURSIVE family(id) AS (
            SELECT ? UNION SELECT n.id FROM nodes n JOIN family f
              ON json_extract(n.data,'$.alias_of')=f.id
              WHERE n.owner=? AND n.kind=? AND n.status!='REJECTED')
            SELECT n.* FROM nodes n JOIN family f ON n.id=f.id ORDER BY n.created,n.id''',
            (identifier,extraction.OWNER,kind)).fetchall()
    return [store.decode_node(row) for row in rows]


def _node_view(node, state, redacted=False):
    data=node['data']
    return {'id':node['id'],'record_id':node['id'],'record_kind':node['kind'],
        'kind':'概念' if node['kind']=='ExtractedConcept' else '结论',
        'label':'已退出知识区的提取对象' if redacted else data.get('title',node['id']),
        'summary':'' if redacted else data.get('derived_text',''),
        'status':node['status'],'revision':node['revision'],'owner':node['owner'],
        'entity_type':data.get('entity_type','概念'),'review_scope':'extraction_accuracy',
        'source_ids':[data.get('source_id')],'evidence':[] if redacted else data.get('evidence',[]),
        'source_kind':data.get('source_kind'),'suggested':node['status']!='VERIFIED',
        'active':state=='current','stale':state!='current','rebuildable':True,
        'uri':None if redacted else node.get('uri')}


def read(identifier):
    if not isinstance(identifier,str) or not re.fullmatch(r'EX-[KC]-[A-Za-z0-9_-]{1,80}',identifier):
        raise ValueError('提取对象地址无效。')
    store=Store();node=store.node(identifier)
    if not _extracted(node):raise ValueError('提取对象不存在。')
    originals={};checks={};nodes={identifier:node}

    def original(source_id):
        if source_id not in originals:originals[source_id]=extraction.source(source_id,store=store)
        return originals[source_id]

    def check(item):
        if item['id'] not in checks:
            checks[item['id']]=extraction.current_state(item,original(item['data'].get('source_id')))
        return checks[item['id']]

    def redacted(item):return check(item) in {'source_out_of_scope','non_knowledge_projection'}

    def source_view(item):
        source_id=item['data'].get('source_id');source=original(source_id) or {}
        hidden=not source.get('eligible') or redacted(item)
        return {'id':source_id,'label':'来源已退出知识区' if hidden else source.get('title',source_id),
            'graph_id':None if hidden else source.get('graph_id'),'doc_id':None if hidden else source.get('doc_id'),
            'paper_id':source_id if not hidden and source.get('kind')=='Paper' else None,
            'path':None if hidden or source.get('kind')=='Paper' else source.get('uri'),
            'source_sha256':source.get('source_sha256'),'projection_sha256':item['data'].get('source_sha256'),
            'status':source.get('status','out_of_scope'),'projection_status':check(item),
            'eligible':not hidden,'extracted_id':item['id'],
            'evidence':[] if hidden else item['data'].get('evidence',[])}

    state=check(node);hidden=redacted(node);reasons=[]
    if state!='current':reasons.append(state)
    if node['status']=='REJECTED':reasons.append('rejected')
    if node['data'].get('alias_of'):reasons.append('aliased')
    numbers_valid=True
    if not hidden and node['kind']=='ExtractedClaim':
        try:extraction._assert_numbers(node['data'].get('derived_text',''),node['data'].get('evidence',[]))
        except ValueError:numbers_valid=False;reasons.append('invalid_numbers')
    code=state if state!='current' else ('rejected' if 'rejected' in reasons else 'aliased' if 'aliased' in reasons else 'current')
    actionable=code=='current'
    members=_merged_sources(store,identifier,node['kind']) if not hidden else [node]
    nodes.update({item['id']:item for item in members})
    sources=[source_view(item) for item in members]
    alias=None;target_id=node['data'].get('alias_of')
    if target_id and not hidden:
        target=store.node(target_id)
        available=bool(_extracted(target) and not redacted(target))
        alias={'target':target_id,'target_revision':target['revision'] if available else None,
               'target_label':target['data'].get('title') if available else '合并目标当前不可见',
               'reason':node['data'].get('alias_reason',''),'available':available}
    relations=[];related={}
    if not hidden:
        members_ids=[item['id'] for item in members];marks=','.join('?' for _ in members_ids)
        with store.connection() as db:
            rows=db.execute('SELECT * FROM relations WHERE source IN ('+marks+') OR target IN ('+marks+') ORDER BY created,id',
                            members_ids+members_ids).fetchall()
        for row in rows:
            edge={**dict(row),'evidence':json.loads(row['evidence'])};endpoints=[];allowed=True;stale=False
            for endpoint in (edge['source'],edge['target']):
                item=nodes.get(endpoint)
                if item is None:item=store.node(endpoint);nodes[endpoint]=item
                if _extracted(item):
                    if redacted(item):allowed=False;break
                    endpoint_view=_node_view(item,check(item));stale|=check(item)!='current'
                else:
                    source=original(endpoint)
                    if not source or not source.get('eligible'):allowed=False;break
                    stale|=source['status']!='ready'
                    endpoint_view={'id':endpoint,'label':source['title'],'kind':'论文' if source['kind']=='Paper' else '知识稿',
                        'record_kind':source['kind'],'graph_id':source.get('graph_id'),'doc_id':source.get('doc_id'),
                        'paper_id':endpoint if source['kind']=='Paper' else None,
                        'path':source.get('uri') if source['kind']!='Paper' else None}
                endpoints.append(endpoint_view)
            if not allowed:continue
            for evidence in edge['evidence']:
                source=original(evidence.get('id'))
                if not source or not source.get('eligible'):allowed=False;break
                stale|=(source['status']!='ready' or evidence.get('source_sha256',evidence.get('fingerprint'))!=source['source_sha256'])
                if evidence.get('text_fingerprint'):
                    stale|=evidence['text_fingerprint']!=source.get('text_fingerprint')
                claim_id=evidence.get('claim_id')
                if claim_id:
                    claim=nodes.get(claim_id) or store.node(claim_id)
                    stale|=not evidence_matches_claim(evidence,claim)
            if not allowed:continue
            related.update({item['id']:item for item in endpoints if item['id']!=identifier})
            relations.append({'id':edge['id'],'from':edge['source'],'to':edge['target'],'kind':edge['kind'],
                'label':LABELS.get(edge['kind'],edge['kind']),'status':edge['status'],'revision':edge['revision'],
                'evidence':edge['evidence'],'explanation':edge['conditions'],'stale':bool(stale),
                'layer':'provenance' if edge['kind']=='DerivedFrom' else 'scientific' if edge['kind'] in {'Supports','Contradicts','Inconclusive','MethodSimilar'} else 'semantic'})
    view=_node_view(node,code,hidden)
    view['source_ids']=list(dict.fromkeys(s['id'] for s in sources if s['eligible']))
    view['evidence']=[e for s in sources for e in s['evidence']]
    return {'node':view,'revision':node['revision'],
        'status':{'code':code,'current':state=='current','reviewable':actionable and numbers_valid,
                  'reasons':[{'code':reason,'message':REASONS[reason]} for reason in dict.fromkeys(reasons)],'redacted':hidden},
        'sources':sources,'relations':relations,'related_nodes':list(related.values()),'alias':alias,
        'actions':{'verify':actionable and numbers_valid and node['status']!='VERIFIED',
                   'reject':actionable,'alias':actionable and numbers_valid,'promote':actionable and numbers_valid}}
