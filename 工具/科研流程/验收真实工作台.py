"""Read-only production browser checks plus one real, non-research DeepSeek proposal."""
import json
import re
import sys
import time
from urllib.parse import quote
import requests
from playwright.sync_api import sync_playwright, expect
import workflow as w
import workspace

base='http://127.0.0.1:8503';logs=w.ROOT/'工具/日志';result={'time':w.now(),'checks':[],'page_errors':[]}
before=w.read_json(w.LIBRARY);ids=[r['id'] for r in before['records']]
with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True);page=browser.new_page(viewport={'width':1440,'height':1100});page.on('pageerror',lambda error:result['page_errors'].append(str(error)))
    page.goto(base);expect(page.locator('#papersCount')).to_have_text(str(len(ids)),timeout=30000);page.locator('[data-section="maps"]').click();expect(page.locator('#graphStage .research-board')).to_be_visible(timeout=30000)
    for name in ['field','papers','timeline','project','reading','workflow']:
        page.locator('[data-graph="'+name+'"]').click();expect(page.locator('#graphMessage')).not_to_have_text('正在绘制…',timeout=30000);assert '图表错误' not in page.locator('#graphMessage').inner_text()
    result['checks'].append('真实文献数量及六类图表正常')
    page.locator('[data-section="project"]').click();assert page.locator('#backgroundDocuments details').count()==2;page.locator('#backgroundDocuments details').first.locator('summary').click();text=page.locator('#backgroundDocuments').inner_text();assert '$itemKey' not in text;assert not re.search(r'%[0-9A-F]{2}%[0-9A-F]{2}',text);page.screenshot(path=str(logs/'科研工作台-背景分类.png'),full_page=True);result['checks'].append('正式背景独立分类，元信息和编码链接隐藏')
    page.locator('[data-section="project"]').click();expect(page.locator('#projectDocuments .markdown')).to_contain_text('最新明确研究范围',timeout=10000);expect(page.locator('#projectDocuments .markdown')).to_contain_text('原始研究报告');assert page.locator('#backgroundPanel').is_visible();result['checks'].append('山药项目记录独立且保留科研状态及报告链接')
    page.locator('[data-section="library"]').click();page.locator('#filter').fill('LASSO');expect(page.locator('#paperRows tr')).to_have_count(1);page.locator('#paperRows').get_by_role('button',name='阅读笔记 / 状态',exact=True).click();expect(page.locator('#documentReader')).to_be_visible();assert 'LASSO' in page.locator('#documentReader .markdown').inner_text();assert page.locator('#documentReader select').count()==0;page.locator('#documentReader').get_by_role('button',name='关闭',exact=True).click();result['checks'].append('真实论文直接打开既有对应卡片')
    page.locator('#filter').fill('');page.locator('[data-section="ai"]').click();page.locator('#question').fill('山药掺假');page.locator('#ask').click();expect(page.locator('#results .result').first).to_be_visible(timeout=45000);result['checks'].append('真实本地检索返回原文片段')
    page.locator('[data-section="library"]').click();page.locator('#filter').fill('Laser-Induced');expect(page.locator('#paperRows tr')).to_have_count(1);page.locator('#paperRows').get_by_role('button',name='看原文 / 图表',exact=True).click();expect(page.locator('#pageImage')).to_be_visible();page.wait_for_function('() => document.getElementById("pageImage").naturalWidth>0',timeout=30000);result['checks'].append('真实 PDF 原页与图表显示')
    if '--vision' in sys.argv:
        previous_notes=set((w.KB/'文献/AI阅读记录').glob('*.md'))
        previous_updates=set((w.KB/'更新记录').glob('*.md'))
        page.locator('#pageNumber').fill('5');page.locator('#pageNumber').press('Tab')
        expect(page.locator('#pageImage')).to_have_attribute('src',re.compile(r'page=5$'))
        page.wait_for_function('() => document.getElementById("pageImage").complete && document.getElementById("pageImage").naturalWidth>0',timeout=30000)
        page.locator('#visionQuestion').fill('这是论文原页阅读入口的功能验收。请只列出这张图片能直接看到的图号、坐标轴名称和单位；看不清写看不清。不要推测实验数值或给出研究路线决定，引用该文献 ID 和 PDF 第 5 页。')
        page.locator('#visionAsk').click();expect(page.locator('#visionAnswer')).to_be_visible(timeout=220000)
        assert len(page.locator('#visionAnswer .markdown').inner_text())>30
        saved=set((w.KB/'文献/AI阅读记录').glob('*.md'))-previous_notes
        assert len(saved)==1 and set((w.KB/'更新记录').glob('*.md'))==previous_updates
        import knowledge
        document=knowledge.read(saved.pop().relative_to(w.KB).as_posix())
        assert document['paper_id']=='LIBS_YAM_2022_MDPI' and document['project']=='山药'
        assert 'PDF 页码：[5]' in document['body']
        result['checks'].append('真实 DeepSeek 接收 PDF 第 5 页图片，回答只存对应论文的待核查历史')
        result['vision']={'success':True,'paper_id':document['paper_id'],'pages':[5],'saved':document['path'],'scope':'验证图片消息与持久保存，不代替科学结论核查'}
        page.screenshot(path=str(logs/'科研工作台-原页AI验收.png'),full_page=True)
    page.locator('[data-section="updates"]').click();expect(page.locator('#updatesPanel')).to_be_visible();candidates=page.locator('#backgroundCandidates .document-card');assert candidates.count()>=5;candidates.first.locator('summary').click();expect(candidates.first.locator('.markdown')).to_be_visible();assert not candidates.first.locator('pre.doc-text').count();result['checks'].append('待核候选正常排版且历史折叠')
    # Use --skip-model for read-only reruns; --vision explicitly checks one public page.
    if '--skip-model' not in sys.argv:
        page.locator('#aiTarget').select_option('workflow');page.locator('#aiEvidence').uncheck();page.locator('#aiInstruction').fill('这是功能验收，只生成预览：把每日更新时间改为晚上 20:30，其他设置完全保留。');page.locator('#aiPropose').click();expect(page.locator('#aiPreview')).to_be_visible(timeout=220000);assert '20:30' in page.locator('#aiPreview').inner_text();result['checks'].append('真实 DeepSeek 返回可保存的结构化流程预览')
        page.locator('#aiPreview').get_by_role('button',name='不采纳',exact=True).click();expect(page.locator('#aiPreview')).not_to_be_visible(timeout=15000);cfg=requests.get(base+'/api/flow-settings',timeout=30).json();assert cfg['values']['daily_time']=='09:30';assert cfg['published'];result['checks'].append('取消真实 AI 预览不改实际时刻，流程已发布')
    page.locator('[data-section="home"]').click();page.screenshot(path=str(logs/'科研工作台-分类首页.png'),full_page=True);page.locator('#advanced > summary').click();page.locator('#knowledge').click();expect(page.locator('#taskStatus')).to_contain_text('原生知识库资料首页',timeout=30000);result['checks'].append('原生资料首页按钮真实打开目标')
    browser.close();assert not result['page_errors'],result['page_errors']
after=w.read_json(w.LIBRARY);assert [r['id'] for r in after['records']]==ids;result['checks'].append('验收未增加或删除用户正式文献')
assert [(r['id'],r.get('reading_status')) for r in after['records']]==[(r['id'],r.get('reading_status')) for r in before['records']]
result['passed']=True;result['papers']=len(ids);w.write_json(logs/('科研工作台原页验收.json' if '--vision' in sys.argv else '科研工作台真实只读验收.json' if '--skip-model' in sys.argv else '科研工作台真实验收.json'),result);print(json.dumps({'passed':True,'checks':len(result['checks']),'papers':len(ids),'page_errors':result['page_errors']},ensure_ascii=False))
