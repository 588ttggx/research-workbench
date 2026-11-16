"""Background refresh process for the large derived radar browse index."""
from filelock import FileLock,Timeout
import workflow as w
import research_radar
import radar_browse
from research_store import Store


def main():
    try:
        with FileLock(str(w.DATA/'.radar-browse-refresh.lock'),timeout=0):
            rules=research_radar.settings()['rules']
            signature=radar_browse.source_signature(rules)
            with radar_browse.connection() as db:
                previous=db.execute("SELECT value FROM cache_meta WHERE key='source'").fetchone()
                if previous and previous['value']==signature:
                    Store().commit_page('radar:index',[],{
                        'status':'completed','checked':w.now(),
                        'message':'提醒索引已与当前资料一致，无需重建。',
                    })
                    return 0
                before=db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0]
                radar_browse._rebuild_index(db,rules,signature)
                active=db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0]
                if before>active*2:
                    db.commit()
                    db.execute('VACUUM')
        Store().commit_page('radar:index',[],{
            'status':'completed','checked':w.now(),
            'message':'新论文提醒索引已重建，当前提醒记录 '+str(active)+' 条。',
            'active_records':active,
        })
        return 0
    except Timeout:
        return 0
    except Exception as exc:
        Store().commit_page('radar:index',[],{
            'status':'failed','error_type':type(exc).__name__,'checked':w.now()
        })
        raise


if __name__=='__main__':
    raise SystemExit(main())
