"""Rebuildable source-bound knowledge projections in the existing business ledger.

Original Markdown/PDF/XML owns the content. Extracted text is a disposable index,
not an independently editable manuscript or a verified scientific conclusion.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from time import monotonic
import hashlib
from copy import deepcopy
import json
import re
import threading
import unicodedata
from filelock import FileLock, Timeout

import knowledge as k
import material_roles
import paper_evidence
from fulltext_parser import text_changed as _text_changed
from research_store import Store, encode, now
import structured_response
import workflow as w

OWNER='KnowledgeExtraction'
VERSION='knowledge-extraction-v1'
CONTROL='knowledge-extraction:control'
_NEXT_PROBE={}
PROVIDER_BLOCK='knowledge-extraction:provider-block'
LOCK=threading.RLock()
KINDS={'ExtractedConcept','ExtractedClaim'}
MAX_CHUNKS=12

# A knowledge manuscript may contain a project-use paragraph or a reading
# receipt. Those statements describe the workspace, not reusable knowledge.
# Apply only to note-derived projections; a paper's own methods, limitations
# and research decisions remain evidence from that paper.
_NOTE_PROCESS=re.compile(r'本人.{0,24}(?:尚无|尚未|暂无|未确认|待确认)|(?:尚无|尚没有|缺少).{0,8}本人|'
    r'当前项目|本项目|本课题|当前主线|选题主线|课题决定|当前仪器|'
    r'自有.{0,12}(?:数据|设备)|用户已批准|文献获取状态|阅读范围索引|期刊分区|影响因子信息|'
    r'补入.{0,8}页.{0,8}PDF|本轮核查|核查日期|文件路径|该综述称尚未(?:取得|确认)',re.I)


def _knowledge_projection(data,source):
    if source.get('source_kind')!='knowledge_manuscript':return True
    text=str(data.get('title',''))+' '+str(data.get('derived_text',''))
    return not _NOTE_PROCESS.search(text)


def _hash(value):
    return hashlib.sha256(encode(value).encode('utf-8')).hexdigest()


def catalog_snapshot():
    import knowledge_catalog
    return knowledge_catalog.source_catalog()


def _source_key(identifier):
    return 'knowledge-extraction:source:'+identifier


def _paper_source(record, allowed, state):
    identifier=record['id']
    source=(paper_evidence.fulltext_sources(record,state) if allowed else
            {'source_id':identifier,'source_sha256':state.get('papers',{}).get(identifier,{}).get('sha256',''),
             'status':'out_of_scope','units':[]})
    return {**source,'title':record.get('title') or identifier,'kind':'Paper',
        'project':record.get('project') or '共享','graph_id':'paper:'+identifier,'uri':record.get('url'),
        'eligible':bool(allowed),'source_kind':'original','owner':'Zotero'}


def _document_source(doc, body=None, *, project_scope=False):
    identifier=doc.get('record_id') or doc['id'];path=doc.get('kb_path') or doc['path']
    generated=doc.get('ai_generated') or path.replace('\\','/').startswith('文献/AI阅读记录/')
    allowed=material_roles.knowledge(doc,global_scope=not project_scope) and not generated
    source={'source_id':identifier,'doc_id':doc['id'],'title':doc.get('display_title') or doc['title'],
        'source_sha256':doc.get('sha',''),'project':doc.get('project') or '共享','kind':'Document',
        'source_kind':'knowledge_manuscript','graph_id':'doc:'+doc['id'],'uri':path,'owner':'Markdown',
        'eligible':bool(allowed),'status':'out_of_scope','units':[]}
    if allowed:
        try:
            if body is None:body=k.split(k.path_for(path).read_text('utf-8-sig'))[1]
            if w.digest(body.rstrip()) != doc.get('sha'):
                source['status']='stale_cache'
            else:
                source['status']='ready' if body.strip() else 'unparsed'
                source['text_fingerprint']=w.digest(body)
                source['legacy_cache']=True
                for start in range(0,len(body),6000):
                    text=body[start:start+6000]
                    if text.strip():source['units'].append({'ref':'body@'+str(start),'kind':'document_excerpt',
                        'location':path+' · 正文字符 '+str(start+1)+'–'+str(start+len(text)),
                        'start':start,'end':start+len(text),'text':text})
        except (OSError,ValueError,UnicodeError):source['status']='missing_original'
    return source


def source(identifier, *, store=None):
    """Resolve and validate one registered original, without scanning other bodies.

    Current front matter is checked even when the catalog has not refreshed yet.
    Library/state JSON remain their existing metadata truth; no graph, project
    usage, classification, catalog reconciliation or model request is involved.
    """
    if not isinstance(identifier,str) or not identifier or len(identifier)>200:return None
    store=store or Store();record=store.node(identifier)
    library=w.read_json(w.LIBRARY,{'records':[]})
    paper=next((row for row in library.get('records',[]) if row.get('id')==identifier),None)
    if paper:
        retired={'RETIRED','REJECTED','DELETED_AT_SOURCE'}
        allowed=(not paper.get('hidden') and paper.get('status') not in retired
                 and (not record or record['status'] not in retired) and paper_evidence.registered(paper))
        return _paper_source(paper,allowed,w.read_json(w.DATA/'state.json',{}))
    uri=record.get('uri') if record else None
    relative=(uri or '').replace('\\','/').removeprefix('科研知识库/')
    with store.connection() as db:
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='documents'").fetchone()
        row=(db.execute('SELECT * FROM documents WHERE id=? OR path=? LIMIT 1',
                        (identifier,'科研知识库/'+relative)).fetchone() if exists else None)
    if row:
        doc={**json.loads(row['data']),'archived':bool(row['archived'])}
        relative=doc.get('kb_path') or row['path'].removeprefix('科研知识库/')
    elif record and record['owner']=='Markdown' and relative:
        doc={'id':identifier,'record_id':identifier,'title':record['data'].get('title',identifier),
             'path':relative,'kb_path':relative,'content_role':'knowledge','global_knowledge':True,
             'visibility':'active','archived':False,'project':record['project'],'sha':record['data'].get('document_sha256','')}
    else:return None
    # Resolve through the existing bounded Markdown entry before reading. A URI
    # that was reassigned to another record is not an alias for the old source.
    try:
        path=k.path_for(relative);raw=path.read_text('utf-8-sig')
        import workspace_catalog
        current=workspace_catalog.describe(path,raw);current['archived']=doc.get('archived',False)
        if not row and not current.get('record_id'):
            current['record_id']=identifier
        if (current.get('record_id') or current['id'])!=identifier:
            return {**_document_source({**doc,'global_knowledge':False}),'status':'out_of_scope'}
        return _document_source(current,k.split(raw)[1])
    except (OSError,ValueError,UnicodeError):
        result=_document_source({**doc,'kb_path':relative},body='')
        if result['eligible']:result['status']='missing_original'
        return result


def sources(snapshot=None):
    """Enumerate qualified originals globally; project selection is irrelevant."""
    snapshot=catalog_snapshot() if snapshot is None else snapshot
    result={};state=w.read_json(w.DATA/'state.json',{})
    allowed_papers={row['id'] for row in snapshot.get('papers',[])}
    for record in w.read_json(w.LIBRARY,{'records':[]}).get('records',[]):
        identifier=record.get('id')
        if not isinstance(identifier,str):continue
        allowed=identifier in allowed_papers and not record.get('hidden')
        result[identifier]=_paper_source(record,allowed,state)
    for doc in snapshot.get('documents',[]):
        item=_document_source(doc);result[item['source_id']]=item
    return result


def _active_projects():
    import project_profiles
    return [profile['project'] for profile in project_profiles.listing() if not profile.get('archived')]


def _analysis_sources():
    """Add active project selections without exposing project-only excerpts globally."""
    result=sources()
    from relation_discovery import scope_materials
    for project in _active_projects():
        documents,_=scope_materials(project)
        for doc in documents:
            identifier=doc.get('record_id') or doc['id']
            if identifier not in result:
                item=_document_source(doc,project_scope=True)
                if item['eligible']:result[identifier]=item
    return result


def _analysis_epoch():
    """Check registered text versions and selected private notes before queuing."""
    from relation_discovery import GLOBAL_SCOPE, input_epoch, scope_materials
    local=set()
    for project in _active_projects():
        documents,_=scope_materials(project)
        local.update((d.get('record_id') or d['id'],d['sha']) for d in documents
                     if not d.get('global_knowledge',True) and not d.get('ai_generated'))
    return _hash([input_epoch(GLOBAL_SCOPE),sorted(local)])


def evidence_options(unit):
    """Model selects server-owned spans rather than inventing character offsets."""
    return [{'ref':'E'+str(index+1),'quote':unit['text'][offset:offset+480],
             'start':unit.get('start',0)+offset,
             'end':unit.get('start',0)+min(offset+480,len(unit['text'])),
             'unit_ref':unit['ref'],'location':unit['location'],
             'page':unit.get('page'),'section':unit.get('section'),'source_kind':unit['kind']}
            for index,offset in enumerate(range(0,len(unit['text']),480))]


def _assert_numbers(text,evidence):
    from decimal import Decimal,InvalidOperation
    def tokens(value):
        value=unicodedata.normalize('NFKC',value).replace('−','-')
        result=set()
        for token in re.findall(r'(?<![\d.])[+-]?(?:\d+(?:\.\d*)?|(?<![A-Za-z])\.\d+)(?:[eE][+-]?\d+)?',value):
            try:result.add(Decimal(token))
            except InvalidOperation:pass
        # Cardinal words are explicit evidence too (e.g. "five markers" ->
        # "5个标志物"). Match whole values, never substrings or inferred sums.
        small=['zero','one','two','three','four','five','six','seven','eight','nine',
               'ten','eleven','twelve','thirteen','fourteen','fifteen','sixteen',
               'seventeen','eighteen','nineteen']
        tens=['twenty','thirty','forty','fifty','sixty','seventy','eighty','ninety']
        ones='|'.join(small[1:10])
        below100=r'(?:(?:'+ '|'.join(tens)+r')(?:[ -]+(?:'+ones+r'))?|'+ '|'.join(small)+r')'
        below1000=r'(?:(?:'+ones+r')\s+hundred(?:[ -]+(?:and[ -]+)?'+below100+r')?|'+below100+r')'
        group=below1000
        for scale in ('thousand','million','billion'):
            group=r'(?:'+below1000+r'\s+'+scale+r'(?:[ -]+(?:and[ -]+)?'+group+r')?|'+group+r')'
        pattern=r'\b(?:(minus|negative)\s+)?('+group+r')\b'
        for match in re.finditer(pattern,value,re.I):
            words=re.split(r'[ -]+',match[2].lower())
            number=section=0
            for word in words:
                if word in small:section+=small.index(word)
                elif word in tens:section+=(tens.index(word)+2)*10
                elif word=='hundred':section*=100
                elif word in ('thousand','million','billion'):
                    number+=section*{'thousand':1000,'million':1000000,'billion':1000000000}[word];section=0
            number+=section
            result.add(Decimal(-number if match[1] else number))
        # Require a numeric context; ordinary words such as "统一" or "一方面"
        # must not manufacture a number. Bare numeral runs at a boundary remain
        # usable labels. Ambiguous "三四种" is not interpreted as 34.
        digits={'零':0,'〇':0,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
        scales={'十':10,'百':100,'千':1000,'万':10000,'亿':100000000}
        for match in re.finditer(r'([负正]?)([零〇一二两三四五六七八九十百千万亿]+)(?=$|\s|[^\w]|[个种组类篇项条次份位例名颗粒片对套章节目维阶倍度天日年月小时分钟秒页点元])',value):
            following=value[match.end():match.end()+1]
            if (not match[1] and not (following and following in '个种组类篇项条次份位例名颗粒片对套章节目维阶倍度天日年月小时分钟秒页点元')
                    and match.start()>0 and re.match(r'[\u4e00-\u9fff]',value[match.start()-1])
                    and value[match.start()-1] not in '第之'):continue
            spelling=match[2]
            if all(char in digits for char in spelling):
                if len(spelling)>1 and not (len(spelling)>=3 or '零' in spelling or '〇' in spelling):continue
                number=int(''.join(str(digits[char]) for char in spelling))
            else:
                number=section=current=0
                for char in spelling:
                    if char in digits:current=digits[char];continue
                    scale=scales[char]
                    if scale<10000:section+=(current or 1)*scale
                    else:number+=(section+current)*scale;section=0
                    current=0
                number+=section+current
            result.add(Decimal(-number if match[1]=='负' else number))
        return result
    # E spans are fixed source slices. Rejoin adjacent slices before reading
    # numbers, including a decimal split at the boundary; never bridge a gap.
    ordered=sorted(enumerate(evidence),key=lambda row:(row[1].get('id',''),row[1].get('unit_ref',''),row[1].get('start',0),row[0]))
    groups=[];previous=None
    for _,span in ordered:
        adjacent=(previous is not None and type(span.get('start')) is int
            and previous.get('end')==span['start']
            and all(previous.get(key)==span.get(key) for key in ('id','unit_ref')))
        if adjacent:
            groups[-1].append(span['quote'])
        else:
            groups.append([span['quote']])
        previous=span
    actual=set().union(*(tokens(''.join(group)) for group in groups))
    if not tokens(text)<=actual:raise ValueError('论断包含所选原文片段中不存在的数字，请逐字保留原文数字和条件。')


def validate(value,source,unit):
    if not isinstance(value,dict):raise ValueError('提取结果必须是 JSON 对象。')
    options={entry['ref']:entry for entry in evidence_options(unit)};known={};rows=[]
    for field,kind in [('concepts','ExtractedConcept'),('claims','ExtractedClaim')]:
        incoming=value.get(field)
        if not isinstance(incoming,list) or len(incoming)>16:raise ValueError('每段最多提取 16 个概念和 16 个论断。')
        for row in incoming:
            if not isinstance(row,dict):raise ValueError('提取条目格式无效。')
            key=row.get('key');label=row.get('label');text=row.get('description' if field=='concepts' else 'statement')
            if not isinstance(key,str) or not re.fullmatch(r'[KC][1-9][0-9]?',key) or key in known:
                raise ValueError('提取条目编号无效或重复。')
            if key[0] != ('K' if field=='concepts' else 'C'):raise ValueError('概念和论断编号不能混用。')
            if not isinstance(label,str) or not 1<=len(label.strip())<=160 or not isinstance(text,str) or not 1<=len(text.strip())<=1500:
                raise ValueError('提取条目需要简短名称及有来源的描述。')
            refs=row.get('evidence_refs')
            if not isinstance(refs,list) or not 1<=len(refs)<=8 or len(set(refs))!=len(refs) or any(not isinstance(ref,str) or ref not in options for ref in refs):
                raise ValueError('提取出处不在本轮实际提供的原文片段中。')
            evidence=[]
            for ref in refs:
                span=options[ref];start=span['start']-unit.get('start',0);end=span['end']-unit.get('start',0)
                if unit['text'][start:end]!=span['quote']:raise ValueError('原文片段偏移核验失败。')
                evidence.append({**span,'id':source['source_id'],'source_sha256':source['source_sha256'],
                    'text_fingerprint':source.get('text_fingerprint'),
                    'quote_sha256':w.digest(span['quote']),'generator':VERSION,'fingerprint':source['source_sha256']})
            if field=='claims':_assert_numbers(text,evidence)
            item={'key':key,'kind':kind,'label':label.strip(),'text':text.strip(),'evidence':evidence,
                  'concept_keys':row.get('concept_keys',[]) if field=='claims' else [],'entity_type':row.get('category','概念') if field=='concepts' else '结论'}
            if item['entity_type'] not in {'概念','材料','方法','仪器','指标','现象','研究问题','结论'}:raise ValueError('概念类别无效。')
            if not isinstance(item['concept_keys'],list) or len(item['concept_keys'])>16 or any(not isinstance(key,str) for key in item['concept_keys']):
                raise ValueError('论断涉及的概念编号无效。')
            known[key]=item;rows.append(item)
    for item in rows:
        if any(key not in known or known[key]['kind']!='ExtractedConcept' for key in item['concept_keys']):
            raise ValueError('论断引用了未提供的概念。')
    relations=value.get('relations',[])
    if not isinstance(relations,list) or len(relations)>12:raise ValueError('每段最多提出 12 条主题关系。')
    for edge in relations:
        if not isinstance(edge,dict) or edge.get('kind')!='AssociatedWith' or edge.get('source_key') not in known or edge.get('target_key') not in known or edge['source_key']==edge['target_key']:
            raise ValueError('自动提取仅允许本段明确的概念主题关联。')
        if any(known[edge[key]]['kind']!='ExtractedConcept' for key in ('source_key','target_key')):
            raise ValueError('主题关联的两端必须是概念。')
        if not isinstance(edge.get('reason'),str) or not 1<=len(edge['reason'])<=1000:raise ValueError('主题关联须说明本段联系。')
    # Whole-page co-occurrence alone must not create topic attraction.
    local=[]
    for edge in relations:
        left=known[edge['source_key']]['evidence'];right=known[edge['target_key']]['evidence']
        if any(abs(a['start']-b['start'])<=480 for a in left for b in right):local.append(edge)
    rows=[item for item in rows if _knowledge_projection(
        {'title':item['label'],'derived_text':item['text']},source)]
    kept={item['key'] for item in rows}
    for item in rows:item['concept_keys']=[key for key in item['concept_keys'] if key in kept]
    return {'items':rows,'relations':[edge for edge in local if edge['source_key'] in kept and edge['target_key'] in kept]}


def model_request(payload,validator):
    return structured_response.request(payload,'知识提取',validator)


def _validated_subset(value,source,unit):
    """Keep fully checked candidates from a known answer, with explicit rejects.

    The strict validator remains the admission gate. This does not correct a
    claim, invent evidence, convert scientific edges, or confirm a human review.
    """
    if (not isinstance(value,dict) or any(not isinstance(value.get(key),list)
            for key in ('concepts','claims')) or not isinstance(value.get('relations',[]),list)):
        raise ValueError('原响应结构不完整，不能恢复局部候选。')
    accepted={'concepts':[],'claims':[],'relations':[]};rejected=[]
    for field in ('concepts','claims','relations'):
        for index,row in enumerate(value.get(field,[])):
            key=row.get('key') if isinstance(row,dict) else None
            if field in ('concepts','claims') and len(accepted[field])>=16:
                rejected.append({'field':field,'key':key or str(index),'reason':'超过每段16条此类候选上限，未入图。'})
                continue
            if field=='relations' and len(accepted[field])>=12:
                rejected.append({'field':field,'key':key or str(index),'reason':'超过每段12条普通主题关联上限，未入图。'})
                continue
            candidate={**accepted,field:accepted[field]+[row]}
            try:validate(candidate,source,unit)
            except ValueError as error:
                rejected.append({'field':field,'key':key or str(index),'reason':str(error)})
            else:accepted[field].append(row)
    result=validate(accepted,source,unit)
    if rejected and not result['items']:raise ValueError('没有可通过证据校验的实质候选，保留失败。')
    if rejected:result['validation_rejections']=rejected
    return result


def _request(source,unit,retry_round=0):
    import research_prompts
    rules=research_prompts.bundle('extraction')
    context={'source_id':source['source_id'],'title':source['title'],'source_sha256':source['source_sha256'],
             'unit_ref':unit['ref'],'evidence':evidence_options(unit),'retry_round':retry_round}
    schema={'concepts':[{'key':'K1','label':'概念名称','category':'材料|方法|仪器|指标|现象|研究问题|概念','description':'来源中的含义和边界','evidence_refs':['E1']}],
        'claims':[{'key':'C1','label':'简短论断','statement':'来源实际报告的论断及适用条件','concept_keys':['K1'],'evidence_refs':['E1']}],
        'relations':[{'source_key':'K1','target_key':'K2','kind':'AssociatedWith','reason':'本段中可定位的主题联系'}]}
    payload={'model':'deepseek-flash','thinking':{'type':'disabled'},'response_format':{'type':'json_object'},
        'max_tokens':7500,'messages':[{'role':'system','content':
        rules['text']+'\n只返回完整JSON，schema为：'+encode(schema)},
        {'role':'user','content':encode(context)}]}
    try:answer=model_request(payload,lambda value:validate(value,source,unit))
    except structured_response.ResponseValidationError as error:
        try:
            result=_validated_subset(error.value,source,unit)
            result['rule_versions']=rules['versions']
            return result
        except ValueError:raise error
    result=validate(answer,source,unit)
    result['rule_versions']=rules['versions']
    return result


def _response_key(source,unit,retry_round):
    return 'knowledge-extraction:response:'+_hash([VERSION,source['source_id'],source['source_sha256'],unit,retry_round])


def _unit_key(source,unit):
    return 'knowledge-extraction:unit:'+_hash([VERSION,source['source_id'],unit['kind'],unit['text']])


def _rebase(result,source,unit):
    result=deepcopy(result);spans={s['ref']:s for s in evidence_options(unit)}
    for item in result['items']:
        for index,old in enumerate(item['evidence']):
            span=spans.get(old.get('ref'))
            if not span or span['quote']!=old['quote']:return None
            item['evidence'][index]={**span,'id':source['source_id'],'source_sha256':source['source_sha256'],
                'text_fingerprint':source.get('text_fingerprint'),
                'quote_sha256':w.digest(span['quote']),'generator':VERSION,'fingerprint':source['source_sha256']}
        if item['kind']=='ExtractedClaim':
            try:_assert_numbers(item['text'],item['evidence'])
            except ValueError:return None
    return result


def _request_units(source,units,progress,store):
    """Pack short pages without losing each page's server-owned evidence options."""
    retry_round=progress.get('retry_round',0)
    result={};pending=[]
    for unit in units:
        saved=store.cursor(_response_key(source,unit,retry_round),None)
        if saved is not None:saved=_rebase(saved,source,unit)
        if saved is None:
            reusable=store.cursor(_unit_key(source,unit),None)
            if reusable is not None:saved=_rebase(reusable,source,unit)
        if saved is None:pending.append(unit)
        else:result[unit['ref']]=saved
    if not pending:return result
    if len(pending)==1:
        result[pending[0]['ref']]=_request(source,pending[0],retry_round)
    else:
        import research_prompts
        rules=research_prompts.bundle('extraction')
        expected={unit['ref']:unit for unit in pending}
        context={'source_id':source['source_id'],'title':source['title'],'source_sha256':source['source_sha256'],
                 'retry_round':retry_round,'units':[{'unit_ref':u['ref'],'evidence':evidence_options(u)} for u in pending]}
        def receipt(row):
            valid=validate(row,source,expected[row['unit_ref']]);valid['rule_versions']=rules['versions']
            return valid
        def check(value):
            rows=value.get('units') if isinstance(value,dict) else None
            if not isinstance(rows,list) or len(rows)!=len(expected):raise ValueError('每个输入原文单元都必须有独立提取回执。')
            found=set()
            for row in rows:
                ref=row.get('unit_ref') if isinstance(row,dict) else None
                if ref not in expected or ref in found:raise ValueError('原文单元回执重复或不存在。')
                found.add(ref);receipt(row)
            return {row['unit_ref']:receipt(row) for row in rows}
        schema={'units':[{'unit_ref':'输入单元编号','concepts':[{'key':'K1','label':'概念名称','category':'材料|方法|仪器|指标|现象|研究问题|概念','description':'原文定义与边界','evidence_refs':['E1']}],
            'claims':[{'key':'C1','label':'简短结论','statement':'保留对象、数字、条件与限制的原文结论','concept_keys':['K1'],'evidence_refs':['E1']}],
            'relations':[]}]}
        payload={'model':'deepseek-flash','thinking':{'type':'disabled'},'response_format':{'type':'json_object'},
            'max_tokens':7500,'messages':[{'role':'system','content':
            rules['text']+'\n每个输入原文单元都要有一条独立回执，按units[].unit_ref返回；E编号和K/C编号只在所属单元有效，禁止跨单元借用。'
            '没有实质内容的单元也返回空数组回执。只返回完整JSON对象。schema：'+encode(schema)},
            {'role':'user','content':encode(context)}]}
        try:result.update(check(model_request(payload,check)))
        except structured_response.ResponseValidationError as error:
            value=error.value;rows=value.get('units') if isinstance(value,dict) else None
            recovered={}
            if isinstance(rows,list) and len(rows)==len(expected) and all(isinstance(r,dict) and isinstance(r.get('unit_ref'),str) for r in rows) and {r.get('unit_ref') for r in rows}==set(expected):
                with store.connection() as db:
                    for row in rows:
                        unit=expected[row['unit_ref']]
                        try:valid=validate(row,source,unit)
                        except ValueError:
                            try:valid=_validated_subset(row,source,unit)
                            except ValueError:continue
                        valid['rule_versions']=rules['versions']
                        recovered[unit['ref']]=valid
                        _write_cursor(db,_unit_key(source,unit),valid)
            if len(recovered)!=len(expected):raise
            result.update(recovered)
    # Preserve known paid results before publishing individual chunks. A crash
    # during a later commit reuses the successful response instead of paying again.
    with store.connection() as db:
        for unit in pending:
            _write_cursor(db,_response_key(source,unit,retry_round),result[unit['ref']])
            _write_cursor(db,_unit_key(source,unit),result[unit['ref']])
    return result


def _write_cursor(db,key,value):
    db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)',(key,encode(value),now()))


def _put_node(db,identifier,kind,owner,project,uri,status,data):
    old=db.execute('SELECT * FROM nodes WHERE id=?',(identifier,)).fetchone()
    if old and old['owner']!=owner:raise ValueError('提取身份与现有权威来源冲突。')
    if old and old['status']=='REJECTED':return False
    if old:
        previous=json.loads(old['data'])
        if old['status']=='VERIFIED' and all(previous.get(key)==data.get(key) for key in ('title','derived_text','source_id','source_kind','generator')) and [e.get('quote_sha256') for e in previous.get('evidence',[])]==[e.get('quote_sha256') for e in data.get('evidence',[])]:status='VERIFIED'
        data={**data,**{key:previous[key] for key in ('alias_of','alias_reason') if key in previous}}
    if old and old['data']==encode(data):return True
    if old:
        Store.log(db,'extraction.revision',identifier,{'before':dict(old)})
        db.execute('UPDATE nodes SET kind=?,project=?,uri=?,status=?,data=?,revision=revision+1,updated=? WHERE id=?',
                   (kind,project,uri,status,encode(data),now(),identifier))
    else:
        db.execute('INSERT INTO nodes(id,kind,owner,project,uri,status,data,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                   (identifier,kind,owner,project,uri,status,encode(data),now(),now()))
    return True


def _put_relation(db,source,target,kind,evidence,conditions):
    identifier='REL-'+_hash([source,target,kind])[:20]
    old=db.execute('SELECT * FROM relations WHERE id=?',(identifier,)).fetchone()
    if old and old['status']=='REJECTED':return
    if old and old['evidence']==encode(evidence) and old['conditions']==conditions:return
    if old:
        Store.log(db,'extraction.relation-revision',identifier,{'before':dict(old)})
        db.execute("UPDATE relations SET evidence=?,conditions=?,status='CANDIDATE',revision=revision+1,updated=? WHERE id=?",
                   (encode(evidence),conditions,now(),identifier))
    else:
        db.execute('INSERT INTO relations(id,source,target,kind,status,evidence,conditions,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                   (identifier,source,target,kind,'CANDIDATE',encode(evidence),conditions,now(),now()))


def _commit(source,unit,result,progress,store):
    """Derived nodes, candidate relations and successful chunk cursor commit together."""
    def normalize(text):return ' '.join(unicodedata.normalize('NFKC',text).casefold().split())
    # Response-local K/C labels and page/chunk positions are not identities.
    # A reordered answer or unchanged quote shifted to a later page reuses IDs.
    identifiers={item['key']:'EX-'+('K-' if item['kind']=='ExtractedConcept' else 'C-')+
        _hash([source['source_id'],item['kind'],normalize(item['label']),normalize(item['text']),
               sorted(e['quote_sha256'] for e in item['evidence'])])[:24] for item in result['items']}
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        # Register only a missing source identity; never replace another owner's data.
        if not db.execute('SELECT 1 FROM nodes WHERE id=?',(source['source_id'],)).fetchone():
            _put_node(db,source['source_id'],source['kind'],source['owner'],source['project'],source['uri'],
                      'INDEXED',{'title':source['title'],'document_sha256':source['source_sha256']})
        for item in result['items']:
            identifier=identifiers[item['key']]
            data={'title':item['label'],'derived_text':item['text'],'rebuildable':True,'generator':VERSION,
                  'source_id':source['source_id'],'source_sha256':source['source_sha256'],'unit_ref':unit['ref'],
                  'text_fingerprint':source.get('text_fingerprint'),
                  'evidence':item['evidence'],'entity_type':item.get('entity_type','概念'),'source_kind':source['source_kind'],'figures_checked':False}
            _put_node(db,identifier,item['kind'],OWNER,source['project'],source['uri'],'CANDIDATE',data)
            _put_relation(db,identifier,source['source_id'],'DerivedFrom',item['evidence'],'原文提取出处；不表示论断已经核实。')
        for item in result['items']:
            for target in item['concept_keys']:
                _put_relation(db,identifiers[item['key']],identifiers[target],'About',item['evidence'],'本段论断涉及此概念；待人工核对。')
        for edge in result['relations']:
            left,right=sorted([identifiers[edge['source_key']],identifiers[edge['target_key']]])
            evidence=[e for item in result['items'] if item['key'] in (edge['source_key'],edge['target_key']) for e in item['evidence']]
            _put_relation(db,left,right,'AssociatedWith',evidence,edge['reason'])
        completed=list(dict.fromkeys(progress.get('completed',[])+[unit['ref']]))
        warnings={**progress.get('validation_warnings',{})}
        if result.get('validation_rejections'):
            warnings[unit['ref']]=result['validation_rejections']
            Store.log(db,'extraction.candidates_rejected',source['source_id'],{
                'unit_ref':unit['ref'],'source_sha256':source['source_sha256'],
                'rejections':result['validation_rejections']})
        updated={**progress,'source_sha256':source['source_sha256'],'completed':completed,
                 'text_fingerprint':source.get('text_fingerprint'),
                 'total_chunks':len(source['units']),'failure':None,'updated':now(),'version':VERSION,
                 'validation_warnings':warnings}
        _write_cursor(db,_source_key(source['source_id']),updated)
        Store.log(db,'extraction.chunk',source['source_id'],{'unit_ref':unit['ref'],'source_sha256':source['source_sha256'],'nodes':list(identifiers.values())})


def _progress(store,source):
    value=store.cursor(_source_key(source['source_id']),{}) or {}
    if (value.get('source_sha256')!=source['source_sha256'] or value.get('version')!=VERSION
            or _text_changed(value,source)):
        return {'source_sha256':source['source_sha256'],'text_fingerprint':source.get('text_fingerprint'),
                'completed':[],'version':VERSION,'retry_round':0,
                'rebuild_required':bool(value.get('completed'))}
    return value


def _projection(source_map,store, *, include_edges=True):
    stored={node['id']:node for node in store.nodes()};visible={};hidden=[];aliases={};eligible_aliases=[]
    for node in stored.values():
        if node['owner']!=OWNER or node['kind'] not in KINDS:continue
        data=node['data'];source=source_map.get(data.get('source_id'));reason=''
        if node['status']=='REJECTED':reason='rejected'
        elif not source or not source['eligible']:reason='source_out_of_scope'
        elif source['status']!='ready':reason=source['status']
        elif source['source_sha256']!=data.get('source_sha256'):reason='source_changed'
        elif _text_changed(data,source):reason='source_text_changed'
        elif data.get('generator')!=VERSION:reason='extractor_changed'
        elif not _knowledge_projection(data,source):reason='non_knowledge_projection'
        elif current_state(node,source)!='current':reason=current_state(node,source)
        if not reason and data.get('alias_of'):
            reason='alias';aliases[node['id']]=data['alias_of'];eligible_aliases.append(node)
        if reason:
            hidden.append({'id':node['id'],'reason':reason});continue
        visible[node['id']]={'id':node['id'],'record_id':node['id'],'kind':'概念' if node['kind']=='ExtractedConcept' else '结论',
            'record_kind':node['kind'],'label':data['title'],'summary':data['derived_text'],'status':node['status'],
            'owner':OWNER,'revision':node['revision'],'suggested':node['status']!='VERIFIED','active':True,'stale':False,
            'source_ids':[data['source_id']],'evidence':data['evidence'],'source_kind':data['source_kind'],
            'entity_type':data.get('entity_type','概念'),'review_scope':'extraction_accuracy','uri':node.get('uri'),'rebuildable':True}
    def canonical(identifier):
        visited=set()
        while identifier in aliases and identifier not in visited:
            visited.add(identifier);identifier=aliases[identifier]
        return identifier
    for node in eligible_aliases:
        target=visible.get(canonical(node['id']))
        if target:
            target['source_ids']=list(dict.fromkeys(target['source_ids']+[node['data']['source_id']]))
            target['evidence']=target['evidence']+node['data']['evidence']
    edges=[];seen=set()
    for edge in store.relations() if include_edges else ():
        if edge['status']=='REJECTED' or not any(e.get('generator')==VERSION for e in edge['evidence']):continue
        if any((not source_map.get(e.get('id'))
                or source_map[e['id']]['status']!='ready'
                or source_map[e['id']]['source_sha256']!=e.get('source_sha256')
                or _text_changed(e,source_map[e['id']]))
               for e in edge['evidence'] if e.get('generator')==VERSION):continue
        origin=canonical(edge['source'])
        if origin not in visible:continue
        target=canonical(edge['target']);layer='semantic'
        if edge['kind']=='DerivedFrom':
            source=source_map.get(target)
            if not source or source['status']!='ready':continue
            target=source['graph_id'];layer='provenance'
        elif target not in visible:continue
        marker=(origin,target,edge['kind'])
        if origin==target or marker in seen:continue
        seen.add(marker)
        edges.append({'id':edge['id'],'from':origin,'to':target,'kind':edge['kind'],
            'label':{'About':'涉及概念','AssociatedWith':'主题相关','DerivedFrom':'提取出处'}.get(edge['kind'],edge['kind']),
            'status':edge['status'],'suggested':edge['status']!='VERIFIED','evidence':edge['evidence'],
            'explanation':edge['conditions'],'revision':edge['revision'],'source':'AI 原文提取','layer':layer})
    return {'nodes':list(visible.values()),'edges':edges,'hidden':hidden,
            'counts':{'concepts':sum(n['record_kind']=='ExtractedConcept' for n in visible.values()),
                      'claims':sum(n['record_kind']=='ExtractedClaim' for n in visible.values()),'hidden':len(hidden)}}


def project(snapshot=None):
    return _projection(sources(snapshot),Store())


def graph_nodes(snapshot=None):
    return project(snapshot)['nodes']


def runtime_status(store,cfg):
    with store.connection() as db:
        latest=db.execute("SELECT id,status,phase,updated FROM jobs WHERE kind='knowledge_extraction' ORDER BY created DESC LIMIT 1").fetchone()
        completed=db.execute("SELECT updated FROM jobs WHERE kind='knowledge_extraction' AND status='completed' ORDER BY updated DESC LIMIT 1").fetchone()
    state='due';reason='等待后台调度'
    if not cfg.get('enabled'):state,reason='disabled','自动知识提取已关闭，资料同步不受此开关影响'
    elif cfg.get('paused'):state,reason='paused','已暂停知识自动提取和全局普通关联'
    elif store.cursor(PROVIDER_BLOCK,{}).get('blocked'):
        state,reason='blocked',store.cursor(PROVIDER_BLOCK,{})['reason']
    elif latest and latest['status'] in ('queued','running'):
        state,reason=latest['status'],latest['phase'] or '等待执行或正在处理；以任务进度为准'
    elif cfg.get('analysis_epoch') and not cfg.get('has_pending'):
        state,reason='current','已检查当前资料，新增或修改后继续分析'
    else:
        try:
            if cfg.get('next_check') and datetime.fromisoformat(cfg['next_check'])>datetime.now(timezone.utc):
                state,reason='scheduled','等待下次计划检查'
        except (ValueError,TypeError):pass
    return {'state':state,'reason':reason,'next_check':None if state in ('blocked','current') else cfg.get('next_check'),
            'job':dict(latest) if latest else None,'last_completed_at':completed['updated'] if completed else None}


def status():
    store=Store();source_map=sources();cfg=store.cursor(CONTROL,{}) or {};coverage=[];failures=[]
    counts={'sources':len(source_map),'ready':0,'missing_original':0,'unparsed':0,'out_of_scope':0,
            'stale_cache':0,'partial_parse':0,'processed_chunks':0,'total_chunks':0,
            'partial_index_units':0,'rejected_candidates':0}
    for source in source_map.values():
        progress=_progress(store,source);done=len(set(progress.get('completed',[]))&{u['ref'] for u in source['units']})
        counts[source['status']]=counts.get(source['status'],0)+1
        if source['eligible']:
            counts['processed_chunks']+=done;counts['total_chunks']+=len(source['units'])
        warnings={key:value for key,value in progress.get('validation_warnings',{}).items()
                  if key in progress.get('completed',[]) and any(u['ref']==key for u in source['units'])}
        rejected=sum(len(value) for value in warnings.values())
        if source['eligible']:
            counts['partial_index_units']+=len(warnings);counts['rejected_candidates']+=rejected
        coverage.append({'source_id':source['source_id'],'title':source['title'],'status':source['status'],
            'source_sha256':source['source_sha256'],'processed_chunks':done,'total_chunks':len(source['units']),
            'partial_index_units':len(warnings),'rejected_candidates':rejected,
            'rebuilding':source['status']=='ready' and bool(progress.get('rebuild_required')) and done<len(source['units']),
            'text_complete':source['status']=='ready' and done==len(source['units']),'figures_checked':False,
            **{key:source.get(key) for key in ('expected_pages','cached_pages','empty_text_locations','methods',
                'quality_failed_locations','text_fingerprint','parser_version')}})
        if progress.get('failure'):failures.append({'source_id':source['source_id'],**progress['failure']})
    projection=_projection(source_map,store,include_edges=False)
    counts.update(projection['counts'])
    remaining=counts['total_chunks']-counts['processed_chunks']
    unavailable=sum(s['eligible'] and s['status']!='ready' for s in source_map.values())
    state=('paused' if cfg.get('paused') else 'needs_attention' if failures else 'pending' if remaining else 'partial' if unavailable else 'complete')
    runtime=runtime_status(store,cfg)
    if runtime['state'] in ('blocked','paused','disabled'):state=runtime['state']
    return {'enabled':bool(cfg.get('enabled')),'paused':bool(cfg.get('paused')),'status':state,
        'revision':cfg.get('revision',0),'counts':counts,'processed_chunks':counts['processed_chunks'],
        'total_chunks':counts['total_chunks'],'remaining':remaining,'coverage':coverage,'failures':failures,
        'next_check':cfg.get('next_check'),'runtime':runtime,'scope':'global_qualified_originals','version':VERSION}


def run(data=None):
    store=Store()
    try:
        with FileLock(str(w.DATA/'.knowledge-extraction.lock'),timeout=0):return _run(data)
    except Timeout:
        return {**status(),'status':'busy'}


def _run(data=None):
    data=data or {};limit=data.get('max_chunks',1)
    if type(limit) is not int or not 1<=limit<=MAX_CHUNKS:raise ValueError('每批处理 1–12 个原文片段。')
    selected=data.get('source_ids')
    if selected is not None and (not isinstance(selected,list) or len(selected)>1000 or any(not isinstance(i,str) for i in selected)):
        raise ValueError('来源选择无效。')
    store=Store();cfg=store.cursor(CONTROL,{}) or {}
    if cfg.get('paused') or cfg.get('enabled') is False or store.cursor(PROVIDER_BLOCK,{}).get('blocked'):return status()
    source_map=_analysis_sources();processed=0
    for source in sorted(source_map.values(),key=lambda item:item['source_id']):
        if source['status']!='ready' or selected is not None and source['source_id'] not in selected:continue
        progress=_progress(store,source)
        failure=progress.get('failure') or {}
        request_id=failure.get('request_id')
        if failure and (failure.get('replay_mismatch') or not structured_response.request_released(store,request_id)):continue
        pending=[u for u in source['units'] if u['ref'] not in progress.get('completed',[])]
        while pending and processed<limit:
            batch=[];size=0
            # A known failed response is retried independently per unit, so one
            # malformed page cannot keep a multi-page request failing forever.
            batch_limit=1 if progress.get('retry_round',0)>0 else 4
            for unit in pending[:min(batch_limit,limit-processed)]:
                if batch and size+len(unit['text'])>12000:break
                batch.append(unit);size+=len(unit['text'])
            unit=batch[0]
            try:
                with structured_response.resume_request(store,request_id):
                    results=_request_units(source,batch,progress,store)
                request_id=None
                latest_control=store.cursor(CONTROL,{}) or {}
                if latest_control.get('paused') or latest_control.get('revision',0)!=cfg.get('revision',0):
                    return status()
                current=_analysis_sources().get(source['source_id'])
                if (not current or current['status']!='ready' or current['source_sha256']!=source['source_sha256']
                        or current.get('text_fingerprint')!=source.get('text_fingerprint')):
                    raise ValueError('来源在提取期间变化，本片结果未发布。')
                for unit in batch:
                    _commit(source,unit,results[unit['ref']],progress,store)
                    progress=_progress(store,source);processed+=1
                pending=pending[len(batch):]
            except Exception as error:
                if block_provider(error,store):return status()
                failure={'message':str(error)[:1000] if isinstance(error,ValueError) else '原文提取暂未完成：'+type(error).__name__,
                         'kind':'invalid_response' if isinstance(error,structured_response.ResponseValidationError) else 'waiting_review',
                         'unit_ref':unit['ref'],'updated':now()}
                if isinstance(error,structured_response.ModelRequestError):
                    failure.update(request_id=error.request_id,replay_mismatch=error.replay_mismatch)
                with store.connection() as db:_write_cursor(db,_source_key(source['source_id']),{**progress,'failure':failure})
                break
            if processed>=limit:return status()
    return status()


def current_state(node, source_record):
    """Shared, side-effect-free current-version check for detail and review."""
    data=node.get('data',{});source=source_record
    if not source or not source.get('eligible'):return 'source_out_of_scope'
    if source['status']!='ready':return source['status']
    if source['source_sha256']!=data.get('source_sha256'):return 'source_changed'
    if _text_changed(data,source):return 'source_text_changed'
    if data.get('generator')!=VERSION:return 'extractor_changed'
    if not _knowledge_projection(data,source):return 'non_knowledge_projection'
    unit=next((u for u in source['units'] if u['ref']==data.get('unit_ref')),None)
    if not unit:return 'source_excerpt_changed'
    if not data.get('evidence'):return 'invalid_evidence'
    for evidence in data['evidence']:
        start=evidence.get('start',-1);end=evidence.get('end',-1)
        if type(start) is not int or type(end) is not int:return 'invalid_evidence'
        start-=unit.get('start',0);end-=unit.get('start',0)
        if (start<0 or end<=start or unit['text'][start:end]!=evidence.get('quote')
                or w.digest(evidence['quote'])!=evidence.get('quote_sha256')
                or evidence.get('id')!=data.get('source_id')
                or evidence.get('source_sha256')!=source['source_sha256']):return 'invalid_evidence'
    return 'current'


def assert_review_current(node,store=None):
    if node.get('owner')!=OWNER:return
    if current_state(node,source(node.get('data',{}).get('source_id'),store=store))!='current':
        raise ValueError('来源、片段或准入范围已变化，请重新提取并核查当前版本。')


def control(data):
    if not isinstance(data,dict):raise ValueError('知识提取操作无效。')
    action=data.get('action');store=Store()
    with LOCK:
        cfg=store.cursor(CONTROL,{}) or {}
        if action in {'start','pause','resume','enable','disable'}:
            with store.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT value FROM cursors WHERE key=?',(CONTROL,)).fetchone()
                cfg=json.loads(row['value']) if row else {}
                expected=data.get('revision')
                if expected is not None and expected!=cfg.get('revision',0):raise ValueError('提取设置已变化，请刷新。')
                cfg.update(enabled=action!='disable',paused=action=='pause')
                cfg.update(revision=cfg.get('revision',0)+1,next_check=None)
                _write_cursor(db,CONTROL,cfg)
                if action in {'start','resume','enable'}:
                    db.execute('DELETE FROM cursors WHERE key=?',(PROVIDER_BLOCK,))
            return status()
        if action=='retry_failed':
            identifiers=data.get('source_ids')
            if identifiers is not None and (not isinstance(identifiers,list) or any(not isinstance(i,str) for i in identifiers)):raise ValueError('来源选择无效。')
            for source in sources().values():
                if identifiers is not None and source['source_id'] not in identifiers:continue
                progress=_progress(store,source);failure=progress.get('failure')
                if not failure:continue
                # Only a known invalid answer gets a new request identity. Unknown
                # provider outcomes reuse the request ledger and cannot bypass it.
                if failure['kind']!='invalid_response':continue
                progress['retry_round']=progress.get('retry_round',0)+1
                progress['failure']=None
                with store.connection() as db:_write_cursor(db,_source_key(source['source_id']),progress)
            _schedule_now(store)
            return status()
        node=store.node(data.get('id')) if isinstance(data.get('id'),str) else None
        if not node or node['owner']!=OWNER or node['kind'] not in KINDS:raise ValueError('提取对象不存在。')
        if type(data.get('revision')) is not int or data['revision']!=node['revision']:raise ValueError('提取对象版本已变化，请刷新。')
        reason=data.get('reason','').strip()
        if action in ('reject','verify'):
            if not reason:raise ValueError('请填写核查说明或不采用原因。')
            return store.review(node['id'],node['revision'],'REJECTED' if action=='reject' else 'VERIFIED',reason)
        if action=='alias':
            target=store.node(data.get('target')) if isinstance(data.get('target'),str) else None
            if not target or target['owner']!=OWNER or target['kind']!=node['kind'] or target['id']==node['id'] or target['status']=='REJECTED' or target['data'].get('alias_of'):
                raise ValueError('请选择不同的同类有效提取对象。')
            if data.get('target_revision') is not None and data['target_revision']!=target['revision']:raise ValueError('合并目标版本已变化，请刷新。')
            if not reason:raise ValueError('请填写合并依据。')
            assert_review_current(node,store);assert_review_current(target,store)
            updated=store.put_node(node['id'],node['kind'],OWNER,project=node['project'],uri=node['uri'],
                status=node['status'],expected=node['revision'],data={**node['data'],'alias_of':target['id'],'alias_reason':reason})
            return {'id':updated['id'],'target':target['id'],'revision':updated['revision'],'status':'aliased'}
        if action=='promote':
            assert_review_current(node,store)
            return _promote(node,data,store)
        raise ValueError('未知知识提取操作。')


def _promote(node,data,store):
    """Explicit human action creates a canonical manuscript; AI cache stays intact."""
    import research_records
    key='knowledge-extraction:promotion:'+node['id'];prior=store.cursor(key,{}) or {}
    if prior.get('record_id') and prior.get('phase')=='completed':
        record=store.node(prior['record_id'])
        if record:return {**prior,'reused':True,'record':record}
    kind='Claim' if node['kind']=='ExtractedClaim' else 'Concept'
    if kind not in research_records.TYPES:raise ValueError('概念知识稿入口尚未登记，请刷新升级后的服务。')
    title=data.get('title') or node['data']['title'];body=data.get('body') or node['data']['derived_text']
    if not isinstance(title,str) or not 1<=len(title.strip())<=200 or not isinstance(body,str) or len(body)>100000:
        raise ValueError('知识稿标题或正文无效。')
    evidence=node['data']['evidence'];body+='\n\n## 来源\n\n'+'\n'.join(
        '- '+e['id']+' · '+e['location']+'\n\n  > '+e['quote'].replace('\n','\n  > ') for e in evidence)
    paper_ids=[node['data']['source_id']] if node['data']['source_kind']=='original' else []
    project=data.get('project') or '共享'
    if not isinstance(project,str) or not project.strip() or len(project)>100 or any(c in project for c in '/\\:\x00') or project in {'.','..'}:
        raise ValueError('知识稿归属无效。')
    if not prior:
        identifier=store.allocate(research_records.TYPES[kind][0])
        relative=('笔记/'+project+'/'+research_records.TYPES[kind][1]+'/'+identifier+'.md')
        raw=k.properties('',{'id':identifier,'type':'research_record','record_type':kind,'title':title,
            'project':project,'content_role':'knowledge','global_knowledge':True,'review_owner':'SQLite',
            'paper_ids':paper_ids,'knowledge_sources':[{'record_id':node['id'],'source_id':node['data']['source_id'],
                'source_sha256':node['data']['source_sha256']} ]})+'# '+title+'\n\n'+body.rstrip()+'\n'
        prior={'record_id':identifier,'path':relative,'raw':raw,'kind':kind,'project':project,
            'title':title,'source_projection':node['id'],'phase':'planned','created':now()}
        with store.connection() as db:_write_cursor(db,key,prior)
    # Filesystem + SQLite use a durable intent, preserving the reserved identity
    # after interruption instead of creating a second human manuscript.
    path=(w.KB/prior['path']).resolve()
    if not path.is_relative_to(w.KB.resolve()):raise ValueError('知识稿位置超出知识库。')
    with k.editing():
        before=path.read_text('utf-8-sig') if path.exists() else ''
        if before and before!=prior['raw']:raise ValueError('知识稿已有人修改，原稿保留，请先核对未完成的提炼。')
        if not before:k.persist(path,'',prior['raw'],w.KB.resolve())
        body_sha=w.digest(k.split(prior['raw'])[1].rstrip())
        record=store.put_node(prior['record_id'],prior['kind'],'Markdown',project=prior['project'],uri=prior['path'],
            status='CANDIDATE',data={'title':prior['title'],'document_sha256':body_sha,
                'source':'human-promotion','source_projection':node['id']})
    store.relation(record['id'],node['id'],'DerivedFrom',evidence,'本人选择从此提取结果建立知识稿；科学结论另行核查。',mechanical=True)
    store.relation(record['id'],node['data']['source_id'],'DerivedFrom',evidence,'知识稿引用此原文版本；这条出处记录不表示支持或科学验证。',mechanical=True)
    value={key:value for key,value in prior.items() if key!='raw'};value['phase']='completed'
    with store.connection() as db:_write_cursor(db,key,value)
    return {**value,'record':record,'reused':False}


def block_provider(error,store=None):
    """A confirmed account rejection blocks the service, not every source."""
    if not isinstance(error,ValueError) or 'HTTP 402' not in str(error):return False
    store=store or Store()
    with store.connection() as db:
        _write_cursor(db,PROVIDER_BLOCK,{'blocked':True,'http_status':402,'updated':now(),
            'reason':'DeepSeek 返回 HTTP 402，知识自动提取和全局普通关联已暂停。账户恢复后选择“服务恢复后继续”。'})
    return True


def due():
    store=Store();cfg=store.cursor(CONTROL,{}) or {}
    if not cfg.get('enabled') or cfg.get('paused'):return False
    if store.cursor(PROVIDER_BLOCK,{}).get('blocked'):return False
    if any(structured_response.request_released(store,i) for i in cfg.get('waiting_requests',[])):return True
    if not cfg.get('next_check'):return True
    try:
        if datetime.fromisoformat(cfg['next_check'])>datetime.now(timezone.utc):return False
    except (TypeError,ValueError):return True
    if cfg.get('has_pending') or not cfg.get('analysis_epoch'):return True
    stamp=monotonic()
    if stamp<_NEXT_PROBE.get(store.path,0):return False
    if cfg['analysis_epoch']!=_analysis_epoch():return True
    _NEXT_PROBE[store.path]=stamp+60
    return False


def _pending_work(store):
    pending=False;waiting=set()
    for source in _analysis_sources().values():
        if source['status']!='ready':continue
        progress=_progress(store,source)
        failure=progress.get('failure') or {}
        if failure:
            if failure.get('request_id') and not failure.get('replay_mismatch'):
                waiting.add(failure['request_id'])
        elif len(progress.get('completed',[]))<len(source['units']):
            pending=True
    return pending,sorted(waiting)


def _schedule_now(store):
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT value FROM cursors WHERE key=?',(CONTROL,)).fetchone()
        if row:
            value=json.loads(row['value']);value['next_check']=None
            _write_cursor(db,CONTROL,value)


def tick():
    if not due():return {'status':'not_due'}
    store=Store();cfg=store.cursor(CONTROL,{}) or {}
    epoch=_analysis_epoch()
    result=run({'max_chunks':12})
    pending,waiting=_pending_work(store)
    failed={r['source_id'] for r in result['failures']}
    pending=pending or any(r['status']=='ready' and r['processed_chunks']<r['total_chunks']
                           and r['source_id'] not in failed for r in result['coverage'])
    minutes=1 if pending else 5
    # A user can change controls while extraction is running.
    with LOCK,store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT value FROM cursors WHERE key=?',(CONTROL,)).fetchone()
        latest=json.loads(row['value']) if row else {}
        if latest.get('revision',0)==cfg.get('revision',0) and latest.get('enabled') and not latest.get('paused'):
            latest['next_check']=(datetime.now(timezone.utc)+timedelta(minutes=minutes)).isoformat()
            latest.update(analysis_epoch=epoch,has_pending=pending,waiting_requests=waiting)
            _write_cursor(db,CONTROL,latest)
    return result
