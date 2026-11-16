"""Shared admission and reading-state rules for the one literature library."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import knowledge as k
import workflow as w


def eligible(record, project=None, linked=()):
    if w.chosen_artifact(record) is None:
        return False
    return project is None or record.get('project') == project or record['id'] in linked


def original_availability(record):
    """Availability never decides whether an already registered identity survives."""
    if eligible(record):
        return 'fulltext_on_disk'
    if any(a.get('kind') in ('pdf', 'jats_xml') for a in record.get('artifacts', [])):
        return 'original_missing'
    return 'metadata_only'


def registered(record):
    """Legacy bare clues stay out; retained library records remain navigable."""
    return bool(record.get('availability') or record.get('reading_card')
                or record.get('artifacts'))


def candidate_records(candidates=None):
    """Keep pending bibliographic identities in the existing discovery inbox."""
    candidates = candidates if candidates is not None else __import__('radar_inbox').snapshot()
    return [deepcopy(row['workspace_record']) for row in candidates['records'] if isinstance(row.get('workspace_record'), dict)]


def candidate_record(*, identifier=None, doi=None, zotero_key=None, candidates=None):
    normalized = w.normalize_doi(doi)
    source = candidates if candidates is not None else __import__('radar_inbox').snapshot()
    for row in source['records']:
        record = row.get('workspace_record')
        if not isinstance(record, dict):continue
        if (identifier and record.get('id') == identifier
                or normalized and w.normalize_doi(record.get('doi')) == normalized
                or zotero_key and record.get('zotero_key') == zotero_key):
            return deepcopy(record)
    return None


def _identity_keys(record, candidate=False):
    native = record.get('workspace_record') if candidate else record
    native = native if isinstance(native, dict) else {}
    keys = []
    identifier = record.get('workspace_id') if candidate else record.get('id')
    if identifier:keys.append(('id', identifier))
    doi = w.normalize_doi(record.get('doi'))
    if doi:keys.append(('doi', doi))
    if native.get('zotero_key'):keys.append(('zotero', native['zotero_key']))
    if record.get('openalex_id'):keys.append(('openalex', record['openalex_id']))
    if record.get('external_id'):keys.append(('external', record.get('source'), record['external_id']))
    return keys


def _update_candidate_rows(candidates, records, outcomes):
    """Merge one batch in memory, indexing the large inbox only once."""
    index = {}
    for row in candidates['records']:
        for key in _identity_keys(row, candidate=True):index.setdefault(key, row)
    changed = False
    for record in records:
        available = record['availability'] == 'fulltext_on_disk'
        row = next((index[key] for key in _identity_keys(record) if key in index), None)
        if row is None:
            if available:continue
            row = {'source': '本机待全文题录', 'external_id': record['id'],
                   'first_seen': w.now(), 'selected': False}
            candidates['records'].append(row)
            changed = True
        before = deepcopy(row)
        row.update({key: deepcopy(record[key]) for key in (
            'title', 'doi', 'project', 'url', 'openalex_id', 'journal', 'issn',
            'creators', 'publication_date', 'year', 'abstract') if record.get(key)})
        row.update(workspace_id=record['id'], workspace_record=deepcopy(record),
                   evidence_status='fulltext_on_disk' if available else 'pending_fulltext')
        if record['id'] in outcomes:
            row['acquisition'] = deepcopy(outcomes[record['id']])
        elif not available and not row.get('acquisition'):
            row['acquisition'] = {'id': record['id'], 'status': 'no_open_fulltext',
                                  'checked': w.now(), 'message': '题录已保留，取得全文后再进入活动文献库。'}
        changed = changed or row != before
        for key in _identity_keys(row, candidate=True):index.setdefault(key, row)
    return changed


def admit_many(records, library, outcomes=None, candidates=None):
    """Apply a batch with one inbox write, and no write for unchanged input.

    Zotero and original files remain untouched. Pending identities retain their
    workspace ID and reading scope until an actual local full text arrives.
    Already registered records remain in the library if originals become unavailable.
    The locked merge checks source identity and rereads only after concurrent changes.
    """
    records = list({record['id']: record for record in records}.values())
    if not records:return set()
    existing={r['id']:r for r in library['records']}
    before_availability={key:row.get('availability') for key,row in existing.items()}
    for record in records:
        previous=existing.get(record['id'])
        if not previous or previous is record:continue
        for field, value in previous.items():
            record.setdefault(field, deepcopy(value))
        if previous.get('reading_card') and not record.get('reading_card'):
            record['reading_card'] = previous['reading_card']
        # Incoming metadata and XML are additions to the source inventory. They
        # cannot remove registered PDFs, annotations or an explicit reading scope.
        artifacts={str(Path(a['path']).resolve()).casefold():deepcopy(a) for a in previous.get('artifacts',[])}
        for artifact in record.get('artifacts',[]):
            key=str(Path(artifact['path']).resolve()).casefold()
            artifacts[key]={**artifacts.get(key,{}),**artifact}
        record['artifacts']=list(artifacts.values())
        if (previous.get('reading_status_updated') and (not record.get('reading_status_updated') or str(record['reading_status_updated'])<=str(previous['reading_status_updated']))
                or not record.get('reading_status_updated') and previous.get('reading_status') not in (None, '', 'unread', '未读')):
            for field in ('reading_status','reading_scope','reading_status_updated'):
                if field in previous:record[field]=previous[field]
    available = set()
    for record in records:
        record['availability'] = original_availability(record)
        fulltext = record['availability'] == 'fulltext_on_disk'
        if fulltext:available.add(record['id'])
    outcomes = outcomes or {}
    from radar_inbox import candidate_edit
    with candidate_edit(candidates) as current:
        _update_candidate_rows(current, records, outcomes)
    incoming = {record['id']: record for record in records}
    present = {record['id'] for record in library['records']}
    library['records'] = [incoming.get(record['id'], record) for record in library['records']]
    library['records'].extend(record for record in records if record['id'] in available and record['id'] not in present)
    changes = [record for record in records if record['id'] in existing
               and before_availability[record['id']] != record['availability']]
    if changes:
        from research_store import Store
        with Store().connection() as db:
            for record in changes:
                Store.log(db, 'paper.availability_changed', record['id'], {
                    'before': before_availability[record['id']], 'after': record['availability'],
                    'registration_retained': True,
                    'registered_paths': [a['path'] for a in record.get('artifacts', [])
                                         if a.get('kind') in ('pdf', 'jats_xml')],
                })
    return available


def admit(record, library, outcome=None, *, candidates=None):
    outcomes = {record['id']: outcome} if outcome is not None else None
    return record['id'] in admit_many([record], library, outcomes, candidates=candidates)


def reading_state(record, entry=None, kb=None):
    """A dated explicit edit wins; an undated generated entry cannot undo a review."""
    kb = kb or w.KB
    entry = entry or {}
    labels = {'未读':'unread', '阅读范围见历史记录':'see_linked_historical_review_scope',
              '待核查阅读范围':'not_asserted_by_this_import'}
    state = {'reading_status':record.get('reading_status') or 'unread',
             'reading_scope':record.get('reading_scope') or ''}
    def stamp(value):
        try:
            date = datetime.fromisoformat(str(value).replace('Z','+00:00'))
            return date.replace(tzinfo=timezone.utc).timestamp() if date.tzinfo is None else date.timestamp()
        except (ValueError, TypeError):
            return 0
    reviewed = stamp(record.get('reading_status_updated'))
    card = record.get('reading_card')
    if card:
        path = (Path(card) if Path(card).is_absolute() else kb/card).resolve()
        if path.is_relative_to(kb.resolve()) and path.is_file():
            meta, _, _ = k.split(path.read_text('utf-8-sig'))
            if meta.get('status') == '已核查指定范围' and meta.get('reading_scope') and meta.get('standard_template') is not True:
                card_date = meta.get('status_updated') or meta.get('reviewed_date')
                if stamp(card_date) >= reviewed:
                    state.update(reading_status=meta['status'], reading_scope=meta['reading_scope'])
                    reviewed = stamp(card_date)
                    if card_date:state['reading_status_updated'] = str(card_date)
    native = entry.get('status')
    if isinstance(native,str) and len(native)<=100:
        dated = stamp(entry.get('status_updated'))
        if dated > reviewed or (not reviewed and state['reading_status'] != '已核查指定范围'):
            state['reading_status'] = labels.get(native,native)
            if entry.get('reading_scope'):state['reading_scope'] = entry['reading_scope']
            if entry.get('status_updated'):state['reading_status_updated'] = str(entry['status_updated'])
    return state


def chunks(text, size=6000):
    """Keep every supplied character, with bounded request units and stable order."""
    text = str(text or '')
    return [text[start:start+size] for start in range(0,len(text),size)]


def fulltext_sources(record, state=None, *, size=6000):
    """Return every current cached original-text unit, without project selection.

    The cache is usable only when its SHA matches the actual retained attachment.
    Metadata, cards and AI notes are deliberately absent from this source stream.
    Offsets refer to a single PDF page / XML section, never invented PDF pages.
    """
    import re
    from organization import current_artifact_sha
    state = state if state is not None else w.read_json(w.DATA/'state.json', {})
    sha = state.get('papers', {}).get(record['id'], {}).get('sha256', '')
    result = {'source_id':record['id'], 'source_sha256':sha, 'status':'unparsed', 'units':[]}
    artifact = w.chosen_artifact(record)
    if artifact is None:
        result['status']='missing_original'
        return result
    try:
        actual_sha=current_artifact_sha(artifact)
    except OSError:
        result['status']='missing_original'
        return result
    if not isinstance(sha,str) or not re.fullmatch(r'[a-f0-9]{64}',sha):
        return result
    if actual_sha != sha:
        result['status']='stale_cache'
        return result
    import fulltext_parser
    cached=fulltext_parser.read_cache(w.DATA/'正文'/(sha+'.json'))
    if cached.get('sha256') != sha:
        return result
    result.update({key:cached.get(key) for key in ('text_fingerprint','parser_version','legacy_cache',
                    'previous_text_fingerprint','quality_failed_locations')})
    if cached.get('status')=='low_quality_text':
        result['status']='low_quality_text';return result
    pages=cached.get('pages',[])
    result['cached_pages']=len(pages);result['expected_pages']=None
    if artifact.get('kind')=='pdf':
        try:
            import pymupdf
            with pymupdf.open(artifact['path']) as pdf:expected=pdf.page_count
            result['expected_pages']=expected
            if {p.get('page') for p in pages}!=set(range(1,expected+1)):
                result['status']='partial_parse';return result
        except (OSError,RuntimeError,ValueError):return result
    result['empty_text_locations']=[p.get('page') or p.get('section') or index+1 for index,p in enumerate(pages) if not str(p.get('text') or '').strip()]
    result['methods']=sorted({p.get('method','unknown') for p in pages})
    for page_index,page in enumerate(pages):
        text=str(page.get('text') or '')
        location=('PDF 第 '+str(page['page'])+' 页' if page.get('page') else
                  'XML '+str(page.get('section') or '正文'))
        from document_parser import unit_spans
        for start,end in unit_spans(page,size=size):
            part=text[start:end]
            if not part.strip():continue
            result['units'].append({'ref':'excerpt-'+str(page_index)+'@'+str(start),
                'kind':'fulltext_excerpt','location':location,'page':page.get('page'),
                'section':page.get('section'),'start':start,'end':start+len(part),
                'text':part,'method':page.get('method')})
    if result['units']:result['status']='ready'
    return result
