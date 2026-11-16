"""Current, server-side admission of retrieval results before UI/model exposure."""
from collections import Counter
import workflow as w
import material_roles
import re


def _retrieval_documents(paths, notes):
    counts = Counter(row['note_id'] for row in notes.values() if row.get('note_id'))
    return {row['note_id']:paths[path] for path,row in notes.items()
            if path in paths and counts[row.get('note_id')] == 1}


def filter_search(result,*,scope='knowledge',project=None):
    if scope not in {'knowledge','project'}:raise ValueError('请选择知识或项目检索范围。')
    import workspace_catalog as catalog
    from project_materials import source_snapshot,snapshot,prose
    docs=catalog.rows(reconcile_records=False);allowed={d['id']:d for d in docs if material_roles.knowledge(d,global_scope=True)}
    paper_ids=None
    if scope=='project':
        if not project:raise ValueError('项目检索需要明确项目。')
        members=snapshot(project,base=source_snapshot(project,readonly=True));allowed=members['documents'];paper_ids=set(members['papers'])
    by_path={d.get('kb_path'):d for d in docs if d.get('kb_path')}
    state=w.load_state()
    remote=_retrieval_documents(by_path,state.get('notes',{}))
    library=w.read_json(w.LIBRARY,{'records':[]})['records']
    counts=Counter(p['open_notebook_source_id'] for p in library if p.get('open_notebook_source_id'))
    papers={p['open_notebook_source_id']:p for p in library
            if counts[p.get('open_notebook_source_id')]==1 and not p.get('hidden') and w.chosen_artifact(p)}
    records=[]
    for item in result.get('results',[]):
        source=item.get('parent_id') or item.get('id');doc=remote.get(source)
        if doc and doc['id'] in allowed:
            current=allowed[doc['id']]
            if current.get('stage_removed'):continue
            text=prose(current)
            records.append({'id':item.get('id',source),'parent_id':source,'document_id':current['id'],'title':current['title'],
                            'score':item.get('score'),'content':text[:1600],'text':text[:1600],'matches':[{'text':text[:1600]}]})
        elif source in papers and (paper_ids is None or papers[source]['id'] in paper_ids):
            import fulltext_parser
            sha=state.get('papers',{}).get(papers[source]['id'],{}).get('sha256','')
            if not isinstance(sha,str) or not re.fullmatch(r'[a-f0-9]{64}',sha):continue
            cached=fulltext_parser.read_cache(w.DATA/'正文'/(sha+'.json'),usable_only=True)
            if (cached.get('sha256')==sha
                    and not fulltext_parser.text_changed(state.get('papers',{}).get(papers[source]['id'],{}),cached)):
                records.append(item)
    return {**result,'results':records,'scope':scope,'project':project if scope=='project' else None}


def search_catalog(project):
    import workspace_catalog as catalog
    import knowledge_catalog
    from project_materials import source_snapshot,snapshot
    base=source_snapshot(project,readonly=True);members=snapshot(project,base=base)
    result=knowledge_catalog.catalog(include_classification=False)
    documents=list(members['documents'].values())
    paths={d.get('kb_path'):d['id'] for d in documents if d.get('kb_path')}
    return {**result,'documents':documents,'papers':[p for p in result['papers'] if p['id'] in members['papers']],
            'retrieval_documents':_retrieval_documents(paths,w.load_state().get('notes',{})),'scope':'project','project':project}
