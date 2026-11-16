"""Global read views over the original document index and recorded relations.

Browsing has no project-selection, task, model or prose-writing side effects.
"""
from collections import Counter
from pathlib import Path

import bibliography
import workflow as w
import workspace_catalog as originals
import material_roles
from research_store import Store, encode


def _profiles():
    import project_profiles
    fields=('project','title','topic','status','archived')
    return [{f:row.get(f) for f in fields} for row in project_profiles.listing()]


def _usage(documents, profiles):
    """Project the same current knowledge scope as the project directory."""
    import project_materials
    import project_knowledge
    document_usage={d['id']:[] for d in documents};paper_usage={}
    by_id={d['id']:d for d in documents};store=Store()
    for profile in profiles:
        project=profile['project'];saved=store.cursor('project-canvas:'+project,{'nodes':{},'papers':[]})
        base=project_materials.source_snapshot(project,readonly=True,documents=documents)
        selected=project_materials.selected_document_ids(project,saved=saved,base=base)
        node_ids={row.get('source',{}).get('document_id'):identifier for identifier,row in saved.get('nodes',{}).items()
                  if not row.get('deleted') and row.get('source',{}).get('kind')=='document'}
        local=set()
        for doc in documents:
            if doc.get('archived') or doc.get('visibility')=='system' or doc.get('question_id') or doc.get('canvas_include') is False:continue
            if not (w.ROOT/doc['path']).resolve().is_relative_to((w.KB/'项目'/project).resolve()):continue
            if Path(doc['path']).name in ('当前课题状态.md','研究主线.md','方向选择.md'):continue
            identifier=doc.get('canvas_node') or 'a-'+w.digest('doc:'+doc['id'])[:24]
            if saved.get('nodes',{}).get(identifier,{}).get('deleted'):continue
            local.add(doc['id']);node_ids.setdefault(doc['id'],identifier)
        entry={**profile}
        members=project_materials.snapshot(project,saved=saved,base=base)
        current,_,_=project_knowledge.current_scope(project,base,members,project_knowledge.state(project),saved.get('papers',[]))
        for doc in current:
            identifier=doc['id']
            document_usage[identifier].append({**entry,'node_id':node_ids.get(identifier),'reason':doc['knowledge_scope_reason']})
        for identifier in selected|local|{d['id'] for d in current}:
            if identifier not in by_id:continue
            # An archived document is navigation history, not current evidence.
            if not by_id[identifier].get('archived') and by_id[identifier].get('visibility')!='system':
                for paper in by_id[identifier].get('paper_ids',[]):
                    reason='正文引用' if paper in by_id[identifier].get('paper_citations',[]) else '关联论文'
                    existing=paper_usage.setdefault(paper,{}).get(project)
                    if existing is None or reason=='正文引用':
                        paper_usage[paper][project]={**entry,'reason':reason}
        for identifier in saved.get('papers',[]):paper_usage.setdefault(identifier,{})[project]={**entry,'reason':'加入项目文献池'}
        for node_id,row in saved.get('nodes',{}).items():
            source=row.get('source',{})
            if not row.get('deleted') and source.get('kind')=='paper':
                paper_usage.setdefault(source.get('paper_id'),{})[project]={**entry,'node_id':node_id,'reason':'明确选用论文节点'}
    return document_usage,{identifier:list(rows.values()) for identifier,rows in paper_usage.items()}


def _registered_papers():
    """Shared admission before optional display metadata is attached."""
    retired={r['id'] for r in Store().nodes(kind='Paper') if r['status'] in ('RETIRED','REJECTED','DELETED_AT_SOURCE')}
    from paper_evidence import registered
    return [r for r in w.read_json(w.LIBRARY,{'records':[]})['records']
            if not r.get('hidden') and r['id'] not in retired
            and r.get('status') not in ('RETIRED','REJECTED','DELETED_AT_SOURCE') and registered(r)]


def source_catalog():
    """Current extraction inputs, without display ranks, usage or classification."""
    return {'documents':[d for d in originals.rows(reconcile_records=False)
                         if material_roles.knowledge(d,global_scope=True,history=True)],
            'papers':_registered_papers()}


def catalog(*, include_classification=True):
    all_documents=originals.rows(reconcile_records=False)
    documents=[d for d in all_documents if material_roles.knowledge(d,global_scope=True,history=True)]
    profiles=_profiles();profile_map={p['project']:p for p in profiles}
    usage,paper_usage=_usage(all_documents,profiles)
    for doc in documents:
        source=doc['source_project'] if 'source_project' in doc else doc.get('project')
        if source in ('待归类',''):source=None
        doc.update(source_project=source,source_project_title=profile_map.get(source,{}).get('title',source or '来源未确定'),
                   source_project_archived=bool(profile_map.get(source,{}).get('archived')),used_by=usage.get(doc['id'],[]))
    from paper_evidence import original_availability
    records=bibliography.enriched(_registered_papers())
    from knowledge_graph import paper_display
    import journal_ranks
    ranks=journal_ranks.resolve_many(records)
    fields=('id','title','doi','pmcid','url','topic','project','reading_status','year','year_source',
            'publication_date','zotero_key','open_notebook_source_id','journal','issn')
    papers=[]
    for record in records:
        artifact = w.chosen_artifact(record)
        papers.append({**{key:record.get(key) for key in fields},'display_title':paper_display(record)['label'],
                       'documents':[{'id':d['id'],'title':d['title'],'kind':d['kind']} for d in documents
                                    if record['id'] in d.get('paper_ids',[]) and not d['archived'] and d['visibility']!='system'],
                       'has_original':bool(artifact),'original_kind':(artifact or {}).get('kind'),
                       'availability':original_availability(record),
                       'journal_ranks':ranks.get(record['id']),'used_by':paper_usage.get(record['id'],[])})
    by_path={doc['kb_path']:doc['id'] for doc in documents if doc.get('kb_path')}
    retrieval={value['note_id']:by_path[path] for path,value in w.load_state().get('notes',{}).items()
               if path in by_path and value.get('note_id')}
    result={'documents':documents,'papers':papers,'project_profiles':profiles,'retrieval_documents':retrieval,
            'catalog_issues':originals.scan_issues(),
            'relation_types':__import__('relation_schema').definitions(),
            'counts':dict(Counter(d['kind'] for d in documents if not d['archived'] and d['visibility']!='system'))}
    if include_classification:
        result['classification']=__import__('workspace_navigation').global_view(result)
    result['fingerprint']=w.digest(encode({'documents':documents,'papers':papers,'profiles':profiles,
                                          'classification':result.get('classification',{}).get('fingerprint')}))
    return result


def _relation_inputs(relations, docs, papers, store):
    """Validate only recorded evidence IDs against existing immutable snapshots."""
    from relation_discovery import document_input, paper_input, managed
    requested={e.get('id') for edge in relations if managed(edge) for e in edge['evidence']}
    result={}
    with store.connection() as db:
        for doc in docs:
            identifier=doc.get('record_id') or doc['id']
            if identifier not in requested or doc['archived'] or doc['visibility']=='system':continue
            snapshot=db.execute('SELECT body FROM document_source_snapshots WHERE document=? AND sha=?',(doc['id'],doc['sha'])).fetchone()
            if snapshot and w.digest(snapshot['body'].rstrip())==doc['sha']:
                item=document_input(doc,snapshot['body'])
                if item:result[identifier]=item
    active={p['id'] for p in papers}&requested
    if active:
        state=w.load_state()
        for record in w.read_json(w.LIBRARY,{'records':[]})['records']:
            if record['id'] in active:result[record['id']]=paper_input(record,state)
    return result


def graph(*, catalog_snapshot=None, include_history=False, scope=None):
    snapshot=catalog_snapshot if catalog_snapshot is not None else catalog()
    docs=[d for d in snapshot['documents'] if material_roles.knowledge(d,global_scope=True,history=include_history)]
    papers=snapshot['papers'];nodes={};aliases={};edges=[];seen=set()
    for doc in docs:
        identifier='doc:'+doc['id']
        nodes[identifier]={'id':identifier,'doc_id':doc['id'],'record_id':doc.get('record_id'),'label':doc.get('display_title') or doc['title'],
                           'kind':doc['kind'],'record_kind':doc.get('record_type'),'semantic_kind':doc.get('record_type'),'path':doc.get('kb_path') or doc['path'],'status':doc['status'],
                           'summary':doc.get('excerpt',''),'archived':doc['archived'],'visibility':doc['visibility'],
                           'source_project':doc.get('source_project'),'used_by':doc.get('used_by',[])}
        for alias in (doc['id'],doc.get('record_id'),doc['path'],doc.get('kb_path')):
            if alias:aliases[alias]=identifier
    for paper in papers:
        identifier='paper:'+paper['id'];aliases[paper['id']]=identifier
        nodes[identifier]={'id':identifier,'paper_id':paper['id'],'label':paper.get('display_title') or paper['title'],
                           'kind':'论文','status':paper.get('reading_status') or '阅读范围待核查','summary':paper['title'],
                           'source_project':paper.get('project'), 'has_original':paper.get('has_original'),
                           'availability':paper.get('availability')}
    store=Store()
    stored_nodes={record['id']:record for record in store.nodes()}
    for record in stored_nodes.values():
        # A projection points at its source URI but keeps its own identity.
        # Only canonical manuscript/application records may alias to a source.
        if record['owner']=='KnowledgeExtraction' or record['kind'] in ('ExtractedConcept','ExtractedClaim'):continue
        if record['status'] in ('RETIRED','REJECTED','DELETED_AT_SOURCE'):continue
        alias=aliases.get(record['id']) or aliases.get(record.get('uri')) or aliases.get(record['data'].get('doc_id'))
        if alias:
            aliases[record['id']]=alias;nodes[alias].update(record_id=record['id'],uri=record.get('uri'),owner=record['owner'])
    def add(edge):
        source=aliases.get(edge['from'],edge['from']);target=aliases.get(edge['to'],edge['to'])
        marker=(source,target,edge['label'],edge.get('suggested',False))
        if source==target or source not in nodes or target not in nodes or marker in seen:return
        seen.add(marker);edges.append({**edge,'from':source,'to':target})
    for doc in docs:
        for reference in doc.get('references',[]):
            add({'id':'reference:'+doc['id']+':'+reference['id'],'from':doc['id'],'to':reference['id'],
                 'label':'正文引用','source':'原稿中的明确链接','changed':reference.get('changed',False),
                 'explanation':'资料导航关系；科研支持关系需要单独核查。'})
        for paper in doc.get('paper_ids',[]):
            add({'id':'paper-doc:'+doc['id']+':'+paper,'from':doc['id'],'to':'paper:'+paper,
                 'label':'关联论文','kind':'AssociatedWith','layer':'provenance','source':'已登记文献 ID',
                 'explanation':'资料中登记的论文关联；不能单凭登记断言正文引用或科研支持。'})
    from relation_discovery import current_candidate, managed, stale
    from relation_schema import RELATIONS
    relations=store.relations()
    current=_relation_inputs(relations,docs,papers,store)
    for relation in relations:
        if any(e.get('generator','').startswith(('knowledge-extraction-','knowledge-comparison-')) for e in relation['evidence']):continue
        if not current_candidate(relation) or relation.get('stale') or managed(relation) and stale(relation,current):continue
        add({'id':relation['id'],'from':relation['source'],'to':relation['target'],
             'label':RELATIONS.get(relation['kind'],{}).get('label',relation['kind']),
             'kind':relation['kind'],'status':relation['status'],'revision':relation['revision'],
             'source':'AI 内容分析' if any(e.get('generator') for e in relation['evidence']) else '关系账本',
             'evidence':relation['evidence'],'explanation':relation['conditions'],
             'suggested':relation['status']!='VERIFIED'})
    import knowledge_extraction
    extracted=knowledge_extraction.project(snapshot)
    for node in extracted['nodes']:
        nodes[node['id']]={**node,'extracted':True,'semantic_kind':node.get('record_kind'),
                           'source_refs':node.get('evidence',[])}
    for edge in extracted['edges']:add(edge)
    manual_relations=[r for r in relations if r['kind']=='DerivedFrom' and stored_nodes.get(r['source'],{}).get('owner')=='Markdown' and stored_nodes.get(r['source'],{}).get('kind') in ('Claim','Concept') and any(e.get('generator')==knowledge_extraction.VERSION for e in r['evidence'])]
    source_versions=knowledge_extraction.sources(snapshot) if manual_relations else {}
    for relation in manual_relations:
        if relation['kind']!='DerivedFrom' or relation['status']=='REJECTED':continue
        if not any(e.get('generator')==knowledge_extraction.VERSION for e in relation['evidence']):continue
        source=stored_nodes.get(relation['source'])
        if not source or source['owner']!='Markdown' or source['kind'] not in ('Claim','Concept'):continue
        stale=any(e.get('source_sha256') and source_versions.get(e.get('id'),{}).get('source_sha256')!=e['source_sha256'] for e in relation['evidence'])
        add({'id':relation['id'],'from':relation['source'],'to':relation['target'],'kind':'DerivedFrom',
             'label':'知识稿出处','layer':'provenance','status':relation['status'],'revision':relation['revision'],
             'suggested':False,'stale':stale,'evidence':relation['evidence'],'explanation':relation['conditions'],'source':'本人提炼知识稿'})
    for edge in __import__('knowledge_comparison').project(extracted['nodes'],store):add(edge)
    from knowledge_scene import apply_scope,query_scope
    selection=scope or query_scope({'include_history':['1' if include_history else '0']})
    return apply_scope({'nodes':list(nodes.values()),'edges':edges,'extraction_counts':extracted['counts']},snapshot,selection)
