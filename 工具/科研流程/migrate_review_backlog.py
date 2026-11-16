"""Read-only backlog classification for the review redesign.

Run without --apply to write a reviewable classification receipt. With --apply
it also records the same classification in the existing SQLite cursor ledger;
it never edits Markdown, proposals, previews or scientific state.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import argparse
import json

import workflow as w
from research_store import Store

REPORT = '旧待办分类.json'
MARKER = 'change-impact:migration:20261108'


def classify(proposals,previews):
    rows=[]
    for proposal in proposals:
        kind=proposal.get('kind');status=proposal.get('status');automatic=bool(proposal.get('automatic'))
        if kind=='work_add':
            category='reference_suggestion'
        elif status=='applied':
            category='completed_auto' if proposal.get('automatic_applied') else 'completed_manual'
        elif status=='superseded':
            category='history'
        elif status in ('deferred','rejected'):
            category='history'
        elif status=='failed':
            category='exception'
        elif status in ('writing','blocked'):
            category='decision'
        elif status=='stale':
            category='observation'
        elif status in ('pending','needs_choice'):
            category='observation' if automatic else 'decision'
        else:
            category='observation'
        rows.append({'source':'change-impact','id':proposal.get('id'),'kind':kind,'status':status,
                     'automatic':automatic,'category':category,'target_id':proposal.get('target_id'),
                     'summary':proposal.get('summary') or ''})
    for proposal in previews:
        status=proposal.get('status');automatic=bool(proposal.get('automatic'))
        if status=='已采纳':category='completed_auto' if proposal.get('automatic_applied') else 'completed_manual'
        elif status=='不采纳':category='history'
        elif status=='无需修改':category='no_change'
        elif status=='待确认':category='observation' if automatic else 'decision'
        else:category='observation'
        target=proposal.get('target') or {}
        rows.append({'source':'ai-preview','id':proposal.get('id'),'kind':proposal.get('kind'),
                     'status':status,'automatic':automatic,'category':category,
                     'target_id':target.get('path') or target.get('kind'),
                     'summary':proposal.get('summary') or ''})
    rows.sort(key=lambda item:(item.get('category') or '',item.get('source') or '',item.get('id') or ''))
    return {'rows':rows,'counts':dict(Counter(item['category'] for item in rows))}


def load():
    with Store().connection() as db:
        proposals=[json.loads(row['value']) for row in db.execute(
            "SELECT value FROM cursors WHERE key LIKE 'change-impact:proposal:%'")]
    previews=[]
    for path in sorted((w.DATA/'AI修改').glob('*.json')):
        try:previews.append(json.loads(path.read_text('utf-8')))
        except (OSError,ValueError):continue
    return proposals,previews


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true',help='record the same classification in the ledger')
    args=parser.parse_args(argv)
    proposals,previews=load();result=classify(proposals,previews)
    here=w.ROOT/'output/科研工作区重构/_临时/审核分层'
    here.mkdir(parents=True,exist_ok=True)
    receipt={'created':w.now(),'apply':args.apply,'scope':'只读分类；不移动原稿、不删除预览、不改变科研状态',
             'counts':result['counts'],'rows':result['rows']}
    (here/REPORT).write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf-8')
    if args.apply:
        migrated=0
        store=Store()
        for row in result['rows']:
            if not row.get('id'):continue
            proposal=None;path=None;key=None
            if row['source']=='ai-preview':
                path=w.DATA/'AI修改'/(row['id']+'.json')
                if path.exists():
                    try:proposal=json.loads(path.read_text('utf-8'))
                    except (OSError,ValueError):continue
            elif row['source']=='change-impact':
                key='change-impact:proposal:'+row['id'];proposal=store.cursor(key,{})
            if proposal:
                proposal['migration']={'category':row['category'],'at':w.now(),'source':'migrate_review_backlog'}
                if path is not None:w.write_json(path,proposal)
                else:store.commit_page(key,[],proposal)
                migrated+=1
        marker={'revision':1,'classified_at':w.now(),'counts':result['counts'],'migrated_previews':migrated,
                'rows':[{'source':row['source'],'id':row['id'],'category':row['category']} for row in result['rows']]}
        Store().commit_page(MARKER,[],marker)
    print(json.dumps({'counts':result['counts'],'report':str(here/REPORT),'applied':args.apply},ensure_ascii=True))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
