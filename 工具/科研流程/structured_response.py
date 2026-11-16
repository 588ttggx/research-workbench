"""A single bounded retry for malformed/empty JSON; never infer missing fields or facts."""
from contextlib import contextmanager
from contextvars import ContextVar
import copy
import hashlib
import json

_RECOVERY=ContextVar('structured_response_recovery',default=None)


class ResponseValidationError(ValueError):
    """The provider answered, but its known result failed local validation."""
    def __init__(self, label, feedback, finish_reason, value=None):
        self.feedback = feedback
        self.finish_reason = finish_reason
        # Retain only the final parsed response for callers that isolate rows.
        # This value is still untrusted and must pass their full validation.
        self.value = value
        ending = '模型输出被截断。' if finish_reason == 'length' else ''
        super().__init__(label+'未完成：'+(feedback or '模型没有返回完整、合法的 JSON 对象。')
                         +' 已自动修正重试一次，仍未通过校验。'+ending+'原资料和已有关系保留。')


class ModelRequestError(ValueError):
    """Provider error with the existing paid-request ledger identity, if any."""
    def __init__(self, response):
        super().__init__(response['error'])
        self.request_id=response.get('request_id')
        self.replay_mismatch=response.get('replay_mismatch',False)


def request_released(store,request_id):
    job=store.job(request_id) if request_id else None
    return bool(job and job['kind']=='model_call' and job['status'] in ('queued','completed'))


@contextmanager
def resume_request(store,request_id):
    """Restrict recovery to the released paid request and already saved responses."""
    token=_RECOVERY.set((store,request_id) if request_id else None)
    try:yield
    finally:_RECOVERY.reset(token)


def _check_recovery(payload):
    recovery=_RECOVERY.get()
    if not recovery:return
    from model_settings import decorate
    from research_store import encode
    store,identifier=recovery
    candidate=decorate(payload)
    fingerprint=hashlib.sha256(encode({k:v for k,v in candidate.items() if not k.startswith('_')}).encode()).hexdigest()
    saved=store.job(identifier,private=True)
    if saved and saved['payload'].get('request_sha256')==fingerprint:return
    with store.connection() as db:
        cached=db.execute("SELECT 1 FROM jobs WHERE kind='model_call' AND idem=? AND status='completed'",
                          ('model:'+fingerprint,)).fetchone()
    if not cached:
        raise ModelRequestError({'error':'已核查的原请求与当前输入或设置不同，已停止自动接续。',
                                 'request_id':identifier,'replay_mismatch':True})


def request(payload, label, validator=None, *, include_metadata=False):
    from model_gateway import call_deepseek
    request_body=copy.deepcopy(payload)
    last=None
    for attempt in range(2):
        feedback=''
        value=None
        _check_recovery(request_body)
        response=call_deepseek(request_body)
        if response.get('error'):raise ModelRequestError(response)
        text=response.get('answer');last=response.get('finish_reason')
        if isinstance(text,str):
            text=text.strip().removeprefix('\ufeff')
            if text.startswith('```json\n') and text.endswith('```'):text=text[8:-3].strip()
        try:
            value=json.loads(text)
            if isinstance(value,dict):
                if validator:validator(value)
                if include_metadata:value['_model_output']={key:response.get(key) for key in ('reasoning_content','model')}
                return value
        except (ValueError,TypeError) as error:feedback=str(error)[:250] if isinstance(error,ValueError) and not isinstance(error,json.JSONDecodeError) else ''
        if attempt==0:
            request_body['messages'][0]['content']+='\n请严格返回完整且合法的 JSON 对象：所有字段名和字符串使用双引号，字符串内换行必须转义，禁止尾部逗号、注释或代码围栏。保持原 schema 和全部必需字段。'
            if label=='阅读笔记':request_body['messages'][0]['content']+='每段简洁写全，120 中文字以内；保留来源字段，不补猜测。'
            if feedback:request_body['messages'][0]['content']+='\n上一轮校验未通过：'+feedback+'。请从本次输入重新生成完整结果，严格只用对应材料的来源 ID、ref 和实际位置；背景与其他论文的页码不能用于这篇论文。未提供的发现应明确缺口，不能猜测或改用其他来源掩盖。'
    raise ResponseValidationError(label, feedback, last, value)
