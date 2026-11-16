"""Annual, sourced CAS/JCR/Xinrui metadata. No title guessing.

The licensed source/export remains authoritative. SQLite holds immutable import
versions and their source identity; consumers can rebuild every displayed rank.
"""
import csv
import io
import json
import re
from urllib.parse import urlparse
import workflow as w
from research_store import Store, encode, now

LABELS = {'CAS': '中科院', 'JCR': 'JCR', 'XR':'新锐'}
HEADER = 'issn,eissn,title,category,scope,quartile\n'


def matches_filter(ranks,system,quartile):
    """CAS major category; JCR JIF any subject. Unknown never passes a numbered filter."""
    value=(ranks or {}).get(system,{})
    entries=[entry for entry in value.get('entries',[]) if system!='CAS' or entry.get('scope')=='major']
    known=value.get('status')=='matched' and bool(entries)
    if quartile=='unknown':return not known
    return known and any(entry.get('quartile')==('Q'+quartile if system=='JCR' else quartile) for entry in entries)


def issns(value):
    if isinstance(value, list):
        return sorted(set(x for v in value for x in issns(v)))
    found = []
    for token in re.split(r'[;,|\s]+', str(value or '').strip()):
        compact = token.replace('-', '').upper()
        if not compact:
            continue
        if not re.fullmatch(r'\d{7}[\dX]', compact):
            raise ValueError('ISSN 格式不正确：' + token[:30])
        digits = [int(x) if x != 'X' else 10 for x in compact]
        if sum(d * (8-i) for i, d in enumerate(digits)) % 11:
            raise ValueError('ISSN 校验位不正确：' + token)
        found.append(compact[:4] + '-' + compact[4:])
    return sorted(set(found))


def _schema(store):
    with store.connection() as db:
        db.executescript('''
          CREATE TABLE IF NOT EXISTS rank_sources(
            id TEXT PRIMARY KEY,system TEXT NOT NULL,year INTEGER NOT NULL,
            edition TEXT NOT NULL,metric TEXT NOT NULL,label TEXT NOT NULL,
            uri TEXT NOT NULL,checksum TEXT NOT NULL,active INTEGER NOT NULL,
            created TEXT NOT NULL,rows INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS rank_entries(
            source_id TEXT NOT NULL REFERENCES rank_sources(id),
            identity TEXT NOT NULL,title TEXT NOT NULL,issns TEXT NOT NULL,
            category TEXT NOT NULL,scope TEXT NOT NULL,quartile TEXT NOT NULL,
            PRIMARY KEY(source_id,identity,category,scope));
        ''')


def sources():
    store = Store(); _schema(store)
    with store.connection() as db:
        records = [dict(r) for r in db.execute('SELECT * FROM rank_sources ORDER BY year DESC,created DESC')]
    return {'records': records, 'template': HEADER, 'public_refresh': store.cursor('journal-ranks-public', {}),
            'message': '尚未导入年度分区来源' if not records else '年度、学科和来源分别保留；缺失与歧义不会推测补全'}


def import_csv(data):
    system = data.get('system')
    if system not in LABELS:
        raise ValueError('请选择中科院、JCR 或新锐')
    try:
        year = int(data.get('year'))
    except (TypeError, ValueError):
        raise ValueError('请填写分区数据年度')
    if not 1997 <= year <= 2100:
        raise ValueError('分区年度超出范围')
    metric = str(data.get('metric') or (system if system != 'JCR' else 'JIF'))
    if metric not in ((system,) if system != 'JCR' else ('JIF', 'JCI')):
        raise ValueError('JCR 的 JIF 和 JCI 四分位需要分别登记')
    edition = str(data.get('edition') or {'CAS':'升级版','JCR':'JCR','XR':'新锐'}[system]).strip()
    label = str(data.get('label') or '').strip()
    uri = str(data.get('uri') or '').strip()
    if not label or len(label) > 200 or not edition or len(edition) > 80:
        raise ValueError('请填写来源名称与版本')
    if urlparse(uri).scheme not in ('https', 'http') or not urlparse(uri).netloc or len(uri) > 1500:
        raise ValueError('请填写可核对的来源网页链接')
    content = str(data.get('content') or '').lstrip('\ufeff')
    if not content or len(content.encode('utf-8')) > 20*1024*1024:
        raise ValueError('分区 CSV 为空或超过 20 MB')
    reader = csv.DictReader(io.StringIO(content))
    if not {'issn','eissn','title','category','scope','quartile'} <= set(reader.fieldnames or []):
        raise ValueError('CSV 列名需要：issn,eissn,title,category,scope,quartile')
    rows = {}
    for number, row in enumerate(reader, 2):
        if number > 150002:
            raise ValueError('分区记录过多')
        codes = issns([row.get('issn'), row.get('eissn')])
        title = str(row.get('title') or '').strip()
        category = str(row.get('category') or '').strip()
        scope = str(row.get('scope') or '').strip().lower()
        value = str(row.get('quartile') or '').strip().upper().replace('区','')
        if system != 'JCR':
            scope = {'大类':'major','小类':'minor'}.get(scope,scope)
            value = value.removeprefix('Q')
        else:
            scope = {'学科':'category'}.get(scope,scope)
            value = 'Q' + value.removeprefix('Q')
        if not codes or not title or not category or len(title) > 400 or len(category) > 400:
            raise ValueError(f'第 {number} 行缺少有效 ISSN、刊名或学科')
        if scope not in (('major','minor') if system != 'JCR' else ('category',)):
            raise ValueError(f'第 {number} 行分区范围应为大类/小类，或 JCR 学科 category')
        if value not in (('1','2','3','4') if system != 'JCR' else ('Q1','Q2','Q3','Q4')):
            raise ValueError(f'第 {number} 行分区值无效；未分区记录应保留为缺失，不填写猜测值')
        identity = w.digest(encode(codes))
        key = (identity, category, scope)
        entry = {'identity': identity, 'title': title, 'issns': codes, 'category': category, 'scope': scope, 'quartile': value}
        if key in rows and rows[key] != entry:
            raise ValueError(f'第 {number} 行与同 ISSN、同学科记录冲突，未导入任何记录')
        rows[key] = entry
    if not rows:
        raise ValueError('分区文件只有列名，没有记录')
    checksum = w.digest(content.encode('utf-8'))
    identifier = 'RANK-' + w.digest(encode([system,year,edition,metric,uri,checksum]))[:24]
    store = Store(); _schema(store)
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        old = db.execute('SELECT * FROM rank_sources WHERE id=?', (identifier,)).fetchone()
        if old:
            return {'id': identifier, 'rows': old['rows'], 'reused': True}
        active = [r['id'] for r in db.execute('SELECT id FROM rank_sources WHERE system=? AND year=? AND edition=? AND metric=? AND uri=? AND active=1', (system,year,edition,metric,uri))]
        if sorted(active) != sorted(data.get('expected_sources') or []):
            raise ValueError('这个年度来源已被更新，请重新打开分区设置后再导入')
        # Keep both the original source bytes and all previous revisions.
        folder = w.DATA/'期刊分区原始导入'; folder.mkdir(parents=True, exist_ok=True)
        path = folder/(identifier+'.csv')
        if not path.exists():
            w.atomic_text(path, content)
        db.executemany('UPDATE rank_sources SET active=0 WHERE id=?', [(x,) for x in active])
        db.execute('INSERT INTO rank_sources VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   (identifier,system,year,edition,metric,label,uri,checksum,1,now(),len(rows)))
        db.executemany('INSERT INTO rank_entries VALUES(?,?,?,?,?,?,?)',
                       [(identifier,r['identity'],r['title'],encode(r['issns']),r['category'],r['scope'],r['quartile']) for r in rows.values()])
        Store.log(db,'rank-source-imported',identifier,{'rows':len(rows),'superseded':active,'checksum':checksum})
    return {'id': identifier, 'rows': len(rows), 'reused': False}


def resolve_many(records, year=None):
    store = Store(); _schema(store)
    with store.connection() as db:
        source_rows = [dict(r) for r in db.execute('SELECT * FROM rank_sources WHERE active=1')]
        entries = [dict(r) for r in db.execute('SELECT e.* FROM rank_entries e JOIN rank_sources s ON s.id=e.source_id WHERE s.active=1')]
    by_source = {s['id']:s for s in source_rows}
    index = {}
    for entry in entries:
        for code in json.loads(entry['issns']):
            index.setdefault(code, []).append(entry)
    result = {}
    for record in records:
        try:
            codes = issns(record.get('issn') or record.get('ISSN') or [])
        except ValueError:
            codes = []
        record_result = {}
        for system in LABELS:
            # JCI is retained but never substituted for the normal JIF quartile.
            available = [s for s in source_rows if s['system']==system and (system!='JCR' or s['metric']=='JIF')]
            selected_year = int(year) if year else max((s['year'] for s in available), default=None)
            matches = {encode(e):e for code in codes for e in index.get(code, [])
                       if by_source[e['source_id']]['system']==system and by_source[e['source_id']]['year']==selected_year
                       and (system!='JCR' or by_source[e['source_id']]['metric']=='JIF')}
            values = []
            for e in matches.values():
                source = by_source[e['source_id']]
                values.append({**{k:e[k] for k in ('title','category','scope','quartile')},
                               'source_id':source['id'],'source':source['label'],'uri':source['uri'],
                               'edition':source['edition'],'metric':source['metric'],'year':source['year'],'checksum':source['checksum']})
            conflicts = {}
            for value in values:
                conflicts.setdefault((value['category'],value['scope'],value['edition']),set()).add(value['quartile'])
            ambiguous = any(len(q)>1 for q in conflicts.values()) or len({v['title'].casefold() for v in values})>1
            state = 'needs_source' if not available else 'needs_issn' if not codes else 'missing' if not values else 'ambiguous' if ambiguous else 'matched'
            record_result[system] = {'status':state,'year':selected_year,'entries':values,'match':'ISSN' if values else None}
        result[record['id']] = record_result
    from journal_rank_sources import cached_supplement
    return cached_supplement(records,result,year)
