"""Readable graph labels derived from current records, without renaming stable paper IDs."""
from pathlib import Path
import re
import knowledge as k
import workflow as w
import organization as org
from paper_notes import note_path


def paper_display(record,kb=None):
    kb=(kb or w.KB).resolve()
    paths = []
    card = record.get('reading_card')
    if card:
        path = Path(card) if Path(card).is_absolute() else kb/card
        if path.resolve().is_relative_to(kb): paths.append(path.resolve())
    paths.append(note_path(record['id'],kb))
    for path in paths:
        if path.is_file():
            doc = k.read(path.relative_to(kb).as_posix(),kb)
            if doc.get('type')=='reading_card' and k.split(path.read_text('utf-8-sig'))[0].get('standard_template'): continue
            title = doc['title'].removesuffix(' · 阅读笔记')
            if re.search(r'[\u4e00-\u9fff]',title): return {'label':title, 'path':doc['path'], 'status':doc['status'] or '阅读范围见笔记'}
    topic = str(record.get('topic') or '').split('；')[0].split('/')[0]
    label = topic if re.search(r'[\u4e00-\u9fff]',topic) else '已登记研究论文'
    return {'label':label+' · '+record['title'][:28], 'path':'文献/条目/'+record['id']+'.md', 'status':'笔记待补全'}


def view(project):
    lines = k.lines(project)
    inputs, _ = org.paper_inputs(project); ids = {p['id'] for p in inputs}
    records = [r for r in w.read_json(w.KB/'文献/library.json', {'records':[]})['records'] if r['id'] in ids]
    current=k.read(f'项目/{project}/当前课题状态.md')
    nodes = [{'id':'project','label':project+' · 当前课题','kind':'项目','path':current['path'],'status':current['status'],'summary':current['body'][:800]}]
    organization = org.view(project).get('papers', {})
    record_map={r['id']:r for r in records}
    edges = []; grouped = set()
    for row in lines['rows']:
        line_id = 'line:'+row['id']; nodes.append({'id':line_id,'label':row['title'],'kind':'主线','path':lines['path'],'status':row['status'],'goal':row['goal']})
        edges.append({'from':'project','to':line_id,'label':'研究问题','explanation':row['goal'],'source':'用户主线'})
        for identifier in row['paper_ids']:
            if identifier not in ids:continue
            recorded=record_map[identifier].get('mainline_relations',{}).get(row['id'],{})
            organized=organization.get(identifier,{})
            relevant=organized.get('mainline_id')==row['id']
            edges.append({'from':line_id,'to':'paper:'+identifier,'label':recorded.get('role') or (organized.get('relation') if relevant else '用途待补'),
                          'explanation':recorded.get('reason') or (organized.get('summary') if relevant else '用户已关联此论文，具体用途和依据尚未填写。'),
                          'scope':recorded.get('scope') or ('；'.join(s['location'] for s in organized.get('sources',[])) if relevant else '待补阅读范围'),
                          'source':recorded.get('source') or ('用户关联 · AI 说明待核查' if relevant else '用户关联'), 'suggested':False})
            grouped.add(identifier)
    # AI links remain visibly provisional; they never rewrite the user's mainlines.
    for identifier,organized in organization.items():
        line=next((r for r in lines['rows'] if r['id']==organized.get('mainline_id')),None)
        if identifier not in ids or not line or identifier in line['paper_ids']:continue
        edges.append({'from':'line:'+line['id'],'to':'paper:'+identifier,'label':organized.get('relation') or '主题相关','explanation':organized.get('summary') or '待核查',
                      'scope':'；'.join(s['location'] for s in organized.get('sources',[])) or '仅题录归类', 'source':'AI 建议 · 待核查','suggested':True})
        grouped.add(identifier)
    themes = {}
    for record in records:
        display = paper_display(record)
        organized=organization.get(record['id'],{})
        nodes.append({'id':'paper:'+record['id'],'paper_id':record['id'],'kind':'论文笔记',**display,'original_title':record['title'],'summary':organized.get('summary') or '现有资料尚无可靠摘要，请打开原文或笔记核对。','basis':organized.get('basis') or '阅读范围见笔记'})
        if record['id'] not in grouped:
            theme = str(organization.get(record['id'], {}).get('theme') or record.get('topic') or '待归类资料').split('；')[0][:45]
            if theme not in themes:
                theme_id = 'theme:'+w.digest(theme)[:12]; themes[theme] = theme_id
                nodes.append({'id':theme_id,'label':theme,'kind':'主题草稿','status':'AI 分类 · 待核查'})
                edges.append({'from':'project','to':theme_id,'label':'主题归类'})
            edges.append({'from':themes[theme],'to':'paper:'+record['id'],'label':'资料归类'})
    from note_management import NOTE_KINDS
    inventory=[i for i in k.inventory(project) if i['kind'] in NOTE_KINDS]
    for item in inventory:
        if item['kind'] not in ('笔记','项目经验','方法记录','论文批注'):continue
        node_id='note:'+w.digest(item['path'])[:16]
        nodes.append({'id':node_id,'label':item['title'],'kind':item['kind'],'path':item['path'],'status':item['status'],'paper_ids':item['paper_ids']})
        links=['line:'+r['id'] for r in item['mainlines']]
        if not links:
            group_id='notes:'+item['kind']
            if not any(n['id']==group_id for n in nodes):
                nodes.append({'id':group_id,'label':item['kind'],'kind':'积累类型','status':'自己的积累'});edges.append({'from':'project','to':group_id,'label':'研究积累'})
            links=[group_id]
        for link in links:edges.append({'from':link,'to':node_id,'label':item['kind'],'explanation':'自己保存的'+item['kind']+'，关联来自笔记选择的主线或论文。','source':'用户记录'})
        for identifier in item['paper_ids']:
            if identifier in ids:edges.append({'from':'paper:'+identifier,'to':node_id,'label':'笔记 / 经验 / 方法','source':'用户关联'})
    from overview import tasks
    task_items=tasks(project)['items']
    return {'project':project,'nodes':nodes,'edges':edges,'inventory':inventory,'tasks':task_items,'fingerprint':w.digest(str(nodes)+str(edges)+str(inventory)+str(task_items)),
            'scope':'从项目问题沿主线查看论文、经验和方法。实线为用户记录，虚线为 AI 关联建议。点击节点或连线可查看用途、理由和依据范围。缺少依据的关系保留待补。'}
