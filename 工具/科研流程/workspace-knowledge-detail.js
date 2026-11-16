/* Stable extracted knowledge pages. Scientific review remains in the existing ledger. */
(function(root){
 'use strict';
 function nodeRoute(node){
  if(!node)return null;
  if(/^EX-[KC]-/.test(node.id||''))return {route:'knowledge-node',id:node.id};
  if(node.paper_id)return {route:'paper',id:node.paper_id};
  if(node.doc_id)return {route:'document',id:node.doc_id};
  return null;
 }
 function mount(parent,bridge,id){
  const host=document.createElement('article');host.className='knowledge-detail';parent.append(host);
  let destroyed=false,data,reading;const requests=new Set();
  const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!==undefined&&text!==null)node.textContent=String(text);if(cls)node.className=cls;return node;};
  const button=(text,action,cls='quiet-button')=>{const node=el('button',text,cls);node.type='button';node.onclick=()=>Promise.resolve().then(action).catch(error=>message(error.message,true));return node;};
  function message(text,error=false){if(destroyed)return;let notice=host.querySelector('.kd-notice');if(!notice){notice=el('p',null,'kd-notice');host.prepend(notice);}notice.textContent=text;notice.classList.toggle('error',error);notice.setAttribute('role',error?'alert':'status');}
  async function read(){
   reading?.abort();const controller=new AbortController();reading=controller;requests.add(controller);
   try{const result=await bridge.api('/api/knowledge/node?id='+encodeURIComponent(id||''),undefined,{signal:controller.signal});if(!destroyed&&reading===controller){data=result;draw();}}
   catch(error){if(!destroyed&&error.name!=='AbortError'){message(error.message,true);host.append(button('重新读取',read));}}
   finally{requests.delete(controller);}
  }
  function open(node){const target=nodeRoute(node);if(target)bridge.navigate(target.route,target.id);else message('这个来源当前没有可打开的知识页面。');}
  function sourceLink(source,ref){
   if(source.paper_id&&ref){const page=Number(ref.page);bridge.navigate('paper',source.paper_id,'original',page>0?'page='+page:ref.section||ref.location||'');}
   else open(source);
  }
  function form(action,relation){
   host.querySelector('.kd-action-form')?.remove();
   const box=el('form',null,'kd-action-form'),label=el('label'),reason=el('textarea'),isPromote=action==='promote';reason.rows=3;reason.required=!isPromote;reason.setAttribute('aria-label',isPromote?'知识稿说明':'核查说明或合并依据');label.append(el('span',isPromote?'可补充知识稿说明':'核查说明或合并依据'),reason);box.append(label);
   let target,title,body;
   if(action==='alias'){target=el('input');target.required=true;target.placeholder='目标概念或结论的 ID';target.setAttribute('aria-label','合并目标ID');box.append(target,el('p','仅明确对应的同类对象可以合并；所有出处仍会保留。','section-subtitle'));}
   if(isPromote){title=el('input');title.value=data.node.label;title.required=true;title.maxLength=200;title.setAttribute('aria-label','知识稿标题');body=el('textarea');body.rows=7;body.value=data.node.summary||'';body.setAttribute('aria-label','知识稿正文');box.append(title,body,el('p','保存到共享知识稿，原提取对象与原文继续保留。','section-subtitle'));}
   const submit=el('button',isPromote?'保存知识稿':'保存核查','primary'),cancel=button('取消',()=>box.remove());submit.type='submit';box.append(submit,cancel);
   box.onsubmit=async event=>{
    event.preventDefault();if(!box.reportValidity())return;submit.disabled=true;
    try{
     let result;
     if(relation)result=await bridge.api('/api/research/review',{id:relation.id,revision:relation.revision,action,reason:reason.value.trim()});
     else{const payload={action,id:data.node.id,revision:data.revision,reason:reason.value.trim()};
      if(target){const other=await bridge.api('/api/knowledge/node?id='+encodeURIComponent(target.value.trim()));payload.target=other.node.id;payload.target_revision=other.revision;}
      if(isPromote)Object.assign(payload,{title:title.value.trim(),body:body.value,project:'共享'});
      result=await bridge.api('/api/knowledge/extraction',payload);
     }
     if(destroyed)return;bridge.notify?.(isPromote?'知识稿已保存，原文和提取出处保留。':'核查已保存。');await read();
     if(isPromote&&result.path){const targetSource=data.sources.find(s=>s.path===result.path);if(targetSource)open(targetSource);}
    }catch(error){message(error.message+'；输入已保留，可重新读取当前版本后核对。',true);}finally{if(!destroyed)submit.disabled=false;}
   };
   host.querySelector('.kd-actions')?.after(box);reason.focus();
  }
  function draw(){
   if(destroyed)return;host.replaceChildren();const n=data.node,status=data.status||{},head=el('header',null,'kd-heading');
   head.append(el('span',n.kind||'知识','overline'),el('h1',n.label),el('p',n.status==='VERIFIED'?'提取准确性已核查':'AI 提取 · 科研含义与关系分别核查','section-subtitle'));
   host.append(head);for(const reason of status.reasons||[])host.append(el('p',reason.message||reason,'kd-status'));
   if(data.alias){const row=el('div',null,'kd-status');row.append(el('span','此对象已合并，原身份和出处保留。'),button('查看合并后的知识',()=>bridge.openNode(data.alias.target)));host.append(row);}
   if(n.summary)host.append(el('p',n.summary,'kd-statement'));
   const actions=el('div',null,'kd-actions');
   for(const [action,label]of [['verify','提取准确'],['reject','不采用'],['alias','合并建议'],['promote','提炼为知识稿']])if(data.actions?.[action])actions.append(button(label,()=>form(action)));
   if(n.record_kind==='ExtractedClaim'&&n.source_kind==='original'&&status.reviewable&&bridge.compareOriginal)actions.append(button('比对原文',bridge.compareOriginal));
   actions.append(button('重新核对来源',read));host.append(actions);
   const sources=el('section',null,'kd-sources');sources.append(el('h2','原文与出处'),el('p','核查保留对象、条件、数值和限定语；提取准确不等于科研结论已验证。','section-subtitle'));
   for(const source of data.sources||[]){const card=el('article',null,'kd-source'),top=el('div',null,'kd-source-title');top.append(el('h3',source.label||source.id));if(source.eligible&&nodeRoute(source))top.append(button('打开来源',()=>sourceLink(source)));card.append(top);
    card.append(el('small',({ready:'当前来源可用',missing_original:'原文缺失',stale_cache:'缓存与原文版本不符',out_of_scope:'已退出知识区',partial_parse:'仅部分正文可用',low_quality_text:'原文文字质量未通过，待修复',unparsed:'原文尚未解析'}[source.status]||source.status||'来源待核对')));
    for(const ref of source.evidence||[]){if(ref.quote)card.append(el('blockquote',ref.quote));card.append(el('small',ref.location||ref.section||(ref.page?'第 '+ref.page+' 页':'')));if(source.eligible&&nodeRoute(source))card.append(button(ref.page?'打开原文第 '+ref.page+' 页':'打开这段依据',()=>sourceLink(source,ref)));}
    sources.append(card);
   }
   if(!(data.sources||[]).length)sources.append(el('p',status.redacted?'来源已退出知识区，当前页面仅保留身份和状态。':'尚无可展示的原文出处。'));
   host.append(sources);
   const relations=el('section',null,'kd-relations');relations.append(el('h2','知识关系'));
   const related=new Map((data.related_nodes||[]).map(node=>[node.id,node]));related.set(n.id,n);
   for(const edge of data.relations||[]){const card=el('article',null,'kd-source');card.append(el('h3',edge.label||edge.kind));const ends=el('div',null,'kd-endpoints');for(const endpoint of [edge.from,edge.to]){const node=related.get(endpoint);ends.append(nodeRoute(node)?button(node?.label||endpoint,()=>open(node)):el('span',node?.label||endpoint));}card.append(ends);
    if(edge.explanation)card.append(el('p',typeof edge.explanation==='string'?edge.explanation:JSON.stringify(edge.explanation)));
    for(const ref of edge.evidence||[])if(ref.quote||ref.location)card.append(el('blockquote',ref.quote||ref.location));
    card.append(el('small',edge.status==='REJECTED'?'已不采用':edge.stale?'历史证据 · 来源或主张已有变化':edge.status==='VERIFIED'?'科学关系已核查':edge.layer==='scientific'?'AI 科研关系候选':'出处或内容组织关系'));
    if(edge.layer==='scientific'&&edge.status==='CANDIDATE'&&!edge.stale&&Number.isInteger(edge.revision))card.append(button('确认科研关系',()=>form('VERIFIED',edge)),button('不采用关系',()=>form('REJECTED',edge)));
    const endpoints=[related.get(edge.from),related.get(edge.to)];
    if(!edge.stale&&edge.status!=='REJECTED'&&edge.evidence?.length&&edge.evidence.every(ref=>!ref.generator)&&endpoints.every(Boolean)&&bridge.showRelationEditor){
     card.append(button('编辑登记关系',()=>bridge.showRelationEditor(endpoints,{source:edge.from,target:edge.to,
       kind:edge.kind,revision:edge.revision,evidence:edge.evidence,conditions:edge.explanation})));
    }
    relations.append(card);
   }
   if(!(data.relations||[]).length)relations.append(el('p','当前没有可展示的局部关系。','section-subtitle'));host.append(relations);
  }
  host.append(el('p','正在读取这条知识及其出处…','section-subtitle'));read();
  return {refresh:read,destroy(){destroyed=true;for(const request of requests)request.abort();requests.clear();host.remove();}};
 }
 const api={mount,nodeRoute};root.WorkspaceKnowledgeDetail=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
