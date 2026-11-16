from pathlib import Path
import json
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT/'工具/日志'
with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome',headless=True)
    page = browser.new_page(viewport={'width':1500,'height':1050},locale='zh-CN')
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto('http://127.0.0.1:8503')
    page.wait_for_load_state('networkidle')
    page.wait_for_function("() => document.querySelector('#papersCount').textContent === '28'")
    assert page.locator('#indexedCount').inner_text()=='28'
    assert page.locator('#paperRows tr').count()==28
    page.screenshot(path=str(LOG/'科研看板.png'),full_page=True)
    page.get_by_label('科研问题',exact=True).fill('山药粉掺假 玉米 小麦 激光诱导击穿光谱')
    page.get_by_role('button',name='检索文献',exact=True).click()
    page.locator('.result').first.wait_for(timeout=60000)
    first=page.locator('.result').first.inner_text()
    assert 'Accurate Identification' in first,first
    assert 'PDF 第' in page.locator('#results').inner_text()
    page.locator('.result').first.get_by_role('button',name='查看证据原页').click()
    page.wait_for_function("() => document.querySelector('#pageImage').complete && document.querySelector('#pageImage').naturalWidth > 500")
    assert 'Chinese Yam' in page.locator('#readerTitle').inner_text()
    page.locator('#pageNumber').fill('5')
    page.locator('#pageNumber').dispatch_event('change')
    page.wait_for_load_state('networkidle')
    page.wait_for_function("() => document.querySelector('#pageImage').complete && document.querySelector('#pageImage').naturalWidth > 500")
    page.locator('#reader').screenshot(path=str(LOG/'论文图表查看.png'))
    assert page.locator('#visionAsk').is_disabled()
    assert not errors,errors
    result={'dashboard':True,'papers':28,'indexed':28,'retrieval_top_result':first[:500],'page_image_width':page.locator('#pageImage').evaluate('(img)=>img.naturalWidth'),'key_missing_buttons_disabled':True,'browser_errors':errors}
    (LOG/'科研浏览器验收.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    # Verify actual Open Notebook notebook cards loaded, not only the initial empty shell.
    # Next.js repeatedly prefetches source links; loaded notebook cards are the completion condition.
    page.goto('http://127.0.0.1:8502/notebooks',wait_until='domcontentloaded')
    page.get_by_text('科研共享背景',exact=True).first.wait_for(timeout=20000)
    page.get_by_text('山药课题',exact=True).first.wait_for(timeout=20000)
    page.screenshot(path=str(LOG/'OpenNotebook-已加载资料.png'),full_page=True)
    result['open_notebook_cards_loaded']=True
    assert not errors,errors
    (LOG/'科研浏览器验收.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    browser.close()
print(json.dumps(result,ensure_ascii=True))
