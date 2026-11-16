"""Use Open Notebook's encrypted credential without exposing the key to the UI."""
import asyncio
import json
import os
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[1] / 'OpenNotebook/open-notebook-1.15.0'
sys.path.insert(0,str(APP))
from dotenv import load_dotenv


def _load_environment():
    """Load .env, but merge its NO_PROXY with the system one instead of replacing it.

    .env only needs to keep localhost off the proxy; dropping the system exclusions
    would push api.deepseek.com through a proxy the user configured for other hosts.
    """
    system_no_proxy = os.environ.get('NO_PROXY') or os.environ.get('no_proxy') or ''
    load_dotenv(APP/'.env',override=True)
    entries = []
    for value in (os.environ.get('NO_PROXY',''), system_no_proxy):
        for item in value.split(','):
            item = item.strip()
            if item and item not in entries:
                entries.append(item)
    os.environ['NO_PROXY'] = os.environ['no_proxy'] = ','.join(entries)


_load_environment()

import requests  # noqa: E402 - loaded after .env so proxy settings are settled
import proxy_policy  # noqa: E402 - same reason

ENDPOINT = 'https://api.deepseek.com'


def _open(url):
    """按配置与可用性选代理：配置了且连得上才走，否则直连；NO_PROXY 始终生效。"""
    session = requests.Session()
    session.trust_env = False
    return session, proxy_policy.proxies_for(url) or {}


def _failure_detail(error):
    """把失败变成一句可展示的具体原因；不包含密钥、请求头或供应商响应体。"""
    if isinstance(error, requests.exceptions.ProxyError):
        return '代理连接失败（配置的代理不可用）'
    if isinstance(error, requests.exceptions.ConnectTimeout):
        return '连接 api.deepseek.com 超时'
    if isinstance(error, requests.exceptions.ReadTimeout):
        return '等待 DeepSeek 响应超时'
    if isinstance(error, requests.exceptions.SSLError):
        return '与 api.deepseek.com 的 TLS 握手失败'
    if isinstance(error, requests.exceptions.ConnectionError):
        return '无法连接 api.deepseek.com（网络不可达）'
    if isinstance(error, KeyError):
        return f'返回缺少字段 {error}'
    if isinstance(error, IndexError):
        return '返回结构不完整（choices 为空）'
    if isinstance(error, ValueError):
        return '响应内容不是有效的 JSON'
    text = ' '.join(str(error).split())[:160]
    return f'{type(error).__name__}：{text}' if text else type(error).__name__


async def run(payload):
    from open_notebook.domain.credential import Credential
    credentials = await Credential.get_by_provider('deepseek')
    credential = next((c for c in credentials if c.api_key and not c.decryption_error),None)
    if not credential:
        return {'error':'请先在本机设置页保存 DeepSeek API Key。'}
    try:
        if payload.get('_action')=='list_models':
            session, proxies = _open(ENDPOINT)
            with session:
                response=session.get(ENDPOINT+'/models',headers={'Authorization':'Bearer '+credential.api_key.get_secret_value()},timeout=35,proxies=proxies)
            if not response.ok:return {'error':f'DeepSeek 模型列表请求失败（HTTP {response.status_code}）。'}
            return response.json()
        import model_settings
        if payload.get('model') not in {m['id'] for m in model_settings.available()}:return {'error':'请选择已列出的 DeepSeek 模型。'}
        from research_store import Store,encode
        import hashlib
        store=Store()
        fingerprint=hashlib.sha256(encode({k:v for k,v in payload.items() if not k.startswith('_')}).encode()).hexdigest()
        request_id=store.enqueue('model_call',{'request_sha256':fingerprint},idem='model:'+fingerprint,safe_retry=False)
        previous=store.job(request_id)
        if previous['status']=='completed':return {**previous['result'],'reused':True}
        if previous['status']!='queued' or not store.claim(request_id):
            return {'error':'相同模型请求已有未核查或失败记录。请先检查任务结果，避免重复付费。','request_id':request_id}
        session, proxies = _open(ENDPOINT)
        with session:
            response = session.post(ENDPOINT+'/chat/completions',headers={'Authorization':'Bearer '+credential.api_key.get_secret_value(),'Content-Type':'application/json'},json=payload,timeout=180,proxies=proxies)
        if not response.ok:
            # Do not echo provider error bodies or request headers; keys must never reach logs.
            error=f'DeepSeek 请求失败（HTTP {response.status_code}），请检查密钥、余额及服务状态。'
            store.finish(request_id,error=error)
            return {'error':error,'request_id':request_id}
        result = response.json()
        value = {'answer':result['choices'][0]['message']['content'],'reasoning_content':result['choices'][0]['message'].get('reasoning_content') or '', 'usage':result.get('usage'), 'model':result.get('model'), 'finish_reason':result['choices'][0].get('finish_reason')}
        store.finish(request_id,result=value)
        return value
    except (requests.RequestException, ValueError, KeyError, IndexError) as error:
        detail = _failure_detail(error)
        message = f'DeepSeek 请求失败：{detail}。请求已记入账本，核查后可重试。'
        if 'request_id' in locals():
            store.uncertain_call(request_id, detail)
        return {'error': message, 'detail': detail,
                'request_id': locals().get('request_id')}


if __name__=='__main__':
    try:
        value = asyncio.run(run(json.loads(sys.stdin.read())))
    except Exception:
        value = {'error':'无法读取本机模型配置，请检查 Open Notebook 服务。'}
    sys.stdout.write(json.dumps(value,ensure_ascii=True))
