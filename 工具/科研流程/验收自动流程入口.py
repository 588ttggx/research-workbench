"""验证真实首页按钮及首次自动登录；独立测试窗口关闭，不触碰用户原窗口。"""
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
import workflow as w

spec=importlib.util.spec_from_file_location('editor_entry',w.ROOT/'工具/n8n/打开编辑器.py')
editor=importlib.util.module_from_spec(spec)
spec.loader.exec_module(editor)
contexts=[]
result={'time':w.now()}

@contextmanager
def observed_playwright():
    with sync_playwright() as playwright:
        launch=playwright.chromium.launch_persistent_context
        def observed_launch(*args,**kwargs):
            context=launch(*args,**kwargs)
            contexts.append(context)
            return context
        with patch.object(playwright.chromium,'launch_persistent_context',side_effect=observed_launch):
            yield playwright

def check_first_open():
    context=contexts[0]
    page=context.pages[0]
    for name in ['科研区 · 文献笔记持续积累','科研区 · 新论文与背景每日更新']:
        expect(page.get_by_text(name,exact=True).first).to_be_visible(timeout=15000)
    result.update(first_open=True,auto_login=True,workflows_visible=2)
    page.screenshot(path=str(w.ROOT/'工具/日志/n8n-首次自动登录.png'),full_page=True)
    context.close()
    time.sleep(0.5)

with tempfile.TemporaryDirectory(dir=w.ROOT/'_临时/科研区维护') as temporary:
    test_root=Path(temporary)
    (test_root/'工具/n8n/data').mkdir(parents=True)
    with patch.object(editor,'ROOT',test_root),patch.object(editor,'sync_playwright',observed_playwright),patch.object(editor,'ready',check_first_open):
        editor.main()

with sync_playwright() as playwright:
    browser=playwright.chromium.launch(channel='chrome',headless=True)
    page=browser.new_page()
    errors=[]
    page.on('pageerror',lambda error:errors.append(type(error).__name__))
    page.goto('http://127.0.0.1:8503')
    for _ in range(2):
        page.locator('#automation').click()
        expect(page.locator('#taskStatus')).to_have_text('已打开本机流程编辑器；重复点击可再次打开。',timeout=45000)
        expect(page.locator('#automation')).to_be_enabled()
    assert not errors,errors
    result.update(button_clicks=2,page_errors=errors)
    browser.close()
w.write_json(w.ROOT/'工具/日志/自动流程入口验收.json',result)
print(json.dumps(result,ensure_ascii=False))
