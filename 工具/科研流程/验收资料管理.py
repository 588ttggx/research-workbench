"""Read-only deployed checks; writing and file actions are covered by isolated tests."""
import json
from pathlib import Path
from urllib.parse import quote
from playwright.sync_api import expect, sync_playwright
import workflow as w
import note_management as notes


def main():
    output=w.ROOT/'output/科研工作区体验诊断';baseline=w.read_json(output/'本轮资料管理保护基线.json')
    checks={};errors=[];url='http://127.0.0.1:8503'
    def protect():
        records=w.read_json(w.LIBRARY)['records']
        checks['文献身份保留']=[r['id'] for r in records]==baseline['ids']
        checks['阅读状态保留']={r['id']:r.get('reading_status') for r in records}==baseline['reading_statuses']
        checks['部署前最新项目、主线与背景保留']=all(w.digest((w.KB/p).read_bytes())==h for p,h in baseline['deployment_formal_documents'].items())
        checks['原始阅读卡片保留']=all(w.digest((Path(p) if Path(p).is_absolute() else w.KB/p).read_bytes())==h for p,h in baseline['reading_cards'].items())
        checks['原文附件保留']=all(Path(a['path']).is_file() for r in records for a in r.get('artifacts',[]) if a.get('path'))
    protect();note_count=notes.count_notes()
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':980});page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(url+'/?section=home');expect(page.locator('#papersCount')).to_have_text(str(len(baseline['ids'])),timeout=30000)
        expect(page.locator('#researchStart')).to_contain_text('太谷山药和铁棍区分',timeout=15000)
        expect(page.locator('#researchStart')).to_contain_text('沿主线看证据');checks['首页以研究问题和下一步为入口']=True
        expect(page.locator('#notesCount')).to_have_text(str(note_count));checks['计数只统计实际笔记']=True
        page.screenshot(path=str(output/'改进后_研究工作台.png'),full_page=True)
        page.locator('[data-section="library"]').click();expect(page.locator('#newPersonalNote')).to_be_visible()
        page.locator('#newPersonalNote').click();expect(page.locator('#personalNoteEditor')).to_be_visible()
        page.get_by_label('我的笔记标题').fill('未保存的只读验收内容');page.get_by_label('我的笔记类别').select_option('方法记录');page.get_by_label('我的笔记保存范围').select_option('shared')
        expect(page.locator('#personalNoteBody .toastui-editor-ww-container .ProseMirror')).to_be_editable()
        page.locator('#personalNoteEditor').screenshot(path=str(output/'改进后_自己的笔记.png'))
        page.locator('#personalNoteEditor').get_by_role('button',name='关闭',exact=True).click();checks['自己的笔记与共享方法入口可编辑']=True
        page.locator('#showPapers').click();page.locator('#paperRows tr').first.get_by_role('button',name='快捷分类 / 关联').click()
        expect(page.get_by_label('这篇论文的用途')).to_be_enabled();expect(page.get_by_label('论文与研究的关联说明')).to_be_editable();expect(page.get_by_label('关联依据范围')).to_be_editable()
        page.locator('#quickAssociate').get_by_role('button',name='关闭',exact=True).click();checks['快捷论文归类和关联依据可填写']=True
        page.locator('#showNotes').click();expect(page.locator('.note-card').first).to_be_visible(timeout=15000)
        page.locator('.note-card').first.get_by_role('button',name='打开笔记',exact=True).click();expect(page.locator('#documentReader .markdown')).to_contain_text('代谢组学',timeout=15000)
        page.locator('#documentReader').get_by_role('button',name='存放位置',exact=True).click();expect(page.locator('#noteStorage')).to_contain_text(str(w.KB.resolve()))
        page.locator('#noteStorage').get_by_role('button',name='关闭',exact=True).click();page.locator('#documentReader').get_by_role('button',name='关闭',exact=True).click();checks['笔记可打开且能看到本机真实位置']=True
        page.locator('.note-card').first.get_by_role('button',name=__import__('re').compile('关联笔记')).click();expect(page.locator('#noteRelations')).to_be_visible();page.locator('#noteRelations').get_by_role('button',name='关闭',exact=True).click();checks['笔记关联入口可用']=True
        page.screenshot(path=str(output/'改进后_论文与笔记.png'),full_page=True)
        page.locator('#openTrash').click();trash=page.request.get(url+'/api/trash?project='+quote('山药')).json()
        checks['此前明确不采纳草稿进入可恢复垃圾箱']=len([i for i in trash['records'] if not i.get('direction')])>=3
        expect(page.locator('#trashPanel')).to_contain_text('恢复到原位置');page.locator('#trashPanel').screenshot(path=str(output/'改进后_垃圾箱.png'));page.locator('#trashPanel').get_by_role('button',name='关闭',exact=True).click()
        page.locator('[data-section="maps"]').click();expect(page.locator('#knowledgeNetwork svg')).to_be_visible(timeout=15000)
        expect(page.locator('#overviewPanel')).not_to_be_visible();expect(page.locator('#dataPanel')).not_to_be_visible();checks['关系网、实验图和其他视图独立切换']=True
        expect(page.locator('#knowledgeNetwork')).not_to_contain_text('group-');expect(page.locator('#knowledgeNetwork')).to_contain_text('太谷山药和铁棍区分')
        page.locator('#knowledgeNetwork [data-node-id="paper:LASSO_2024"]').click();expect(page.locator('#researchNodeDetail')).to_contain_text('如何联系到研究问题与资料');expect(page.locator('#researchNodeDetail')).to_contain_text('依据')
        page.locator('#researchNodeDetail').screenshot(path=str(output/'改进后_论文用途与依据.png'));page.locator('#researchNodeDetail').get_by_role('button',name='关闭',exact=True).click();checks['每篇论文关系能展开用途和实际材料范围']=True
        page.screenshot(path=str(output/'改进后_研究关系网.png'),full_page=True)
        page.locator('[data-maps-view="data"]').click();expect(page.locator('#dataPanel')).to_be_visible();checks['原数据分析图表入口保留']=True
        page.locator('[data-maps-view="other"]').click();checks['原有六种脉络与流程图保留']=page.locator('[data-graph]').count()==6
        page.locator('[data-section="ai"]').click();expect(page.locator('#maintainAll')).to_be_visible();page.locator('#viewDirections').click()
        checks['不采用和移出主线的历史方向不占日常候选列表']=not any('不采用' in t for t in page.locator('.direction-card .draft-badge').all_text_contents())
        page.locator('#directionsPreview').get_by_role('button',name='关闭',exact=True).click()
        if not page.locator('#administratorChat').is_visible():page.locator('#openAdministratorChat').click()
        page.locator('.chat-model-settings summary').click();checks['实时文字模型可选']=page.locator('#chatModelSelect option').count()>=2
        checks['图片模型仅显示支持图片的选项']=page.locator('#chatImageModel option').count()>=1
        expect(page.locator('#chatThinking')).to_be_enabled();page.locator('#administratorChat').screenshot(path=str(output/'改进后_模型设置.png'));page.locator('.chat-model-settings summary').click()
        page.locator('[data-section="updates"]').click();expect(page.locator('#manualUpdate')).not_to_have_attribute('open','');expect(page.locator('#modificationHistory')).to_be_visible();page.locator('#modificationHistory summary').click()
        expect(page.locator('#modificationHistory button').first).to_be_visible(timeout=15000);page.locator('#modificationHistory button').first.click();expect(page.locator('#historicalModification')).to_contain_text('只读');expect(page.locator('#historicalModification').get_by_role('button',name='确认并保存修改')).to_have_count(0)
        page.locator('#historicalModification').get_by_role('button',name='关闭',exact=True).click();checks['历史可回看、默认只读、旧预览不再挤占待处理']=True
        page.set_viewport_size({'width':390,'height':844});page.locator('[data-section="library"]').click();page.locator('#showNotes').click()
        checks['窄屏导航不溢出']=page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
        browser.close()
    protect();checks['只读验收没有产生新笔记']=notes.count_notes()==note_count;checks['浏览器没有脚本错误']=not errors
    result={'time':w.now(),'passed':all(checks.values()),'checks':checks,'page_errors':errors,'real_notes':notes.count_notes(),'user_changes_observed_and_kept':baseline.get('changes_observed_before_deployment',[]),'model_verification':w.read_json(output/'DeepSeek模型与思考验收.json')}
    w.write_json(output/'资料管理验收.json',result);print(json.dumps({'passed':result['passed'],'checks':len(checks),'failed':[k for k,v in checks.items() if not v],'page_errors':errors},ensure_ascii=False));assert result['passed']


if __name__=='__main__':main()
