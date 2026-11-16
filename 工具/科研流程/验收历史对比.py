"""开发验收：需手动启用本机 Obsidian 9223 调试端口；日常启动不开放该端口。"""
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b=p.chromium.connect_over_cdp('http://127.0.0.1:9223');page=b.contexts[0].pages[0]
    page.evaluate('()=>{app.commands.executeCommandById("obsidian-git:open-history-view")}')
    page.wait_for_timeout(500)
    view=page.locator('.workspace-leaf-content[data-type="git-history-view"]')
    view.locator('.nav-folder-title').first.click()
    page.wait_for_timeout(400)
    view.locator('.nav-file-title').first.evaluate('el=>el.click()')
    page.wait_for_timeout(800)
    print(page.locator('body').inner_text()[-4500:])
    page.screenshot(path='工具/日志/Obsidian-版本增删.png')
