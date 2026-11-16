"""One-way, verified migration from the legacy candidate JSON to SQLite state."""
from contextlib import contextmanager
import gzip
import hashlib
import json
import os
from pathlib import Path
from filelock import FileLock
import workflow as w
from research_store import Store


@contextmanager
def _candidate_lock():
    w.DATA.mkdir(parents=True,exist_ok=True)
    with FileLock(str(w.DATA/'.radar-candidates.lock'),timeout=30):yield


def migrate_legacy_candidates():
    """Archive the full legacy JSON, import only durable overlays, then rebuild.

    Candidate metadata already exists in Seen. Selected/acquisition/workspace
    state and source rows absent from Seen are copied into radar_candidate_state.
    The original full JSON is retained as a verified gzip archive.
    """
    import radar_inbox
    import radar_browse
    import research_radar
    path=w.DATA/'candidates.json'
    if not path.exists():
        return {'status':'not_needed','message':'候选主数据已由 SQLite 管理'}
    with _candidate_lock():
        raw=path.read_bytes()
        data=json.loads(raw.decode('utf-8'))
        records=data.get('records',[])
        store=Store()
        seen_ids={radar_inbox.candidate_identity(row) for row in
                  radar_inbox.merged(store.seen())}
        imported=0;missing=0
        for row in records:
            identity=radar_inbox.candidate_identity(row)
            if not identity:continue
            state={}
            for key in ('collection','acquisition','workspace_id','workspace_record'):
                if row.get(key) not in (None,'',[],{}):state[key]=row[key]
            if row.get('selected') is True:state['selected']=True
            if identity not in seen_ids:
                state['legacy_record']=row
                missing+=1
            if state:
                store.update_radar_candidate_state(identity,state)
                imported+=1
        archive_dir=w.DATA/'归档'/'文献雷达'
        archive_dir.mkdir(parents=True,exist_ok=True)
        checksum=hashlib.sha256(raw).hexdigest()
        archive=archive_dir/f'candidates-20261031-{checksum[:12]}.json.gz'
        if not archive.exists():
            with archive.open('wb') as destination:
                with gzip.GzipFile(filename='',mode='wb',fileobj=destination,mtime=0) as target:
                    target.write(raw)
        with gzip.open(archive,'rb') as source:
            digest=hashlib.sha256()
            for chunk in iter(lambda:source.read(1024*1024),b''):digest.update(chunk)
        if digest.hexdigest()!=checksum:
            raise RuntimeError('候选归档校验失败，原 JSON 未移动')
        retired=path.with_name(path.name+'.migrating')
        if retired.exists():retired.unlink()
        os.replace(path,retired)
        try:
            rules=research_radar.settings()['rules']
            signature=radar_browse.source_signature(rules)
            with radar_browse.connection() as db:
                radar_browse._rebuild_index(db,rules,signature)
        except Exception:
            os.replace(retired,path)
            raise
        retired.unlink()
        store.commit_page('radar:storage-migration',[],{
            'status':'completed','from':'candidates.json','archive':str(archive),
            'original_sha256':checksum,'records':len(records),'state_rows':imported,
            'legacy_only_rows':missing,'checked':w.now(),
        })
        return {'status':'completed','archive':str(archive),'sha256':checksum,
                'records':len(records),'state_rows':imported,
                'legacy_only_rows':missing}


if __name__=='__main__':
    print(json.dumps(migrate_legacy_candidates(),ensure_ascii=False))
