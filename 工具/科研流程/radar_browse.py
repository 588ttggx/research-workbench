"""Rebuildable SQLite browsing index; original discovery metadata stays untouched."""
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import workflow as w
from research_store import Store,RADAR_HANDLED_DECISIONS

LOCK=threading.RLock()
REFRESHING=threading.Event()
PUBLIC_FIELDS=('source','sources','external_id','openalex_id','wos_id','doi','title','abstract','url','journal','venue','year','publication_date','first_seen','last_seen','discovered','priority','ai_relevance','issn','project','selected','collection','acquisition','workspace_id','watch_ids','watch_id','query','keywords')
TZ=timezone(timedelta(hours=8))
REMINDER_LIMITS=(5,10,20,50,100)
DEFAULT_REMINDER_LIMIT=10


def reminder_preferences():
    value=Store().cursor('radar:preferences',{}) or {}
    limit=value.get('reminder_limit')
    if type(limit) is not int or limit not in REMINDER_LIMITS:
        limit=DEFAULT_REMINDER_LIMIT
    return {'reminder_limit':limit}


def save_reminder_preferences(values):
    if not isinstance(values,dict):raise ValueError('提醒设置格式无效。')
    limit=values.get('reminder_limit')
    if type(limit) is not int or limit not in REMINDER_LIMITS:
        raise ValueError('每日提醒篇数只能选择 5、10、20、50 或 100 篇。')
    result={'reminder_limit':limit}
    Store().commit_page('radar:preferences',[],result)
    return result


@contextmanager
def connection():
    w.DATA.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(w.DATA/'radar_browse.sqlite3',timeout=30)
    db.row_factory=sqlite3.Row
    # 分页排序的临时结果放内存，不依赖系统 TEMP 是否可写。
    db.execute('PRAGMA temp_store=MEMORY')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA busy_timeout=30000')
    try:
        db.executescript('''CREATE TABLE IF NOT EXISTS cache_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS candidates(position INTEGER PRIMARY KEY,band TEXT NOT NULL,selected INTEGER NOT NULL,search TEXT NOT NULL,data TEXT NOT NULL,identity TEXT,tier TEXT NOT NULL DEFAULT 'noise');
            CREATE INDEX IF NOT EXISTS candidate_scope ON candidates(selected,tier,position);''')
        columns={row[1] for row in db.execute('PRAGMA table_info(candidates)')}
        if 'identity' not in columns:db.execute('ALTER TABLE candidates ADD COLUMN identity TEXT')
        if 'tier' not in columns:db.execute("ALTER TABLE candidates ADD COLUMN tier TEXT NOT NULL DEFAULT 'noise'")
        with db:yield db
    finally:db.close()


def source_signature(rules):
    import research_radar
    policy=research_radar.reminder_policy()
    path=w.DATA/'candidates.json'
    ai=Store().cursor('radar:relevance',{})
    if path.exists():
        stamp=path.stat()
        source={'kind':'legacy-json','path':str(path.resolve()),'mtime':stamp.st_mtime_ns,'size':stamp.st_size}
    else:
        source={'kind':'sqlite','state':Store().radar_source_signature()}
    source_rules=[{key:value for key,value in rule.items() if key!='reading_enabled'} for rule in rules]
    return json.dumps({'version':19,'source':source,'rules':source_rules,'policy':policy,'ai_checked':ai.get('checked')},
                      sort_keys=True,ensure_ascii=False)


def _rebuild_index(db,rules,signature):
    import radar_inbox
    material=radar_inbox.snapshot()['records']
    store=Store()
    relevance=store.radar_relevance()
    decisions=store.radar_decisions()
    policy=__import__('research_radar').reminder_policy()
    rows=radar_inbox.reviewable(radar_inbox.merged(material),rules,decisions,
                                recent_days=policy['recent_days'],
                                background_days=policy['background_days'],relevance=relevance)
    db.execute('SAVEPOINT rebuild_candidates')
    try:
        db.execute('DELETE FROM candidates');values=[]
        for index,row in enumerate(rows):
            public={key:row[key] for key in PUBLIC_FIELDS if key in row}
            search=' '.join(str(row.get(key) or '') for key in (
                'title','abstract','doi','source','external_id','openalex_id','journal','venue',
                'publication_date')).casefold()
            values.append((index,row['priority']['band'],bool(row.get('selected')),search,
                           json.dumps(public,ensure_ascii=False),
                           radar_inbox.candidate_identity(row),
                           row['priority'].get('tier','noise')))
            if len(values)>=200:
                db.executemany('INSERT INTO candidates VALUES(?,?,?,?,?,?,?)',values);values=[]
        if values:db.executemany('INSERT INTO candidates VALUES(?,?,?,?,?,?,?)',values)
        if source_signature(rules)!=signature:raise ValueError('雷达资料刚有更新，请重新读取；旧索引与选用保留。')
        db.execute("INSERT INTO cache_meta VALUES('source',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(signature,))
        db.execute('RELEASE rebuild_candidates')
    except Exception:
        db.execute('ROLLBACK TO rebuild_candidates');db.execute('RELEASE rebuild_candidates');raise
    store.commit_page('radar:index',[],{
        'status':'completed','checked':w.now(),'active_records':len(rows),
        'message':'新论文提醒索引已重建，当前提醒记录 '+str(len(rows))+' 条。',
    })


def _reconcile_receipt(db):
    """Keep the visible index receipt equal to the index actually served."""
    count=db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0]
    store=Store();receipt=store.cursor('radar:index',{})
    if receipt.get('status')=='completed' and receipt.get('active_records')==count:return
    store.commit_page('radar:index',[],{
        'status':'completed','checked':w.now(),'active_records':count,'reconciled':True,
        'message':'新论文提醒索引已与当前资料一致，当前提醒记录 '+str(count)+' 条。',
    })


def _background_rebuild(rules,signature):
    process=None
    try:
        w.DATA.mkdir(parents=True,exist_ok=True)
        with (w.DATA/'radar-refresh.log').open('a',encoding='utf-8') as log:
            process=subprocess.Popen(
                [sys.executable,'-m','radar_refresh'],
                cwd=str(Path(__file__).resolve().parent),
                stdout=log,
                stderr=log,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),
            )
            returncode=process.wait(timeout=300)
        if returncode:
            Store().commit_page('radar:index',[],{
                'status':'failed','error_type':'ChildProcessError',
                'exit_code':returncode,'checked':w.now(),
                'message':'后台索引子进程异常退出；旧索引继续服务。',
            })
    except subprocess.TimeoutExpired as exc:
        if process and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill()
        Store().commit_page('radar:index',[],{
            'status':'failed','error_type':type(exc).__name__,'checked':w.now(),
            'message':'后台索引刷新超时；旧索引继续服务。',
        })
    except Exception as exc:
        # Keep serving the last complete cache and expose the launch failure.
        Store().commit_page('radar:index',[],{
            'status':'failed','error_type':type(exc).__name__,'checked':w.now(),
            'message':'后台索引未能启动；旧索引继续服务。',
        })
    finally:
        REFRESHING.clear()


def ensure_index(db,rules):
    signature=source_signature(rules)
    previous=db.execute("SELECT value FROM cache_meta WHERE key='source'").fetchone()
    if previous and previous['value']==signature:
        _reconcile_receipt(db)
        return 'ready'
    indexed=db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0]
    if previous and indexed>5000:
        if not REFRESHING.is_set():
            REFRESHING.set()
            Store().commit_page('radar:index',[],{
                'status':'running','started':w.now(),
                'message':'大型浏览索引正在后台重建；旧索引继续服务。',
            })
            threading.Thread(target=_background_rebuild,
                             args=(rules,signature),daemon=True).start()
        return 'refreshing'
    _rebuild_index(db,rules,signature)
    return 'ready'


def page(*,scope='direct',offset=0,limit=30,q='',include_read=False,days=None,tier=None,source=None,reminder_limit=None,rank_system='CAS',rank_quartile=''):
    aliases={'focus':'direct','supplementary':'background'}
    scope=aliases.get(scope,scope)
    if scope not in ('direct','adjacent','background','pending','noise','supplementary','later','queue','archive','new','recent','updates','reading'):
        raise ValueError('雷达范围无效。')
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:raise ValueError('每页 1–100 条，页位置不能为负数。')
    if not isinstance(q,str) or len(q)>500 or type(include_read) is not bool:raise ValueError('雷达筛选无效。')
    if days not in (None,7,30,90,365) or tier not in (None,'direct','adjacent','background','pending','noise'):
        raise ValueError('雷达时间或层级筛选无效。')
    preferences=reminder_preferences()
    if rank_system not in ('CAS','JCR') or rank_quartile not in ('','1','2','3','4','unknown'):raise ValueError('分区筛选无效。')
    if reminder_limit is None:reminder_limit=preferences['reminder_limit']
    if type(reminder_limit) is not int or reminder_limit not in REMINDER_LIMITS:
        raise ValueError('每日提醒篇数只能选择 5、10、20、50 或 100 篇。')
    if source not in (None,'WoS','OpenAlex','Crossref','本机待全文题录') or (source is not None and (not isinstance(source,str) or len(source)>50)):
        raise ValueError('雷达来源筛选无效。')
    if scope=='reading':
        return __import__('radar_reading').page(offset=offset,limit=limit,q=q,source=source,
            rank_system=rank_system,rank_quartile=rank_quartile)
    import research_radar
    import journal_ranks
    search=q.strip().casefold().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
    store=Store()
    decisions=store.radar_decisions()
    with LOCK,connection() as db:
        index_status=ensure_index(db,research_radar.settings()['rules'])
        counts={key:0 for key in ('direct','adjacent','background','pending','noise','later','queue','archive')}
        excluded=[identity for identity,item in decisions.items() if item.get('decision') in RADAR_HANDLED_DECISIONS]
        normal_where='selected=0'
        normal_params=[]
        cutoff=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat() if days is not None else None
        if cutoff:
            normal_where+=" AND datetime(COALESCE(json_extract(data,'$.first_seen'),json_extract(data,'$.discovered')))>=datetime(?)"
            normal_params.append(cutoff)
        if excluded:
            normal_where+=' AND identity NOT IN ('+','.join('?' for _ in excluded)+')'
            normal_params.extend(excluded)
        for row in db.execute('SELECT tier,COUNT(*) AS n FROM candidates WHERE '+normal_where+' GROUP BY tier',normal_params):
            counts[row['tier'] or 'noise']=row['n']
        counts['queue']=db.execute('SELECT COUNT(*) FROM candidates WHERE selected=1').fetchone()[0]
        handled_ids=list(decisions)
        if handled_ids:
            marks=','.join('?' for _ in handled_ids)
            counts['archive']=db.execute(
                'SELECT COUNT(*) FROM candidates WHERE selected=0 AND identity IN ('+marks+')',
                handled_ids).fetchone()[0]
        later_ids=[identity for identity,item in decisions.items() if item.get('decision')=='later']
        if later_ids:
            counts['later']=db.execute('SELECT COUNT(*) FROM candidates WHERE selected=0 AND identity IN ('+
                                       ','.join('?' for _ in later_ids)+')',later_ids).fetchone()[0]
        start=datetime.now(TZ).replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc).isoformat()
        # "New" is based only on the first observation. Re-scanning an old
        # record updates discovered/last_seen but must not replay it tomorrow.
        new_where="selected=0 AND datetime(json_extract(data,'$.first_seen'))>=datetime(?)"
        new_params=[start]
        if excluded:
            new_where+=' AND identity NOT IN ('+','.join('?' for _ in excluded)+')'
            new_params.extend(excluded)
        new_where+=" AND tier IN ('direct','adjacent')"
        today_counts={key:0 for key in ('direct','adjacent')}
        for row in db.execute('SELECT tier,COUNT(*) AS n FROM candidates WHERE '+new_where+' GROUP BY tier',new_params):
            today_counts[row['tier']]=row['n']
        if tier:
            new_where+=' AND tier=?';new_params.append(tier)
        counts['new']=min(today_counts['direct']+min(5,today_counts['adjacent']),reminder_limit)
        params=[]
        if scope=='new':
            where=new_where;params=new_params
        elif scope=='later':
            ids=[identity for identity,item in decisions.items() if item.get('decision')=='later']
            where='selected=0 AND identity IN ('+','.join('?' for _ in ids)+')' if ids else '0'
            params=ids
        elif scope=='queue':
            where='selected=1'
        elif scope=='recent':
            where=normal_where+" AND tier IN ('direct','adjacent')";params=list(normal_params)
        elif scope=='archive':
            ids=list(decisions)
            where='selected=0 AND identity IN ('+','.join('?' for _ in ids)+')' if ids else '0'
            params=ids
        elif scope=='supplementary':
            where="selected=0 AND tier='background'"
            if excluded:
                where+=' AND identity NOT IN ('+','.join('?' for _ in excluded)+')'
                params.extend(excluded)
        elif tier=='noise' or scope=='noise':
            where='0'
        else:
            where='selected=0 AND tier=?'
            params=[tier or scope]
            if excluded:
                where+=' AND identity NOT IN ('+','.join('?' for _ in excluded)+')'
                params.extend(excluded)
        if cutoff and scope not in ('updates','queue','later','archive'):
            where+=" AND datetime(COALESCE(json_extract(data,'$.first_seen'),json_extract(data,'$.discovered')))>=datetime(?)"
            params.append(cutoff)
        if source and scope!='updates':
            where+=" AND json_extract(data,'$.source')=?"
            params.append(source)
        if search:where+=" AND search LIKE ? ESCAPE '\\'";params.append('%'+search+'%')
        if rank_quartile and scope!='updates':
            # Resolve each distinct ISSN list once, before pagination and counts.
            values=[row[0] for row in db.execute("SELECT DISTINCT COALESCE(json_extract(data,'$.issn'),'[]') FROM candidates WHERE "+where,params)]
            rank_records=[{'id':str(i),'issn':json.loads(value)} for i,value in enumerate(values)]
            resolved=journal_ranks.resolve_many(rank_records)
            accepted=[value for i,value in enumerate(values) if journal_ranks.matches_filter(resolved.get(str(i)),rank_system,rank_quartile)]
            if accepted:
                where+=" AND COALESCE(json_extract(data,'$.issn'),'[]') IN ("+','.join('?' for _ in accepted)+')';params.extend(accepted)
            else:where+=' AND 0'
        if scope in ('new','recent'):
            # Only a small method reference shelf is included in the main feed.
            method_where=where;method_params=list(params)
            where+=" AND (tier!='adjacent' OR position IN (SELECT position FROM candidates WHERE "+method_where+" AND tier='adjacent' ORDER BY position LIMIT 5))"
            params.extend(method_params)
        if scope=='new':
            total=min(reminder_limit,db.execute('SELECT COUNT(*) FROM candidates WHERE '+where,params).fetchone()[0])
        else:
            total=db.execute('SELECT COUNT(*) FROM candidates WHERE '+where,params).fetchone()[0] if scope!='updates' else 0
        candidate_limit=min(limit,max(0,reminder_limit-offset)) if scope=='new' else limit
        candidates=[{**json.loads(row['data']),'id':row['identity'],
                     'decision':(decisions.get(row['identity']) or {}).get('decision','new'),
                     'decision_reason_code':(decisions.get(row['identity']) or {}).get('reason_code',''),
                     'decision_reason':(decisions.get(row['identity']) or {}).get('reason','')}
                    for row in db.execute('SELECT identity,data FROM candidates WHERE '+where+' ORDER BY position LIMIT ? OFFSET ?',[*params,candidate_limit,offset])] if scope!='updates' else []
    ranks=journal_ranks.resolve_many([{**row,'id':str(index)} for index,row in enumerate(candidates)])
    candidates=[{**row,'journal_ranks':ranks.get(str(index))} for index,row in enumerate(candidates)]
    alerts=[]
    with store.connection() as db:
        counts['updates']=db.execute('SELECT COUNT(*) FROM radar_alerts WHERE acknowledged IS NULL').fetchone()[0]
        if scope=='updates':
            where='1=1' if include_read else 'acknowledged IS NULL';params=[]
            if search:
                where+=" AND lower(COALESCE(json_extract(data,'$.title'),'') || ' ' || COALESCE(json_extract(data,'$.doi'),'') || ' ' || source) LIKE ? ESCAPE '\\'";params.append('%'+search+'%')
            total=db.execute('SELECT COUNT(*) FROM radar_alerts WHERE '+where,params).fetchone()[0]
            alerts=[{**json.loads(row['data']),'id':row['id'],'created':row['created'],'acknowledged':row['acknowledged']} for row in db.execute('SELECT * FROM radar_alerts WHERE '+where+' ORDER BY created DESC,id LIMIT ? OFFSET ?',[*params,limit,offset])]
    from dashboard import n8n_owns_schedule
    counts['focus']=counts['direct']+counts['adjacent']
    counts['recent_visible']=counts['direct']+min(5,counts['adjacent'])
    counts['supplementary']=counts['background']
    return {'candidates':candidates,'alerts':alerts,
            'today_counts':today_counts,
            'counts':{key:counts.get(key,0) for key in (
                'direct','adjacent','background','pending','noise','later','queue','archive','new','updates','focus','recent_visible','supplementary')},
            'total':total,'offset':offset,'limit':limit,'has_more':offset+limit<total,
            'reminder_limit':reminder_limit,'preferences':preferences,
            'index_status':index_status,
            'feedback':store.radar_decision_insights(),
            'weekly':__import__('weekly_brief').status(store),'scheduler':'n8n' if n8n_owns_schedule('discover') else 'local_fallback','last_attempt':store.cursor('radar:last_attempt',{}),'last_success':store.cursor('radar:last_success',{}),'last_index':store.cursor('radar:index',{})}


def find(identity):
    """Return one indexed candidate by stable radar identity."""
    if not isinstance(identity,str) or not identity.startswith('RADAR-'):
        raise ValueError('雷达候选身份无效')
    import research_radar
    with LOCK,connection() as db:
        status=ensure_index(db,research_radar.settings()['rules'])
        row=db.execute('SELECT data FROM candidates WHERE identity=?',(identity,)).fetchone()
    value=json.loads(row['data']) if row else None
    if value is not None:value['index_status']=status
    return value


def cache_summary():
    """Read bounded counts for status views; never parse candidates.json."""
    decisions=Store().radar_decisions()
    with LOCK,connection() as db:
        rows=db.execute('SELECT identity,tier,selected FROM candidates').fetchall()
        counts={key:0 for key in ('direct','adjacent','background','pending','noise','later','queue','archive')}
        for row in rows:
            state=(decisions.get(row['identity']) or {}).get('decision')
            if row['selected']:counts['queue']+=1
            elif state:
                counts['archive']+=1
                if state=='later':counts['later']+=1
            elif row['tier'] in ('direct','adjacent','background','pending'):
                counts[row['tier']]+=1
        total=counts['queue']+counts['archive']+counts['direct']+counts['adjacent']+counts['background']+counts['pending']
        selected=counts['queue']
        source=db.execute("SELECT value FROM cache_meta WHERE key='source'").fetchone()
    return {'indexed':bool(source),'total':total,'selected':selected,
            'counts':{**counts,'focus':counts['direct']+counts['adjacent'],
                      'supplementary':counts['background']}}
