"""PaddleOCR-VL adapter. Heavy GPU dependencies stay outside the web environment."""
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import hashlib
import sys
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
import threading
from urllib.parse import urlsplit
from html.parser import HTMLParser
from urllib.request import urlopen
from datetime import datetime, timedelta, timezone

import workspace_runtime as w

METHOD = 'paddleocr_vl_1_6'
VISUAL_LABELS = {'chart','image','header_image','footer_image','seal'}
_GPU_LOCK = threading.Lock()
_INFERENCE_SESSION = ContextVar('document_inference_session',default=False)
_PARSER_BATCH = ContextVar('document_parser_batch',default=False)
_SYNC_RETRY = ContextVar('sync_inference_retry',default=None)


class ManagedInferenceUnavailable(ValueError):
    """The managed GPU service is unavailable; existing parses are usable."""


@contextmanager
def sync_inference_retry(state):
    """Share one persisted accelerator retry window across synchronization items."""
    retry = state.setdefault('document_parser_retry', {})
    token = _SYNC_RETRY.set(retry)
    try:
        yield retry
    finally:
        _SYNC_RETRY.reset(token)
        if not retry:
            state.pop('document_parser_retry', None)


def _check_sync_retry():
    retry = _SYNC_RETRY.get()
    if retry and retry.get('retry_after', '') > w.now():
        raise ManagedInferenceUnavailable(retry['error'])


def _inference_failure(detail):
    message = '受管文档推理服务未就绪，原解析保留。'+detail
    retry = _SYNC_RETRY.get()
    if retry is not None:
        failures = min(int(retry.get('failures', 0))+1, 5)
        delay = timedelta(minutes=min(60,5*2**(failures-1)))
        retry.update(failures=failures,error=message,
                     retry_after=(datetime.now(timezone.utc)+delay).isoformat())
    return ManagedInferenceUnavailable(message)


def _registered_process_alive(entry):
    if os.name!='nt':return False
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.restype=wintypes.HANDLE
    handle=kernel.OpenProcess(0x1000,False,int(entry.get('id',0)))
    if not handle:return False
    try:
        created,exited,cpu1,cpu2=(wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle,ctypes.byref(created),ctypes.byref(exited),ctypes.byref(cpu1),ctypes.byref(cpu2)):return False
        stamp=entry['started'];started=datetime.fromisoformat(stamp)
        delta=started-datetime(1601,1,1,tzinfo=timezone.utc)
        fraction=stamp.split('.',1)[1].rstrip('Z').split('+',1)[0] if '.' in stamp else ''
        expected=((delta.days*86400+delta.seconds)*1000000+delta.microseconds)*10
        if len(fraction)>=7:expected+=int(fraction[6])
        actual=(created.dwHighDateTime<<32)|created.dwLowDateTime
        if actual!=expected or exited.dwHighDateTime or exited.dwLowDateTime:return False
        name=ctypes.create_unicode_buffer(32768);size=wintypes.DWORD(len(name))
        if not kernel.QueryFullProcessImageNameW(handle,0,name,ctypes.byref(size)):return False
        return Path(name.value)==Path(os.environ['SystemRoot'])/'System32/wsl.exe'
    except (ValueError,KeyError,TypeError):return False
    finally:kernel.CloseHandle(handle)


def _managed_inference_ready():
    entry=w.read_json(w.ROOT/'工具/OpenNotebook/进程.json',{}).get('document-parser',{})
    receipt=w.read_json(w.ROOT/'工具/日志/document-parser.linux.json',{})
    try:
        if (entry.get('ready') is not True or not entry.get('linux_nonce') or entry['linux_nonce']!=receipt.get('nonce')
                or not _registered_process_alive(entry)):return False
        with urlopen('http://127.0.0.1:8118/health',timeout=2) as response:return response.status==200
    except (OSError,ValueError):return False


@contextmanager
def inference_session():
    """Start the optional accelerator through the existing manager, once per batch."""
    config=settings()
    worker_options(config)
    if config.get('inference_backend','native')!='vllm-server' or _INFERENCE_SESSION.get():
        yield
        return
    manager=w.ROOT/'工具/OpenNotebook/管理服务.ps1'
    base=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(manager),'-Action']
    token=None;started_here=False
    try:
        if not _managed_inference_ready():
            _check_sync_retry()
            try:
                result=subprocess.run(base+['start-document-parser'],capture_output=True,timeout=360,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise _inference_failure(type(exc).__name__) from exc
            if result.returncode:
                detail=getattr(result,'stderr',b'')
                if isinstance(detail,bytes):detail=detail.decode('utf-8',errors='replace')
                raise _inference_failure(str(detail).strip()[:500])
            started_here=True
        retry = _SYNC_RETRY.get()
        if retry is not None:
            retry.clear()
        token=_INFERENCE_SESSION.set(True)
        yield
    finally:
        if token is not None:_INFERENCE_SESSION.reset(token)
        if started_here:
            primary_error=sys.exc_info()[0] is not None
            stopped=subprocess.run(base+['stop-document-parser'],capture_output=True,timeout=60,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if stopped.returncode and not primary_error:raise RuntimeError('文档任务结束，但受管推理服务释放失败；请查看服务登记。')


@contextmanager
def parser_lock():
    """One local GPU parser across CLI, imports and background synchronization."""
    if not _GPU_LOCK.acquire(blocking=False):raise ValueError('已有文档解析任务，请等待完成后接续。')
    locked=False
    try:
        path=w.DATA/'.document-parser.lock';path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('a+b') as handle:
            if not path.stat().st_size:handle.write(b'0');handle.flush()
            handle.seek(0)
            try:
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                locked=True
            except OSError as error:raise ValueError('已有文档解析任务，请等待完成后接续。') from error
            try:yield
            finally:
                if locked:
                    handle.seek(0)
                    if os.name=='nt':msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
                    else:fcntl.flock(handle,fcntl.LOCK_UN)
    finally:_GPU_LOCK.release()


def settings():
    return w.read_json(w.ROOT/'工具/工具版本.json', {}).get('document_parser', {})


def configured():
    return settings().get('enabled') is True


def worker_options(config):
    backend=config.get('inference_backend','native')
    if backend not in {'native','vllm-server'}:raise ValueError('未登记的文档推理后端。')
    values={'THZ_DOCUMENT_VLM_BACKEND':backend}
    if backend=='vllm-server':
        endpoint=config.get('endpoint','');parsed=urlsplit(endpoint)
        if (parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or parsed.port!=8118
                or parsed.path.rstrip('/')!='/v1' or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError('文档推理服务必须使用登记的本机入口。')
        values.update(THZ_DOCUMENT_VLM_URL=endpoint,THZ_DOCUMENT_LAYOUT_DEVICE='cpu')
    else:values['THZ_DOCUMENT_LAYOUT_DEVICE']='gpu:0'
    return values


class _TableText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows=[];self.row=[];self.cell=None;self.hidden=0

    def handle_starttag(self,tag,attrs):
        if tag in {'script','style'}:self.hidden+=1
        elif tag=='tr':self.row=[]
        elif tag in {'td','th'}:self.cell=[]
        elif tag=='br' and self.cell is not None:self.cell.append(' ')

    def handle_endtag(self,tag):
        if tag in {'script','style'}:self.hidden=max(0,self.hidden-1)
        elif tag in {'td','th'} and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()));self.cell=None
        elif tag=='tr' and self.row:self.rows.append(self.row);self.row=[]

    def handle_data(self,data):
        if self.cell is not None and not self.hidden:self.cell.append(data)


def _body_text(label,text):
    if label!='table' or '<table' not in text.lower():return text
    table=_TableText();table.feed(text);table.close()
    return '\n'.join('\t'.join(row) for row in table.rows)


def unit_spans(page, *, size):
    """Prefer actual block boundaries, keeping offsets in the canonical page text."""
    text = page.get('text') or ''
    blocks = [b.get('evidence_text',b.get('text','')) for b in page.get('blocks',[])
              if b.get('body_evidence',True) and isinstance(b.get('text'),str)
              and b.get('evidence_text',b['text']).strip()]
    boundaries = []
    if blocks and '\n\n'.join(blocks) == text:
        offset = 0
        for index, block in enumerate(blocks):
            offset += len(block) + (2 if index < len(blocks)-1 else 0)
            boundaries.append(offset)
    spans = []; start = 0
    while start < len(text):
        limit = min(start+size,len(text))
        end = max((n for n in boundaries if start < n <= limit), default=limit)
        spans.append((start,end)); start = end
    return spans


def validate_pages(payload, *, expected_pages):
    """Reject incomplete output before replacing any last-known parse pointer."""
    pages = payload.get('pages') if isinstance(payload, dict) else None
    if not isinstance(pages, list) or len(pages) != expected_pages:
        raise ValueError('文档解析页数不完整，原解析版本保留。')
    result = []
    for number, page in enumerate(pages, 1):
        if not isinstance(page, dict) or type(page.get('page')) is not int or page['page'] != number:
            raise ValueError('文档解析页码缺失或重复，原解析版本保留。')
        blocks = page.get('blocks')
        if not isinstance(blocks, list):raise ValueError('文档解析缺少版面区块。')
        accepted = []
        for block in blocks:
            if not isinstance(block, dict):raise ValueError('文档解析区块格式无效。')
            text, bbox = block.get('text'), block.get('bbox')
            if not isinstance(text, str) or len(text) > 2_000_000:
                raise ValueError('文档解析区块文字无效。')
            if (not isinstance(bbox, (list, tuple)) or len(bbox) != 4
                    or any(type(x) not in (int, float) or not math.isfinite(x) for x in bbox)
                    or bbox[2] < bbox[0] or bbox[3] < bbox[1]):
                raise ValueError('文档解析区块坐标无效。')
            label=str(block.get('label') or 'text')[:80]
            accepted.append({'label':label, 'text':text, 'bbox':list(bbox),
                             'order':len(accepted), 'body_evidence':label not in VISUAL_LABELS,
                             'evidence_text':_body_text(label,text)})
        text = '\n\n'.join(b['evidence_text'] for b in accepted if b['body_evidence'] and b['evidence_text'].strip())
        if len(text) > 5_000_000:raise ValueError('单页解析文字超过上限。')
        result.append({'page':number, 'text':text, 'blocks':accepted, 'method':METHOD,
                       'width':page.get('width'), 'height':page.get('height'),
                       'render_dpi':page.get('render_dpi',216)})
    return result


def parse_pdf(source):
    if _PARSER_BATCH.get():return _parse_pdf(source)
    with parser_lock(), inference_session():return _parse_pdf(source)


@contextmanager
def parser_batch():
    with parser_lock(), inference_session():
        token=_PARSER_BATCH.set(True)
        try:yield
        finally:_PARSER_BATCH.reset(token)


def _parse_pdf(source):
    config = settings()
    runtime = Path(config.get('runtime', ''))
    python = runtime/'Scripts/python.exe'
    if not config.get('enabled') or not python.is_file():
        raise ValueError('专用文档解析环境不可用；原论文和已有解析保留，请检查登记环境。')
    source = Path(source).resolve(strict=True)
    if source.suffix.lower() != '.pdf':raise ValueError('专用解析入口只接受 PDF。')
    import pymupdf
    with pymupdf.open(source) as pdf:expected = pdf.page_count
    cache = Path(config.get('cache', str(w.ROOT/'runtime/cache/document-parser')))
    cache.mkdir(parents=True, exist_ok=True)
    # Paddle's Windows C++ model loader requires an ASCII pathname. This
    # registered junction points to the same E-drive files, with no second copy.
    native_cache = Path(config.get('native_cache',str(cache)))
    env = {**os.environ, **worker_options(config), 'PYTHONUTF8':'1', 'PYTHONIOENCODING':'utf-8',
           'PADDLE_PDX_CACHE_HOME':(native_cache/'paddlex').as_posix(), 'HF_HOME':(native_cache/'huggingface').as_posix(),
           'PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK':'True'}
    # Keep only the small in-flight result beside the project's version cache.
    # The running workflow account may read the registered E-drive models while
    # lacking permission to create new directories in their cache root.
    staging = w.DATA/'正文/解析临时'
    staging.mkdir(parents=True,exist_ok=True)
    source_sha=hashlib.sha256(source.read_bytes()).hexdigest()
    checkpoint=w.DATA/'正文/解析检查点'/(source_sha+'.json')
    with tempfile.TemporaryDirectory(prefix='parse-',dir=staging) as temporary:
        output = Path(temporary)/'result.json'
        log = Path(temporary)/'worker.log'
        command = [str(python), str(w.HERE/'document_parser_worker.py'), str(source), str(output),
                   '--checkpoint',str(checkpoint)]
        if checkpoint.is_file():command += ['--resume',str(checkpoint)]
        try:
            with log.open('wb') as diagnostic:
                process = subprocess.run(command, env=env, stdout=diagnostic, stderr=subprocess.STDOUT,
                    timeout=3600, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if process.returncode or not output.is_file():
                # Logs contain paths/model diagnostics only; no model credentials are used.
                with log.open('rb') as handle:
                    handle.seek(max(0,log.stat().st_size-16000)); tail=handle.read().decode('utf-8','replace')
                w.atomic_text(w.DATA/'正文/解析错误.log',tail)
                raise ValueError('专用文档解析失败；诊断保留在正文解析错误日志，原解析未覆盖。')
            if output.stat().st_size > 200_000_000:raise ValueError('文档解析结果超过大小上限。')
            return validate_pages(json.loads(output.read_text('utf-8')), expected_pages=expected)
        except subprocess.TimeoutExpired as error:
            raise ValueError('专用文档解析超时，原解析版本保留。') from error
        finally:
            # Progress is never a usable full-text cache or a paid-model ledger.
            # Completed pages can be reused after an interrupted local GPU job.
            if output.is_file() and output.stat().st_size <= 200_000_000:
                try:
                    partial=json.loads(output.read_text('utf-8'))
                    count=len(partial.get('pages',[])) if isinstance(partial,dict) else 0
                    if (count and partial.get('source_sha256')==source_sha
                            and partial.get('pipeline_version')=='v1.6' and 0<count<=expected):
                        validate_pages(partial,expected_pages=count)
                        w.write_json(checkpoint,partial)
                except (ValueError,TypeError,OSError):pass


def repair_library(identifiers=(), *, all_pdfs=False, run=False, progress=None):
    """Preview by default; explicit IDs or --all select a bounded local migration."""
    import workflow
    import fulltext_parser
    library=w.read_json(w.LIBRARY,{}).get('records',[])
    known={r['id']:r for r in library}
    if any(identifier not in known for identifier in identifiers):raise ValueError('文献 ID 不在当前登记库中。')
    if not identifiers and not all_pdfs:raise ValueError('请指定文献 ID，或明确选择 --all。')
    rows=[]
    with ExitStack() as sessions:
        started=False
        for record in library:
            if not all_pdfs and record['id'] not in identifiers:continue
            artifact=workflow.chosen_artifact(record)
            if not artifact or artifact['kind']!='pdf':continue
            sha=w.digest(Path(artifact['path']).read_bytes())
            old=fulltext_parser.read_cache(w.DATA/'正文'/(sha+'.json'))
            current=(old.get('parser_version')==fulltext_parser.VERSION and old.get('status')=='ready'
                     and old.get('pages') and all(p.get('method')==METHOD for p in old['pages']))
            row={'id':record['id'],'sha256':sha,'status':'current' if current else 'planned'}
            if progress:progress('PDF '+str(len(rows)+1)+' · '+record['id']+' · '+row['status'])
            if run and not current:
                if not started:sessions.enter_context(parser_batch());started=True
                try:
                    parsed=workflow.extract(record,artifact,repair=True)
                    row.update(status=parsed['status'],pages=len(parsed['pages']),text_fingerprint=parsed['text_fingerprint'])
                except (ValueError,OSError,RuntimeError) as error:
                    row.update(status='failed',message=str(error))
            rows.append(row)
    failed=sum(row['status']=='failed' for row in rows)
    return {'engine':METHOD,'executed':run,'records':rows,'total':len(rows),'failed':failed,
            'status':'partial' if failed else 'completed' if run else 'preview'}


def repair_task(data=None,progress=None):
    data=data or {};ids=data.get('ids',[])
    if not isinstance(ids,list) or any(not isinstance(i,str) for i in ids):
        raise ValueError('PDF 修复范围无效。')
    return repair_library(ids,all_pdfs=data.get('all') is True,run=True,progress=progress)


if __name__=='__main__':
    import argparse
    cli=argparse.ArgumentParser(description='Preview/repair retained PDFs with the registered structured document parser.')
    cli.add_argument('--id',dest='ids',action='append',default=[])
    cli.add_argument('--all',dest='all_pdfs',action='store_true')
    cli.add_argument('--run',action='store_true')
    args=cli.parse_args()
    entry=sys.modules.setdefault('document_parser',sys.modules[__name__])
    print(json.dumps(entry.repair_library(args.ids,all_pdfs=args.all_pdfs,run=args.run),ensure_ascii=True,indent=2))
