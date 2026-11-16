"""DeepSeek status and managed bridge calls, independent of the HTTP dashboard.

Credentials stay in Open Notebook; the bridge owns the existing paid-request
ledger. No retry or provider selection is introduced here.
"""
import json
import subprocess
import sys

import requests
import model_settings
import workspace_runtime as runtime


def dashboard_compat(function):
    """Mark the old public adapter so overrides work without recursive calls."""
    function._model_gateway_compat = True
    return function


def _legacy_override(name):
    # Compatibility for callers that explicitly replace the old public adapter.
    # Never import the dashboard from a model client or start its dependencies.
    module = sys.modules.get('dashboard')
    function = getattr(module, name, None) if module else None
    if callable(function) and getattr(function, '_model_gateway_compat', False) is not True:
        return function
    return None


def model_status():
    override = _legacy_override('model_status')
    if override:
        return override()
    response = requests.request('GET', runtime.API+'/credentials', timeout=180)
    response.raise_for_status()
    credentials = response.json() if response.content else []
    configured = any(item['provider'] == 'deepseek' and item.get('has_api_key') for item in credentials)
    preferences = model_settings.settings()
    return {'configured': configured, 'model': preferences['text_model'],
            'settings': preferences, 'models': model_settings.available(),
            'tested': runtime.read_json(runtime.DATA/'deepseek-test.json', {})}


def call_deepseek(payload):
    override = _legacy_override('call_deepseek')
    if override:
        return override(payload)
    # Lifecycle is checked immediately before the existing managed subprocess.
    # Import lazily so loading this client alone has no project or store effects.
    __import__('project_profiles').check_current()
    decorated = model_settings.decorate(payload)
    app = runtime.ROOT/runtime.read_json(runtime.ROOT/'工具/工具版本.json')['open_notebook']['runtime']
    python = app/'.venv/Scripts/python.exe'
    process = subprocess.run([str(python), str(runtime.HERE/'deepseek_bridge.py')],
                             input=json.dumps(decorated, ensure_ascii=True), capture_output=True,
                             text=True, encoding='utf-8', timeout=210,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), cwd=str(app))
    try:
        return json.loads(process.stdout)
    except (ValueError, TypeError):
        return {'error': '模型调用没有返回可用结果，请检查模型配置。'}
