"""Read-only project entrance. Graph construction is deliberately separate."""
import knowledge as k
import workflow as w
import project_materials as materials
import project_profiles as profiles
import project_tasks
from research_store import Store


def view(project):
    from project_canvas import project_overview
    base = materials.source_snapshot(project, readonly=True)
    members = materials.snapshot(project, base=base)
    references = materials.reference_scope(project, base=base, members=members)
    profile = profiles.get(project)
    summary = project_overview(project, base, members, profile)
    status = k.line_path(project, w.KB).parent/'当前课题状态.md'
    body = k.split(status.read_text('utf-8-sig'))[1].strip() if status.is_file() else ''
    import re
    sections=[]
    for match in re.finditer(r'(?m)^#{1,6}\s+(.+)$',body):
        sections.append((match.start(),match.group(1)))
    excerpts=[]
    for i,(start,title) in enumerate(sections):
        if any(word in title for word in ('判断','结论','待决定','待确认','开放问题','尚未解决')):
            excerpts.append(body[start:sections[i+1][0] if i+1<len(sections) else len(body)].strip())
    summary['brief'] = '\n\n'.join(excerpts) if excerpts else body
    decisions = []
    # 首页只做只读投影：这里不能调用 workspace_catalog.rows()/reconcile，它会把变化原稿的旧确认降级。
    import workspace_catalog
    question_titles={q['id']:q.get('title','') for q in summary.get('questions',[])}
    for node in Store().nodes(project, 'Decision'):
        if node['project']!=project:continue
        try:
            path = k.path_for(node['uri'])
            _, body, _ = k.split(path.read_text('utf-8-sig'))
            stale = w.digest(body.rstrip()) != (node['data'].get('confirmed_sha256') if node['status']=='VERIFIED' and node['data'].get('confirmed_sha256') else node['data'].get('document_sha256'))
        except (OSError, ValueError, TypeError):
            stale = True
        context=(node.get('data') or {}).get('context') or {}
        labels={}
        if context.get('question_id'):labels['question']=question_titles.get(context['question_id'],'')
        document_id=workspace_catalog.identify('科研知识库/'+node['uri'])
        with workspace_catalog.database().connection() as db:
            document=db.execute('SELECT archived FROM documents WHERE id=?',(document_id,)).fetchone()
        if document and document['archived']:continue
        decisions.append({**node, 'stale': stale, 'context': context, 'context_labels': labels,
                          'document_id':document_id})
    work=project_tasks.read(project)
    store=Store()
    with store.connection() as db:
        updates=[dict(row) for row in db.execute('SELECT event,object_id,created FROM audit WHERE object_id=? ORDER BY id DESC LIMIT 12',(project,))]
    import project_stages
    progress=project_stages.progress(project)
    return {'project': project, 'project_profile': profile, 'project_overview': summary, 'progress':progress,
            'work': work, 'decisions': decisions, 'updates':updates,
            'compatibility':{'legacy_task_ids':[r['id'] for r in work['items'] if r['legacy']],
                             'warnings':work['warnings'],'decision_drafts':sum(d['status']=='DRAFT' for d in decisions),
                             'note':'首页不会补编号、确认历史决定或迁移原稿；旧图偏好仅在主动切图后使用。'},
            'project_materials': {'documents': list(references['documents'].values()),
                                  'history': list(references['history'].values())},
            'plan_candidates':[{'id':d['id'],'title':d['display_title']} for d in members['documents'].values()],
            'papers': [{**base['papers'][i], **references['papers'][i]} for i in references['papers']],
            'nodes': [], 'groups': [], 'kinds': {}, 'statuses': []}
