"""Mechanical compaction of the legacy weekly list, retaining source URLs and prose."""
import re


def compact_paper_note(body):
    """Group a known generated template; preserve every evidence paragraph/comment."""
    labels=['本笔记的用途','实际材料与阅读范围','研究问题','方法、材料与条件','提供材料中的主要发现','数据与图表','对当前课题的价值','限制与待核条件','下一步怎么用','我的批注']
    matches=list(re.finditer(r'(?m)^## ([^\n]+)\n',body))
    if [match[1].strip() for match in matches]!=labels:
        return body
    sections={match[1].strip():body[match.end():matches[i+1].start() if i+1<len(matches) else len(body)].strip() for i,match in enumerate(matches)}
    groups=[('阅读范围',['实际材料与阅读范围']),('问题与方法',['研究问题','方法、材料与条件']),('发现与图表',['提供材料中的主要发现','数据与图表']),('用途与待核',['对当前课题的价值','限制与待核条件','下一步怎么用'])]
    result=body[:matches[0].start()].rstrip()+'\n\n'+sections['本笔记的用途']
    for title,keys in groups:
        result+='\n\n## '+title+'\n\n'
        for i,key in enumerate(keys):
            text=sections[key]
            if key=='实际材料与阅读范围':
                text=text.replace('AI 基于已提供的材料整理；本次未重新核查整篇原文，不提升阅读等级。','AI 整理，未经本轮全文复核。',1)
            result+=('**'+key+'**\n\n' if len(keys)>1 else '')+text+('\n\n' if i+1<len(keys) else '')
    comments=sections['我的批注']
    # Remove only exact generated empty-editor notices, never a human annotation.
    for notice in ['可直接编辑这份笔记并添加批注。自动更新检测到人工修改时，会另外保存新版草稿。','可直接编辑这份笔记并添加批注。后续修改建议集中在本笔记的更新预览，核对后保存。']:
        comments=comments.replace(notice,'')
    if comments.strip():result+='\n\n## 我的批注\n\n'+comments.strip()
    return result.rstrip()+'\n'


def compact_weekly(body, priority_urls, *, limit=12):
    if type(limit) is not int or not 1<=limit<=30:
        raise ValueError('周报正文显示数量为 1–30 条。')
    section=re.search(r'(?ms)^## 本周首次发现 · (\d+) 篇[^\n]*\n(.*?)(?=^## |\Z)',body)
    if not section:
        raise ValueError('这份正文不是已识别的旧周报格式，原稿保留。')
    chunks=re.split(r'(?m)(?=^- )',section[2]);items=[c.strip() for c in chunks if c.strip()]
    if any(not item.startswith('- ') for item in items) or len(items)!=int(section[1]):
        raise ValueError('旧清单数量或格式与正文不一致，原稿保留。')
    priority={url.casefold().rstrip('/') for url in priority_urls};selected=[];seen=set()
    for item in items:
        links=re.findall(r'\]\((https?://[^)]+)\)',item)
        key=next((url.casefold().rstrip('/') for url in links if url.casefold().rstrip('/') in priority),None)
        if key and key not in seen:
            seen.add(key);selected.append(re.sub(r'\s+',' ',item))
        if len(selected)>=limit:break
    replacement='## 本周首次发现 · 精简浏览\n\n原清单 '+str(len(items))+' 条；按当前关注范围显示 '+str(len(selected))+' 条，不代表已核查论文或确认课题关联。\n\n'
    replacement+='\n'.join(selected) if selected else '原清单暂未命中当前重点范围，保留全部题录等待后续筛选。'
    replacement+='\n\n完整题录继续保存在[文献雷达](http://127.0.0.1:8503/#discover)，原始长清单可从本资料的“修改历史”查看。\n\n'
    return body[:section.start()]+replacement+body[section.end():],{'listed':len(selected),'total':len(items)}
