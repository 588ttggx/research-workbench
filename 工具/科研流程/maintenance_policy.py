"""Metadata-bound write policy for AI-maintained Markdown regions.

The policy is deliberately narrow: it answers whether a proposed body change
only touches prose the user explicitly delegated to AI maintenance. It never
edits a file and never grants a permission by itself; callers must still use the
original save/confirmation path.
"""
from __future__ import annotations

import re

import workflow as w

HEADING = re.compile(r'^(#{1,6})[ \t]+(.+?)[ \t]*$')


def _clean_path(path):
    if not isinstance(path,(list,tuple)) or len(path)>12:
        raise ValueError('维护区域路径无效')
    result=[]
    for part in path:
        if not isinstance(part,str) or not part.strip() or len(part)>300:
            raise ValueError('维护区域标题无效')
        result.append(part.strip())
    return result


def key(path):
    return tuple(_clean_path(path))


def blocks(body):
    """Split body into heading-addressed blocks; duplicate headings get #n."""
    if not isinstance(body,str):
        raise ValueError('正文无效')
    result=[];stack=[];counts={};current=None
    for line in body.splitlines():
        match=HEADING.match(line)
        if match:
            level=len(match.group(1));title=match.group(2).strip()
            base=tuple(stack[:level-1]+[title])
            number=counts.get(base,0)+1;counts[base]=number
            path=list(base)
            if number>1:path[-1]=path[-1]+'#'+str(number)
            stack=path
            current={'path':path,'title':title,'level':level,'lines':[line]}
            result.append(current)
        elif current is None:
            current={'path':[],'title':'（前言）','level':0,'lines':[line]}
            result.append(current)
        else:
            current['lines'].append(line)
    values=[]
    for item in result:
        text='\n'.join(item['lines'])
        values.append({'path':item['path'],'title':item['title'],'level':item['level'],
                       'text':text,'sha':w.digest(text.rstrip())})
    return values


def paragraph_units(body):
    """Heading units plus paragraph units addressed by heading path + paragraph index."""
    units=[]
    for block in blocks(body):
        lines=block['text'].splitlines()
        heading=lines[0] if lines else ''
        units.append({'path':block['path'],'title':block['title'],'level':block['level'],
                      'text':heading,'sha':w.digest(heading.rstrip()),'kind':'heading'})
        groups=[];current=[]
        for line in lines[1:]:
            if not line.strip():
                if current:groups.append(current);current=[]
            else:current.append(line)
        if current:groups.append(current)
        for number,group in enumerate(groups,1):
            text='\n'.join(group);title=(group[0].strip()[:60] if group else '段落 '+str(number)) or '段落 '+str(number)
            units.append({'path':block['path']+['¶'+str(number)],'title':title,'level':block['level']+1,
                          'text':text,'sha':w.digest(text.rstrip()),'kind':'paragraph'})
    return units


def by_path(body):
    return {key(item['path']):item for item in paragraph_units(body)}


def _paragraphs_for_heading(body,heading):
    prefix=key(heading);return [item for item in paragraph_units(body)
                               if len(item['path'])==len(prefix)+1 and key(item['path'][:-1])==prefix]



    return {key(item['path']):item for item in blocks(body)}


def changed_paths(before,after):
    """Return paths whose content or position changed, in document order."""
    first=paragraph_units(before);second=paragraph_units(after)
    first_by={key(item['path']):item for item in first}
    second_by={key(item['path']):item for item in second}
    first_order=[key(item['path']) for item in first]
    second_order=[key(item['path']) for item in second]
    changed=[]
    for path in dict.fromkeys([*first_order,*second_order]):
        old=first_by.get(path);new=second_by.get(path)
        moved=(path in first_order and path in second_order and
               first_order.index(path)!=second_order.index(path))
        if old is None or new is None or old['sha']!=new['sha'] or moved:
            changed.append(list(path))
    return changed


def region_entries(body,paths):
    """Turn selected headings/paragraphs into versioned paragraph receipts."""
    if not isinstance(paths,list):
        raise ValueError('维护区域格式无效')
    indexed=by_path(body);entries=[];seen=set()
    for path in paths:
        normalized=key(path)
        if normalized in seen:continue
        item=indexed.get(normalized)
        if item is None:raise ValueError('维护区域已不存在，请刷新后重新选择：'+'/'.join(normalized))
        children=_paragraphs_for_heading(body,normalized)
        selected=[item] if item['kind']=='paragraph' or not children else children
        for unit in selected:
            child_key=key(unit['path'])
            if child_key in seen:continue
            seen.add(child_key)
            entries.append({'path':list(child_key),'sha':unit['sha'],'title':unit['title']})
    return entries


def update_regions(body,regions):
    """Refresh stored region receipts after an authorized write; drop missing paths."""
    indexed=by_path(body);result=[]
    for item in (regions or []):
        if not isinstance(item,dict):continue
        try:normalized=key(item.get('path') or [])
        except ValueError:continue
        current=indexed.get(normalized)
        if current is None:continue
        result.append({'path':list(normalized),'sha':current['sha'],'title':current['title']})
    return result


def block_list(body,regions=None):
    """Display list for the heading/paragraph maintenance selector."""
    registered={}
    for item in (regions or []):
        if not isinstance(item,dict):continue
        try:registered[key(item.get('path') or [])]=str(item.get('sha') or '')
        except ValueError:continue
    units=paragraph_units(body);result=[]
    for item in units:
        normalized=key(item['path']);expected=registered.get(normalized)
        selected=expected is not None;stale=selected and expected!=item['sha']
        if item['kind']=='heading':
            children=_paragraphs_for_heading(body,normalized)
            if children:
                selected=all(key(child['path']) in registered for child in children)
                stale=selected and any(registered[key(child['path'])]!=child['sha'] for child in children)
        result.append({**item,'selected':selected,
                       'stale':stale})
    return result


def authorize(owner,basis,managed_hash,regions,before,after):
    """Decide whether an automatic proposal may write without a new decision."""
    if before.rstrip()==after.rstrip():
        return {'allowed':False,'reason':'正文没有实际变化','changed':[],'owner':owner}
    changed=changed_paths(before,after)
    if not changed:
        return {'allowed':False,'reason':'只有行尾或排版差异，未发现可维护段落','changed':[],'owner':owner}
    if owner=='human':
        return {'allowed':False,'reason':'这份资料默认人工维护，自动修改只生成预览','changed':changed,'owner':owner}
    if owner=='ai':
        if managed_hash and managed_hash!=w.digest(before.rstrip()):
            return {'allowed':False,'reason':'正文已不在管理指纹内，自动修改只生成预览','changed':changed,'owner':owner}
        if basis=='managed_hash' and not managed_hash:
            return {'allowed':False,'reason':'缺少管理指纹，自动修改只生成预览','changed':changed,'owner':owner}
        return {'allowed':True,'reason':'AI维护正文，按授权范围落稿','changed':changed,'owner':owner}
    if owner=='mixed':
        current=by_path(before);authorized=set()
        for item in (regions or []):
            if not isinstance(item,dict):continue
            try:path_key=key(item.get('path') or [])
            except ValueError:continue
            if current.get(path_key) and current[path_key]['sha']==item.get('sha'):authorized.add(path_key)
        if all(key(path) in authorized for path in changed):
            return {'allowed':True,'reason':'只改动了已授权的混合维护段落','changed':changed,'owner':owner}
        return {'allowed':False,'reason':'改动涉及未授权或已被人工修改的段落，自动修改只生成预览','changed':changed,'owner':owner}
    return {'allowed':False,'reason':'维护归属未知，自动修改只生成预览','changed':changed,'owner':owner}
