"""Bounded, source-grounded comparisons between extracted claims; always candidates."""
import json

from filelock import FileLock, Timeout
import knowledge_extraction as extraction
from research_store import Store, encode, now
import structured_response
import workflow as w

VERSION='knowledge-comparison-v1'
KEY='knowledge-comparison:progress'
KINDS={'Supports','Contradicts','Inconclusive','MethodSimilar'}


def allowed_kinds(pair):
    return KINDS if all(n['data']['source_kind']=='original' for n in pair) else {'MethodSimilar'}


def inputs(store=None,source_map=None, *, projection=None):
    store=store or Store()
    if projection is None:
        projection=extraction._projection(extraction.sources() if source_map is None else source_map,store,include_edges=False)
    visible={n['id'] for n in projection['nodes'] if n.get('record_kind')=='ExtractedClaim'}
    result={}
    for node in store.nodes():
        if node['id'] not in visible:continue
        try:extraction._assert_numbers(node['data']['derived_text'],node['data']['evidence'])
        except ValueError:continue
        result[node['id']]=node
    return result


def model_request(payload,validator):
    return structured_response.request(payload,'知识关系比对',validator)


def _options(pair):
    result=[]
    for alias,node in zip(('A','B'),pair):
        for index,evidence in enumerate(node['data']['evidence'][:8]):
            result.append({**evidence,'ref':alias+'-E'+str(index+1),'claim':alias,
                           'claim_id':node['id'],'source_id':node['data']['source_id']})
    return result


def _request(pair,retry_round=0):
    for node in pair:extraction._assert_numbers(node['data']['derived_text'],node['data']['evidence'])
    options=_options(pair);known={e['ref']:e for e in options};nodes=dict(zip(('A','B'),pair))
    def validate(value):
        rows=value.get('relations') if isinstance(value,dict) else None
        if not isinstance(rows,list) or len(rows)>4:raise ValueError('每对论断最多提出4条关系，可返回空数组。')
        result=[]
        for row in rows:
            if not isinstance(row,dict) or row.get('source') not in nodes or row.get('target') not in nodes or row['source']==row['target'] or row.get('kind') not in KINDS:
                raise ValueError('论断关系类型或两端无效。')
            refs=row.get('evidence_refs')
            if not isinstance(refs,list) or not refs or any(r not in known for r in refs) or {known[r]['claim'] for r in refs}!={'A','B'}:
                raise ValueError('论断比较必须使用本次两端实际提供的原文依据。')
            if row['kind'] in {'Supports','Contradicts','Inconclusive'} and any(nodes[a]['data']['source_kind']!='original' for a in ('A','B')):
                raise ValueError('知识笔记或二手描述不能自动成为科学证据关系。')
            reason=row.get('reason');conditions=row.get('conditions')
            if not isinstance(reason,str) or not 1<=len(reason.strip())<=1500 or not isinstance(conditions,str) or not 1<=len(conditions.strip())<=1500:
                raise ValueError('请说明比较依据及可比条件；条件缺失时不得猜测支持或反驳。')
            evidence=[{**known[r],'generator':VERSION,
                       'claim_fingerprint':_fingerprint(nodes[known[r]['claim']])} for r in dict.fromkeys(refs)]
            result.append({'source':nodes[row['source']]['id'],'target':nodes[row['target']]['id'],
                           'kind':row['kind'],'evidence':evidence,'conditions':reason+'\n适用条件：'+conditions})
        return result
    context={'retry_round':retry_round,'claims':[{ 'id':alias,'statement':n['data']['derived_text'],'source_kind':n['data']['source_kind']}
                        for alias,n in nodes.items()],'evidence':options}
    schema={'relations':[{'source':'A','target':'B','kind':'|'.join(sorted(allowed_kinds(pair))),
                         'reason':'两端原文的具体比较','conditions':'对象、测量/验证条件是否可比','evidence_refs':['A-E1','B-E1']}]}
    payload={'model':'deepseek-flash','thinking':{'type':'disabled'},'response_format':{'type':'json_object'},'max_tokens':2600,
        'messages':[{'role':'system','content':__import__('research_prompts').task('comparison')+'\n本次仅允许关系类型：'+encode(sorted(allowed_kinds(pair)))+'；不适用时返回空数组。返回JSON：'+encode(schema)}, {'role':'user','content':encode(context)}]}
    return validate(model_request(payload,validate))


def _fingerprint(node):
    data=node['data']
    fields=('source_id','source_sha256','text_fingerprint','unit_ref','derived_text')
    return w.digest(encode([*(data.get(k) for k in fields),sorted(encode(e) for e in data['evidence'])]))


def _pair_key(pair):
    return w.digest(encode([VERSION,sorted((n['id'],_fingerprint(n)) for n in pair)]))


def _previous_result(store,pair):
    # Historical completed comparisons used the edit revision. A single review
    # may have incremented that revision without changing the evidence.
    from itertools import product
    current=tuple(n['revision'] for n in pair)
    choices=[(n['revision'],n['revision']-1) if n['status']=='VERIFIED' else (n['revision'],) for n in pair]
    for revisions in product(*choices):
        old_key=w.digest(encode([VERSION,[(n['id'],rev,n['data']['source_sha256']) for n,rev in zip(pair,revisions)]]))
        saved=store.cursor('knowledge-comparison:pair:'+old_key,{}) or {}
        if revisions==current and saved.get('status') in ('complete','response_ready','needs_attention'):return saved
        if saved.get('status')!='complete' or not saved.get('relations'):continue
        nodes={n['id']:n for n in pair}
        evidence=[e for edge in store.relations() if {edge['source'],edge['target']}==nodes.keys()
                  for e in edge['evidence'] if e.get('generator')==VERSION]
        if evidence and all(evidence_matches_claim(e,nodes.get(e.get('claim_id'))) for e in evidence):return saved
    return {}


def _read_pair(data,store,*,expected=None):
    picked=[]
    for side in ('left','right'):
        ref=data.get(side)
        if not isinstance(ref,dict) or not isinstance(ref.get('id'),str) or type(ref.get('revision')) is not int:
            raise ValueError('请明确选择两条论断后比对原文。')
        node=store.node(ref['id'])
        if (not node or node['owner']!=extraction.OWNER or node['kind']!='ExtractedClaim'
                or node['status']=='REJECTED' or node['data'].get('alias_of')
                or node['data'].get('source_kind')!='original'):
            raise ValueError('请选择两条仍在知识区的原文论断。')
        if expected is None and node['revision']!=ref['revision']:
            raise ValueError('论断已有更新，请重新打开后选择。')
        extraction.assert_review_current(node,store)
        picked.append(node)
    if picked[0]['data']['source_id']==picked[1]['data']['source_id']:
        raise ValueError('请选择来自两份不同原文的论断。')
    picked.sort(key=lambda n:n['id'])
    if expected is not None and _pair_key(picked)!=expected:
        raise ValueError('原文或论断在比对期间变化，请重新选择。')
    return picked


def _option(node,source):
    if (not node or node['owner']!=extraction.OWNER or node['kind']!='ExtractedClaim'
            or node['status']=='REJECTED' or node['data'].get('alias_of')
            or node['data'].get('source_kind')!='original'
            or extraction.current_state(node,source)!='current'):
        return None
    return {'id':node['id'],'revision':node['revision'],'label':node['data']['title'],
            'paper_id':source['source_id'],'paper_title':source['title']}


def question_options(project,identifier):
    """Read only original claims from papers explicitly attached to this question."""
    from project_questions import detail
    question=detail(project,identifier)
    references={row['paper_id']:row for row in question.get('references',[])
                if row.get('origin')=='manual' and row.get('paper_id') and not question.get('deleted')}
    result={'title':question['title'],'papers':[{'id':pid,'title':row.get('title') or pid}
            for pid,row in references.items()],'claims':[]}
    if not references:return result
    store=Store()
    sources={pid:extraction.source(pid,store=store) for pid in references}
    current=[pid for pid,source in sources.items() if source and source['status']=='ready']
    if not current:return result
    placeholders=','.join('?' for _ in current)
    with store.connection() as db:
        rows=db.execute("SELECT * FROM nodes WHERE owner=? AND kind='ExtractedClaim' AND status!='REJECTED' "
                        "AND json_extract(data,'$.source_id') IN ("+placeholders+") ORDER BY id",
                        [extraction.OWNER,*current]).fetchall()
    for row in rows:
        node=store.decode_node(row)
        option=_option(node,sources[node['data']['source_id']])
        if option:result['claims'].append(option)
    return result


def anchor_options(identifier,query='',after=''):
    """Keep the chosen original fixed and read a bounded page of matching partners."""
    if len(identifier)>120 or len(query)>120 or len(after)>120:
        raise ValueError('论断或查找内容过长。')
    store=Store();node=store.node(identifier)
    anchor_source=extraction.source(node['data'].get('source_id'),store=store) if node else None
    anchor=_option(node,anchor_source)
    if not anchor:raise ValueError('这条原文论断已变化，请从当前论断详情重新打开。')
    with store.connection() as db:
        rows=db.execute("""SELECT n.* FROM nodes n JOIN nodes p ON p.id=json_extract(n.data,'$.source_id')
            WHERE n.owner=? AND n.kind='ExtractedClaim' AND n.status!='REJECTED'
              AND json_extract(n.data,'$.source_kind')='original' AND json_extract(n.data,'$.alias_of') IS NULL
              AND p.id!=? AND n.id>? AND (instr(lower(json_extract(n.data,'$.title')),lower(?))>0
                  OR instr(lower(json_extract(p.data,'$.title')),lower(?))>0)
            ORDER BY n.id LIMIT 100""",(extraction.OWNER,anchor['paper_id'],after,query.strip(),query.strip())).fetchall()
    sources={};claims=[];cursor=rows[-1]['id'] if len(rows)==100 else ''
    for index,row in enumerate(rows):
        candidate=store.decode_node(row);paper=candidate['data']['source_id']
        if paper not in sources:sources[paper]=extraction.source(paper,store=store)
        option=_option(candidate,sources[paper])
        if not option:continue
        claims.append(option)
        if len(claims)==20:
            cursor=row['id'] if index<len(rows)-1 or cursor else ''
            break
    return {'anchor':anchor,'claims':claims,'after':cursor}


def run(data=None):
    """Compare one explicitly chosen current pair and reuse the same evidence version."""
    data=data or {}
    store=Store()
    try:
        with FileLock(str(w.DATA/'.knowledge-comparison.lock'),timeout=0):
            pair=_read_pair(data,store)
            identity=_pair_key(pair);key='knowledge-comparison:pair:'+identity
            prior=store.cursor(key,{}) or _previous_result(store,pair)
            if prior.get('status')=='complete':
                return {**prior,'compared':0,'reused':True}
            failure=prior.get('status')=='needs_attention'
            retry_round=prior.get('retry_round',0)
            if failure:
                if data.get('retry_failed') is not True:
                    return {**prior,'compared':0}
                if prior.get('kind')=='invalid_response':
                    retry_round+=1
                elif prior.get('kind')=='waiting_review' and not prior.get('request_id'):
                    return {**prior,'compared':0}
                elif prior.get('kind')=='replay_mismatch' or prior.get('request_id') and not structured_response.request_released(store,prior['request_id']):
                    return {**prior,'compared':0}
            try:
                with structured_response.resume_request(store,prior.get('request_id')):
                    relations=prior['relations'] if prior.get('status')=='response_ready' else _request(pair,retry_round)
            except structured_response.ResponseValidationError as error:
                return _save_failure(store,key,pair,retry_round,'invalid_response',error)
            except structured_response.ModelRequestError as error:
                return _save_failure(store,key,pair,retry_round,
                    'replay_mismatch' if error.replay_mismatch else 'waiting_review' if error.request_id else 'temporary_failure',error)
            # A completed response can be reused if saving is interrupted.
            store.commit_page(key,[],{'status':'response_ready','relations':relations,'updated':now()})
            import knowledge
            with knowledge.editing():
                _read_pair(data,store,expected=identity)
                result={'status':'complete','compared':1,'relations':len(relations),'updated':now()}
                with store.connection() as db:
                    db.execute('BEGIN IMMEDIATE')
                    for edge in relations:extraction._put_relation(db,**edge)
                    extraction._write_cursor(db,key,result)
            return result
    except Timeout:
        return {'status':'busy','compared':0}


def _save_failure(store,key,pair,retry_round,kind,error):
    result={'status':'needs_attention','kind':kind,'retry_round':retry_round,
            'pair':[n['id'] for n in pair],'message':str(error)[:500],
            'request_id':getattr(error,'request_id',None),'updated':now(),'compared':0}
    store.commit_page(key,[],result)
    return result


def evidence_matches_claim(evidence,node):
    if not node or node['status']=='REJECTED' or node['data'].get('alias_of'):
        return False
    if evidence.get('claim_fingerprint'):
        return evidence['claim_fingerprint']==_fingerprint(node)
    # Legacy records copied the exact excerpt, but used a generic edit revision
    # as their key. Compare the original evidence instead of review state.
    fields=('id','source_sha256','text_fingerprint','unit_ref','start','end','quote_sha256','quote')
    return any(all(evidence.get(k)==span.get(k) for k in fields) for span in node['data'].get('evidence',[]))


def assert_review_current(edge,store=None):
    store=store or Store()
    for evidence in edge.get('evidence',[]):
        if evidence.get('generator')!=VERSION:continue
        node=store.node(evidence.get('claim_id',''))
        if not evidence_matches_claim(evidence,node):raise ValueError('被比较论断已有变化，请重新核查。')
        extraction.assert_review_current(node,store)


def project(nodes,store=None):
    store=store or Store();allowed={n['id'] for n in nodes};rows=[]
    claims={n['id']:n for n in store.nodes(kind='ExtractedClaim') if n['id'] in allowed}
    labels={'Supports':'支持','Contradicts':'反驳','Inconclusive':'证据未定','MethodSimilar':'方法相近'}
    for edge in store.relations():
        if edge['source'] not in claims or edge['target'] not in claims or edge['status']=='REJECTED':continue
        if not edge['evidence'] or any(e.get('generator')!=VERSION or not evidence_matches_claim(e,claims.get(e.get('claim_id'))) for e in edge['evidence']):continue
        rows.append({'id':edge['id'],'from':edge['source'],'to':edge['target'],'kind':edge['kind'],
            'label':labels[edge['kind']],'status':edge['status'],'revision':edge['revision'],'suggested':edge['status']!='VERIFIED',
            'evidence':edge['evidence'],'explanation':edge['conditions'],'layer':'scientific','source':'AI 原文比对'})
    return rows


def _failure_rows(store):
    with store.connection() as db:
        return db.execute("SELECT key,value FROM cursors WHERE key LIKE 'knowledge-comparison:pair:%' AND json_extract(value,'$.status')='needs_attention'").fetchall()


def _current_failures(store,items,rows=None):
    rows=_failure_rows(store) if rows is None else rows
    failures=[]
    for row in rows:
        value=json.loads(row['value']);pair=value.get('pair',[])
        if value.get('status')!='needs_attention' or len(pair)!=2 or any(i not in items for i in pair):continue
        if row['key']=='knowledge-comparison:pair:'+_pair_key([items[i] for i in pair]):failures.append(value)
    return failures


def status(source_map=None, *, projection=None):
    store=Store();value=store.cursor(KEY,{'status':'pending','candidate_pairs':0,'remaining':0,'failures':[]})
    rows=_failure_rows(store)
    failures=_current_failures(store,inputs(store,source_map,projection=projection),rows) if rows else []
    state='needs_attention' if failures else 'pending' if value.get('remaining') else 'complete'
    return {**value,'status':state,'failures':failures}



