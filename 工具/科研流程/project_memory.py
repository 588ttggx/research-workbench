"""Source-bound reuse suggestions, without promoting a draft into experience."""
import workflow as w
import knowledge as k
from research_store import Store
from research_records import reconcile
import workspace_catalog as catalog

KINDS={'Decision','Issue','Failure','Solution','Lesson','Experience','SOP','Method','Review','Closure'}


def overview(project,query=None,*,retrieve=False):
    lines=k.lines(project)
    query=(query or ' '.join(str(row.get('title',''))+' '+str(row.get('goal','')) for row in lines['rows'] if row.get('status')!='不采用')).strip()[:2000]
    reconcile();store=Store();docs=catalog.rows();by_record={d['record_id']:d for d in docs if d.get('record_id') and not d['archived'] and d['visibility']!='system'}
    own=[];past=[]
    for node in store.nodes():
        if node['kind'] not in KINDS or node['owner']!='Markdown' or node['id'] not in by_record:continue
        doc=by_record[node['id']]
        from material_roles import knowledge
        if node['project']!=project and not knowledge(doc,global_scope=True):continue
        row={'id':node['id'],'doc_id':doc['id'],'title':doc['display_title'],'kind':node['kind'],'label':doc['kind'],
             'project':node['project'],'status':node['status'],'excerpt':doc['excerpt'],'sha256':doc['sha']}
        (own if node['project']==project else past).append(row)
    from research_store import encode
    signature=w.digest(encode([query,past]));cache=store.cursor('project-memory:'+project,{})
    matches=[];method='未运行';remaining=0;needs=bool(query and past and cache.get('signature')!=signature)
    if query and past and not needs:
        matches=cache['suggestions'];method=cache['retrieval'];remaining=cache.get('remaining_vectors',0)
    if query and past and needs and retrieve:
        from relation_discovery import database,local_vectors,digest
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        items={'query':{'title':query,'fingerprint':digest(query),'sources':[]}}
        for row in past:
            items[row['id']]={'title':row['title'],'fingerprint':digest([row['sha256'],row['title']]),'sources':[{'text':row['excerpt']}]}
        vectors=local_vectors(items,database())
        if isinstance(vectors,list):matrix=vectors;method='Qwen3 Embedding 4B · 本地相似资料'
        else:
            remaining=vectors.get('remaining',0) if isinstance(vectors,dict) else 0
            matrix=TfidfVectorizer(analyzer='char',ngram_range=(2,4)).fit_transform([query,*[r['title']+'\n'+r['excerpt'] for r in past]])
            method='文本匹配 · 本地向量暂未就绪'
        scores=cosine_similarity(matrix)[0][1:]
        matches=[{**row,'score':round(float(score),4),'candidate':True} for row,score in zip(past,scores) if score>=.1]
        matches.sort(key=lambda r:(r['status']!='VERIFIED',-r['score'],r['id']))
        store.commit_page('project-memory:'+project,[],{'signature':signature,'suggestions':matches,'retrieval':method,'remaining_vectors':remaining})
        needs=False
    return {'project':project,'query':query,'records':own,'suggestions':matches,'retrieval':method,'remaining_vectors':remaining,
            'needs_retrieval':needs,'historical_records':len(past),'signature':signature,
            'scope':'历史相似资料仅作复用候选，保留原项目、原稿与核查状态；匹配分数不代表科研有效性，不自动写入经验或科研关系。'}
