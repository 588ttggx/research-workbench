"""Use the configured proxy only while it is reachable; otherwise connect directly.

The workspace keeps ``HTTP(S)_PROXY`` pointed at a local proxy that is not always
running.  Requests must follow whatever the user configured, but a proxy that is
not answering should not break local research work.  ``NO_PROXY`` is always
honoured, so hosts the user excluded keep connecting directly.
"""
from __future__ import annotations

import os
import socket
import time
from urllib.parse import urlsplit

CACHE_SECONDS = 30
NAMES = ('HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY')
_cache = {}
_originals = None


def _env(name):
    for key in (name, name.lower(), name.upper()):
        value = os.environ.get(key)
        if value and value.strip():
            return value.strip()
    return ''


def configured():
    """Return ``(proxy_url, variable_name)`` for the first configured proxy."""
    for name in NAMES:
        value = _env(name)
        if value:
            return value, name
    return '', ''


def bypass(host):
    """True when the user excluded this host from the proxy (``NO_PROXY``)."""
    allowed = _env('NO_PROXY')
    host = (host or '').strip().lower().strip('.')
    if not host:
        return False
    for item in allowed.split(','):
        item = item.strip().lower().lstrip('.')
        if item and (host == item or host.endswith('.' + item)):
            return True
    return False


def reachable(proxy_url, timeout=0.4):
    """True when a TCP connection to the proxy succeeds; cached briefly."""
    now = time.monotonic()
    cached = _cache.get(proxy_url)
    if cached and now - cached[0] < CACHE_SECONDS:
        return cached[1]
    ok = False
    try:
        parts = urlsplit(proxy_url if '://' in proxy_url else 'http://' + proxy_url)
        port = parts.port or (443 if parts.scheme == 'https' else 80)
        if parts.hostname:
            with socket.create_connection((parts.hostname, port), timeout=timeout):
                ok = True
    except OSError:
        ok = False
    _cache[proxy_url] = (now, ok)
    return ok


def proxies_for(url):
    """``requests`` proxies mapping when the configured proxy should be used.

    Returns ``None`` (connect directly) when no proxy is configured, the host is
    in ``NO_PROXY``, or the configured proxy is not answering.
    """
    parts = urlsplit(url if '://' in url else 'https://' + url)
    if bypass(parts.hostname):
        return None
    scheme = 'https' if parts.scheme == 'https' else 'http'
    proxy = _env(scheme.upper() + '_PROXY')
    if not proxy:
        return None
    return {scheme: proxy} if reachable(proxy) else None


def refresh_environment():
    """Keep proxy variables only while the configured proxy answers.

    Children (for example the DeepSeek bridge subprocess) inherit the result.
    Returns the decision so callers can surface it.
    """
    global _originals
    if _originals is None:
        _originals = {}
        for name in NAMES:
            for key in (name, name.lower()):
                if key in os.environ:
                    _originals[key] = os.environ[key]
    proxy = ''
    for name in NAMES:
        for key in (name, name.lower()):
            if _originals.get(key):
                proxy = _originals[key]
                break
        if proxy:
            break
    if not proxy:
        return {'mode': 'direct', 'reason': '未配置代理'}
    if reachable(proxy):
        for key, value in _originals.items():
            os.environ[key] = value
        return {'mode': 'proxy', 'proxy': proxy}
    for key in list(_originals):
        os.environ.pop(key, None)
    return {'mode': 'direct', 'reason': '代理未响应，已回落直连', 'proxy': proxy}


def reset():
    """Forget cached probes and captured environment (tests / reconfiguration)."""
    global _originals
    _cache.clear()
    _originals = None
