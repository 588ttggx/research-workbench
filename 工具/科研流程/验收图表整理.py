"""Read-only browser checks of the research boards and navigation."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
import workflow as w

parser = argparse.ArgumentParser()
parser.add_argument('--url', default='http://127.0.0.1:8503')
parser.add_argument('--expect-active', action='store_true')
args = parser.parse_args()
output = w.ROOT/'output/科研工作区体验诊断'
output.mkdir(parents=True, exist_ok=True)
result = {'time': w.now(), 'page_errors': [], 'views': {}}
with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    page.on('pageerror', lambda error: result['page_errors'].append(str(error)))
    page.goto(args.url+'/?section=home')
    expect(page.locator('#papersCount')).not_to_have_text('—', timeout=30000)
    expect(page.locator('#intakePanel')).to_be_visible()
    expect(page.locator('#inboxLocation')).to_contain_text('待入库', timeout=15000)
    expect(page.locator('#pdfDrop')).to_be_visible()
    expect(page.locator('#dailyGuide .guide-card')).to_have_count(3)
    expect(page.locator('#dailyReplies .processing-row').first).to_be_visible()
    result['intake_and_guidance'] = True
    daily = page.request.get(args.url+'/api/daily?project='+__import__('urllib.parse',fromlist=['quote']).quote('山药')).json()
    result['notes_ready'] = daily['notes_ready']
    records = page.request.get(args.url+'/api/status').json()['papers']
    for record in records:
        response = page.request.get(args.url+'/api/evidence?paper='+record['id'])
        assert response.status == 200
        doc = response.json()
        assert len(doc['body']) > 400, record['id']
        if doc.get('type') == 'ai_paper_note':
            assert '## 本笔记的用途' in doc['body'] and '## 下一步怎么用' in doc['body']
    result['all_paper_notes_accessible'] = True
    page.screenshot(path=str(output/'改进后_科研首页.png'), full_page=True)
    page.locator('[data-section="maps"]').click()
    expect(page.locator('#graphStage .research-board')).to_be_visible(timeout=15000)
    assert page.locator('#graphViewport').bounding_box()['y'] < 650
    for name in ['field', 'papers', 'timeline', 'project', 'reading', 'workflow']:
        page.locator('[data-graph="'+name+'"]').click()
        expect(page.locator('#graphMessage')).not_to_have_text('正在绘制…', timeout=15000)
        expect(page.locator('#graphStage')).to_be_visible()
        assert '图表错误' not in page.locator('#graphMessage').inner_text()
        assert page.locator('#graphStage').inner_text().strip(), name
        if name == 'workflow':
            assert page.locator('#graphStage svg').bounding_box()['height'] <= page.locator('#graphViewport').bounding_box()['height']
            result['workflow_fits_vertical'] = True
        page.locator('#overviewPanel').screenshot(path=str(output/('改进后_图表_'+name+'.png')))
        result['views'][name] = True
    page.locator('#graphPresentation').select_option('diagram')
    for name in ['field', 'papers', 'timeline', 'project', 'reading', 'workflow']:
        page.locator('[data-graph="'+name+'"]').click()
        expect(page.locator('#graphStage svg')).to_be_visible(timeout=15000)
        assert '图表错误' not in page.locator('#graphMessage').inner_text()
    result['original_six_diagrams'] = True
    page.locator('#graphPresentation').select_option('cards')
    page.locator('[data-graph="reading"]').click()
    page.get_by_role('button', name='去文献库改阅读状态', exact=True).click()
    expect(page.locator('#libraryPanel')).to_be_visible()
    expect(page.locator('[data-section="library"]')).to_have_attribute('aria-selected', 'true')
    page.locator('[data-section="maps"]').click()
    page.locator('[data-graph="field"]').click()
    paper = page.locator('#graphStage button[data-paper]').first
    if paper.count():
        paper.click()
        expect(page.locator('#evidencePreview')).to_be_visible()
        page.locator('#evidencePreview').get_by_role('button', name='关闭', exact=True).click()
        result['paper_detail'] = True
    original = page.locator('#graphStage').get_by_role('button', name='原文', exact=True).first
    if original.count():
        original.click()
        expect(page.locator('#reader')).to_be_visible()
        expect(page.locator('#pageImage')).to_be_visible()
        expect(page.locator('#pageImage')).to_have_attribute('src', __import__('re').compile('/api/page\\?paper='))
        result['paper_original'] = True
        page.locator('[data-section="maps"]').click()
    expect(page.locator('#scientificChart .main-svg').first).to_be_visible()
    result['literature_statistics'] = True
    page.locator('[data-chart="pca"]').click()
    expect(page.locator('#dataFile')).to_be_visible()
    result['scientific_analysis_entry'] = True
    page.locator('[data-section="ai"]').click()
    expect(page.locator('#organizePapers')).to_be_visible()
    if args.expect_active:
        expect(page.locator('#adminEnabled')).to_be_checked()
        result['administrator_enabled_with_user_authorization'] = True
    else:
        expect(page.locator('#adminEnabled')).not_to_be_checked()
        result['administrator_kept_paused'] = True
    page.locator('[data-section="library"]').click()
    page.locator('#paperRows').get_by_role('button', name='阅读笔记 / 状态', exact=True).first.click()
    expect(page.locator('#documentReader')).to_contain_text('本笔记的用途')
    expect(page.locator('#documentReader').get_by_role('button',name='编辑正文',exact=True)).to_be_visible()
    page.locator('#documentReader').screenshot(path=str(output/'改进后_已补全阅读笔记.png'))
    page.locator('#documentReader').get_by_role('button',name='关闭',exact=True).click()
    assert not result['page_errors'], result['page_errors']
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
    page.locator('[data-section="maps"]').click()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
    page.screenshot(path=str(output/'改进后_窄屏.png'), full_page=True)
    browser.close()
w.write_json(output/'图表整理验收.json', result)
print(json.dumps(result, ensure_ascii=False))
