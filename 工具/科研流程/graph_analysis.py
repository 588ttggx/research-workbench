"""Read-only semantic communities and deterministic seeds shared by both renderers.

Citation/provenance volume is excluded from topic affinity. Isolated sources use
the existing taxonomy for display grouping, without inventing scientific edges.
"""
from collections import OrderedDict, defaultdict, Counter
from copy import deepcopy
import math
import threading
import unicodedata

import networkx as nx
import workflow as w
from research_store import encode

PALETTE = ['#60c8ff', '#b99aff', '#61d7b4', '#ffc47a', '#ef8fb7', '#87baff', '#b3cf76', '#a1b0cd']
AFFINITY = {'About', 'RelatedTo', 'MethodSimilar', '涉及概念', '内容相关', '方法相近'}
_cache = OrderedDict()
_previous = {}
_lock = threading.RLock()


def fingerprint(snapshot):
    value = {'nodes': sorted(snapshot.get('nodes', []), key=lambda n: n['id']),
             'edges': sorted(snapshot.get('edges', []), key=lambda e: (e.get('id', ''), e['from'], e['to'])),
             'scope': snapshot.get('scope', {})}
    return w.digest(encode(value))


def _build(snapshot):
    graph = nx.Graph()
    graph.add_nodes_from(sorted(n['id'] for n in snapshot.get('nodes', [])))
    by_id={n['id']:n for n in snapshot.get('nodes',[])}
    seen = set();prepared=[]
    def concept_key(identifier):
        node=by_id[identifier]
        if node.get('record_kind')=='ExtractedConcept' or node.get('kind') in ('概念','ExtractedConcept'):
            return node.get('entity_type','概念')+':'+unicodedata.normalize('NFKC',node.get('label','')).casefold()
        return identifier
    for edge in sorted(snapshot.get('edges', []), key=lambda e: e.get('id', '')):
        a, b = edge.get('from'), edge.get('to')
        if (a not in graph or b not in graph or a == b or edge.get('stale')
                or edge.get('status') == 'REJECTED'
                or (edge.get('kind', edge.get('label')) not in AFFINITY and not
                    (edge.get('kind')=='AssociatedWith' and edge.get('layer')=='semantic'))):
            continue
        source = tuple(sorted({str(e.get('source_id') or e.get('id', '')) for e in edge.get('evidence', [])}))
        key = (tuple(sorted((a, b))), edge.get('kind', edge.get('label')), source)
        if key in seen:
            continue
        seen.add(key)
        logical=(tuple(sorted((concept_key(a),concept_key(b)))),edge.get('kind',edge.get('label')),source)
        prepared.append((a,b,.25 if edge.get('suggested') else 1.,logical))
    frequencies=Counter(row[3] for row in prepared)
    for a,b,weight,logical in prepared:
        weight/=frequencies[logical]
        graph.add_edge(a,b,weight=graph.get_edge_data(a,b,{}).get('weight',0)+weight)
    names=defaultdict(list)
    for node in by_id.values():
        if node.get('record_kind')!='ExtractedConcept' and node.get('kind') not in ('概念','ExtractedConcept'):continue
        name=' '.join(unicodedata.normalize('NFKC',node.get('label','')).casefold().split())
        if len(name)<2 or name in {'研究','方法','数据','结果','模型','样品','结论'}:continue
        names[(node.get('entity_type',''),name)].append(node['id'])
    # Same-name concept occurrences are a topic affinity, not an identity merge
    # or a scientific relationship. Normalisation prevents repeated pages voting.
    for members in names.values():
        members=sorted(members)
        if len(members)<2:continue
        for a,b in zip(members,members[1:]):graph.add_edge(a,b,weight=.5/max(1,len(members)-1))
    concepts=[n for n in by_id.values() if (n.get('record_kind') in ('ExtractedConcept','ExtractedClaim','Concept','Claim') or n.get('kind') in ('概念','结论','论断')) and len(n.get('label',''))>2]
    if len(concepts)>1:
        # Content retrieval supplies weak layout affinity, never persisted as
        # an identity merge, citation, or scientific relation.
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.neighbors import NearestNeighbors
        texts=[n.get('label','')+' '+n.get('summary','')[:300] for n in concepts]
        try:
            matrix=TfidfVectorizer(analyzer='char',ngram_range=(2,3),max_features=12000).fit_transform(texts)
            search=NearestNeighbors(n_neighbors=min(4,len(concepts)),metric='cosine').fit(matrix)
            for offset in range(0,len(concepts),200):
                distances,indices=search.kneighbors(matrix[offset:offset+200])
                for row,(ds,js) in enumerate(zip(distances,indices)):
                    a=concepts[offset+row]
                    for distance,index in zip(ds,js):
                        b=concepts[index]
                        if a['id']==b['id'] or distance>.55 or set(a.get('source_ids',[]))&set(b.get('source_ids',[])):continue
                        if a.get('entity_type','概念')!='概念' and b.get('entity_type','概念') not in ('概念',a.get('entity_type')):continue
                        if not graph.has_edge(a['id'],b['id']):graph.add_edge(a['id'],b['id'],weight=(1-distance)*.5)
        except ValueError:pass # No usable terms is an empty content projection.
    return graph


def _groups(snapshot, graph):
    connected = sorted(n for n, degree in graph.degree if degree)
    groups = []
    if connected:
        groups.extend(nx.community.leiden_communities(graph.subgraph(connected),
                      weight='weight', metric='modularity', resolution=1., seed=42))
    by_id = {n['id']: n for n in snapshot.get('nodes', [])}
    isolated = defaultdict(set)
    for identifier in graph:
        if graph.degree(identifier):
            continue
        node = by_id[identifier]
        topics = node.get('topics') or []
        category = ('topic:' + sorted(topics)[0]) if topics else 'unlinked:' + str(node.get('entity_type') or node.get('kind', '资料'))
        isolated[category].add(identifier)
    groups.extend(isolated.values())
    return sorted((sorted(group) for group in groups), key=lambda members: (-len(members), members))


def _identities(groups, scope_key):
    prior = _previous.get(scope_key, {})
    overlaps = sorted(((len(set(members) & set(old)), identifier, index)
                       for index, members in enumerate(groups) for identifier, old in prior.items()),
                      key=lambda x: (-x[0], x[1], x[2]))
    assigned, used = {}, set()
    for size, identifier, index in overlaps:
        if size and index not in assigned and identifier not in used:
            assigned[index] = identifier
            used.add(identifier)
    for index, members in enumerate(groups):
        if index not in assigned:
            assigned[index] = 'community:' + w.digest(members[0])[:12]
    _previous[scope_key] = {assigned[i]: members for i, members in enumerate(groups)}
    if len(_previous) > 24:
        del _previous[next(iter(_previous))]
    return assigned


def layout(snapshot, dimensions=2):
    if dimensions not in (2, 3):
        raise ValueError('布局维度必须是二维或三维。')
    signature = snapshot.get('graph_fingerprint') or fingerprint(snapshot)
    key = (str(w.DATA.resolve()), signature, dimensions)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return deepcopy(_cache[key])
        graph = _build(snapshot)
        groups = _groups(snapshot, graph)
        scope_key = (str(w.DATA.resolve()), encode(snapshot.get('scope', {})))
        ids = _identities(groups, scope_key)
        by_id = {n['id']: n for n in snapshot.get('nodes', [])}
        titles = {n['id']: n.get('title', n.get('label', n['id'])) for n in snapshot.get('topics', [])}
        positions, communities = {}, []
        total = max(1, len(groups))
        golden = math.pi * (3 - math.sqrt(5))
        for index, members in enumerate(groups):
            identifier = ids[index]
            color = PALETTE[int(w.digest(identifier)[:8], 16) % len(PALETTE)]
            concepts = [n for n in members if by_id[n].get('record_kind') == 'ExtractedConcept' or by_id[n].get('kind') in ('概念', 'ExtractedConcept')]
            topical = next((t for n in members for t in by_id[n].get('topics', []) if t in titles), None)
            ranked = sorted(concepts or members, key=lambda n: (-graph.degree(n), by_id[n].get('label', n)))
            label = ' · '.join(list(dict.fromkeys(by_id[n].get('label',n)[:24] for n in ranked))[:2])
            if not concepts and topical:
                label = titles[topical]
            elif not any(graph.degree(n) for n in members) and not concepts:
                label = '来源资料' if len(members) > 1 else by_id[members[0]].get('label', members[0])
            angle = index * golden
            radius = 0 if total == 1 else 260 * math.sqrt(index + .5)
            cy, cx, cz = radius * math.sin(angle), radius * math.cos(angle), 0.
            if dimensions == 3 and total > 1:
                z = 1 - 2 * (index + .5) / total
                spread = math.sqrt(max(0, 1 - z*z))
                cx, cy, cz = radius*spread*math.cos(angle), radius*spread*math.sin(angle), radius*z
            local_radius = max(100, 52 * math.sqrt(len(members)))
            for number, node in enumerate(members):
                theta = number * golden
                r = local_radius * math.sqrt((number + .5) / len(members))
                x, y, z = cx + r * math.cos(theta), cy + r * math.sin(theta), cz
                if dimensions == 3:
                    fraction = 1 - 2*(number+.5)/len(members)
                    spread = math.sqrt(max(0, 1-fraction*fraction))
                    x, y, z = cx+r*spread*math.cos(theta), cy+r*spread*math.sin(theta), cz+local_radius*fraction
                point = {'x': round(x, 3), 'y': round(y, 3), 'community': identifier, 'color': color}
                if dimensions == 3:
                    point['z'] = round(z, 3)
                positions[node] = point
            communities.append({'id': identifier, 'label': label, 'size': len(members), 'members': members,
                                'color': color, 'center': {'x': cx, 'y': cy, 'z': cz}})
        links={}
        for a,b,data in graph.edges(data=True):
            left,right=positions[a]['community'],positions[b]['community']
            if left==right:continue
            key=tuple(sorted((left,right)))
            if key not in links:links[key]={'id':'theme-affinity:'+':'.join(key),'from':key[0],'to':key[1],
                'kind':'ThemeAffinity','label':'主题内容相近','count':0,'weight':0,'layer':'navigation','suggested':True,
                'explanation':'主题投影的内容联系汇总；不代表引用、身份合并、支持或反驳。'}
            links[key]['count']+=1;links[key]['weight']+=data['weight']
        result = {'community_links':list(links.values()),'communities': communities, 'nodes': positions, 'algorithm': 'Leiden',
                  'dimensions': dimensions, 'scope': snapshot.get('scope', {}),
                  'stats': {'nodes': len(graph), 'edges': len(snapshot.get('edges', [])),
                            'affinity_edges': graph.number_of_edges(), 'communities': len(groups)},
                  'graph_fingerprint': signature, 'fingerprint': signature}
        _cache[key] = result
        while len(_cache) > 24:
            _cache.popitem(last=False)
        return deepcopy(result)
