"""One scope and identity projection for the knowledge graph and both layouts."""
from collections import Counter
from copy import deepcopy
from collections import OrderedDict
from pathlib import Path
import threading
import workflow as w
from research_store import encode

_snapshots=OrderedDict()
_catalogs=OrderedDict()
_snapshot_lock=threading.RLock()

def _stamp():
    paths=[]
    for folder in (w.KB,w.ROOT/'output',w.ROOT/'research'):
        if folder.exists():paths.extend(p for p in folder.rglob('*.md') if not {'_临时','node_modules','.git'}&set(p.parts))
    if w.DATA.exists():paths.extend(w.DATA.glob('*.json'));paths.extend(w.DATA.glob('*.sqlite3*'));paths.extend((w.DATA/'正文').glob('*.json'))
    paths.append(w.LIBRARY)
    for record in w.read_json(w.LIBRARY,{'records':[]}).get('records',[]):
        paths.extend(Path(a['path']) for a in record.get('artifacts',[]) if a.get('path'))
    rows=[]
    for path in set(paths):
        try:
            stat=path.stat();rows.append((str(path),stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns))
        except OSError:rows.append((str(path),None))
    return str(w.DATA.resolve()),tuple(sorted(rows))

import graph_analysis
import material_roles


class SceneConflict(ValueError):
    pass


def query_scope(query):
    def value(name, default=''):
        row = query.get(name, [default])
        result = row[0] if isinstance(row, list) else row
        if not isinstance(result, str) or len(result) > 200:
            raise ValueError('知识图筛选格式无效。')
        return result
    view = value('view', 'knowledge')
    if view not in ('knowledge', 'materials'):
        raise ValueError('知识图视图不存在。')
    history = value('include_history', '0')
    candidates = value('include_candidates', '1')
    if history not in ('0', '1') or candidates not in ('0', '1'):
        raise ValueError('知识图范围格式无效。')
    return {'view': view, 'include_history': history == '1', 'include_candidates': candidates == '1',
            **{key: value(key) for key in ('source_project', 'topic', 'purpose', 'kind')}}


def apply_scope(snapshot, catalog, scope=None):
    scope = scope or query_scope({})
    classification = catalog.get('classification', {})
    assignments = classification.get('assignments', {})
    topics = classification.get('nodes', [])
    descendants = {scope['topic']} if scope.get('topic') else set()
    while descendants:
        expanded = descendants | {n['id'] for n in topics if n.get('parent') in descendants}
        if expanded == descendants:
            break
        descendants = expanded
    nodes = deepcopy(snapshot['nodes'])
    source_aliases, allowed, by_id = {}, set(), {}
    for node in nodes:
        by_id[node['id']] = node
        if node.get('extracted'):
            continue
        assignment = assignments.get(node['id'], assignments.get(node.get('doc_id'), {}))
        node['topics'] = assignment.get('topics', node.get('topics', []))
        node['purpose'] = assignment.get('usage', '')
        for key in (node['id'], node.get('doc_id'), node.get('paper_id'), node.get('record_id')):
            if key:
                source_aliases[key] = node['id']
        if scope.get('source_project') and node.get('source_project') != scope['source_project']:
            continue
        if descendants and not descendants.intersection(node['topics']):
            continue
        if scope.get('purpose') and scope['purpose'] != node['purpose']:
            continue
        if scope.get('kind') and scope['kind'] not in ('概念', '结论', 'ExtractedConcept', 'ExtractedClaim') and node['kind'] != scope['kind']:
            continue
        allowed.add(node['id'])
    for node in nodes:
        if not node.get('extracted'):
            continue
        sources = [source_aliases.get(identifier) for identifier in node.get('source_ids', [])]
        sources = [identifier for identifier in sources if identifier in allowed]
        if not sources or (not scope['include_candidates'] and node.get('suggested')):
            continue
        if scope.get('kind') in ('概念', '结论', 'ExtractedConcept', 'ExtractedClaim') and scope['kind'] not in (node['kind'], node.get('record_kind')):
            continue
        node['source_project'] = by_id[sources[0]].get('source_project')
        node['topics'] = sorted({topic for identifier in sources for topic in by_id[identifier].get('topics', [])})
        allowed.add(node['id'])
    rows = sorted((node for node in nodes if node['id'] in allowed), key=lambda n: n['id'])
    edges = sorted((edge for edge in snapshot['edges'] if edge['from'] in allowed and edge['to'] in allowed
                    and (scope['include_candidates'] or not edge.get('suggested'))), key=lambda e: e['id'])
    result = {**snapshot, 'nodes': rows, 'edges': edges, 'scope': scope,
              'admission_version': material_roles.RULES_VERSION,
              'topics': [t for t in topics if t.get('dimension') == 'topic'],
              'stats': {'nodes': len(rows), 'edges': len(edges),
                        'types': dict(Counter(n['kind'] for n in rows)),
                        'candidates': sum(bool(n.get('suggested')) for n in rows)}}
    result['graph_fingerprint'] = graph_analysis.fingerprint(result)
    result['fingerprint'] = result['graph_fingerprint']
    return result


def read(query):
    import knowledge_catalog
    scope = query_scope(query)
    with _snapshot_lock:
        signature=(material_roles.RULES_VERSION,_stamp());key=(encode(scope),signature)
        if key in _snapshots:return deepcopy(_snapshots[key])
        catalog=_catalogs.get(signature)
        if catalog is None:
            catalog=knowledge_catalog.catalog();_catalogs[(material_roles.RULES_VERSION,_stamp())]=catalog
            while len(_catalogs)>2:_catalogs.popitem(last=False)
        result=knowledge_catalog.graph(catalog_snapshot=catalog,include_history=scope['include_history'],scope=scope)
        # Catalog reconciliation can update its index; stamp the completed read.
        key=(encode(scope),(material_roles.RULES_VERSION,_stamp()));_snapshots[key]=result
        while len(_snapshots)>8:_snapshots.popitem(last=False)
        return deepcopy(result)


def layout(query):
    snapshot = read(query)
    expected = query.get('fingerprint', [''])
    expected = expected[0] if isinstance(expected, list) else expected
    if expected and expected != snapshot['graph_fingerprint']:
        raise SceneConflict('资料或筛选范围已变化，正在重新读取知识图。')
    dimensions = query.get('dimensions', ['2'])
    dimensions = dimensions[0] if isinstance(dimensions, list) else dimensions
    if dimensions not in ('2', '3'):
        raise ValueError('布局维度无效。')
    return graph_analysis.layout(snapshot, dimensions=int(dimensions))


def explore(query):
    """One admitted scope for semantic map neighborhoods and query selection."""
    import knowledge_exploration
    snapshot=read(query)
    def value(name):
        result=query.get(name,['']);result=result[0] if isinstance(result,list) else result
        if not isinstance(result,str) or len(result)>500:raise ValueError('知识检索格式无效。')
        return result
    expected=value('fingerprint')
    if expected and expected!=snapshot['graph_fingerprint']:raise SceneConflict('知识范围已变化，请重新检索。')
    text=value('q').strip();root=value('root')
    if text or root:return knowledge_exploration.search(snapshot,text,root)
    result=knowledge_exploration.index(snapshot)
    return {**result,'fingerprint':snapshot['graph_fingerprint'],'scope':snapshot['scope']}
