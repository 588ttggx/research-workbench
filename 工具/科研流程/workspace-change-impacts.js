// Follow-up drafts share the existing automation dialog and original write APIs.
async function renderChangeImpacts(host){return renderMaterialReview(host);}

function showImpactWatchBinding(bindings,project){
 const body=modal('设置关注依据'),rule=select([['','选择关注'],...bindings.rules.map(r=>[r.id,r.title])],'选择关注'),source=select([['','选择依据资料'],...bindings.sources.map(s=>[s.id,s.title])],'选择依据资料');
 const generation=S.overlayGeneration,active=()=>generation===S.overlayGeneration&&$('overlay').open&&project===S.project;
 body.append(el('p','明确选用研究范围或方案作为关注依据。保存关联不改检索词、不调用模型；以后资料变化时可准备关注修改建议。','section-subtitle'),field('选择关注',rule),field('选择依据资料',source));
 const bound=el('div',null,'watch-source-bindings');body.append(bound);
 rule.onchange=()=>{bound.replaceChildren();const chosen=bindings.rules.find(r=>r.id===rule.value);for(const id of chosen?.sources||[]){const row=el('div',null,'form-actions');row.append(el('span',bindings.sources.find(s=>s.id===id)?.title||id),btn('移除依据关联',async()=>{await api('/api/change-impacts/bind-watch',{project,rule_id:chosen.id,source_id:id,revision:bindings.revision,action:'remove'});if(active())await showAutomation('schedule');},'quiet-button'));bound.append(row);}};
 body.append(btn('取消',()=>showAutomation('schedule'),'quiet-button'),btn('保存依据关联',async()=>{if(!rule.value||!source.value)throw Error('请选择关注及依据资料。');await api('/api/change-impacts/bind-watch',{project,rule_id:rule.value,source_id:source.value,revision:bindings.revision});if(!active())return;await showAutomation('schedule');notify('关注依据已关联，原启停与检索词保留');},'primary','check'));
}

async function openImpactOwner(target,project){
 if(project!==S.project)return;
 if(target.open_action==='method'){await showMethods(target.method_id);return;}
 if(target.open_action==='stage'){
  dismiss();location.hash='#projects?'+new URLSearchParams({project,view:'progress',stage:target.native_id});return;
 }
 if(target.open_action==='closure'){const body=modal('核对结项依据');await renderProjectClosure(body);return;}
 if(target.open_action==='lab'){
  const generation=S.overlayGeneration,data=await api('/api/rspace/records');if(generation!==S.overlayGeneration||project!==S.project||!$('overlay').open)return;
  const node=data.records.find(n=>n.id===target.native_id);if(!node)throw Error('原生索引已变化，请刷新后打开。');showNativeRecord(node);
  const body=$('overlayBody'),confirm=el('input');confirm.type='checkbox';const label=el('label',null,'check-field');label.append(confirm,el('span','已在正式记录中核对本次版本变化及其依赖。'));body.append(label,btn('已核对这个原生版本',async()=>{if(!confirm.checked)throw Error('请先核对并勾选确认。');await api('/api/change-impacts/native-review',{project,id:target.native_id,version:target.version});if(project!==S.project)return;await showAutomation('changes');notify('已记录版本核对，正式实验事实保留');},'quiet-button','check'));
 }
}

function impactValue(value){
 if(value===undefined||value===null||value==='')return '（空）';
 return typeof value==='string'?value:JSON.stringify(value,null,2);
}

function impactIsSafeForBatch(target){
 return Boolean(target&&target.kind==='document'&&target.status==='pending'&&target.proposal_id
  &&Number.isInteger(target.proposal_revision)&&!target.edited&&!target.blocked_reason);
}

function impactBatchItems(groups){
 return groups.filter(group=>impactIsSafeForBatch(group?.impact))
  .map(group=>({id:group.impact.proposal_id,revision:group.impact.proposal_revision}));
}

function impactBatchChunks(groups,size=30){
 const chunks=[];
 for(let index=0;index<groups.length;index+=size)chunks.push(groups.slice(index,index+size));
 return chunks;
}

function appendImpactDiff(host,rows){
 const changed=(rows||[]).filter(row=>row.kind!=='same');
 const pane=el('div',null,'impact-diff');
 const legend=el('p',null,'impact-diff-legend');
 legend.append(el('span','旧内容', 'removed'),el('span','新内容','added'));
 host.append(el('h3','修改红绿对照'),legend);
 if(!changed.length){host.append(el('p','这份建议没有提出正文改动。','muted'));return;}
 host.append(pane);
 const groups=[];
 for(const row of rows){const last=groups[groups.length-1];if(last?.kind===row.kind)last.rows.push(row);else groups.push({kind:row.kind,rows:[row]});}
 for(const group of groups){
  if(group.kind==='same'&&group.rows.length>6){
   const folded=el('details',null,'impact-diff-folded');
   folded.append(el('summary','未改动内容 · '+group.rows.length+' 行'));
   folded.ontoggle=()=>{
    if(!folded.open||folded.dataset.rendered)return;folded.dataset.rendered='true';
    const fragment=document.createDocumentFragment();
    for(const row of group.rows)fragment.append(el('div',row.text,'diff-row same'));
    folded.append(fragment);
   };
   pane.append(folded);
  }else for(const row of group.rows)pane.append(el('div',row.text,'diff-row '+group.kind));
 }
}

async function showImpactProposal(id,project=S.project){
 const body=modal('核对修改建议'),generation=S.overlayGeneration;body.append(el('p','正在读取建议…','loading-state'));
 let proposal=await api('/api/change-impacts/proposal?project='+encodeURIComponent(project)+'&id='+encodeURIComponent(id));
 const active=()=>generation===S.overlayGeneration&&$('overlay').open&&project===S.project;
 if(!active())return;
 body.replaceChildren();body.append(el('h3',proposal.target_label),el('p',proposal.summary));
 if(proposal.written_recovery)body.append(el('p','修改已保存。可补记本次完成回执，之后的来源变化会保留。','notice'));
 else if(proposal.source_stale||proposal.target_stale)body.append(el('p','来源或原稿已有新变化。请核对最新版本后再保存。','notice'));
 const comparison=el('section',null,'impact-comparison');
 if(proposal.kind==='document'){
  const details=el('details');details.append(el('summary','查看生成时的原内容'),el('pre',impactValue(proposal.before),'code-text'));comparison.append(details);
 }
 appendImpactDiff(comparison,proposal.diff);
 body.append(comparison);
 if(proposal.source_coverage){const coverage=el('details');coverage.append(el('summary','来源与本批处理范围'));for(const [id,row] of Object.entries(proposal.source_coverage))coverage.append(el('p',id+' · '+row.characters+' 字 · '+(row.complete?'完整提供':'未完整提供'),'muted'));if(proposal.remaining_source_ids?.length)coverage.append(el('p','还有 '+proposal.remaining_source_ids.length+' 份来源留待下一批处理。'));body.append(coverage);}
 const draftKey='research:impact-draft:'+id;
 let saved;try{saved=JSON.parse(localStorage.getItem(draftKey));}catch(_){}
 const same=saved?.revision===proposal.revision;
 const recoverable=proposal.status==='writing';
 const editable=proposal.status==='pending';let documentEditor=null,fields={};
 const manualPanel=el('section',null,'impact-manual-editor');manualPanel.hidden=true;
 manualPanel.append(el('h3','手工修改建议正文'),el('p','只有需要调整 AI 建议文字时才使用。直接采纳时无需打开。','section-subtitle'));
 if(proposal.kind==='document'){
  documentEditor=el('textarea',null,'impact-editor');documentEditor.rows=14;documentEditor.setAttribute('aria-label','建议正文');documentEditor.value=same?saved.after:proposal.after;documentEditor.disabled=!editable;
  manualPanel.append(el('p','建议正文（Markdown）','impact-editor-label'),documentEditor);
 }else{
  const labels={title:'标题',next_step:'下一步',execution_notes:'工作说明',due_on:'日期',phase:'阶段',item_type:'新增类型',query:'检索词',name:'关注名称',relevance_tier:'推荐用途'};
  const source=same?saved.after:proposal.after;
  for(const [key,value] of Object.entries(source)){
   if(key==='references')continue;
   const control=Array.isArray(value)||typeof value==='object'?el('textarea'):input('',String(value??''));
   if(control.tagName==='TEXTAREA')control.value=JSON.stringify(value,null,2);
   control.disabled=!editable;control.setAttribute('aria-label',labels[key]||key);fields[key]={control,structured:Array.isArray(value)||typeof value==='object',type:typeof value};manualPanel.append(field(labels[key]||key,control));
  }
 }
 if(same)body.append(el('p','本机编辑稿已恢复。先更新修改对照，再确认保存。','section-subtitle'));
 body.append(manualPanel);
 const after=()=>documentEditor?documentEditor.value:{...proposal.after,...Object.fromEntries(Object.entries(fields).map(([key,{control,structured,type}])=>[key,structured?JSON.parse(control.value):type==='boolean'?control.value==='true':type==='number'?Number(control.value):control.value]))};
 const differs=()=>JSON.stringify(after())!==JSON.stringify(proposal.after);
 const persist=()=>{try{if(differs())localStorage.setItem(draftKey,JSON.stringify({revision:proposal.revision,after:after()}));else if(same)localStorage.removeItem(draftKey);}catch(_){};};
 if(saved&&!same){const recovery=el('details');recovery.append(el('summary','查看尚未合并的本机编辑稿'),el('pre',typeof saved.after==='string'?saved.after:JSON.stringify(saved.after,null,2)));body.append(recovery);}
 const message=el('p',null,'notice'),actions=el('div',null,'form-actions impact-actions');message.hidden=true;body.append(message,actions);
 const payload=()=>({project,id,revision:proposal.revision});
 if(editable||recoverable){
  const apply=btn(recoverable?'继续恢复保存':'采纳并保存',async()=>{
   apply.disabled=true;
   const controls=[documentEditor,...Object.values(fields).map(f=>f.control)].filter(Boolean),disabled=controls.map(c=>c.disabled);controls.forEach(c=>c.disabled=true);
   message.hidden=false;message.className='notice info';message.textContent='正在核对来源版本并保存…';
   try{if(editable&&differs())throw Error('请先更新对照，核对后再保存。');
    await api('/api/change-impacts/apply',{...payload(),confirmed:true});localStorage.removeItem(draftKey);S.workspaceStale=true;
    if(!active())return;if(await finishReview('impact',id))return;
    if(S.reviewSession){await openReviewItem();return;}
    await showAutomation('review');notify('修改已保存；未覆盖的来源继续接续。');
   }catch(error){if(active()){message.hidden=false;message.className='notice';message.textContent=error.message;}throw error;}finally{controls.forEach((c,i)=>c.disabled=disabled[i]);if(apply.isConnected)refreshButtons();}
  },'primary','check');
  const reviewDraft=btn('更新修改对照',async()=>{
   const content=after();if(!differs())return;
   await api('/api/change-impacts/revise',{...payload(),after:content});
   localStorage.removeItem(draftKey);S.workspaceStale=true;
   if(active())await showImpactProposal(id,project);
  },'primary','edit');
  const refreshButtons=()=>{
   let changed=false,valid=true;try{changed=editable&&differs();}catch(_){changed=true;valid=false;}
   reviewDraft.hidden=!changed;reviewDraft.disabled=!valid;
   apply.disabled=changed||Boolean(!proposal.written_recovery&&(proposal.source_stale||(!recoverable&&proposal.target_stale)));
  };
  const onEdit=()=>{persist();refreshButtons();};
  if(documentEditor)documentEditor.oninput=onEdit;for(const {control} of Object.values(fields))control.oninput=onEdit;
  refreshButtons();actions.append(reviewDraft);
  if(proposal.decision_id)actions.append(btn('查看本次项目修改',()=>showDecisionReview(proposal.decision_id,project),'primary','check'));
  else actions.append(apply);
  let manualButton;
  manualButton=btn(same?'继续手工修改':'手工修改',()=>{
   manualPanel.hidden=!manualPanel.hidden;
   manualButton.textContent=manualPanel.hidden?(same?'继续手工修改':'手工修改'):'收起手工修改';
   if(!manualPanel.hidden){const control=documentEditor||Object.values(fields)[0]?.control;control?.focus();}
  },'quiet-button','edit');
  actions.append(manualButton);
  for(const [action,label] of [['defer','暂缓'],['reject','不采纳']])actions.append(btn(label,async()=>{persist();await api('/api/change-impacts/respond',{...payload(),action});S.workspaceStale=true;if(!active())return;if(await finishReview('impact',id))return;await showAutomation('review');},'quiet-button'));
 }else if(['deferred','rejected'].includes(proposal.status))actions.append(btn('恢复处理',async()=>{await api('/api/change-impacts/respond',{...payload(),action:'resume'});if(active())await showImpactProposal(id,project);},'quiet-button'));
 actions.append(btn('返回待处理',()=>{persist();return showAutomation('review');},'quiet-button','back'));
}

async function showDecisionReview(id,project=S.project){
 const body=modal('核对本次项目修改'),generation=S.overlayGeneration;
 body.append(el('p','正在读取修改差异…','loading-state'));
 const active=()=>generation===S.overlayGeneration&&project===S.project&&$('overlay').open;
 const decision=await api('/api/change-impacts/decision?project='+encodeURIComponent(project)+'&id='+encodeURIComponent(id));
 if(!active())return;
 body.replaceChildren(el('h3',decision.label||'本次项目修改'));
 const results=new Map((decision.results||[]).map(row=>[row.id,row]));
 const proposals=new Map(decision.items.map(row=>[row.target_id,row]));
 const ready=[];let hasConflict=false;
 for(const row of decision.items){
  const result=results.get(row.id),section=el('details',null,'source-change');section.open=row.status!=='applied';
  section.append(el('summary',row.target_label+(row.status==='applied'?' · 已保存':'')));
  if(result?.message)section.append(el('p',result.message,'notice'));
  const pending=row.status==='pending'||row.status==='writing';
  const conflicted=pending&&!row.written_recovery&&(row.source_stale||row.target_stale);
  if(conflicted)hasConflict=true;
  else if(pending)ready.push({id:row.id,revision:row.revision});
  if(row.summary)section.append(el('p',row.summary,'muted'));
  appendImpactDiff(section,row.diff);body.append(section);
 }
 for(const row of decision.preparation||[])if(!proposals.has(row.id)&&row.message)body.append(el('p',row.message,'notice'));
 const actions=el('div',null,'form-actions');body.append(actions);
 if(ready.length)actions.append(btn('确认保存本次修改',async()=>{
  const result=await job('/api/change-impacts/apply-decision',{project,decision_id:id,confirmed:true,items:ready});
  if(!active())return;S.workspaceStale=true;
  await showDecisionReview(id,project);
  notify('已保存 '+result.applied+' 项'+(result.failed?'，'+result.failed+' 项留待核对':''),Boolean(result.failed));
 },'primary','check'));
 if(hasConflict)actions.append(btn('按当前资料重新准备',async()=>{
  await job('/api/change-impacts/prepare-decision',{project,decision_id:id});
  if(active())await showDecisionReview(id,project);
 },'quiet-button','sparkles'));
 actions.append(btn('返回待处理',()=>showAutomation('review'),'quiet-button'));
}
