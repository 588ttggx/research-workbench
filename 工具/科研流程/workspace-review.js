// Human work is counted by material; optional relationship suggestions stay grouped.
function materialReviewItems(groups){
 const items=[];
 for(const g of groups){
  const decision=Boolean(g.impact&&(g.impact.review_level?g.impact.review_level==='decision':g.impact.proposal_id));
  const openable=Boolean(g.impact?.proposal_id&&!['stale','failed','blocked'].includes(g.impact.status)&&
   (decision||['deferred','rejected'].includes(g.impact.status)));
  const manualDraft=(g.drafts||[]).some(draft=>draft.automatic!==true);
  const needs=!g.optional&&(openable||g.sync?.length||manualDraft||g.judgments?.length);
  if(!needs)continue;
  if(openable)items.push({id:'impact:'+g.impact.proposal_id,kind:'impact',target:g.impact.proposal_id,title:g.label});
  else if(g.sync?.length)items.push({id:'sync:'+g.sync[0].id,kind:'sync',target:g.sync[0].id,title:g.label});
  else if(manualDraft)items.push({id:'proposal:'+g.drafts.find(draft=>draft.automatic!==true).id,kind:'proposal',target:g.drafts.find(draft=>draft.automatic!==true).id,title:g.label});
  else if(g.judgments?.length)items.push({id:'candidate:'+g.judgments[0].id,kind:'candidate',candidate:{...g.judgments[0],title:g.label},title:g.label});
 }
 return items;
}
async function startReview(items,context,currentId){
 if(currentId&&!items.some(item=>item.id===currentId))throw Error('这项审核已变化，请重新打开。');
 S.reviewSession=ReviewQueue.create(items,{kind:context.tab,context:{...context,project:S.project},currentId});await openReviewItem();
}
async function openReviewItem(){
 if(!S.reviewSession)return;S.reviewSession=ReviewQueue.resume(S.reviewSession);const item=ReviewQueue.current(S.reviewSession);
 if(!item){const session=S.reviewSession,body=modal('本轮审核已结束');body.append(el('h3','已处理 '+session.completed.length+' 项'),el('p',session.skipped.length+' 项跳过，仍保留在待处理列表。','section-subtitle'),btn('返回原列表',returnReviewList,'primary'));return;}
 const generation=S.overlayGeneration;
 let openingGeneration=generation;
 const progress=()=>{
  const bar=el('div',null,'review-progress');
  bar.append(el('strong','第 '+(S.reviewSession.index+1)+' / '+S.reviewSession.items.length+' 项'),
             btn('跳过，稍后处理',async()=>{S.reviewSession=ReviewQueue.skip(S.reviewSession);await openReviewItem();},'quiet-button'),
             btn('返回原列表',returnReviewList,'quiet-button'));
  $('overlayBody').prepend(bar);$('overlay').scrollTop=0;
 };
 try{
  let opening;
  if(item.kind==='document'){const doc=S.workspace.documents.find(d=>d.id===item.target);if(!doc)throw Error('资料索引已变化，请返回列表重新读取。');opening=showDocumentUpdate(doc);}
  else if(item.kind==='proposal')opening=showProposal(item.target);
  else if(item.kind==='sync')opening=showNoteSync(item.target);
  else if(item.kind==='impact')opening=showImpactProposal(item.target,S.project);
  else opening=showReview(item.candidate,S.reviewSession.context.tab);
  openingGeneration=S.overlayGeneration;
  await opening;
 }catch(error){
  if(openingGeneration!==S.overlayGeneration||!$('overlay').open)return;
  const body=modal('这一条暂时无法打开');
  body.append(el('h3',item.title||'当前审核项'),el('p',error.message,'notice'),
              el('p','审核队列没有结束。可以跳过这一项继续下一条，或回到原列表重新读取。','section-subtitle'));
  progress();
  return;
 }
 if(openingGeneration!==S.overlayGeneration||!$('overlay').open||!S.reviewSession||ReviewQueue.current(S.reviewSession)?.id!==item.id)return;
 progress();
 for(const button of $('overlayBody').querySelectorAll('button')){const action=button.onclick;if(!action)continue;button.onclick=async event=>{button.disabled=true;try{await action(event);}finally{if(button.isConnected)button.disabled=false;}};}
}
async function finishReview(kind,identifier){
 if(!S.reviewSession||ReviewQueue.current(S.reviewSession)?.id!==kind+':'+identifier)return false;
 S.reviewSession=ReviewQueue.complete(S.reviewSession,{ok:true,id:kind+':'+identifier});S.workspaceStale=true;await openReviewItem();return true;
}
async function returnReviewList(){if(!S.reviewSession)return;const context=S.reviewSession.context;S.reviewReturnContext=context;S.reviewSession=null;await showAutomation(context.tab);requestAnimationFrame(()=>$('overlay').scrollTop=context.scrollTop||0);}
function reviewReturnButton(){return S.reviewSession?btn('返回连续审核',async()=>{S.reviewSession=ReviewQueue.resume(S.reviewSession);await openReviewItem();},'quiet-button','back'):null;}
function reviewReasonChoices(reason){const choices=el('div',null,'review-reasons');for(const text of ['与当前问题相关','材料不同','方法不适用','依据不足，暂不采纳','已核对所列证据与适用条件'])choices.append(btn(text,()=>{reason.value=text;},'quiet-button'));return choices;}

async function showAutomation(tab='review',{area='all'}={}){
 if(tab==='changes')tab='review';
 if(tab==='relations')tab='jobs';
 const project=S.project,body=modal('自动化与审核'),generation=S.overlayGeneration;
 body.append(el('p','正在读取自动化状态…','loading-state'));
 let reviewPreloaded=null;
 try{
  const reviewRead=tab==='review'||tab==='recent';
  const reads=[api('/api/automation?'+(reviewRead?'view=review&':'')+'project='+encodeURIComponent(project))];
  if(tab==='review')reads.push(api('/api/note-sync'),api('/api/research?section=review&project='+encodeURIComponent(project)));
  const [state,...reviewData]=await Promise.all(reads);
  if(tab==='review')reviewPreloaded=[reviewData[0],reviewData[1],state.impacts];
  if(generation!==S.overlayGeneration||project!==S.project||!$('overlay').open)return;
  const old=S.workspaceProject===project?S.workspace||{}:{};const papers=new Map((old.papers||[]).map(p=>[p.id,p]));
  S.workspace={...old,...state,papers:state.papers.map(p=>({...papers.get(p.id),...p}))};S.workspaceProject=project;S.workspaceStale=true;
 }catch(error){if(generation===S.overlayGeneration)body.replaceChildren(empty('自动化状态暂未读取',error.message,btn('重新读取',()=>showAutomation(tab,{area}))));return;}
 if(generation!==S.overlayGeneration||!$('overlay').open||project!==S.project)return;
 body.replaceChildren();const options=[['review','待处理'],['recent','审核历史'],['schedule','自动化设置'],['jobs','运行记录']];
 const tabbar=tabs(options,tab,draw),box=el('div');body.append(tabbar,box);
 async function draw(key){
  tabbar.querySelectorAll('button').forEach((b,i)=>b.classList.toggle('active',options[i][0]===key));const page=el('div');box.replaceChildren(page);
  if(['schedule','jobs'].includes(key)&&S.workspace.review_only){
   page.append(el('p','正在读取设置与运行记录…','loading-state'));
   try{
    const state=await api('/api/automation?project='+encodeURIComponent(project));
    if(generation!==S.overlayGeneration||project!==S.project||!$('overlay').open)return;
    const old=S.workspace||{},papers=new Map((old.papers||[]).map(p=>[p.id,p]));
    S.workspace={...old,...state,papers:state.papers.map(p=>({...papers.get(p.id),...p}))};S.workspaceProject=project;page.replaceChildren();
   }catch(error){page.replaceChildren(empty('设置与运行记录暂未读取',error.message,btn('重新读取',()=>draw(key))));return;}
  }
  if(key==='recent'){
   const impacts=S.workspace.impacts||await api('/api/change-impacts?view=targets&project='+encodeURIComponent(project));
   if(generation===S.overlayGeneration&&project===S.project&&page.isConnected)renderRecent(page,impacts);return;
  }
  if(key==='schedule'){await renderSchedule(page);return;}
  if(key==='jobs'){
   const top=el('div',null,'toolbar');top.append(el('p','成功阶段会复用；结果不明的付费调用等待核查。','section-subtitle'),btn('刷新任务',()=>showAutomation('jobs'),'quiet-button'));page.append(top);
   const jobs=S.workspace.jobs.filter(j=>j.kind!=='model_call'||['failed','needs_review'].includes(j.status)),filter=select([['active','执行中与需要检查'],['all','全部近期执行']],'任务范围'),list=el('div');page.append(filter,list);
   const drawJobs=()=>{list.replaceChildren();const rows=jobs.filter(j=>filter.value==='all'||['running','queued','failed','needs_review','partial','waiting'].includes(j.status)||['partial','waiting','needs_attention'].includes(j.result?.status));
   for(const row of rows){const n=el('div',null,'queue-row'),copy=el('div');copy.append(el('strong',row.kind==='model_call'?'模型调用 · 需要核查':jobLabels[row.kind]||'后台处理'),el('p',(row.phase||jobStates[row.status]||row.status)+' · '+date(row.updated)+((row.error||row.result?.error)?' · '+(['relations','relation_tick'].includes(row.kind)?relationFailureMessage(row.error||row.result.error):row.error||row.result.error):'')));n.append(copy);
    if(row.kind==='sync'&&row.result){
     const errors=Array.isArray(row.result.errors)?row.result.errors:[],dependencies=Object.entries(row.result.dependencies||{}).filter(([,value])=>value?.error);
     if(row.result.message)copy.append(el('p',row.result.message,'section-subtitle'));
     if(errors.length||dependencies.length){
      const details=el('details');details.append(el('summary','查看本轮未完成项'));
      for(const [name,value]of dependencies)details.append(el('p',(name==='zotero'?'Zotero':name==='document_parser'?'文档解析':name)+' · '+value.error,'section-subtitle'));
      for(const error of errors)details.append(el('p',(error.id?error.id+' · ':'')+(error.error||error.message||'等待核查'),'section-subtitle'));
      copy.append(details);
     }
    }
    if(row.result?.steps){const details=el('details');details.append(el('summary','查看处理步骤'));for(const step of row.result.steps)details.append(el('p',step.label+' · '+step.status+(step.error?' · '+step.error:''),'section-subtitle'));copy.append(details);}
    if(Array.isArray(row.result?.failures))for(const failure of row.result.failures){
     if(failure?.message)n.append(el('p',relationFailureMessage(failure.message),'muted'));
    }
    if(row.kind==='model_call')n.append(btn('核查并解除阻塞',()=>showCallRecovery(row),'quiet-button','check'));
    if(row.kind==='catalog_update'&&row.result?.body)n.append(btn('打开草稿',async()=>{const doc=await api('/api/workspace/document?id='+row.result.id);if(doc.fingerprint!==row.result.fingerprint)throw Error('原稿已变化，草稿需与当前正文合并');dismiss();S.pendingDraft={id:doc.id,body:row.result.body};navigate('document',doc.id);}));
    if(row.safe_retry&&['failed','needs_review'].includes(row.status))n.append(btn('重试',async()=>{await api('/api/research/retry',{id:row.id});notify('任务已重新进入队列');}));list.append(n);
   }if(!rows.length)list.append(empty('当前没有执行中或异常任务','完整执行记录可切换为全部近期执行查看。'));};filter.onchange=drawJobs;drawJobs();return;
  }
  const ready=reviewPreloaded;reviewPreloaded=null;await renderMaterialReview(page,ready,area);
 }await draw(tab);
}

function reviewMaterials(data){
 const documents=visibleDocs(),byId=new Map(documents.flatMap(d=>[d.id,d.record_id].filter(Boolean).map(id=>[id,d])));
 const paths=new Set(documents.flatMap(d=>[d.path,d.kb_path].filter(Boolean)));
 const byPath=new Map(documents.flatMap(d=>[d.path,d.kb_path].filter(Boolean).map(path=>[path,d])));
 for(const n of data.nodes)if(n.owner==='Markdown'&&byPath.has(n.uri))byId.set(n.id,byPath.get(n.uri));
 const available=new Set([...byId.keys(),...S.workspace.papers.map(p=>p.id),...data.nodes.filter(n=>n.owner!=='Markdown'||paths.has(n.uri)).map(n=>n.id)]);
 return {documents,byId,available};
}

function renderRecent(page,impacts){
 const rows=impacts?.recent||[];
 const history=impacts?.review_history||(impacts?.targets||[]).filter(ReviewQueue.isHistoryImpact);
 if(!rows.length&&!history.length){page.append(empty('暂无审核历史'));return;}
 const list=el('div',null,'review-material-list');
 for(const row of history){
  const item=el('article',null,'review-material'),copy=el('div',null,'review-material-copy');
  copy.append(el('h3',row.label),el('p',row.status==='deferred'?'已暂缓':'未采纳','muted'));
  item.append(copy,btn('查看建议',()=>showImpactProposal(row.proposal_id,S.project),'quiet-button','activity'));list.append(item);
 }
 for(const row of rows){
  const item=el('article',null,'review-material'),copy=el('div',null,'review-material-copy'),actions=el('div',null,'review-material-actions');
  copy.append(el('h3',row.target_label||row.target_id),el('p',row.summary||'已保存正文修改','muted'));
  copy.append(el('p',(row.automatic_applied?'自动落稿':'人工采纳')+' · '+date(row.applied)+(row.depth?' · 链路 '+row.depth+' 层':''),'section-subtitle'));
  actions.append(btn(row.kind==='note'?'打开笔记':'查看来源与差异',()=>row.kind==='note'?(()=>{dismiss();navigate('document',row.target_id);})():row.kind==='preview'?showProposal(row.id):showImpactProposal(row.id,S.project),'quiet-button',row.kind==='note'?'folder':'activity'));
  item.append(copy,actions);list.append(item);
 }
 page.append(list);
}

async function renderAutomationConnections(box){
 const project=S.project,generation=S.overlayGeneration,active=()=>generation===S.overlayGeneration&&project===S.project&&box.isConnected;
 const area=(id,title,description)=>{const panel=el('section',null,'reading-settings');panel.setAttribute('data-automation-area',id);panel.append(el('h3',title),el('p',description,'muted'));const content=el('div');panel.append(content);box.append(panel);return content;};
 const knowledge=area('knowledge','知识图自动更新 · 全局','自动提取概念、结论和普通关联。支持或反驳可从资料或研究问题发起比对。');
 const lab=area('lab','实验区 · 自动同步（全局）','同步正式实验记录、样品与版本；连接参数在本区展开修改。');
 const analysis=area('analysis','分析区 · 自动计算（按方法）','按已核对的方法配置输入目录与条件，满足条件后接续 QC、分析与运行登记。');
 const outputs=area('outputs','产出区 · 依据变化跟踪（本项目）','跟踪正文引用与结项依据变化，进入待处理核对；沿资料版本自动检查，无独立启停开关，冻结结果保留。');
 outputs.append(btn('查看结项依据',()=>openImpactOwner({open_action:'closure'},project),'quiet-button'));
 const backup=area('backup','数据自动备份 · 全局','沿已连接的目录备份受版本管理的数据；原始数据及已有副本保留。');
 const connections=el('details',null,'reading-settings');connections.append(el('summary','各区接续状态与关注依据'));box.append(connections);
 connections.ontoggle=async()=>{if(!connections.open||connections.dataset.loaded)return;connections.dataset.loaded='true';try{const value=await api('/api/change-impacts?view=targets&project='+encodeURIComponent(project));if(!active())return;for(const row of value.connections||[])connections.append(el('p',(value.areas.find(a=>a.id===row.area)?.title||row.area)+'：'+row.message,'muted'));if(value.watch_bindings?.rules.length)connections.append(btn('设置关注依据',()=>showImpactWatchBinding(value.watch_bindings,project),'quiet-button','link'));}catch(error){if(active()){connections.dataset.loaded='';connections.append(el('p',error.message,'notice'));}}};
 const load=async(host,render)=>{host.append(el('p','正在读取设置…','loading-state'));try{await render();}catch(error){if(active())host.replaceChildren(el('p',error.message,'notice'),btn('重新读取本区',()=>load(host,render),'quiet-button'));}};
 const loads=[load(lab,()=>renderRSpaceConnection(lab)),load(backup,()=>renderDataRemote(backup)),load(analysis,async()=>{
  const [methods,snapshot]=await Promise.all([api('/api/methods'),api('/api/analysis-automation')]);if(!active())return;
  analysis.replaceChildren();const configured=new Set(snapshot.records.map(p=>p.method_id));
  const available=methods.records.filter(m=>configured.has(m.id)||m.status==='VERIFIED'&&!m.archived);
  if(!available.length)analysis.append(el('p','尚未配置可用方法。先在“方法与 QC”保存并核对方法，再在这里配置自动接续。','muted'),btn('维护方法与 QC',()=>showMethods(),'quiet-button'));
  const rows=await Promise.allSettled(available.map(async method=>{const row=el('div');analysis.append(row);const render=async snapshot=>{if(!active()||!row.isConnected)return;row.replaceChildren(el('h4',method.data.title||method.id));await renderAnalysisAutomation(row,method,{snapshot,onSaved:()=>render()});};await render(snapshot);}));
  for(const result of rows)if(result.status==='rejected')throw result.reason;
 })];
 loads.push(load(knowledge,async()=>{
 let state=await api('/api/knowledge/extraction');if(!active())return;
  knowledge.replaceChildren();
  const text=el('p',null,'muted'),actions=el('div',null,'form-actions');
  const draw=()=>{text.textContent=(state.runtime?.reason||state.status)+' · 已处理 '+(state.processed_chunks||0)+' / '+(state.total_chunks||0)+' 段';actions.replaceChildren();
   const save=async action=>{state=await api('/api/knowledge/extraction',{action,revision:state.revision});if(active())draw();};
   actions.append(btn(state.enabled?'关闭知识图自动更新':'启用知识图自动更新',()=>save(state.enabled?'disable':'enable'),'quiet-button'));
   if(state.enabled)actions.append(btn(state.runtime?.state==='blocked'?'服务恢复后继续':state.paused?'继续处理':'暂停处理',()=>save(state.paused||state.runtime?.state==='blocked'?'resume':'pause'),'quiet-button'));
  };
  knowledge.append(text,actions);draw();
 }));await Promise.all(loads);
}

async function renderMaterialReview(box,preloaded=null,initialArea='all'){
 const generation=S.overlayGeneration,project=S.project;
 const [sync,data,impacts]=preloaded||await Promise.all([api('/api/note-sync'),api('/api/research?section=review&project='+encodeURIComponent(project)),api('/api/change-impacts?view=targets&project='+encodeURIComponent(project))]);
 if(generation!==S.overlayGeneration||project!==S.project||!box.isConnected)return;
 const {documents,available}=reviewMaterials(data);
 const groups=ReviewQueue.materials({documents,pending:S.workspace.pending,targets:impacts.targets,
  sync:sync.records.filter(r=>['needs_review','needs_refresh'].includes(r.status)),
  judgments:data.nodes.filter(n=>n.status==='CANDIDATE'&&available.has(n.id))});
 const search=searchField('查找待处理事项'),summary=el('p',null,'review-summary'),list=el('div');
 search.node.hidden=!groups.some(group=>initialArea==='all'||group.area===initialArea);
 box.append(search.node,summary,list);
 const hasIndependent=g=>g.sync.length||g.judgments.length||g.drafts.length;
 const events=new Map();
 for(const group of groups){
  const id=group.impact?.prepared_decision_id;
  if(id){if(!events.has(id))events.set(id,[]);events.get(id).push(group);}
 }
 const attention=new Set(groups.flatMap(g=>g.impact?.prepared_decision_id?
  ['event:'+g.impact.prepared_decision_id,...(hasIndependent(g)?[g.key]:[])]:[g.key])).size;
 S.workspace.review_counts={...(S.workspace.review_counts||{}),attention};updateAutomationAttention();
 let limit=15;
 const more=btn('继续显示',()=>{limit+=15;draw();},'quiet-button');box.append(more);
 function draw(){
  const query=search.input.value.trim().toLowerCase();
  const rows=groups.filter(g=>initialArea==='all'||g.area===initialArea)
   .filter(g=>[g.label,...g.reasons,...(g.impact?.sources||[]).map(s=>s.title)].join(' ').toLowerCase().includes(query));
  const displayed=[],seen=new Set();
  for(const row of rows){
   const id=row.impact?.prepared_decision_id;
   if(id&&!seen.has(id)){displayed.push({event:id,items:events.get(id)});seen.add(id);}
   if(!id||hasIndependent(row))displayed.push(id?{...row,impact:null}:row);
  }
  displayed.sort((left,right)=>Number(Boolean(right.event))-Number(Boolean(left.event)));
  list.replaceChildren();
  summary.hidden=!displayed.length;summary.textContent=displayed.length+' 项';
  for(const g of displayed.slice(0,limit)){
   const row=el('article',null,'review-material'),copy=el('div',null,'review-material-copy'),actions=el('div',null,'review-material-actions');
   if(g.event){
    const representative=g.items[0].impact;row.dataset.target='event:'+g.event;
    copy.append(el('h3',representative.decision_label||representative.sources?.[0]?.title||'本次项目变化'),
                el('p',g.items.map(item=>item.label).join('、'),'muted'));
    actions.append(btn('查看本次修改',()=>showDecisionReview(g.event,project),'primary','check'));
   }else{
    row.dataset.target=g.key;copy.append(el('h3',g.label));
    for(const reason of new Set(g.reasons))copy.append(el('p',reason,'section-subtitle'));
    const t=g.impact;
    if(t?.kind==='native_review')actions.append(btn('打开所属入口',()=>openImpactOwner(t,project),'primary','link'));
    else if(t?.proposal_id){
     const label={writing:'继续恢复保存',needs_choice:'对照保留的人工稿'}[t.status]||'查看修改建议';
     actions.append(btn(label,()=>showImpactProposal(t.proposal_id,project),'primary','edit'));
     if(t.can_prepare&&t.status==='needs_choice')actions.append(btn('保留人工稿并准备新版',async()=>{
      const result=await job('/api/change-impacts/prepare',{project,group_id:t.group_id,target_id:t.id,replace_edited:true});
      if(generation===S.overlayGeneration&&project===S.project)await showImpactProposal(result.id,project);
     },'quiet-button'));
    }
    for(const item of g.sync)actions.append(btn('比较同步差异',()=>showNoteSync(item.id),'quiet-button'));
    for(const item of g.drafts)actions.append(btn('核对修改预览',()=>showProposal(item.id),'primary','edit'));
    for(const item of g.judgments)actions.append(btn('核查科研判断',()=>showReview({...item,title:g.label},'review'),'quiet-button'));
    if(g.doc)actions.append(btn('打开正文',()=>{dismiss();navigate('document',g.doc.id);},'text-link'));
   }
   row.append(copy,actions);list.append(row);
  }
  more.hidden=limit>=displayed.length;
  if(!displayed.length)list.append(query?empty('没有匹配的待处理事项'):
   empty('当前没有待处理事项','有项目修改建议需要确认时，会在这里出现。'));
 }
 search.input.oninput=()=>{limit=15;draw();};draw();
}

async function showProposal(id){
 const body=modal('核对修改建议'),generation=S.overlayGeneration;body.append(el('p','正在读取修改建议…','loading-state'));
 let proposal;try{proposal=await api('/api/ai-proposal?id='+encodeURIComponent(id));}catch(error){if(generation===S.overlayGeneration)body.replaceChildren(empty('修改预览暂未读取',error.message,btn('重新读取',()=>showProposal(id))));return;}
 if(generation!==S.overlayGeneration||!$('overlay').open)return;body.replaceChildren();
 body.append(el('p',proposal.summary,'section-subtitle'),el('p','目标：'+(proposal.target.title||proposal.target.path||proposal.kind),'section-subtitle'));
 if(['no_change','already_current'].includes(proposal.target_state)){
  body.append(empty(proposal.target_state==='no_change'?'这份预览没有提出正文改动':'当前正文已包含这份预览内容','不需要重复保存；原正文和预览历史均保留。'),btn('返回待处理',()=>showAutomation(),'primary'));return;
 }
 const stale=proposal.target_state==='stale',unavailable=proposal.target_state==='unavailable';
 if(stale)body.append(el('div','你已修改原稿，这份 AI 预览基于旧版本。下面比较当前正文与预览；先手动合并，再核对保存。','notice'));
 if(unavailable)body.append(el('div','当前原稿无法读取，请先恢复对应资料；这份预览保留。','notice'));
 if(proposal.source_stale)body.append(el('p','依据资料已有新版本，请从当前资料重新准备修改建议。','notice'));
 const pane=el('div',null,'note-comparison-pane'),views=proposal.kind==='document'?[['diff','修改红绿对照'],['body','拟更新正文']]:[['diff','修改红绿对照']];
 const choose=tabs(views,views[0][0],drawPreview);body.append(choose,pane);
 function drawPreview(tab){choose.querySelectorAll('button').forEach((b,i)=>b.classList.toggle('active',views[i][0]===tab));pane.replaceChildren();pane.classList.toggle('document-body',tab==='body');
  if(tab==='body'){pane.append(markdown(proposal.after,objectForPath(proposal.target.path)?.id));return;}
  pane.append(el('p','红色：删去的旧文字；绿色：加入的新文字。颜色只表示改动，不代表内容已核查。','section-subtitle'));
  const rows=stale?proposal.current_diff:proposal.diff||[],groups=[];for(const row of rows){const last=groups[groups.length-1];if(last?.kind===row.kind)last.rows.push(row);else groups.push({kind:row.kind,rows:[row]});}
  for(const group of groups){const fragment=document.createDocumentFragment();for(const row of group.rows)fragment.append(el('div',row.text,'diff-row '+row.kind));
   if(group.rows.length>12&&group.kind!=='added'){const folded=el('details',null,'source-change');folded.append(el('summary',(group.kind==='removed'?'移除的旧内容':'未改动的内容')+' · '+group.rows.length+' 行'));folded.append(fragment);pane.append(folded);}else pane.append(fragment);
  }
 }drawPreview(views[0][0]);
 const actions=el('div',null,'form-actions');
 if(proposal.kind==='document'&&!unavailable&&!proposal.source_stale)actions.append(btn(stale?'手动合并到当前稿':'手工修改建议正文',()=>editProposalPreview(proposal),'','edit'));
 actions.append(btn('不采纳这份预览',async()=>{await api('/api/ai-reject',{id,fingerprint:proposal.fingerprint});if(await finishReview('proposal',id))return;await showAutomation();notify('预览已移入可恢复垃圾箱，原稿保留');}));
 if(!stale&&!unavailable&&!proposal.source_stale)actions.append(btn('确认保存到原稿',async()=>{await api('/api/ai-apply',{id,fingerprint:proposal.fingerprint,confirmed:true});if(await finishReview('proposal',id))return;await loadWorkspace();dismiss();renderRoute();notify('已保存到正式正文，关联页面自动刷新');},'primary','check'));
 body.append(actions);
}

function editProposalPreview(proposal){
 const stale=proposal.target_state==='stale',body=modal(stale?'合并当前正文与旧 AI 预览':'手工修改建议正文');
 const generation=S.overlayGeneration,project=S.project,active=()=>generation===S.overlayGeneration&&project===S.project&&$('overlay').open;
 body.append(el('p',stale?'合并稿以你的当前正文开始。按需补入 AI 建议，保留已经更新的内容，核对后一次保存。':'只有需要调整 AI 建议文字时才使用；保存前仍会再次核对来源版本。','section-subtitle'));
 if(stale){const details=el('details',null,'source-change');details.open=true;details.append(el('summary','对照旧 AI 预览'));const original=el('div',null,'source-change-body');original.append(markdown(proposal.after,objectForPath(proposal.target.path)?.id));details.append(original);body.append(details);}
 const text=el('textarea');text.rows=16;text.style.width='100%';text.value=stale?proposal.current.body:proposal.after;text.setAttribute('aria-label',stale?'合并后的建议正文':'建议正文');
 const draftKey='research:proposal-draft:'+proposal.id;let draft=null;try{draft=JSON.parse(localStorage.getItem(draftKey));}catch(_){}
 if(draft?.body&&draft.fingerprint===proposal.fingerprint&&draft.current_fingerprint===(proposal.current?.fingerprint||'')){text.value=draft.body;body.append(el('p','已恢复尚未保存的本机编辑稿。','section-subtitle'));}
 else if(draft?.body){const recovery=el('details',null,'source-change');recovery.append(el('summary','有一份基于旧版本的本机编辑稿'),el('p','当前预览或原稿已经变化，先对照后再继续合并。','section-subtitle'),el('pre',draft.body),btn('载入本机编辑稿继续合并',()=>{text.value=draft.body;text.oninput();},'quiet-button'));body.append(recovery);}
 text.oninput=()=>localStorage.setItem(draftKey,JSON.stringify({body:text.value,fingerprint:proposal.fingerprint,current_fingerprint:proposal.current?.fingerprint||''}));
 body.append(text,btn('更新修改对照',async()=>{
  await api('/api/ai-revise',{id:proposal.id,fingerprint:proposal.fingerprint,after:text.value,
   ...(stale?{rebase:true,current_fingerprint:proposal.current.fingerprint}:{})});if(!active())return;
  localStorage.removeItem(draftKey);await showProposal(proposal.id);
 },'primary'));
}


function relationFailureMessage(message){
 return String(message||'').replace(/跨资料关联两次未通过格式或来源校验；原资料保留，可稍后重试。/,'关联分析未完成。')
  .replace('关联必须指向本次提供的候选资料，不能编造对象。','AI 返回的资料编号或关系类型不在本批允许列表中，该批候选未保存。')
  .replace(/[；。]?结束状态：stop/g,'');
}

function updateAutomationAttention(){
 const count=S.workspace.review_counts?.attention??(S.workspace.pending||[]).filter(row=>!row.automatic).length,attention=$('attentionCount');
 attention.textContent=count;attention.hidden=!count;
 attention.title=count+' 项需要处理';
}

