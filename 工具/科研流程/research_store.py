"""Controlled, transactional business ledger. Native application databases stay separate.

Markdown owns prose; these tables own IDs, relations, reviews and execution state.
Exports are disposable read-only snapshots, never imported as edits.
"""
from __future__ import annotations
from contextlib import contextmanager, closing
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

DEFAULT_DB = Path(__file__).parent/'数据/research.sqlite3'
BUILTIN_DB = DEFAULT_DB
SCHEMA_VERSION = 2
RADAR_HANDLED_DECISIONS = frozenset(('later','irrelevant','browsed','skipped'))
RADAR_DECISION_REASONS = {
    'object_mismatch': '研究对象不符',
    'method_mismatch': '研究方法不符',
    'task_mismatch': '研究任务不符',
    'peer_review': '同行评审材料',
    'duplicate': '重复线索',
    'insufficient_evidence': '题录信息不足',
    'other': '其他原因',
}
RADAR_DECISION_SUGGESTIONS = {
    'object_mismatch': '多次人工判断研究对象不符。可在关注规则中收紧对象词，并把只有方法交集、没有目标对象的线索降为背景。',
    'method_mismatch': '多次人工判断研究方法不符。建议核对关注规则中的方法词，避免把非太赫兹或非光谱方法当作可迁移方法。',
    'task_mismatch': '多次人工判断研究任务不符。建议复查任务层关键词，区分成分检测、品种鉴别和普通材料表征。',
    'peer_review': '同行评审材料应只保留来源事件，不进入普通候选库；当前准入已直接剔除。',
    'duplicate': '出现了重复线索，建议保留稳定身份合并结果并检查来源别名，不必建立内容排除规则。',
    'insufficient_evidence': '题录信息不足不能证明论文不相关；建议保留为待补，不用单次反馈生成排除规则。',
}


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class Store:
    def __init__(self, path=None):
        if path is None and DEFAULT_DB == BUILTIN_DB:
            import workspace_runtime
            path=workspace_runtime.DATA/'research.sqlite3'
        self.path = Path(path or DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            has_meta = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
            if has_meta:
                schema = db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
                if schema and int(schema['value']) >= SCHEMA_VERSION:
                    return
            db.executescript('''
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                INSERT OR IGNORE INTO meta VALUES('schema','1');
                CREATE TABLE IF NOT EXISTS nodes(
                    id TEXT PRIMARY KEY,kind TEXT NOT NULL,owner TEXT NOT NULL,
                    external_id TEXT,uri TEXT,project TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,
                    data TEXT NOT NULL,created TEXT NOT NULL,updated TEXT NOT NULL,
                    UNIQUE(owner,external_id));
                CREATE INDEX IF NOT EXISTS nodes_extraction_alias
                    ON nodes(owner,kind,json_extract(data,'$.alias_of'));
                CREATE TABLE IF NOT EXISTS relations(
                    id TEXT PRIMARY KEY,source TEXT NOT NULL REFERENCES nodes(id),
                    target TEXT NOT NULL REFERENCES nodes(id),kind TEXT NOT NULL,
                    status TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,
                    evidence TEXT NOT NULL,conditions TEXT NOT NULL,created TEXT NOT NULL,
                    updated TEXT NOT NULL,UNIQUE(source,target,kind));
                CREATE INDEX IF NOT EXISTS relations_target ON relations(target);
                CREATE TABLE IF NOT EXISTS reviews(
                    id INTEGER PRIMARY KEY,object_id TEXT NOT NULL,revision INTEGER NOT NULL,
                    action TEXT NOT NULL,reason TEXT NOT NULL,actor TEXT NOT NULL,created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,
                    idem TEXT UNIQUE,status TEXT NOT NULL,phase TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,safe_retry INTEGER NOT NULL,
                    result TEXT,error TEXT,created TEXT NOT NULL,updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS seen(
                    source TEXT NOT NULL,external_id TEXT NOT NULL,doi TEXT,
                    first_seen TEXT NOT NULL,last_seen TEXT NOT NULL,data TEXT NOT NULL,
                    cold INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(source,external_id));
                CREATE INDEX IF NOT EXISTS seen_doi ON seen(doi);
                CREATE INDEX IF NOT EXISTS seen_updated ON seen(last_seen);
                CREATE TABLE IF NOT EXISTS cursors(
                    key TEXT PRIMARY KEY,value TEXT NOT NULL,updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS radar_alerts(
                    id TEXT PRIMARY KEY,source TEXT NOT NULL,external_id TEXT NOT NULL,
                    paper_id TEXT,doi TEXT,kind TEXT NOT NULL,data TEXT NOT NULL,
                    created TEXT NOT NULL,acknowledged TEXT);
                CREATE TABLE IF NOT EXISTS radar_decisions(
                    identity TEXT PRIMARY KEY,candidate_id TEXT,decision TEXT NOT NULL,
                    reason TEXT NOT NULL,reason_code TEXT NOT NULL DEFAULT 'other',
                    updated TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS radar_decisions_state
                    ON radar_decisions(decision,updated);
                CREATE TABLE IF NOT EXISTS radar_candidate_state(
                    identity TEXT PRIMARY KEY,state TEXT NOT NULL,updated TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS radar_candidate_state_updated
                    ON radar_candidate_state(updated);
                CREATE TABLE IF NOT EXISTS audit_daily(
                    event TEXT NOT NULL,day TEXT NOT NULL,count INTEGER NOT NULL,
                    first_id INTEGER NOT NULL,last_id INTEGER NOT NULL,
                    min_created TEXT NOT NULL,max_created TEXT NOT NULL,
                    PRIMARY KEY(event,day));
                CREATE TABLE IF NOT EXISTS audit(
                    id INTEGER PRIMARY KEY,event TEXT NOT NULL,object_id TEXT NOT NULL,
                    detail TEXT NOT NULL,created TEXT NOT NULL);
            ''')
            schema = int(db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()['value'])
            if schema < SCHEMA_VERSION:
                decision_columns = {row[1] for row in db.execute('PRAGMA table_info(radar_decisions)')}
                if 'reason_code' not in decision_columns:
                    db.execute("ALTER TABLE radar_decisions ADD COLUMN reason_code TEXT NOT NULL DEFAULT 'other'")
                seen_columns = {row[1] for row in db.execute('PRAGMA table_info(seen)')}
                if 'cold' not in seen_columns:
                    db.execute('ALTER TABLE seen ADD COLUMN cold INTEGER NOT NULL DEFAULT 0')
                # Schema 1 could already have the column after an interrupted ALTER.
                db.execute("""UPDATE seen SET cold=1 WHERE cold=0 AND
                           CASE WHEN json_valid(data) THEN json_extract(data,'$.data_minimal') END=1""")
                db.execute('CREATE INDEX IF NOT EXISTS seen_visible ON seen(cold,last_seen)')
                db.execute("UPDATE meta SET value=? WHERE key='schema'", (str(SCHEMA_VERSION),))

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        # 排序与去重的临时结果放内存，系统 TEMP 不可写时也不会让整页读取失败。
        db.execute('PRAGMA temp_store=MEMORY')
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def log(db, event, identifier, detail=None):
        db.execute('INSERT INTO audit(event,object_id,detail,created) VALUES(?,?,?,?)',
                   (event, identifier, encode(detail or {}), now()))

    def allocate(self, prefix):
        # The same transaction increments the sequence across processes and restarts.
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            key = 'sequence:'+prefix
            row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
            value = int(row['value'])+1 if row else 1
            db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', (key, str(value)))
            return f'{prefix}-{value:04d}'

    def node(self, identifier):
        with self.connection() as db:
            row = db.execute('SELECT * FROM nodes WHERE id=?', (identifier,)).fetchone()
        return self.decode_node(row) if row else None

    @staticmethod
    def decode_node(row):
        value = dict(row)
        value['data'] = json.loads(value['data'])
        return value

    def nodes(self, project=None, kind=None):
        with self.connection() as db:
            rows = db.execute('SELECT * FROM nodes ORDER BY created DESC').fetchall()
        return [self.decode_node(r) for r in rows if (not project or r['project'] in (project, '共享')) and (not kind or r['kind']==kind)]

    def put_node(self, identifier, kind, owner, *, project='', external_id=None,
                 uri=None, status='REGISTERED', data=None, expected=None):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM nodes WHERE id=?', (identifier,)).fetchone()
            if old and old['owner'] != owner:
                raise ValueError('只能由权威来源更新此记录')
            if expected is not None and (not old or old['revision'] != expected):
                raise ValueError('记录已变化，请刷新后重试')
            values = (kind, owner, external_id, uri, project, status, encode(data or {}))
            if old:
                before = tuple(old[k] for k in ('kind','owner','external_id','uri','project','status','data'))
                if before == values:
                    return self.decode_node(old)
                db.execute('UPDATE nodes SET kind=?,owner=?,external_id=?,uri=?,project=?,status=?,data=?,revision=revision+1,updated=? WHERE id=?', (*values, now(), identifier))
            else:
                db.execute('INSERT INTO nodes(id,kind,owner,external_id,uri,project,status,data,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)', (identifier, *values, now(), now()))
            self.log(db, 'node.updated' if old else 'node.created', identifier, {'owner':owner})
        return self.node(identifier)

    def relation(self, source, target, kind, evidence, conditions='', *, mechanical=False, expected=None):
        from relation_schema import RELATIONS,MECHANICAL
        if kind not in RELATIONS or not isinstance(evidence, list) or not evidence:
            raise ValueError('关系需要有效类型及证据定位')
        if mechanical and kind not in MECHANICAL:
            raise ValueError('科研判断必须先作为候选审核')
        identifier = 'REL-'+hashlib.sha256(encode([source,target,kind]).encode()).hexdigest()[:20]
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM relations WHERE id=?', (identifier,)).fetchone()
            if expected is not None and (not old or old['revision'] != expected):
                raise ValueError('关系已在其他窗口更新，请重新打开后核对')
            if old:
                if old['evidence']==encode(evidence) and old['conditions']==conditions:
                    return identifier
                # A changed evidence set requires review again.
                db.execute('UPDATE relations SET evidence=?,conditions=?,status=?,revision=revision+1,updated=? WHERE id=?',
                           (encode(evidence), conditions, 'VERIFIED' if mechanical else 'CANDIDATE', now(), identifier))
            else:
                if not all(db.execute('SELECT 1 FROM nodes WHERE id=?',(i,)).fetchone() for i in (source,target)):
                    raise ValueError('请先登记关系两端的稳定 ID')
                db.execute('INSERT INTO relations(id,source,target,kind,status,evidence,conditions,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                           (identifier, source, target, kind, 'VERIFIED' if mechanical else 'CANDIDATE', encode(evidence), conditions, now(), now()))
            self.log(db, 'relation.updated' if old else 'relation.created', identifier)
        return identifier

    def relations(self, status=None):
        with self.connection() as db:
            rows = db.execute('SELECT * FROM relations ORDER BY created').fetchall()
        return [{**dict(r),'evidence':json.loads(r['evidence'])} for r in rows if not status or r['status']==status]

    def review(self, identifier, revision, action, reason, *, actor='local-human'):
        node=self.node(identifier)
        if node and node['owner']=='KnowledgeExtraction':
            import knowledge
            import knowledge_extraction
            with knowledge.editing():
                if action=='VERIFIED' and node['kind']=='ExtractedClaim':knowledge_extraction._assert_numbers(node['data']['derived_text'],node['data'].get('evidence',[]))
                knowledge_extraction.assert_review_current(node,self)
                return self._review_current(identifier,revision,action,reason,actor=actor)
        if action == 'VERIFIED' and identifier.startswith('REL-'):
            edge = next((r for r in self.relations() if r['id'] == identifier), None)
            if edge:
                if any(e.get('generator')=='knowledge-comparison-v1' for e in edge['evidence']):
                    import knowledge
                    import knowledge_comparison
                    with knowledge.editing():
                        knowledge_comparison.assert_review_current(edge,self)
                        return self._review_current(identifier,revision,action,reason,actor=actor)
                from relation_discovery import managed, assert_review_current
                if managed(edge):
                    import knowledge
                    with knowledge.editing():
                        assert_review_current(edge, self)
                        return self._review_current(identifier, revision, action, reason, actor=actor)
        return self._review_current(identifier, revision, action, reason, actor=actor)

    def _review_current(self, identifier, revision, action, reason, *, actor='local-human'):
        if action not in ('VERIFIED','REJECTED') or not reason.strip():
            raise ValueError('请填写审核结论和理由')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            table = 'relations' if identifier.startswith('REL-') else 'nodes'
            row = db.execute(f'SELECT * FROM {table} WHERE id=?', (identifier,)).fetchone()
            if not row or row['revision'] != revision:
                raise ValueError('记录已变化，请重新核查当前版本')
            if row['status'] != 'CANDIDATE':
                raise ValueError('此版本已处理，不重复审核')
            db.execute(f'UPDATE {table} SET status=?,revision=revision+1,updated=? WHERE id=?', (action, now(), identifier))
            db.execute('INSERT INTO reviews(object_id,revision,action,reason,actor,created) VALUES(?,?,?,?,?,?)',
                       (identifier, revision, action, reason, actor, now()))
            self.log(db, 'review.'+action.lower(), identifier, {'reason':reason,'revision':revision})
        return {'id':identifier, 'status':action, 'revision':revision+1}

    def enqueue(self, kind, payload, *, safe_retry=False, idem=None, identifier=None):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if __import__('job_policy').policy(kind)['coalesce'] and payload.get('enabled') is not False:
                # Daily n8n, continuation and a manual click share one in-flight scan.
                for active in db.execute("SELECT id,payload FROM jobs WHERE kind=? AND status IN ('queued','running')",(kind,)):
                    if json.loads(active['payload']).get('enabled') is not False:return active['id']
            if idem:
                old = db.execute('SELECT id,status FROM jobs WHERE idem=?', (idem,)).fetchone()
                if old:
                    return old['id']
            else:
                active=db.execute("SELECT id FROM jobs WHERE kind=? AND payload=? AND status IN ('queued','running')",(kind,encode(payload))).fetchone()
                if active:return active['id']
            if db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running') AND kind!='model_call'").fetchone()[0]>=20:
                raise ValueError('任务队列已有 20 项，请等待已提交任务完成')
            identifier = identifier or uuid.uuid4().hex
            db.execute('INSERT INTO jobs(id,kind,payload,idem,status,phase,safe_retry,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                       (identifier, kind, encode(payload), idem, 'queued', '等待执行', int(safe_retry), now(), now()))
            self.log(db, 'job.queued', identifier, {'kind':kind})
        return identifier

    def job(self, identifier, private=False):
        with self.connection() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone()
        if not row:
            return None
        value = dict(row)
        value['result'] = json.loads(value['result']) if value['result'] else None
        value['started'] = value['created']
        if private:
            value['payload'] = json.loads(value['payload'])
        else:
            value.pop('payload')
        return value

    def claim(self, identifier):
        with self.connection() as db:
            changed = db.execute("UPDATE jobs SET status='running',phase='正在执行',attempts=attempts+1,updated=? WHERE id=? AND status='queued'", (now(), identifier)).rowcount
        return bool(changed)

    def finish(self, identifier, result=None, error=None):
        outcome = result if isinstance(result, dict) else {}
        result_status = outcome.get('status')
        phases = {'completed':'已完成','partial':'部分完成，保留进度','waiting':'等待依赖或下轮接续',
                  'skipped':'已跳过','failed':'未完成','needs_review':'执行结果待核查'}
        with self.connection() as db:
            row = db.execute('SELECT kind FROM jobs WHERE id=?',(identifier,)).fetchone()
            if not row:
                return
            status = 'failed' if error else 'completed'
            if not error and result_status in ('failed','needs_review','skipped'):
                status = result_status
            if not error and row['kind']=='sync' and result_status in ('partial','waiting'):
                status = result_status
            if status in ('failed','needs_review') and not error:
                detail = outcome.get('message') or outcome.get('error')
                error = detail if isinstance(detail,str) else phases[status]
            phase = phases[status]
            if status=='completed' and (result_status in ('partial','waiting','needs_attention') or outcome.get('synthesis_status')=='needs_attention'):
                phase = phases['partial']
            db.execute('UPDATE jobs SET status=?,phase=?,result=?,error=?,updated=? WHERE id=?',
                       (status, phase, encode(result), error, now(), identifier))
            self.log(db, 'job.'+status, identifier)

    def progress(self, identifier, phase):
        if not isinstance(phase,str) or not phase.strip() or len(phase)>200:raise ValueError('任务阶段无效')
        with self.connection() as db:
            db.execute("UPDATE jobs SET phase=?,updated=? WHERE id=? AND status='running'",(phase,now(),identifier))

    def recover(self):
        with self.connection() as db:
            # Paid calls and external writes with unknown outcomes are never replayed blindly.
            db.execute("UPDATE jobs SET status=CASE WHEN safe_retry=1 THEN 'queued' ELSE 'needs_review' END,phase=CASE WHEN safe_retry=1 THEN '重启后续跑' ELSE '执行结果待核查' END,updated=? WHERE status='running'", (now(),))
            rows = db.execute("SELECT id FROM jobs WHERE status='queued' AND kind!='model_call'").fetchall()
        return [r['id'] for r in rows]

    def retry(self, identifier):
        with self.connection() as db:
            row=db.execute('SELECT * FROM jobs WHERE id=?',(identifier,)).fetchone()
            if not row or not row['safe_retry'] or row['status'] not in ('failed','needs_review'):
                raise ValueError('此任务需要先核查外部结果，不能自动重复执行')
            db.execute("UPDATE jobs SET status='queued',error=NULL,updated=? WHERE id=?",(now(),identifier))
        return identifier

    def uncertain_call(self, identifier, detail=None):
        message = '服务结果未确认，请核查后再决定是否重试'
        if isinstance(detail, str) and detail.strip():
            # 具体原因（代理拒连、超时、响应缺字段等）留在任务账本里，后台任务可见。
            message = '结果未确认：' + detail.strip()[:180] + '；请核查后再决定是否重试'
        with self.connection() as db:
            db.execute("UPDATE jobs SET status='needs_review',phase='模型结果不明',error=?,updated=? WHERE id=? AND kind='model_call' AND status='running'", (message, now(), identifier))
            self.log(db,'model.uncertain',identifier)

    def release_call(self, identifier, updated, reason):
        if not isinstance(reason,str) or not 4 <= len(reason.strip()) <= 1000:
            raise ValueError('请记录核查结果和允许重新调用的原因')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM jobs WHERE id=?',(identifier,)).fetchone()
            if not row or row['kind']!='model_call' or row['status'] not in ('failed','needs_review'):
                raise ValueError('只能释放已停止且需要核查的模型请求')
            if row['updated']!=updated:
                raise ValueError('任务状态已变化，请刷新后核对')
            db.execute("UPDATE jobs SET status='queued',phase='用户核查后允许重试',error=NULL,updated=? WHERE id=?",(now(),identifier))
            self.log(db,'model.retry_authorized',identifier,{'actor':'user','reason':reason.strip(),'previous_status':row['status'],'previous_error':row['error']})
        return {'id':identifier,'status':'released','message':'已解除该请求的阻塞；返回原功能再次提交时才会调用，成功阶段仍会复用'}

    def compact_jobs(self, retain_days=30, now_at=None):
        """Keep routine task identities, but bound old successful diagnostic detail."""
        if type(retain_days) is not int or retain_days < 30:
            raise ValueError('普通成功任务的完整记录至少保留 30 天。')
        moment = datetime.fromisoformat(now_at) if now_at else datetime.now(timezone.utc)
        if moment.tzinfo is None: raise ValueError('历史维护时间必须包含时区。')
        moment = moment.astimezone(timezone.utc)
        cutoff = (moment - timedelta(days=retain_days)).isoformat()
        routine = ('sync', 'versions', 'relation_tick', 'administrator_tick', 'rspace_sync')
        changed = 0
        with self.connection() as db:
            rows = db.execute("SELECT * FROM jobs WHERE status='completed' AND safe_retry=1 AND updated<? AND kind IN (?,?,?,?,?)",
                              (cutoff, *routine)).fetchall()
            for row in rows:
                result = json.loads(row['result']) if row['result'] else {}
                if not isinstance(result, dict) or result.get('history_compacted'):
                    continue
                def incomplete(value):
                    if isinstance(value, dict):
                        return (value.get('status') in ('partial', 'waiting', 'needs_attention', 'needs_review', 'running', 'queued',
                                                       'needs_configuration', 'unavailable', 'deferred', 'failed', 'unknown', 'interrupted', 'error')
                                or any(value.get(key) for key in ('errors', 'error', 'error_type', 'pending_pages', 'remaining', 'unresolved'))
                                or any(incomplete(child) for child in value.values()))
                    return isinstance(value, list) and any(incomplete(child) for child in value)
                if incomplete(result):
                    continue
                summary = {'history_compacted': True, 'summary': '普通成功任务；完整诊断保留期已结束，原身份与完成时间保留。',
                           **{key: value for key, value in result.items() if isinstance(value, (int, float, bool)) or key == 'status'}}
                db.execute('UPDATE jobs SET payload=?,result=? WHERE id=?', ('{}', encode(summary), row['id']))
                changed += 1
        return {'compacted': changed, 'retain_days': retain_days}

    def jobs(self):
        with self.connection() as db:
            # Frequent successful syncs must not push unresolved tasks out of view.
            rows=db.execute("SELECT id FROM jobs ORDER BY CASE WHEN status IN ('running','queued') THEN 0 WHEN status IN ('failed','needs_review') THEN 1 ELSE 2 END,updated DESC LIMIT 100").fetchall()
        return [self.job(r['id']) for r in rows]

    def cursor(self, key, default=None):
        with self.connection() as db:
            row=db.execute('SELECT value FROM cursors WHERE key=?',(key,)).fetchone()
        return json.loads(row['value']) if row else default

    def commit_page(self, key, records, cursor, *, alerts=()):
        # A failed page must not advance its cursor; page and Seen are one transaction.
        with self.connection() as db:
            for r in records:
                r=dict(r)
                old=db.execute('SELECT data FROM seen WHERE source=? AND external_id=?',(r['source'],r['external_id'])).fetchone()
                before=json.loads(old['data']) if old else {}
                r['watch_ids']=sorted(set(before.get('watch_ids',[])+([r['watch_id']] if r.get('watch_id') else [])))
                db.execute('INSERT INTO seen(source,external_id,doi,first_seen,last_seen,data,cold) VALUES(?,?,?,?,?,?,0) ON CONFLICT(source,external_id) DO UPDATE SET last_seen=excluded.last_seen,data=excluded.data,doi=excluded.doi,cold=0',
                           (r['source'],r['external_id'],r.get('doi'),now(),now(),encode(r)))
            for alert in alerts:
                # The observation, change notice and cursor are committed together.
                identifier='ALERT-'+hashlib.sha256(encode([alert['source'],alert['external_id'],alert['kind'],alert.get('before'),alert.get('after')]).encode()).hexdigest()[:24]
                db.execute('INSERT OR IGNORE INTO radar_alerts(id,source,external_id,paper_id,doi,kind,data,created) VALUES(?,?,?,?,?,?,?,?)',
                           (identifier,alert['source'],alert['external_id'],alert.get('paper_id'),alert.get('doi'),alert['kind'],encode(alert),now()))
            db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)',(key,encode(cursor),now()))

    def radar_alerts(self, *, unread_only=False):
        with self.connection() as db:
            rows=db.execute('SELECT * FROM radar_alerts ORDER BY created DESC,id').fetchall()
        return [{**json.loads(r['data']),'id':r['id'],'created':r['created'],'acknowledged':r['acknowledged']} for r in rows
                if not unread_only or not r['acknowledged']]

    def acknowledge_radar_alert(self, identifier):
        with self.connection() as db:
            row=db.execute('SELECT * FROM radar_alerts WHERE id=?',(identifier,)).fetchone()
            if not row:raise ValueError('这条文献变化不存在，请刷新列表')
            if not row['acknowledged']:
                db.execute('UPDATE radar_alerts SET acknowledged=? WHERE id=?',(now(),identifier))
                self.log(db,'radar.alert_viewed',identifier,{'scientific_impact_reviewed':False})
        return {'id':identifier,'status':'viewed','message':'已标记查看；不代表确认科研影响'}

    def radar_decisions(self):
        with self.connection() as db:
            rows=db.execute('SELECT * FROM radar_decisions ORDER BY updated DESC').fetchall()
        return {row['identity']:dict(row) for row in rows}

    def radar_decision_insights(self):
        """Summarize repeated human reasons into cautious cross-paper guidance."""
        with self.connection() as db:
            rows=db.execute(
                'SELECT reason_code,COUNT(*) AS count FROM radar_decisions '
                "WHERE decision='irrelevant' GROUP BY reason_code ORDER BY count DESC,reason_code"
            ).fetchall()
        groups=[]
        suggestions=[]
        for row in rows:
            code=row['reason_code'] or 'other'
            count=int(row['count'])
            groups.append({'reason_code':code,'label':RADAR_DECISION_REASONS.get(code,'其他原因'),'count':count})
            if count>=2 and code in RADAR_DECISION_SUGGESTIONS:
                suggestions.append({
                    'reason_code':code,
                    'label':RADAR_DECISION_REASONS.get(code,'其他原因'),
                    'count':count,
                    'message':RADAR_DECISION_SUGGESTIONS[code],
                })
        return {'groups':groups,'suggestions':suggestions}

    def radar_decision(self, identity):
        with self.connection() as db:
            row=db.execute('SELECT * FROM radar_decisions WHERE identity=?',(identity,)).fetchone()
        return dict(row) if row else None

    def radar_relevance(self):
        """Return the small AI overlay without rewriting the candidate corpus."""
        with self.connection() as db:
            rows=db.execute("SELECT key,value FROM cursors WHERE key LIKE 'radar:relevance:RADAR-%'").fetchall()
        return {row['key'].removeprefix('radar:relevance:'):json.loads(row['value']) for row in rows}

    def radar_candidate_states(self):
        with self.connection() as db:
            rows=db.execute('SELECT identity,state,updated FROM radar_candidate_state').fetchall()
        return {row['identity']:{**json.loads(row['state']),'updated':row['updated']} for row in rows}

    def radar_candidate_state(self, identity):
        with self.connection() as db:
            row=db.execute('SELECT state,updated FROM radar_candidate_state WHERE identity=?',(identity,)).fetchone()
        return {**json.loads(row['state']),'updated':row['updated']} if row else None

    def update_radar_candidate_state(self, identity, changes):
        allowed={'selected','collection','acquisition','workspace_id','workspace_record',
                 'evidence_status','project','candidate_id','legacy_record'}
        if not isinstance(identity,str) or not identity.startswith('RADAR-'):
            raise ValueError('雷达候选身份无效')
        if not isinstance(changes,dict) or set(changes)-allowed:
            raise ValueError('雷达候选状态无效')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT state FROM radar_candidate_state WHERE identity=?',(identity,)).fetchone()
            state=json.loads(row['state']) if row else {}
            before={key:state.get(key) for key in changes}
            state.update({key:value for key,value in changes.items() if value is not None})
            if row is None or any(state.get(key)!=value for key,value in before.items()):
                observed=now()
                db.execute('INSERT INTO radar_candidate_state(identity,state,updated) VALUES(?,?,?) '
                           'ON CONFLICT(identity) DO UPDATE SET state=excluded.state,updated=excluded.updated',
                           (identity,encode(state),observed))
                self.log(db,'radar.candidate_state',identity,{'fields':sorted(changes)})
        return self.radar_candidate_state(identity)

    def radar_source_signature(self):
        """Small durable fingerprint for rebuilding the derived candidate view."""
        with self.connection() as db:
            seen=db.execute('SELECT COUNT(*) n,COALESCE(MAX(last_seen),\'\') updated FROM seen').fetchone()
            states=db.execute('SELECT COUNT(*) n,COALESCE(MAX(updated),\'\') updated FROM radar_candidate_state').fetchone()
            decisions=db.execute('SELECT COUNT(*) n,COALESCE(MAX(updated),\'\') updated FROM radar_decisions').fetchone()
            relevance=db.execute("SELECT COUNT(*) n,COALESCE(MAX(updated),'') updated FROM cursors "
                                 "WHERE key LIKE 'radar:relevance:RADAR-%'").fetchone()
            compacted=db.execute("SELECT value FROM cursors WHERE key='seen:compaction'").fetchone()
        return {name:{'count':row['n'],'updated':row['updated']}
                for name,row in (('seen',seen),('states',states),('decisions',decisions),('relevance',relevance))} | {
                    'seen_compaction':json.loads(compacted['value']).get('checked','') if compacted else ''
                }

    def close_unresolved_jobs(self, *, retain_days=1):
        """Close historical unresolved jobs whose result was never retained.

        The job identity, timestamps, previous error and a truthful closure
        reason remain in the ledger. No external request is retried.
        """
        if type(retain_days) is not int or retain_days<1:
            raise ValueError('未决任务至少保留1天')
        cutoff=(datetime.now(timezone.utc)-timedelta(days=retain_days)).isoformat()
        closed=[]
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            rows=db.execute(
                "SELECT * FROM jobs WHERE status='needs_review' AND result IS NULL AND updated<?",
                (cutoff,)).fetchall()
            for row in rows:
                reason=f'历史未决任务超过{retain_days}天且未保存有效结果；未重试外部请求，已关闭并保留原身份。'
                result={'status':'closed','history_closed':True,'previous_status':row['status'],
                        'previous_error':row['error'],'reason':reason,'closed_at':now()}
                db.execute("UPDATE jobs SET status='closed',phase='历史未决任务已关闭',result=?,error=?,updated=? WHERE id=?",
                           (encode(result),reason,now(),row['id']))
                self.log(db,'job.closed_unresolved',row['id'],{
                    'kind':row['kind'],'previous_status':row['status'],
                    'previous_error':row['error'],'retried_external_request':False,
                })
                closed.append(row['id'])
        return {'closed':closed,'count':len(closed)}

    def close_historical_failures(self, *, kind, before):
        if not isinstance(kind,str) or not kind.strip() or len(kind)>80:
            raise ValueError('历史失败任务类型无效')
        moment=datetime.fromisoformat(before)
        if moment.tzinfo is None:raise ValueError('历史失败截止时间必须包含时区')
        cutoff=moment.astimezone(timezone.utc).isoformat()
        closed=[]
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            rows=db.execute(
                "SELECT * FROM jobs WHERE kind=? AND status='failed' AND updated<?",
                (kind,cutoff)).fetchall()
            for row in rows:
                reason='修复前历史失败已归档；稳定身份、错误类型和时间保留，不再进入待处理列表。'
                result={'status':'closed','history_archived':True,
                        'previous_status':row['status'],'previous_error':row['error'],
                        'reason':reason,'closed_at':now()}
                db.execute("UPDATE jobs SET status='closed',phase='历史失败已归档',result=?,updated=? WHERE id=?",
                           (encode(result),now(),row['id']))
                self.log(db,'job.historical_failure_closed',row['id'],{
                    'kind':kind,'previous_error':row['error'],'retried_external_request':False,
                })
                closed.append(row['id'])
        return {'closed':closed,'count':len(closed),'kind':kind,'before':cutoff}

    def compact_seen(self, *, archive=True):
        """Bound historical discovery payloads while preserving identity/source.

        Selected/queued and manually decided records stay full. Noise keeps a short
        diagnostic window. Pending, direct and adjacent records share the
        configured recent window; background uses its own window.
        """
        import workspace_runtime as w
        from radar_inbox import candidate_identity,priority
        import research_radar
        rules=research_radar.settings()['rules']
        states=self.radar_candidate_states()
        decisions=self.radar_decisions()
        moment=datetime.now(timezone.utc)
        policy=research_radar.reminder_policy()
        limits={'noise':7,'background':policy['background_days'],
                'pending':policy['recent_days'],
                'adjacent':policy['recent_days'],'direct':policy['recent_days']}
        with self.connection() as db:
            rows=db.execute('SELECT source,external_id,first_seen,last_seen,data,cold FROM seen').fetchall()
        updates=[];archive_rows=[];kept=0
        for row in rows:
            value=json.loads(row['data'])
            identity=candidate_identity(value)
            state=states.get(identity) or {}
            decision=(decisions.get(identity) or {}).get('decision')
            if state.get('selected') or decision in RADAR_HANDLED_DECISIONS:
                kept+=1;continue
            tier=value.get('compacted_tier') or priority(value,rules).get('tier','noise')
            if value.get('record_compacted') and (tier!='noise' or value.get('data_minimal')):
                kept+=1;continue
            try:age=(moment-datetime.fromisoformat(row['first_seen'])).days
            except (TypeError,ValueError):age=0
            if age<limits.get(tier,30):
                kept+=1;continue
            keys=('source','sources','external_id','doi','first_seen','discovered','compacted_tier')
            summary={key:value[key] for key in keys if key in value}
            summary.update(record_compacted=True,record_compacted_at=now(),
                           compacted_tier=tier,
                           data_minimal=True,
                           retention_note='完整发现载荷已压缩归档；仅保留来源、稳定身份、时间和去重键。')
            if not value.get('record_compacted'):
                archive_rows.append({'source':row['source'],'external_id':row['external_id'],
                                     'first_seen':row['first_seen'],'last_seen':row['last_seen'],
                                     'data':value})
            updates.append((encode(summary),1,row['source'],row['external_id'],
                            row['data'],row['first_seen'],row['last_seen'],row['cold'],identity))
        archive_path=''
        if archive and archive_rows:
            from storage_budget import require_capacity
            reserve=sum(len((json.dumps(item,ensure_ascii=False)+'\n').encode('utf-8')) for item in archive_rows)
            require_capacity(w.ROOT,'archives',reserve_bytes=reserve+reserve//100+65536)
            folder=w.DATA/'归档'/'文献雷达'
            folder.mkdir(parents=True,exist_ok=True)
            archive_path=folder/f'seen-{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}-{uuid.uuid4().hex[:8]}.jsonl.gz'
            with gzip.open(archive_path,'wt',encoding='utf-8') as target:
                for item in archive_rows:target.write(json.dumps(item,ensure_ascii=False)+'\n')
            with gzip.open(archive_path,'rt',encoding='utf-8') as source:
                verified=sum(1 for line in source if json.loads(line))
            if verified!=len(archive_rows):
                raise RuntimeError('候选压缩归档校验失败，Seen 未改写')
        elif archive_rows:
            raise RuntimeError('候选压缩归档未创建，Seen 未改写')
        compacted=0
        if updates:
            with self.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                # Archival happens without a write lock. Recheck manual changes
                # inside this transaction, then update only the observed version.
                current_states={row['identity']:{**json.loads(row['state']),'updated':row['updated']}
                                for row in db.execute('SELECT identity,state,updated FROM radar_candidate_state')}
                current_decisions={row['identity']:dict(row) for row in db.execute('SELECT * FROM radar_decisions')}
                unchanged=[update[:-1] for update in updates
                           if current_states.get(update[-1])==states.get(update[-1])
                           and current_decisions.get(update[-1])==decisions.get(update[-1])]
                compacted=db.executemany(
                    'UPDATE seen SET data=?,cold=? WHERE source=? AND external_id=? '
                    'AND data=? AND first_seen=? AND last_seen=? AND cold=?',unchanged).rowcount
                if compacted:
                    receipt={'checked':now(),'compacted':compacted,
                             'archive':str(archive_path) if archive_path else ''}
                    db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)',
                               ('seen:compaction',encode(receipt),now()))
                    self.log(db,'radar.seen_compacted',archive_path.name if archive_path else 'none',{
                        'records':compacted,'archive':str(archive_path) if archive_path else '',
                        'policy':limits,
                    })
        return {'compacted':compacted,'kept':kept+len(updates)-compacted,
                'archive':str(archive_path) if archive_path else ''}

    def compact_audit(self, *, retain_days=7, archive=True):
        """Summarize repetitive routine job events while preserving an archive."""
        import workspace_runtime as w
        if type(retain_days) is not int or retain_days<7:
            raise ValueError('审计汇总至少保留7天')
        cutoff=(datetime.now(timezone.utc)-timedelta(days=retain_days)).isoformat()
        routine=('job.queued','job.completed','job.scheduled_retry')
        with self.connection() as db:
            rows=db.execute(
                "SELECT * FROM audit WHERE created<? AND event IN (?,?,?) ORDER BY id",
                (cutoff,*routine)).fetchall()
        archive_path=''
        if archive and rows:
            from storage_budget import require_capacity
            reserve=sum(len((json.dumps(dict(row),ensure_ascii=False)+'\n').encode('utf-8')) for row in rows)
            require_capacity(w.ROOT,'archives',reserve_bytes=reserve+reserve//100+65536)
            folder=w.DATA/'归档'/'文献雷达'
            folder.mkdir(parents=True,exist_ok=True)
            archive_path=folder/f'audit-{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}-{uuid.uuid4().hex[:8]}.jsonl.gz'
            with gzip.open(archive_path,'wt',encoding='utf-8') as target:
                for row in rows:target.write(json.dumps(dict(row),ensure_ascii=False)+'\n')
            with gzip.open(archive_path,'rt',encoding='utf-8') as source:
                verified=sum(1 for line in source if json.loads(line))
            if verified!=len(rows):
                raise RuntimeError('审计压缩归档校验失败，原记录未删除')
        groups={}
        for row in rows:
            key=(row['event'],row['created'][:10])
            groups.setdefault(key,[]).append(row)
        if rows:
            with self.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                for (event,day),items in groups.items():
                    ids=[item['id'] for item in items]
                    db.execute(
                        'INSERT INTO audit_daily(event,day,count,first_id,last_id,min_created,max_created) '
                        'VALUES(?,?,?,?,?,?,?) ON CONFLICT(event,day) DO UPDATE SET '
                        'count=count+excluded.count,first_id=MIN(first_id,excluded.first_id),'
                        'last_id=MAX(last_id,excluded.last_id),min_created=MIN(min_created,excluded.min_created),'
                        'max_created=MAX(max_created,excluded.max_created)',
                        (event,day,len(items),min(ids),max(ids),
                         min(item['created'] for item in items),max(item['created'] for item in items)))
                db.executemany('DELETE FROM audit WHERE id=?',((item['id'],) for item in rows))
                self.log(db,'maintenance.audit_summarized',archive_path.name if archive_path else 'none',{
                    'records':len(rows),'archive':str(archive_path) if archive_path else '',
                    'retain_days':retain_days,
                })
        return {'summarized':len(rows),'days':len(groups),'archive':str(archive_path) if archive_path else ''}

    def storage_summary(self):
        with self.connection() as db:
            jobs={row['status']:row['n'] for row in
                  db.execute('SELECT status,COUNT(*) n FROM jobs GROUP BY status')}
            audit=int(db.execute('SELECT COUNT(*) FROM audit').fetchone()[0])
            archived_audit=int(db.execute('SELECT COALESCE(SUM(count),0) FROM audit_daily').fetchone()[0])
            seen=int(db.execute('SELECT COUNT(*) FROM seen').fetchone()[0])
            compacted=int(db.execute('SELECT COUNT(*) FROM seen WHERE cold=1').fetchone()[0])
        return {'database_bytes':self.path.stat().st_size,'jobs':jobs,'audit_recent':audit,
                'audit_archived_summary':archived_audit,'seen':seen,'seen_compacted':compacted}

    def set_radar_decision(self, identity, decision, *, reason='', candidate_id='', reason_code='other'):
        if not isinstance(identity,str) or not identity.startswith('RADAR-'):
            raise ValueError('雷达候选身份无效')
        if decision not in RADAR_HANDLED_DECISIONS|{'reset'}:
            raise ValueError('雷达研判状态无效')
        if not isinstance(reason,str) or len(reason)>500:
            raise ValueError('研判原因过长')
        if reason_code not in RADAR_DECISION_REASONS:
            raise ValueError('不相关原因无效')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if decision=='reset':
                db.execute('DELETE FROM radar_decisions WHERE identity=?',(identity,))
                self.log(db,'radar.decision_reset',identity,{'candidate_id':candidate_id})
                return {'identity':identity,'decision':'new','reason':''}
            db.execute('INSERT INTO radar_decisions(identity,candidate_id,decision,reason,reason_code,updated) '
                       'VALUES(?,?,?,?,?,?) ON CONFLICT(identity) DO UPDATE SET '
                       'candidate_id=excluded.candidate_id,decision=excluded.decision,'
                       'reason=excluded.reason,reason_code=excluded.reason_code,updated=excluded.updated',
                       (identity,candidate_id,decision,reason.strip(),reason_code,now()))
            self.log(db,'radar.decision_'+decision,identity,{
                'candidate_id':candidate_id,'reason':reason.strip(),
                'reason_code':reason_code,
                'scientific_impact_reviewed':False,
            })
        insights=self.radar_decision_insights()
        return {'identity':identity,'decision':decision,'reason':reason.strip(),
                'reason_code':reason_code,'insights':insights}

    def seen(self, since=None, *, include_cold=True):
        """Return discovery observations; cold history remains available for dedup/audit."""
        with self.connection() as db:
            where=[];params=[]
            if since:
                where.append('last_seen>?');params.append(since)
            if not include_cold:
                where.append('cold=0')
            query='SELECT * FROM seen'
            if where:query+=' WHERE '+' AND '.join(where)
            query+=' ORDER BY first_seen DESC'
            rows=db.execute(query,params).fetchall()
        return [{**json.loads(r['data']),'first_seen':r['first_seen']} for r in rows]

    def backup(self, destination):
        with closing(sqlite3.connect(self.path)) as source, closing(sqlite3.connect(destination)) as target:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('业务账本快照校验失败')

    def snapshot(self):
        with self.connection() as db:
            reviews=[dict(r) for r in db.execute('SELECT * FROM reviews')]
        return {'schema':1,'generated':now(),'editable':False,'nodes':self.nodes(),'relations':self.relations(),'reviews':reviews}

    def audit(self):
        with self.connection() as db:
            return [dict(r) for r in db.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 100')]
