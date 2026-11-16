"""Read-only display retrieval. Similarity is never a scientific relationship.

Reuse current Qwen vectors already paid for by the existing comparison pipeline.
Opening a map never generates vectors or calls a model. Query embedding is local,
optional, version-checked, and independent of loading the graph.
"""
from collections import OrderedDict
import json
import threading
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors
from sklearn.metrics.pairwise import cosine_similarity
import requests
import networkx as nx
import workflow as w
from research_store import Store, encode
from relation_discovery import digest as vector_digest

_cache=OrderedDict()
_lock=threading.RLock()


def current_vectors(snapshot,store):
    allowed={n['id'] for n in snapshot['nodes'] if not n.get('stale')}
    with store.connection() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='relation_vectors' AND type='table'").fetchone():return '',{}
        model=db.execute("SELECT model FROM relation_vectors WHERE model LIKE 'qwen3-embedding:4b@%' ORDER BY updated DESC LIMIT 1").fetchone()
        if not model:return '',{}
        model=model['model']
        cached={r['fingerprint']:r['vector'] for r in db.execute('SELECT fingerprint,vector FROM relation_vectors WHERE model=?',(model,))}
        rows=db.execute("SELECT id,data FROM nodes WHERE kind IN ('ExtractedClaim','ExtractedConcept')").fetchall()
    result={};dimension=None
    for row in rows:
        if row['id'] not in allowed:continue
        key=vector_digest(['embedding-v1',model,w.digest(encode(json.loads(row['data'])))])
        if key not in cached:continue
        try:
            vector=np.asarray(json.loads(cached[key]),dtype=np.float32)
            if vector.ndim!=1 or len(vector)<32 or not np.isfinite(vector).all() or np.linalg.norm(vector)==0:continue
            if dimension is None:dimension=len(vector)
            if len(vector)==dimension:result[row['id']]=vector
        except (TypeError,ValueError):continue
    return model,result


def _features(snapshot):
    nodes=sorted(snapshot['nodes'],key=lambda n:n['id'])
    texts=[str(n.get('label',''))+' '+str(n.get('summary',''))[:900] for n in nodes]
    vectorizer=TfidfVectorizer(analyzer='char',ngram_range=(2,4),max_features=24000)
    try:matrix=vectorizer.fit_transform(texts)
    except ValueError:
        vectorizer=None;matrix=np.eye(len(nodes),dtype=np.float32)
    return nodes,vectorizer,matrix


def _fuse(rankings):
    scores={}
    for ranking in rankings:
        for rank,identifier in enumerate(ranking):scores[identifier]=scores.get(identifier,0)+1/(60+rank)
    return sorted(scores,key=lambda identifier:(-scores[identifier],identifier)),scores


def index(snapshot,store=None):
    """Uniform kNN rows for the upstream UMAP implementation, not new edges."""
    store=store or Store()
    with store.connection() as db:
        stamp=tuple(db.execute('SELECT COUNT(*),MAX(updated) FROM relation_vectors').fetchone()) if db.execute("SELECT 1 FROM sqlite_master WHERE name='relation_vectors' AND type='table'").fetchone() else (0,None)
    signature=(str(getattr(store,'path','')),snapshot.get('graph_fingerprint'),stamp,
               tuple((n['id'],n.get('summary',''),bool(n.get('stale'))) for n in snapshot['nodes']))
    with _lock:
        if signature in _cache:return _cache[signature]
    nodes,_,matrix=_features(snapshot);ids=[n['id'] for n in nodes];count=len(ids)
    model,vectors=current_vectors(snapshot,store)
    k=min(15,count);width=min(max(k*2,1),count)
    lexical={identifier:[] for identifier in ids};dense={identifier:[] for identifier in ids}
    if count:
        distances,neighbors=NearestNeighbors(n_neighbors=width,metric='cosine').fit(matrix).kneighbors(matrix)
        lexical={identifier:[ids[j] for distance,j in zip(distances[i],neighbors[i]) if j!=i and distance<.9999] for i,identifier in enumerate(ids)}
    if len(vectors)>1:
        known=sorted(vectors);arr=np.stack([vectors[i] for i in known])
        distances,neighbors=NearestNeighbors(n_neighbors=min(width,len(known)),metric='cosine').fit(arr).kneighbors(arr)
        dense={identifier:[known[j] for distance,j in zip(distances[i],neighbors[i]) if j!=i and distance<.65] for i,identifier in enumerate(known)}
    ordinal={identifier:i for i,identifier in enumerate(ids)};indices=[];distances=[]
    for identifier in ids:
        ranked,scores=_fuse([lexical.get(identifier,[]),dense.get(identifier,[])])
        ranked=[identifier]+ranked+[i for i in ids if i!=identifier and i not in scores]
        for neighbor in ranked[:k]:
            indices.append(ordinal[neighbor]);distances.append(0. if neighbor==identifier else max(.001,1-min(.99,30*scores.get(neighbor,0))))
    affinity=nx.DiGraph();affinity.add_nodes_from(ids)
    for row,identifier in enumerate(ids):
        for offset in range(k):
            neighbor=ids[indices[row*k+offset]];distance=distances[row*k+offset]
            if neighbor!=identifier and distance<.999:affinity.add_edge(identifier,neighbor,weight=1-distance)
    importance=nx.pagerank(affinity,weight='weight') if count else {}
    result={'ids':ids,'indices':indices,'distances':distances,'k':k,'model':model,'importance':importance,
            'vector_count':len(vectors),'total_count':count,'method':'hybrid' if vectors else 'text',
            'version':'semantic-knn-v1'}
    with _lock:
        _cache[signature]=result
        while len(_cache)>4:_cache.popitem(last=False)
    return result


def query_vector(text,model):
    """Use only the already-installed model matching the cache's model digest."""
    if not model:return None
    try:
        base='http://127.0.0.1:11434';name,digest=model.split('@',1)
        tags=requests.get(base+'/api/tags',timeout=2);tags.raise_for_status()
        if not any(m.get('name')==name and m.get('digest')==digest for m in tags.json().get('models',[])):return None
        response=requests.post(base+'/api/embed',json={'model':name,'input':[text],'truncate':True,'keep_alive':'10m'},timeout=(2,15))
        response.raise_for_status();vector=np.asarray(response.json()['embeddings'][0],dtype=np.float32)
        return vector if vector.ndim==1 and np.isfinite(vector).all() else None
    except (requests.RequestException,ValueError,KeyError,IndexError,TypeError):return None


def search(snapshot,query='',root='',limit=60,store=None):
    store=store or Store();nodes,vectorizer,matrix=_features(snapshot);by_id={n['id']:n for n in nodes}
    if root and root not in by_id:raise ValueError('当前知识范围内没有此对象。')
    query=str(query).strip()[:500];text=query or ' '.join(str(by_id.get(root,{}).get(key,'')) for key in ('label','summary'))
    lexical=[]
    if vectorizer is not None and text:
        values=cosine_similarity(vectorizer.transform([text]),matrix)[0]
        lexical=[nodes[i]['id'] for i in sorted(range(len(nodes)),key=lambda i:(-values[i],nodes[i]['id'])) if values[i]>.04]
    model,vectors=current_vectors(snapshot,store)
    target=query_vector(query,model) if query else vectors.get(root)
    dense=[]
    if target is not None and vectors:
        known=[i for i in sorted(vectors) if len(vectors[i])==len(target)]
        if known:
            values=cosine_similarity([target],np.stack([vectors[i] for i in known]))[0]
            dense=[known[i] for i in sorted(range(len(known)),key=lambda i:(-values[i],known[i])) if values[i]>.45]
    ranked,_=_fuse([lexical,dense]);ranked=[i for i in ranked if i!=root]
    # Round-robin sources: one prolific source cannot occupy the first screen.
    groups=OrderedDict()
    for identifier in ranked:
        source=tuple(by_id[identifier].get('source_ids') or [identifier]);groups.setdefault(source,[]).append(identifier)
    diversified=[]
    while groups:
        for key in list(groups):
            diversified.append(groups[key].pop(0))
            if not groups[key]:del groups[key]
    return {'ids':([root] if root else [])+diversified[:max(1,min(100,int(limit)))],
            'query':query,'root':root,'fingerprint':snapshot.get('graph_fingerprint'),
            'backend':'hybrid' if dense else 'text','vector_count':len(vectors),
            'total':len(diversified),'model':model}
