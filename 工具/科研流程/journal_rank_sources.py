"""Public ShowJCR data as an explicitly labelled supplement, scoped to this library.

We read CSV data, never install or execute the upstream application. Imported
annual source versions retain their own names, subjects and checksums.
"""
import csv
import io
import re
from functools import lru_cache
from pathlib import Path
from datetime import datetime,timedelta,timezone
from urllib.parse import quote
import requests
import bibliography
import journal_ranks as ranks
import workflow as w
from research_store import Store,encode
from filelock import FileLock

FOLDER='中科院分区表及JCR原始数据文件'
API='https://api.github.com/repos/hitfyd/ShowJCR/contents/'+quote(FOLDER)
PATTERNS={'CAS':r'FQBJCR(\d{4})-UTF8\.csv','JCR':r'JCR(\d{4})-UTF8\.csv','XR':r'XR(\d{4})-UTF8\.csv'}


def codes(value):
    if isinstance(value,list):return sorted({code for part in value for code in codes(part)})
    result=[]
    for token in re.split(r'[\s/;,|]+',str(value or '')):
        try:result.extend(ranks.issns(token))
        except ValueError:continue
    return sorted(set(result))


def normalized(content,system,year,wanted):
    reader=csv.DictReader(io.StringIO(content.lstrip('\ufeff')));out=io.StringIO();writer=csv.writer(out)
    writer.writerow(['issn','eissn','title','category','scope','quartile'])
    for row in reader:
        identifiers=codes(row.get('ISSN/EISSN')) if system=='CAS' else codes(row.get('ISSN'))+codes(row.get('EISSN'))
        if wanted is not None and not wanted.intersection(identifiers):continue
        title=(row.get('Journal') or row.get('刊名') or '').strip()
        if not title:continue
        categories=[]
        if system=='CAS':
            categories.append((row.get('大类'),row.get('大类分区'),'major'))
            categories.extend((row.get('小类'+str(i)),row.get('小类'+str(i)+'分区'),'minor') for i in range(1,7))
        elif system=='XR':
            categories.extend([(row.get('大类中文名') or row.get('大类英文名'),row.get('大类新锐分区'),'major'),
                               (row.get('大类2中文名') or row.get('大类2英文名'),row.get('大类2新锐分区'),'major')])
            categories.extend((row.get('小类'+str(i)+'中文名') or row.get('小类'+str(i)+'英文名'),row.get('小类'+str(i)+'新锐分区'),'minor') for i in range(1,7))
        else:categories.extend((row.get('Category_'+str(i)),row.get('IF Quartile('+str(year)+')_'+str(i)),'category') for i in range(1,7))
        for category,value,scope in categories:
            match=re.match(r'^\s*Q?([1-4])\b',str(value or ''))
            if not category or not match:continue
            writer.writerow([';'.join(sorted(set(identifiers))),'',title,category.strip(),scope,('Q' if system=='JCR' else '')+match[1]])
    return out.getvalue()


@lru_cache(maxsize=6)
def _cached_index(path,mtime,size,system,year):
    raw=Path(path).read_text('utf-8-sig')
    content=normalized(raw,system,year,None);index={}
    checksum=w.digest(raw.encode('utf-8'))
    name=('FQBJCR' if system=='CAS' else 'JCR' if system=='JCR' else 'XR')+str(year)+'-UTF8.csv'
    uri='https://raw.githubusercontent.com/hitfyd/ShowJCR/master/'+quote(FOLDER)+'/'+name
    for row in csv.DictReader(io.StringIO(content)):
        entry={**{key:row[key] for key in ('title','category','scope','quartile')},
            'source':'ShowJCR 公开镜像 · 本机年度缓存','uri':uri,'year':year,'checksum':checksum,
            'source_id':'cached:'+Path(path).name,'edition':'升级版' if system=='CAS' else system,
            'metric':'JIF' if system=='JCR' else system}
        for code in codes(row['issn']):index.setdefault(code,[]).append(entry)
    return index


def cached_supplement(records,result,year=None):
    """Use existing full annual CSVs for new journals; no downloads or source rewrites."""
    folder=w.DATA/'期刊分区公开来源'
    if not folder.is_dir():return result
    available={}
    for path in folder.glob('*.csv'):
        match=re.fullmatch(r'(CAS|JCR|XR)_(\d{4})_[0-9a-f]{16}\.csv',path.name)
        if match and 1997<=int(match[2])<=datetime.now().year and path.stat().st_size<=20*1024*1024:
            available.setdefault(match[1],[]).append((int(match[2]),path))
    for record in records:
        identifiers=codes(record.get('issn') or record.get('ISSN'));value=result[record['id']]
        if not identifiers:continue
        for system,options in available.items():
            current=value[system]
            if current['status'] not in ('missing','needs_source'):continue
            target=int(year) if year else current.get('year') or max(y for y,_ in options)
            matches=[]
            for candidate,path in options:
                if candidate!=target:continue
                stat=path.stat()
                index=_cached_index(str(path.resolve()),stat.st_mtime_ns,stat.st_size,system,candidate)
                matches.extend(entry for code in identifiers for entry in index.get(code,[]))
            entries=list({encode(entry):entry for entry in matches}.values())
            if not entries:continue
            conflicts={}
            for entry in entries:conflicts.setdefault((entry['category'],entry['scope']),set()).add(entry['quartile'])
            ambiguous=any(len(v)>1 for v in conflicts.values()) or len({e['title'].casefold() for e in entries})>1
            value[system]={'status':'ambiguous' if ambiguous else 'matched','year':target,'entries':entries,'match':'ISSN'}
    return result


def refresh(*, force=False, enable=False):
    store=Store();config=store.cursor('journal-ranks-public',{})
    if not config.get('enabled') and not enable:return {'status':'disabled'}
    records=bibliography.enriched(w.read_json(w.LIBRARY,{'records':[]})['records'])
    wanted={code for p in records for code in codes(p.get('issn'))};signature=w.digest(encode(sorted(wanted)))
    if not force and config.get('next_check','')>w.now() and config.get('scope_signature')==signature:return config
    with FileLock(str(w.DATA/'.journal-rank-refresh.lock'),timeout=10):
        if not wanted:return {'status':'needs_issn','enabled':True}
        response=requests.get(API,timeout=25);response.raise_for_status();items=response.json()
        if not isinstance(items,list):raise ValueError('公开分区目录格式无效')
        selected={}
        for system,pattern in PATTERNS.items():
            options=[(int(match[1]),item) for item in items if (match:=re.fullmatch(pattern,str(item.get('name','')))) and int(match[1])<=datetime.now().year]
            if options:selected[system]=max(options,key=lambda value:value[0])
        imported=[];folder=w.DATA/'期刊分区公开来源';folder.mkdir(parents=True,exist_ok=True)
        for system,(year,item) in selected.items():
            sha=str(item.get('sha',''))
            if not re.fullmatch(r'[0-9a-f]{40,64}',sha):raise ValueError('公开数据版本无效')
            source='https://raw.githubusercontent.com/hitfyd/ShowJCR/master/'+quote(FOLDER)+'/'+item['name']
            raw=folder/(system+'_'+str(year)+'_'+sha[:16]+'.csv')
            if not raw.is_file():
                download=requests.get(source,timeout=45);download.raise_for_status()
                if len(download.content)>20*1024*1024:raise ValueError('公开分区 CSV 过大')
                w.atomic_text(raw,download.content.decode('utf-8-sig'))
            content=normalized(raw.read_text('utf-8-sig'),system,year,wanted)
            if len(content.splitlines())<2:continue
            edition='新锐' if system=='XR' else '升级版' if system=='CAS' else 'JCR';metric=system if system!='JCR' else 'JIF'
            active=ranks.sources()['records']
            payload={'system':system,'year':year,'metric':metric,'edition':edition,'uri':source,
                'label':'ShowJCR 公开镜像 · '+ranks.LABELS[system]+' '+str(year),'content':content,
                'expected_sources':[s['id'] for s in active if s['active'] and s['system']==system and s['year']==year and s['metric']==metric and s['edition']==edition and s['uri']==source]}
            imported.append({'system':system,'year':year,**ranks.import_csv(payload)})
        result={'status':'saved','enabled':True,'sources':imported,'checked':w.now(),
                'next_check':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),'source':'https://github.com/hitfyd/ShowJCR',
                'scope':'公开镜像补充；保留来源及年度，不替换已导入的其他授权来源','scope_signature':signature}
        with store.connection() as db:db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)',('journal-ranks-public',encode(result),w.now()))
        return result


def scheduled_refresh():
    """A temporary public-source failure must not block notes or local syncing."""
    store=Store();previous=store.cursor('journal-ranks-public',{})
    if previous.get('retry_after','')>w.now():return previous
    try:return refresh()
    except (requests.RequestException,ValueError,OSError) as error:
        result={**previous,'status':'deferred','error_type':type(error).__name__,
                'retry_after':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}
        with store.connection() as db:db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)',('journal-ranks-public',encode(result),w.now()))
        return result
