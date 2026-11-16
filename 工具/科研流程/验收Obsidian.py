import json
from pathlib import Path
import workflow as w
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser=p.chromium.connect_over_cdp('http://127.0.0.1:9223')
    page=browser.contexts[0].pages[0]
    skip=page.get_by_role('button',name='跳过',exact=True)
    if skip.is_visible():skip.click()
    page.evaluate('async()=>{await app.workspace.getLeaf().openFile(app.vault.getAbstractFileByPath("科研关系.canvas"))}')
    page.wait_for_timeout(700)
    print('CANVAS',page.evaluate('({keys:Object.keys(app.workspace.activeLeaf.view),nodes:app.workspace.activeLeaf.view.canvas.nodes.size})'),flush=True)
    print('CANVAS CLASSES',page.locator('.canvas-node').first.get_attribute('class'),flush=True)
    page.screenshot(path=str(w.ROOT/'工具/日志/Obsidian-科研关系.png'))
    page.evaluate('async()=>{await app.workspace.getLeaf().openFile(app.vault.getAbstractFileByPath("文献阅读.base"))}')
    page.wait_for_timeout(700)
    print('BASE',page.locator('.workspace-leaf.mod-active').inner_text()[-2000:],flush=True)
    page.screenshot(path=str(w.ROOT/'工具/日志/Obsidian-文献阅读.png'))
    page.evaluate('()=>{app.commands.executeCommandById("obsidian-git:open-history-view")}')
    page.wait_for_timeout(600)
    print('HISTORY',page.evaluate('app.workspace.getLeavesOfType("git-history-view").map(l=>({keys:Object.keys(l.view),proto:Object.getOwnPropertyNames(Object.getPrototypeOf(l.view))}))'),flush=True)
    print('HISTORY BODY',page.locator('body').inner_text()[-1500:],flush=True)
    page.screenshot(path=str(w.ROOT/'工具/日志/Obsidian-版本历史.png'))
    print('HISTORY DOM',page.evaluate('app.workspace.getLeavesOfType("git-history-view")[0].view.containerEl.outerHTML.slice(-7000)'),flush=True)
