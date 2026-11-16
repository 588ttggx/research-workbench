"""Verify native editors and the single research entry; retain screenshots in existing logs."""
import json
import re
from pathlib import Path
import workflow as w
from local_secrets import credentials
from playwright.sync_api import sync_playwright,expect

with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    context=browser.new_context(viewport={'width':1440,'height':960})
    page=context.new_page(); errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto('http://127.0.0.1:8503')
    expect(page.locator('#papersCount')).not_to_have_text('—')
    page.screenshot(path=str(w.ROOT/'工具/日志/科研看板.png'),full_page=True)
    print('DASHBOARD',page.locator('#papersCount').inner_text(),page.locator('#projectContext').inner_text(),errors,flush=True)
    page.locator('#background').click()
    expect(page.locator('#taskStatus')).to_have_text(re.compile('.*密钥.*'),timeout=15000)
    print('BACKGROUND',page.locator('#taskStatus').inner_text(),flush=True)
    account=credentials()
    response=context.request.post('http://127.0.0.1:5678/rest/login',data={'emailOrLdapLoginId':account['email'],'password':account['password']})
    assert response.ok
    registry=w.read_json(w.ROOT/'工具/n8n/流程登记.json')
    page.goto(registry['flows'][0]['url']);page.wait_for_timeout(1700)
    print('N8N TEXT',page.locator('body').inner_text()[-5000:],flush=True)
    print('N8N IDS',page.locator('[data-test-id]').evaluate_all('els=>[...new Set(els.map(e=>e.getAttribute("data-test-id")))]'),flush=True)
    close=page.locator('[data-test-id="suggested-actions-close"]')
    if close.is_visible():close.click()
    if '--drag' in __import__('sys').argv:
        node=page.locator('[data-test-id="canvas-node"]').filter(has_text='手动运行').first
        box=node.bounding_box();assert box
        x=box['x']+box['width']/2;y=box['y']+box['height']/2
        page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+70,y+45,steps=8);page.mouse.up();page.wait_for_timeout(500)
        moved=node.bounding_box();assert moved
        print('N8N DRAG',{'changed':moved['x']!=box['x'] or moved['y']!=box['y']},flush=True)
        x=moved['x']+moved['width']/2;y=moved['y']+moved['height']/2
        page.mouse.move(x,y);page.mouse.down();page.mouse.move(x-70,y-45,steps=8);page.mouse.up()
        page.keyboard.press('Control+s');page.wait_for_timeout(1500)
    page.screenshot(path=str(w.ROOT/'工具/日志/n8n-自动积累.png'),full_page=True)
    browser.close()
