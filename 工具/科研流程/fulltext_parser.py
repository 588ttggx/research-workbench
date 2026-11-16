"""Local text quality and immutable parse caches; cache reads never start OCR."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import unicodedata
import threading

VERSION = 'fulltext-parser-v3'
_OCR = None
_CACHE_LOCK = threading.RLock()


def text_changed(previous, current):
    fingerprint = previous.get('text_fingerprint')
    if fingerprint: return fingerprint != current.get('text_fingerprint')
    # Deploying checks does not invalidate healthy legacy work. A real reparse
    # with different text does, including old jobs that predate fingerprints.
    return (not current.get('legacy_cache', True)
            and current.get('previous_text_fingerprint') != current.get('text_fingerprint'))


def text_quality(text, *, method=None, confidence=None):
    chars = [c for c in str(text or '') if not c.isspace()]
    count = len(chars)
    if not count:
        return {'status':'empty', 'characters':0, 'reasons':[]}
    control = sum(unicodedata.category(c) == 'Cc' for c in chars)
    replacement = chars.count('\ufffd')
    letters = sum(unicodedata.category(c)[0] in 'LN' for c in chars)
    private = sum(unicodedata.category(c) == 'Co' for c in chars)
    reasons = []
    if control >= 3 and control/count > .001: reasons.append('invalid_control_characters')
    if replacement >= 3 or replacement/count > .02: reasons.append('replacement_characters')
    if count >= 100 and letters/count < .45: reasons.append('unreadable_symbol_stream')
    if private/count > .15: reasons.append('unmapped_font_glyphs')
    if method == 'local_ocr' and confidence is not None and confidence < .75:
        reasons.append('low_ocr_confidence')
    return {'status':'low_quality_text' if reasons else 'ready', 'characters':count,
            'reasons':reasons, 'control_characters':control, 'replacement_characters':replacement}


def assess_cache(cache):
    """Cheap checks for old caches too, without rewriting their provenance."""
    if not isinstance(cache, dict) or not isinstance(cache.get('pages'), list): return {}
    pages = []
    for page in cache['pages']:
        quality = text_quality(page.get('text'), method=page.get('method'),
                               confidence=page.get('ocr_mean_confidence'))
        pages.append({**page, 'quality':quality})
    fingerprint = hashlib.sha256(json.dumps(
        [[p.get('page'), p.get('section'), p.get('text') or ''] for p in pages],
        ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
    status = ('low_quality_text' if any(p['quality']['status']=='low_quality_text' for p in pages)
              else 'ready' if any(p['quality']['status']=='ready' for p in pages) else 'unparsed')
    return {**cache, 'pages':pages, 'status':status, 'text_fingerprint':fingerprint,
            'legacy_cache':not bool(cache.get('parser_version')),
            'quality_failed_locations':[p.get('page') or p.get('section') or i+1
                                        for i,p in enumerate(pages) if p['quality']['status']=='low_quality_text']}


@lru_cache(maxsize=160)
def _read_assessed(path, size, modified):
    # File metadata is part of the key. Repeated graph/status reads reuse the
    # assessment; a completed atomic replacement invalidates it automatically.
    return assess_cache(json.loads(Path(path).read_text('utf-8-sig')))


def read_cache(legacy_path, *, usable_only=False):
    legacy_path = Path(legacy_path)
    pointer = legacy_path.with_name(legacy_path.stem+'.current.json')
    path = legacy_path
    try:
        if pointer.exists():
            current = json.loads(pointer.read_text('utf-8-sig'))
            name = current.get('cache_file', '')
            if not re.fullmatch(r'fulltext-parser-v[0-9]+-[a-f0-9]{64}\.json', name): return {}
            path = legacy_path.parent/'解析版本'/legacy_path.stem/name
        stat = path.stat()
        # Keep the LRU lookup inside the lock: lru_cache alone allows several
        # cold requests to repeat the same expensive Unicode quality scan.
        with _CACHE_LOCK:
            cached = _read_assessed(str(path.resolve()), stat.st_size, stat.st_mtime_ns)
        return {} if usable_only and cached.get('status')!='ready' else cached
    except (OSError, ValueError, TypeError):
        return {}


def ocr_page(page):
    global _OCR
    import pymupdf
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR
    if _OCR is None: _OCR = RapidOCR(intra_op_num_threads=4, inter_op_num_threads=2)
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
    image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
        pixmap.height, pixmap.width, pixmap.n)[:, :, ::-1].copy()
    lines, _ = _OCR(image); lines = lines or []
    return ('\n'.join(line[1] for line in lines),
            round(sum(float(line[2]) for line in lines)/len(lines), 3) if lines else 0)


def extract(artifact, legacy_path, sha, *, repair=False):
    """Existing bad caches wait for explicit repair; new PDFs OCR suspect pages."""
    import workspace_runtime as w
    import document_parser
    old = read_cache(legacy_path)
    if old and not repair: return old
    pages = []
    if artifact['kind']=='pdf' and document_parser.configured():
        pages = document_parser.parse_pdf(artifact['path'])
    elif artifact['kind']=='pdf':
        import pymupdf
        with pymupdf.open(artifact['path']) as pdf:
            document_pages=list(pdf)
            texts=[page.get_text(sort=True).strip() for page in document_pages]
            damaged=sum(text_quality(text)['status']=='low_quality_text' for text in texts)
            # A broken font map can emit plausible ASCII on a few pages too.
            # When most pages are corrupt, OCR all pages using that text layer.
            font_mapping_failure=damaged>=max(1,(len(texts)+1)//2)
            for number, (page,text) in enumerate(zip(document_pages,texts), 1):
                prior = next((p for p in old.get('pages', []) if p.get('page')==number), None)
                if prior and prior['quality']['status']=='ready' and not font_mapping_failure:
                    pages.append(prior); continue
                method = 'text_layer'; confidence = None
                if font_mapping_failure or len(''.join(text.split())) < 40 or text_quality(text)['status']=='low_quality_text':
                    text, confidence = ocr_page(page); method = 'local_ocr'
                pages.append({'page':number, 'text':text, 'method':method,
                              'ocr_mean_confidence':confidence})
    else:
        import xml.etree.ElementTree as ET
        tree = ET.parse(artifact['path']).getroot()
        for element in list(tree.findall('.//abstract')) + list(tree.findall('.//body')):
            pages.append({'page':None, 'section':element.tag,
                          'text':' '.join(p.strip() for p in element.itertext() if p.strip()), 'method':'jats_xml'})
        if not pages: pages=[{'page':None, 'text':' '.join(tree.itertext()), 'method':'xml_fallback'}]
    return store_pages(artifact,legacy_path,sha,pages,previous=old)


def store_pages(artifact, legacy_path, sha, pages, *, previous=None):
    """Publish a complete parse only after its page and text checks succeed."""
    import workspace_runtime as w
    import document_parser
    old = previous if previous is not None else read_cache(legacy_path)
    result = assess_cache({'sha256':sha, 'pages':pages, 'original':str(artifact['path']),
                           'kind':artifact['kind'], 'created':w.now(), 'parser_version':VERSION,
                           'previous_text_fingerprint':old.get('text_fingerprint')})
    if any(page.get('method')==document_parser.METHOD for page in pages) and result['status']!='ready':
        raise ValueError('专用解析文字质量未通过，已有解析版本保留，请按原页核对异常。')
    parse_digest=hashlib.sha256(json.dumps([result['text_fingerprint'],
        [{key:value for key,value in page.items() if key!='quality'} for page in result['pages']]],
        sort_keys=True,separators=(',', ':')).encode('utf-8')).hexdigest()
    name = VERSION+'-'+parse_digest+'.json'
    destination = Path(legacy_path).parent/'解析版本'/sha/name
    if not destination.exists(): w.write_json(destination, result)
    w.write_json(Path(legacy_path).with_name(sha+'.current.json'), {'cache_file':name})
    return result
