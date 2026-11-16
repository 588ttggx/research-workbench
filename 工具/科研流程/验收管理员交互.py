"""Read-only checks of deployed administrator chat, graph and protected records."""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import expect, sync_playwright
import workflow as w


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8503')
    parser.add_argument('--conversation', required=True)
    args = parser.parse_args()
    output = w.ROOT/'output/科研工作区体验诊断'
    baseline = w.read_json(output/'本轮交互资料保护基线.json')
    records = w.read_json(w.LIBRARY)['records']
    result = {'time': w.now(), 'page_errors': [], 'checks': {}}
    checks = result['checks']
    checks['paper_ids_unchanged'] = [r['id'] for r in records] == baseline['ids']
    checks['reading_statuses_unchanged'] = {r['id']: r.get('reading_status') for r in records} == baseline['reading_statuses']
    checks['original_cards_unchanged'] = all(w.digest(Path(path).read_bytes()) == expected for path, expected in baseline['reading_cards'].items())
    checks['formal_documents_unchanged'] = all(w.digest((w.KB/path).read_bytes()) == expected for path, expected in baseline['formal_documents'].items())
    groups = [w.KB/'文献/条目'/(r['id']+'.md') for r in records if r['id'].startswith('group-')]
    checks['all_group_indexes_preserved'] = len(groups) == baseline['groups'] and all(p.is_file() and p.stat().st_size > 200 for p in groups)
    checks['group_indexes_link_chinese_notes'] = all('中文阅读笔记' in p.read_text('utf-8-sig') for p in groups)
    maintenance = w.read_json(w.DATA/'一键维护.json')
    runtime = w.read_json(w.DATA/'管理员运行.json')
    checks['real_maintenance_completed'] = maintenance.get('status') == 'completed' and not maintenance.get('errors')
    checks['no_notes_remaining'] = runtime.get('notes_remaining') == 0 and not runtime.get('error')
    result.update(papers=len(records), groups=len(groups), empty_group_entries=[], maintenance_steps=[{'label': item['label'], 'status': item['status']} for item in maintenance['steps']])

    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        page.on('pageerror', lambda error: result['page_errors'].append(str(error)))
        page.add_init_script('localStorage.setItem('+json.dumps('researchChat:山药')+','+json.dumps(args.conversation)+');')
        page.goto(args.url+'/?section=ai')
        expect(page.locator('#papersCount')).not_to_have_text('—', timeout=30000)
        expect(page.locator('#administratorChat')).to_be_visible()
        expect(page.locator('#chatHistory')).to_have_value(args.conversation, timeout=15000)
        chat = page.request.get(args.url+'/api/administrator/chat?id='+args.conversation).json()
        expect(page.locator('#chatMessages .chat-turn')).to_have_count(len(chat['messages']))
        checks['persistent_real_chat_loaded'] = len(chat['messages']) >= 6
        previews = [turn['proposal_id'] for turn in chat['messages'] if turn.get('proposal_id')]
        checks['refinement_keeps_same_preview'] = len(previews) >= 2 and len(set(previews)) == 1
        proposal = page.request.get(args.url+'/api/ai-proposal?id='+chat['proposal_id']).json()
        checks['refined_preview_unapplied'] = proposal['status'] == '待确认'
        checks['preview_preserves_original'] = proposal['before'] == proposal['target']['before']
        result.update(conversation_id=chat['id'], conversation_turns=len(chat['messages']), proposal_id=proposal['id'])
        expect(page.locator('#maintainAll')).to_be_visible()
        page.get_by_text('分析技能与自动任务设置', exact=True).click()
        for identifier in ['adminNotes', 'adminProject', 'adminMainlines', 'adminDefaultProject', 'adminDefaultLine']:
            expect(page.locator('#'+identifier)).to_be_visible()
        checks['maintenance_and_default_controls'] = True
        page.locator('#administratorChat').screenshot(path=str(output/'改进后_管理员对话.png'))
        page.locator('#chatMessages').get_by_role('button', name='查看修改与高亮对比').last.click()
        expect(page.locator('#aiPreview')).to_be_visible()
        expect(page.locator('#aiPreview .diff-added').first).to_be_visible()
        expect(page.locator('#aiPreview').get_by_role('button', name='和管理员继续微调')).to_be_visible()
        expect(page.locator('#aiPreview').get_by_role('button', name='确认并保存修改')).to_be_disabled()
        checks['highlight_and_confirmation'] = True
        page.locator('#aiPreview .highlighted-diff').screenshot(path=str(output/'改进后_修改高亮.png'))
        page.keyboard.press('Escape')
        page.locator('#administratorChat').get_by_role('button', name='收起', exact=True).click()
        page.locator('[data-section="maps"]').click()
        expect(page.locator('#knowledgeNetwork svg')).to_be_visible(timeout=15000)
        expect(page.locator('#knowledgeGraphFilter')).to_have_value('active')
        assert not re.search(r'group-[a-f0-9]{8,}', page.locator('#knowledgeNetwork').inner_text())
        checks['chinese_graph_labels_and_live_source'] = True
        page.locator('#knowledgeGraphPanel').screenshot(path=str(output/'改进后_中文知识图.png'))
        page.locator('#knowledgeGraphFilter').select_option('all')
        expect(page.locator('#knowledgeNetwork .network-node')).not_to_have_count(0)
        graph = page.request.get(args.url+'/api/knowledge-graph?project='+quote('山药')).json()
        checks['graph_includes_all_papers'] = len([n for n in graph['nodes'] if n.get('paper_id')]) == len(records)
        page.locator('[data-section="ai"]').click()
        page.locator('#adminRecent').get_by_role('button', name=re.compile('领域方向')).click()
        expect(page.locator('#directionsPreview .direction-card select').first).to_be_visible()
        checks['directions_have_status_and_discussion'] = page.locator('#directionsPreview').get_by_role('button', name='和管理员讨论这个方向').count() > 0
        page.keyboard.press('Escape')
        page.set_viewport_size({'width': 390, 'height': 844})
        expect(page.locator('#administratorChat')).not_to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
        checks['mobile_chat_collapses_without_overflow'] = True
        browser.close()
    result['passed'] = all(checks.values()) and not result['page_errors']
    w.write_json(output/'管理员交互验收.json', result)
    print(json.dumps({'passed': result['passed'], 'checks': len(checks), 'page_errors': result['page_errors'], 'failed': [key for key, value in checks.items() if not value]}, ensure_ascii=False))
    assert result['passed'], result


if __name__ == '__main__':
    main()
