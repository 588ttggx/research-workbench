import project_profiles as lifecycle
"""Filled, source-bounded reading notes; human cards and annotations stay authoritative."""
import json
import re
import threading
from pathlib import Path
import knowledge as k
import organization as org
import workflow as w
import structured_response

SECTIONS = {'problem':'研究问题', 'methods':'方法、材料与条件', 'findings':'提供材料中的主要发现',
            'figures':'数据与图表', 'relevance':'对当前课题的价值', 'limits':'限制与待核条件', 'next_step':'下一步怎么用'}
LOCK = threading.RLock()
TEXT_CHUNK = 6000
REQUEST_TEXT = 12000
REQUEST_LIMIT = 26000
READING_STEPS = 4
NOTE_STANDARD = 2


def _record_completion(identifier,paper,path,project):
    """Keep a small automatic-completion receipt; prose remains in its one file."""
    try:
        import workspace_catalog
        relative=path.relative_to(w.KB.resolve()).as_posix()
        target_id=workspace_catalog.identify(relative)
        receipt=w.DATA/'自动笔记完成.json'
        rows=w.read_json(receipt,[]) if receipt.exists() else []
        rows=[row for row in rows if row.get('target_id')!=target_id]
        rows.append({'kind':'note','target_id':target_id,'target_label':paper.get('title') or path.stem,
                     'summary':'AI 阅读笔记已更新','applied':w.now(),'automatic_applied':True,'project':project})
        w.write_json(receipt,rows[-100:])
    except (OSError,ValueError):
        pass


def note_path(identifier, kb=None):
    return ((kb or w.KB)/'文献/AI阅读记录'/('论文笔记_'+w.digest(identifier)[:20]+'.md')).resolve()


def text_paper(paper):
    """Bound each source without dropping any characters or inventing PDF pages."""
    sources=[]
    for source in paper.get('sources',[]):
        # Cards and generated notes are commentary, never another copy of original text.
        if source.get('kind')!='fulltext_excerpt':continue
        text=str(source.get('text') or '')
        if not text:continue
        for start in range(0,len(text),TEXT_CHUNK):
            part={key:source[key] for key in ('ref','kind','location','method') if key in source}
            if len(text)>TEXT_CHUNK:
                part['ref']=source['ref']+'-part-'+str(start//TEXT_CHUNK+1)
                part['location']=source['location']+' · 字符 '+str(start+1)+'–'+str(min(start+TEXT_CHUNK,len(text)))
            part['text']=text[start:start+TEXT_CHUNK]
            sources.append(part)
    return {key:paper.get(key) for key in ('id','title','doi')}|{'sources':sources}


def original_text(paper):
    state=w.read_json(w.DATA/'state.json',{})
    sha=state.get('papers',{}).get(paper['id'],{}).get('sha256')
    if not isinstance(sha,str) or not re.fullmatch(r'[a-f0-9]{64}',sha):return '',None
    import fulltext_parser
    cached=fulltext_parser.read_cache(w.DATA/'正文'/(sha+'.json'),usable_only=True)
    if cached.get('sha256')!=sha:return sha,None
    return sha,''.join(str(page.get('text') or '') for page in cached.get('pages',[]))


def reading_signature(paper):
    # Project progress, mainlines and purposes must not invalidate original-text work.
    sha,_=original_text(paper)
    return w.digest(json.dumps({'paper':paper,'original_sha256':sha,'note_standard':NOTE_STANDARD},ensure_ascii=False,sort_keys=True))


def reading_coverage(paper, processed):
    sha,cached_text=original_text(paper)
    sources=paper['sources']
    fulltext=[source for source in sources if source.get('kind')=='fulltext_excerpt']
    text=''.join(source['text'] for source in fulltext)
    return {'original_sha256':sha,'source_text_sha256':w.digest(text),
            'supplied_chunks':len(sources),'processed_chunks':processed,
            'locations':list(dict.fromkeys(source['location'] for source in sources[:processed])),
            'text_complete':bool(cached_text and text==cached_text and processed==len(sources)),
            'figures_checked':False,'verification':'ai_text_only'}


def reading_cache_path(identifier):
    return w.DATA/'阅读笔记/正文'/(w.digest(identifier)[:24]+'.json')


def read_text(paper, signature, instructions, *, force=False):
    """Resume bounded rolling synthesis; successful chunks survive later failures."""
    path=reading_cache_path(paper['id'])
    saved=w.read_json(path,{})
    if saved.get('fingerprint')!=signature:
        saved={'fingerprint':signature,'processed_chunks':0,'entry':None}
    if force and saved.get('complete'):
        # An explicit refresh revisits the compact draft, without paying to reread text.
        return saved
    sources=paper['sources']
    cursor=saved.get('processed_chunks',0)
    if type(cursor) is not int or not 0<=cursor<=len(sources):raise ValueError('正文阅读进度无效，原稿保留。')
    if saved.get('complete') and saved.get('entry') is not None:return saved
    for _ in range(READING_STEPS):
        batch=[];size=0
        while cursor+len(batch)<len(sources) and len(batch)<12:
            source=sources[cursor+len(batch)]
            if size+len(source['text'])>REQUEST_TEXT:break
            candidate=batch+[source]
            incoming={'papers':[{**paper,'sources':candidate}],'previous_note':saved.get('entry')}
            if len(json.dumps(incoming,ensure_ascii=False))>REQUEST_LIMIT:break
            batch=candidate;size+=len(source['text'])
        if not batch and sources:raise ValueError('本段阅读输入超出上限，原稿保留。')
        end=cursor+len(batch)
        # Older citations remain valid only for chunks already processed successfully.
        available={**paper,'sources':sources[:end]}
        def check(plan):
            entry=validate(plan,[available])[paper['id']]
            if any(len(section['text'])>500 or len(section['source_refs'])>4 for section in entry['sections'].values()):
                raise ValueError('阅读笔记每段最多 500 字、4 个来源，请精简并保留关键事实。')
        incoming={'papers':[{**paper,'sources':batch}],'previous_note':saved.get('entry')}
        plan=structured_response.request({'model':'deepseek-flash','thinking':{'type':'disabled'},
             'response_format':{'type':'json_object'},'max_tokens':4500,
             'messages':[{'role':'system','content':instructions},
                         {'role':'user','content':json.dumps(incoming,ensure_ascii=False)}]},'阅读笔记',check)
        saved.update(entry=validate(plan,[available])[paper['id']],processed_chunks=end,
                     complete=end==len(sources),coverage=reading_coverage(paper,end),updated=w.now())
        w.write_json(path,saved)
        cursor=end
        if saved['complete']:return saved
    return saved


def validate(plan, papers):
    rows=plan.get('papers') if isinstance(plan,dict) else None
    known={paper['id']:paper for paper in papers}
    if not isinstance(rows,list) or len(rows)!=len(papers): raise ValueError('本批阅读笔记未完整返回，已有笔记保留。')
    result={}
    for row in rows:
        if not isinstance(row,dict) or row.get('id') not in known or row['id'] in result: raise ValueError('阅读笔记返回未知或重复文献。')
        paper=known[row['id']]; sources={source['ref']:source for source in paper['sources']}
        sections=row.get('sections')
        if not isinstance(sections,dict) or set(sections)!=set(SECTIONS): raise ValueError('阅读笔记缺少规定的内容。')
        entry={'title':org.short_text(row.get('title'),200,'笔记标题'),'purpose':org.short_text(row.get('purpose'),650,'笔记用途'),'sections':{}}
        for key,item in sections.items():
            if not isinstance(item,dict): raise ValueError('阅读笔记段落格式无效。')
            text=org.short_text(item.get('text'),1800,'笔记正文'); refs=item.get('source_refs',[])
            if not isinstance(refs,list) or any(not isinstance(ref,str) or ref not in sources for ref in refs): raise ValueError('阅读笔记引用了未提供的来源。')
            cited=set(re.findall(r'PDF\s*第?\s*(\d+)\s*页',text))
            available={page for ref in refs for page in re.findall(r'PDF\s*第?\s*(\d+)\s*页',sources[ref]['location']+' '+sources[ref].get('text',''))}
            if not cited.issubset(available): raise ValueError('阅读笔记包含未提供的 PDF 页码。')
            if key in ('methods','findings','figures') and not refs and not re.search(r'不足|未提供|无法|待核|仅题录|缺少',text): raise ValueError('无来源的实验方法或结果不能写成已知事实。')
            entry['sections'][key]={'text':text,'source_refs':list(dict.fromkeys(refs))}
        result[row['id']]=entry
    return result


def render(paper, entry, project, coverage=None):
    title=entry['title']+' · 阅读笔记'
    properties={'type':'ai_paper_note','title':title,'paper_id':paper['id'],'project':project,'status':'AI 整理 · 待核查','generated':w.now()}
    if coverage is not None:properties['reading_coverage']=coverage
    raw=k.properties('',properties)
    raw+='# '+title+'\n\n## 本笔记的用途\n\n'+entry['purpose']+'\n\n'
    raw+='原始题名：'+paper['title']+'\n\n文献 ID：[[文献/条目/'+paper['id']+']]；DOI：'+str(paper.get('doi') or '未登记')+'。\n\n'
    raw+='## 实际材料与阅读范围\n\n'
    if coverage is not None:
        raw+='本次分段处理 '+str(coverage['processed_chunks'])+'/'+str(coverage['supplied_chunks'])+' 个文字块；'
        raw+='已覆盖全部已缓存文字。' if coverage['text_complete'] else '阅读范围限于本次提供文字，未确认覆盖完整正文缓存。'
        raw+='这是 AI 文字整理，OCR 与索引可能遗漏内容；原图未核查，图题不能代替看图，不提升人工核查等级。\n\n'
    else:
        raw+='AI 基于已提供的材料整理；本次未重新核查整篇原文，不提升阅读等级。\n\n'
    locations=list(dict.fromkeys(source['location'] for source in paper['sources']))
    raw+='\n'.join('- '+location for location in locations[:12]) if locations else '只有题录，缺少原文和结果证据。'
    if len(locations)>12:raw+='\n- 其余 '+str(len(locations)-12)+' 处文字定位见本笔记阅读覆盖记录。'
    sources={source['ref']:source for source in paper['sources']}
    for key,label in SECTIONS.items():
        section=entry['sections'][key]; raw+='\n\n## '+label+'\n\n'+section['text']+'\n'
        raw+='\n依据：'+('；'.join(paper['id']+' · '+sources[ref]['location'] for ref in section['source_refs']) or 'AI 使用建议或材料缺口，不是已核查文献发现')+'。\n'
    raw+='\n## 我的批注\n\n可直接编辑这份笔记并添加批注。后续修改建议集中在本笔记的更新预览，核对后保存。\n'
    from material_cleanup import compact_paper_note
    _,body,_=k.split(raw)
    body=compact_paper_note(body)
    # The catalog can call this note AI-maintained only while this hash still
    # matches the body; a later human edit turns the projection to mixed.
    properties['managed_hash']=w.digest(body.rstrip())
    return k.properties('',properties)+body.rstrip()+'\n'


@lifecycle.automatic
def generate(data):
    with LOCK:
        return generate_locked(data)


def generate_locked(data):
    from model_gateway import model_status
    project=data.get('project') or '山药'; papers,_=org.paper_inputs(project)
    papers=[text_paper(paper) for paper in papers]
    ledger_path=w.DATA/'阅读笔记'/('状态_'+w.digest(project)[:16]+'.json'); ledger=w.read_json(ledger_path,{})
    records={record['id']:record for record in w.read_json(w.KB/'文献/library.json',{'records':[]})['records']}
    selected=data.get('paper_ids')
    if selected is not None:
        known={paper['id'] for paper in papers}
        if not isinstance(selected,list) or not 1<=len(selected)<=3 or any(not isinstance(i,str) or i not in known for i in selected):raise ValueError('请选择当前课题的 1–3 篇论文更新笔记。')
        papers=[p for p in papers if p['id'] in selected]
    if 'force' in data and type(data['force']) is not bool:raise ValueError('笔记更新选项无效。')
    import note_management as notes
    archived_paths=notes.archived_paths()
    pending=[]; fingerprints={};trashed=[];archived=[];needs_fulltext=[]
    for paper in papers:
        relative=note_path(paper['id']).relative_to(w.KB.resolve()).as_posix()
        if notes.suppressed(relative):trashed.append(paper['id']);continue
        if relative in archived_paths:archived.append(paper['id']);continue
        card=records[paper['id']].get('reading_card')
        if card:
            path=Path(card) if Path(card).is_absolute() else w.KB/card
            if not data.get('force') and path.resolve().is_relative_to(w.KB.resolve()) and path.resolve().relative_to(w.KB.resolve()).as_posix() not in archived_paths and path.is_file() and path.read_text('utf-8-sig').strip():
                meta=k.split(path.read_text('utf-8-sig'))[0]
                if meta.get('maintenance_owner')=='human':continue
                if meta.get('standard_template') is not True and meta.get('type')!='ai_paper_note':continue
        note=note_path(paper['id'])
        if note.is_file():
            meta=k.split(note.read_text('utf-8-sig'))[0]
            if meta.get('maintenance_owner')=='human':continue
        if not any(source.get('kind')=='fulltext_excerpt' for source in paper['sources']):needs_fulltext.append(paper['id']);continue
        signature=reading_signature(paper)
        fingerprints[paper['id']]=signature
        if data.get('force') or ledger.get(paper['id'],{}).get('fingerprint')!=signature or not note_path(paper['id']).is_file():pending.append(paper)
    if not pending:return {'written':0,'remaining':0,'paths':[],'reused':True,'trashed':trashed,'archived':archived,'needs_fulltext':needs_fulltext}
    if not model_status()['configured']:return {'status':'needs_configuration','written':0,'remaining':len(pending)}
    # One article at a time. Long texts resume in later maintenance runs.
    batch=pending[:1]
    schema={'papers':[{'id':'输入 ID','title':'简洁、准确的中文标题','purpose':'一句说明保留原因，避免与 relevance 重复','sections':{key:{'text':'具体事实、条件或缺口；通常 1–3 句，不凑字数','source_refs':['输入 ref；建议或缺口可空']} for key in SECTIONS}}]}
    instructions=org.skill_text('reading')+'\n只返回 JSON：'+json.dumps(schema,ensure_ascii=False)
    read=read_text(batch[0],fingerprints[batch[0]['id']],instructions,force=data.get('force',False))
    if not read.get('complete'):
        return {'written':0,'remaining':len(pending),'paths':[],'previews':[],'reused':False,
                'reading':{'paper_id':batch[0]['id'],**read['coverage']}}
    entries={batch[0]['id']:read['entry']};current,_=org.paper_inputs(project)
    current_by_id={paper['id']:text_paper(paper) for paper in current}
    if any(paper['id'] not in current_by_id or reading_signature(current_by_id[paper['id']])!=fingerprints[paper['id']] for paper in batch):raise ValueError('原文在笔记整理期间变化，原稿保留，下轮重试。')
    paths=[];previews=[]
    with lifecycle.automatic_commit(project), k.editing():
        for paper in batch:
            identifier=paper['id'];path=note_path(identifier);prior=ledger.get(identifier,{})
            before=path.read_text('utf-8-sig') if path.exists() else ''
            raw=render(paper,entries[identifier],project,read['coverage'])
            before_meta=k.split(before)[0] if before else {}
            # Keep one manuscript. Explicit human ownership stops automatic
            # rewrite; mixed ownership always goes through a preview.
            if before and (before_meta.get('maintenance_owner')=='mixed' or w.digest(before)!=prior.get('saved_hash')):
                import ai_updates
                current=k.read(path.relative_to(w.KB.resolve()).as_posix())
                target={'kind':'document','path':current['path'],'title':current['title'],'before':current['body'],'fingerprint':current['fingerprint']}
                proposal=ai_updates.store_proposal(target,{'kind':'document','body':k.split(raw)[1],'summary':'阅读材料更新，核对后修改同一份笔记。'},'保留原批注，对照新来源核对阅读笔记',project,automatic=True,already_locked=True)
                previews.append(proposal['id'])
                saved_hash=prior.get('saved_hash') if prior.get('path')==current['path'] else None
            else:
                k.persist(path,before,raw,w.KB.resolve());saved_hash=w.digest(raw)
                _record_completion(identifier,paper,path,project)
            ledger[identifier]={'fingerprint':fingerprints[identifier],'saved_hash':saved_hash,'path':path.relative_to(w.KB.resolve()).as_posix(),'updated':w.now(),'reading_coverage':read['coverage']}
            paths.append(path.relative_to(w.KB.resolve()).as_posix())
        w.write_json(ledger_path,ledger)
    from workspace import refresh_views
    refresh_views()
    return {'written':len(paths),'remaining':len(pending)-len(batch),'paths':paths,'previews':previews,'reused':False}
