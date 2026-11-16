"""开发验收：需手动启用本机 Obsidian 9223 调试端口；日常启动不开放该端口。"""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'工具/科研流程'))
import workflow as w
import yaml
from playwright.sync_api import sync_playwright

with w.process_lock() as acquired:
    if not acquired:raise ValueError('同步正在运行，请稍后验收')
    with sync_playwright() as p:
        b=p.chromium.connect_over_cdp('http://127.0.0.1:9223');page=b.contexts[0].pages[0]
        source=page.locator('.bases-kanban-card').filter(has_text='Diversity analysis reveals significant variations').first
        column=page.locator('.bases-kanban-column').filter(has_text='待核查阅读范围').first
        original=w.KB/'文献/条目/oa-8c2379dbb39e85.md'
        original_status=yaml.safe_load(original.read_text('utf-8').split('---',2)[1]).get('status')
        if original_status!='未读':
            raise ValueError('该验收只用于未读论文；保留用户当前阅读状态。')
        try:
            source.drag_to(column,target_position={'x':80,'y':120})
            page.wait_for_timeout(700)
            text=original.read_text('utf-8')
            assert yaml.safe_load(text.split('---',2)[1])['status']=='待核查阅读范围'
            print('STATUS CHANGED',True)
            print(text[:260])
        finally:
            page.evaluate('async status=>{const f=app.vault.getAbstractFileByPath("文献/条目/oa-8c2379dbb39e85.md");await app.fileManager.processFrontMatter(f,fm=>{fm.status=status})}',original_status)
        page.wait_for_timeout(500)
        print('STATUS RESTORED',original.read_text('utf-8')[:170])
