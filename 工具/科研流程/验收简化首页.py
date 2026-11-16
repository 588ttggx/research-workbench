"""Exercise real graphs, saved candidates, search and PDF pages in the daily UI."""
import json
import re
import sys
from urllib.parse import quote
from playwright.sync_api import sync_playwright, expect
import workflow as w

logs=w.ROOT/'工具/日志'
result={'time':w.now(),'diagrams':{},'page_errors':[]}
with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1100})
    page.on('pageerror',lambda error:result['page_errors'].append(str(error)))
    page.goto('http://127.0.0.1:8503')
    expect(page.locator('#papersCount')).to_have_text('29',timeout=30000)
    expect(page.locator('#graphStage svg')).to_be_visible(timeout=30000)
    assert not page.locator('#advanced').evaluate('(el)=>el.open')
    page.screenshot(path=str(logs/'科研首页-简化.png'),full_page=True)
    for graph in ['field','papers','timeline','project','reading','workflow']:
        page.locator('[data-graph="'+graph+'"]').click()
        expect(page.locator('#graphMessage')).not_to_have_text('正在绘制…',timeout=30000)
        expect(page.locator('#graphStage svg')).to_be_visible()
        assert '图表错误' not in page.locator('#graphMessage').inner_text()
        texts=page.locator('#graphStage svg text, #graphStage svg .nodeLabel').all_text_contents()
        assert texts,graph
        page.locator('#overviewPanel').screenshot(path=str(logs/('科研图-'+graph+'.png')))
        result['diagrams'][graph]={'text_nodes':len(texts),'rendered':True}
    page.locator('[data-graph="papers"]').click()
    names=page.locator('#paperGraphGroup option').all_text_contents()[1:]
    for name in names:
        page.locator('#paperGraphGroup').select_option(label=name)
        expect(page.locator('#graphMessage')).not_to_have_text('正在绘制…',timeout=30000)
        assert '图表错误' not in page.locator('#graphMessage').inner_text()
        assert len(page.locator('#graphStage svg text, #graphStage svg .nodeLabel').all_text_contents())>1
    result['paper_topic_graphs']=len(names)
    page.locator('#graphContext details').filter(has_text='材料身份').locator('summary').click()
    page.locator('#graphContext details').filter(has_text='材料身份').get_by_role('button',name='证据卡片').first.click()
    expect(page.locator('#evidencePreview')).to_be_visible()
    assert '已保存阅读卡片' in page.locator('#evidencePreview').inner_text()
    assert 'LASSO' in page.locator('#evidencePreview pre').inner_text()
    page.locator('#evidencePreview').get_by_role('button',name='关闭',exact=True).click()
    result['actual_reading_card']=True
    page.locator('[data-graph="field"]').click()
    expect(page.locator('#graphMessage')).not_to_have_text('正在绘制…')
    before_width=page.locator('#graphStage svg').evaluate('(el)=>el.getBoundingClientRect().width')
    page.locator('#graphLarger').click()
    enlarged=page.locator('#graphStage svg').evaluate('(el)=>el.getBoundingClientRect().width')
    assert enlarged>before_width
    page.locator('#graphFit').click()
    assert abs(page.locator('#graphStage svg').evaluate('(el)=>el.getBoundingClientRect().width')-before_width)<1
    candidates=page.locator('#backgroundCandidates details')
    result['background_candidates']=candidates.count()
    assert candidates.count()>=4
    candidates.first.locator('summary').click()
    expect(candidates.first.locator('pre')).to_be_visible()
    assert len(candidates.first.locator('pre').inner_text())>1000
    page.locator('#backgroundPanel').screenshot(path=str(logs/'科研首页-背景候选.png'))
    result['candidate_text_visible']=True
    # Check the result-display interaction without an external model call.
    existing=page.request.get('http://127.0.0.1:8503/api/overview?project='+quote('山药')).json()['background_candidates'][0]['path']
    fake='f'*32
    page.route('**/api/background',lambda route:route.fulfill(status=202,json={'job_id':fake}))
    page.route('**/api/job?id='+fake,lambda route:route.fulfill(json={'status':'completed','result':{'status':'candidate_saved','path':existing,'reused':True}}))
    page.locator('#background').click()
    expect(page.locator('#background')).to_be_enabled(timeout=15000)
    expect(page.locator('#taskStatus')).to_have_text('证据与背景相同，已打开上次保存的候选。')
    assert page.locator('#backgroundCandidates details[open]').count()>0
    result['candidate_result_display']='已有文件 + 本地模拟完成回执（未调用模型）'
    page.unroute('**/api/background')
    page.unroute('**/api/job?id='+fake)
    if '--generate' in sys.argv:
        before=candidates.count()
        page.locator('#background').click()
        expect(page.locator('#background')).to_be_enabled(timeout=240000)
        expect(page.locator('#backgroundCandidates details[open]')).not_to_have_count(0)
        assert '候选' in page.locator('#taskStatus').inner_text()
        after=page.locator('#backgroundCandidates details').count()
        result['candidate_generation']={'before':before,'after':after,'real_button_result_visible':True,'model_test_attempts':1}
    page.locator('#question').fill('山药粉掺假 LIBS')
    page.locator('#searchForm button[type=submit]').click()
    expect(page.locator('#results .result').first).to_be_visible(timeout=30000)
    result['search_results']=page.locator('#results .result').count()
    page.locator('#results .result').filter(has_text='LIBS').first.get_by_role('button',name='查看证据原页').click()
    expect(page.locator('#reader')).to_be_visible()
    page.wait_for_function('()=>document.getElementById("pageImage").naturalWidth>0',timeout=30000)
    result['pdf_image_visible']=True
    page.locator('#reader').screenshot(path=str(logs/'科研首页-原文图表.png'))
    if '--native' in sys.argv:
        import subprocess
        cli=(w.ROOT/w.read_json(w.ROOT/'工具/工具版本.json')['obsidian']['executable']).with_suffix('.com')
        page.locator('#advanced > summary').click()
        for tool,target in [('knowledge','graph'),('history','git-history-view')]:
            page.locator('#'+tool).click()
            expected='已打开原生知识库关系图。' if tool=='knowledge' else '已打开知识版本历史；点击记录查看正文变化。'
            expect(page.locator('#taskStatus')).to_have_text(expected,timeout=90000)
            code='JSON.stringify({type:app.workspace.activeLeaf?.view?.getViewType(),main:app.workspace.activeLeaf?.getRoot()===app.workspace.rootSplit})'
            check=subprocess.run([str(cli),'vault=科研知识库','eval','code='+code],capture_output=True,text=True,encoding='utf-8',timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
            value=json.loads(check.stdout.strip().removeprefix('=>').strip())
            assert value=={'type':target,'main':True},value
            subprocess.run([str(cli),'vault=科研知识库','dev:screenshot','path='+str(logs/('Obsidian-修复入口-'+tool+'.png'))],capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW,check=True)
            result[tool]=value
    for relative in ['../AGENTS.md','.obsidian/config.json','文献/library.json']:
        response=page.request.get('http://127.0.0.1:8503/api/document?path='+quote(relative))
        assert response.status==400
    result['private_path_boundaries']=True
    assert not result['page_errors'],result['page_errors']
    browser.close()
w.write_json(logs/'科研首页简化验收.json',result)
print(json.dumps(result,ensure_ascii=True),flush=True)
