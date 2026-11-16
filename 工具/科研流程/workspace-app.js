'use strict';
// The shell owns navigation. Every document link resolves to the same object view.
const $=id=>document.getElementById(id);
const S={project:localStorage.getItem('research:project')||'山药',workspace:null,route:'projects',tab:'papers',doc:null,editor:null,dirty:false,graph:null,chat:null,chatBusy:false,renderToken:0};
const icons={
 radar:'<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><path d="M12 12l7-7M12 4v3M4 12h3M12 17v3M17 12h3"/>',
 book:'<path d="M3 5c3-1 6-1 9 1 3-2 6-2 9-1v14c-3-1-6-1-9 1-3-2-6-2-9-1zM12 6v14"/>',
 layers:'<path d="M3 7l9-4 9 4-9 4zM3 12l9 4 9-4M3 17l9 4 9-4"/>',
 flask:'<path d="M9 3h6M10 3v7l-6 9a1.3 1.3 0 001 2h14a1.3 1.3 0 001-2l-6-9V3M7 15h10"/>',
 chart:'<path d="M4 3v17h17M7 14l4-5 4 3 5-7"/>',
 output:'<rect x="4" y="5" width="16" height="16" rx="2"/><path d="M8 3h8M8 11h8M8 15h5"/>',
 search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/>',
 sparkles:'<path d="M12 3l2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5zM20 2v4M18 4h4"/>',
 close:'<path d="M6 6l12 12M18 6L6 18"/>',
 arrow:'<path d="M5 12h14M14 7l5 5-5 5"/>',
 back:'<path d="M19 12H5M10 7l-5 5 5 5"/>',
 plus:'<path d="M12 5v14M5 12h14"/>',
 settings:'<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3" fill="currentColor" stroke="none"/><circle cx="15" cy="17" r="3" fill="currentColor" stroke="none"/>',
 activity:'<path d="M3 12h4l3-8 4 16 3-8h4"/>',
 file:'<path d="M5 3h9l5 5v13H5zM14 3v5h5M9 12h6M9 16h6"/>',
 network:'<circle cx="12" cy="5" r="3"/><circle cx="5" cy="18" r="3"/><circle cx="19" cy="18" r="3"/><path d="M10.5 8L6.5 15M13.5 8l4 7M8 18h8"/>',
 check:'<path d="M5 12l4 4L19 6"/>',
 clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
 pause:'<path d="M9 5v14M15 5v14"/>',
 edit:'<path d="M14 5l5 5M4 20l4-1L21 6l-5-5L3 14z"/>',
 upload:'<path d="M12 16V3M7 8l5-5 5 5M4 15v6h16v-6"/>',
 link:'<path d="M9 15l6-6M8 16l-1 1a4 4 0 01-6-6l5-5a4 4 0 016 0M16 8l1-1a4 4 0 016 6l-5 5a4 4 0 01-6 0"/>',
 folder:'<path d="M3 6h7l2 2h9v12H3zM3 6V4h7l2 2h9v2"/>',
 archive:'<path d="M4 8v13h16V8M3 3h18v5H3zM9 12h6"/>',
 download:'<path d="M12 3v13M7 11l5 5 5-5M4 17v4h16v-4"/>',
 external:'<path d="M14 3h7v7M21 3L10 14M10 5H3v16h16v-7"/>'
};
function el(tag,text,cls){const e=document.createElement(tag);if(text!==undefined&&text!==null)e.textContent=String(text);if(cls)e.className=cls;return e;}
function ic(name){const s=document.createElementNS('http://www.w3.org/2000/svg','svg');s.setAttribute('viewBox','0 0 24 24');s.setAttribute('aria-hidden','true');s.classList.add('icon');s.innerHTML=icons[name]||icons.file;return s;}
function decorateIcons(root=document){root.querySelectorAll('[data-icon]').forEach(node=>node.replaceChildren(ic(node.dataset.icon)));}
function btn(text,action,cls='',icon){const b=el('button',null,cls);if(icon)b.append(ic(icon));b.append(document.createTextNode(text));b.type='button';b.onclick=()=>Promise.resolve().then(action).catch(error=>notify(error.message,true));return b;}
function field(label,input){const l=el('label',null,'form-field');l.append(el('span',label),input);input.setAttribute('aria-label',label);return l;}
function input(placeholder='',value=''){const i=el('input');i.placeholder=placeholder;i.value=value;return i;}
function select(options,label){const s=el('select');s.setAttribute('aria-label',label||'选择');for(const [v,t] of options){const o=el('option',t);o.value=v;s.append(o);}return s;}
function badge(text,tone=''){return el('span',text,'pill '+tone);}
function date(value){if(!value)return '时间待补';const d=new Date(typeof value==='number'?value*1000:value);return isNaN(d)?String(value).slice(0,10):d.toLocaleDateString('zh-CN',{month:'2-digit',day:'2-digit'});}
function docLabel(doc){return doc.display_title||doc.title;}
function docTime(doc){if(!doc.created)return date(doc.file_modified);const value=new Date(doc.created);return isNaN(value)?date(doc.file_modified):value.toLocaleString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});}
function safeUrl(url){try{const parsed=new URL(url,location.origin);if(['https:','http:','zotero:'].includes(parsed.protocol))return parsed.href;}catch(_){}return null;}
function extLink(label,url,cls='text-link'){const a=el('a',label,cls);const target=safeUrl(url);if(target){a.href=target;a.target='_blank';a.rel='noopener noreferrer';}return a;}
function notify(text,error=false){$('toast').textContent=text;$('toast').className='toast'+(error?' error-toast':'');$('toast').hidden=false;clearTimeout(notify.timer);notify.timer=setTimeout(()=>$('toast').hidden=true,error?9000:4500);}
async function api(path,body,options={}){const response=await fetch(path,body===undefined?options:{...options,method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});let data;try{data=await response.json();}catch(_){throw Error('服务暂时没有返回内容，请稍后重试');}const progress=body===undefined&&['/api/relations','/api/job'].includes(path.split('?')[0])&&typeof data.status==='string';if(!response.ok||(data.error&&!progress))throw Error((data.error||'请求没有完成')+(data.request_id?'（诊断号 '+data.request_id+'）':''));if(body!==undefined&&/\/api\/(workspace\/|knowledge\/classification\/|research\/create|project\/(?:profile|question|canvas)|administrator\/chat\/save-note)/.test(path)){S.knowledge=null;S.knowledgeRequest=null;S.workspaceStale=true;}return data;}
async function job(path,body,onProgress){
 const start=await api(path,body);if(!start.job_id)return start;
 for(;;){
  const item=await api('/api/job?id='+start.job_id);if(onProgress)onProgress(item);
  if(['done','completed','partial','waiting','skipped'].includes(item.status))return item.result;
  if(['failed','needs_review','unknown'].includes(item.status))throw Error(item.error||item.result?.message||'该任务需要核查，已保留在自动化与审核中');
  await new Promise(resolve=>setTimeout(resolve,1500));
 }
}
function markdown(body,base){return documentMarkdown(body,base);}
function empty(title,description,action){const n=el('div',null,'empty');n.append(ic('folder'),el('h3',title),el('p',description));if(action)n.append(action);return n;}
function heading(kicker,title,description,actions=[]){const n=el('div',null,'page-heading');const copy=el('div');copy.append(el('span',kicker,'overline'),el('h1',title));if(description)copy.append(el('p',description));n.append(copy);if(actions.length){const right=el('div',null,'page-actions');right.append(...actions);n.append(right);}return n;}
function section(title,description){const n=el('section');const h=el('div',null,'section-heading');h.append(el('h2',title));if(description)h.append(el('span',description));n.append(h);return n;}
function tabs(options,current,onChange){const n=el('div',null,'tabs');n.setAttribute('role','tablist');for(const [key,label]of options){const b=btn(label,()=>{for(const item of n.children){const selected=item===b;item.classList.toggle('active',selected);item.setAttribute('aria-selected',String(selected));}return onChange(key);},key===current?'active':'');b.setAttribute('role','tab');b.setAttribute('aria-selected',String(key===current));n.append(b);}return n;}
function searchField(placeholder){const n=el('div',null,'search-field'),i=input(placeholder);i.setAttribute('aria-label',placeholder);n.append(ic('search'),i);return {node:n,input:i};}
function modal(title){S.overlayGeneration=(S.overlayGeneration||0)+1;$('overlay').classList.remove('professional-dialog','skills-dialog');$('overlayTitle').textContent=title;$('overlayBody').classList.remove('scholarly-search');$('overlayBody').replaceChildren();if(!$('overlay').open)$('overlay').showModal();return $('overlayBody');}
function dismiss(){S.overlayGeneration=(S.overlayGeneration||0)+1;$('overlay').close();}
function visibleDocs(){return S.workspace.documents.filter(d=>!d.archived&&d.visibility!=='system');}
function objectForPath(path){return S.workspace.documents.find(d=>d.path===path||d.kb_path===path);}
function docRow(doc){const b=btn('',()=>navigate('document',doc.id),'list-row');const mark=el('span',null,'row-icon note');mark.append(ic(doc.kind.includes('报告')?'output':'file'));const copy=el('div',null,'row-copy');copy.append(el('strong',docLabel(doc)),el('p',doc.kind+' · '+doc.project+' · '+(doc.references.length+' 个引用 / '+doc.backlinks.length+' 处使用')+(doc.created?' · '+docTime(doc):'')));const aside=el('div',null,'row-aside');aside.append(badge(documentState(doc),!doc.ai_review_pending&&!doc.needs_review&&/候选/.test(doc.status)?'orange':''),el('span',date(doc.file_modified),'row-date'),ic('arrow'));b.append(mark,copy,aside);return b;}
function paperAvailabilityLabel(paper){return paper.has_original?'原文已保存':paper.availability==='original_missing'?'原文路径失效':'PDF / XML 待补';}
function paperRow(paper){const b=btn('',()=>navigate('paper',paper.id),'list-row'),mark=el('span',null,'row-icon paper');mark.append(ic('book'));const copy=el('div',null,'row-copy');copy.append(el('strong',paper.display_title||paper.title),el('p',(paper.publication_date||paper.year||'年份待补')+' · '+(paper.topic||'主题待补')+' · '+paper.documents.length+' 份相关资料'));const aside=el('div',null,'row-aside');aside.append(badge(paperAvailabilityLabel(paper),paper.has_original?'green':'orange'),ic('arrow'));b.append(mark,copy,aside);return b;}
function docCard(doc){const b=btn('',()=>navigate('document',doc.id),'doc-card');const meta=el('div',null,'card-meta');meta.append(el('span',doc.kind),el('span',docTime(doc)));const f=el('footer');f.append(doc.needs_review?badge('来源有更新','orange'):badge(doc.status),el('span',(doc.paper_ids.length||doc.references.length)+' 个关联来源'));b.append(meta,el('h3',docLabel(doc)),el('p',doc.excerpt),f);return b;}
function updateProjectPicker(data){
 const profiles=data.project_profiles||[],names=data.projects||profiles.map(p=>p.project),picker=$('projectContext');
 if(profiles.length)S.projectProfiles=profiles;
 const options=names.map(name=>{const profile=profiles.find(p=>p.project===name)||S.projectProfiles?.find(p=>p.project===name),o=el('option',(profile?.title||name)+(profile?.archived?'（已归档）':''));o.value=name;return o;});
 if(!names.includes(S.project)){const option=el('option',names.length?'请选择项目':'暂无项目');option.value='';option.disabled=true;options.unshift(option);}
 picker.replaceChildren(...options);picker.value=names.includes(S.project)?S.project:'';picker.disabled=!names.length;
 for(const id of ['searchButton','createRecord','assistantButton'])$(id).disabled=false;
}
const readWorkspace=WorkspaceLoading.createLoader(project=>api('/api/workspace?project='+encodeURIComponent(project)),()=>S.project,(workspace,project)=>{
 S.workspace=workspace;S.workspaceProject=project;S.workspaceStale=false;S.discoverWorkspaceRefresh?.(workspace,project);
});
function workspaceShell(request,project,token){return request.then(workspace=>{
 if(S.project===project&&S.renderToken===token){if(document.activeElement!==$('projectContext'))updateProjectPicker(workspace);updateAutomationAttention();$('connectionStatus').textContent='本机工作区已连接';}return workspace;
});}
function loadWorkspace(){const project=S.project,token=S.renderToken;return workspaceShell(readWorkspace(project,{refresh:true}),project,token);}
function ensureWorkspace(){const project=S.project,token=S.renderToken;return workspaceShell(S.workspace&&!S.workspaceStale&&S.workspaceProject===project?Promise.resolve(S.workspace):readWorkspace(project),project,token);}
function prepareIndependentShell(){
 for(const id of ['searchButton','createRecord','assistantButton'])$(id).disabled=false;
 const token=S.renderToken,project=S.project;
 api('/api/projects').then(data=>{if(token!==S.renderToken||project!==S.project)return;if(document.activeElement!==$('projectContext'))updateProjectPicker({project_profiles:data.records});$('connectionStatus').textContent='本机工作区已连接';}).catch(()=>{if(token===S.renderToken&&project===S.project)$('connectionStatus').textContent='项目列表等待连接恢复';});
}
function prepareKnowledgeShell(){
 for(const id of ['searchButton','createRecord','assistantButton'])$(id).disabled=false;
 if(S.knowledge)updateProjectPicker(S.knowledge);
 if(S.route==='knowledge-node'){if(!S.knowledge)updateProjectPicker({projects:[S.project]});return;}
 loadKnowledge().then(data=>{if(!['knowledge','knowledge-node'].includes(S.route))return;updateProjectPicker(data);$('breadcrumb').textContent=projectLabel(S.project);$('connectionStatus').textContent='全局知识已连接';}).catch(()=>{if(['knowledge','knowledge-node'].includes(S.route))$('connectionStatus').textContent='保留知识视图，等待连接恢复';});
}
async function selectWorkspaceProject(project){
 if(!project)return false;
 const selection=(S.projectSelection||Promise.resolve()).catch(()=>{}).then(async()=>{
  if(project===S.project)return false;
  await api('/api/administrator/settings',{project});
  preserveEditor();
  const input=$('chatInput'),drafts=S.chatInputs||=new Map();
  drafts.set(S.project,input.value);
  S.project=project;localStorage.setItem('research:project',project);input.value=drafts.get(project)||'';
  S.chatEpoch=(S.chatEpoch||0)+1;
  S.chat=null;S.discussion=null;S.workspace=null;S.questionId=null;S.reviewSession=null;
  if($('assistant').hidden===false){
   updateChatControls();$('chatStatus').textContent=S.chatBusy?'正在结合当前资料讨论…':'';
   updateAssistantContext();renderChat();refreshChat().catch(e=>notify(e.message,true));
  }
  return true;
 });
 S.projectSelection=selection;
 try{return await selection;}finally{if(S.projectSelection===selection)S.projectSelection=null;}
}
function preserveEditor(){if(!S.editor||!S.doc)return;const value={body:S.editor.getMarkdown(),title:$('editorTitle')?.value||S.doc.title,fingerprint:S.doc.fingerprint};if(value.body!==S.doc.body||value.title!==S.doc.title)localStorage.setItem('research:draft:'+S.doc.id,JSON.stringify(value));S.editor.destroy();S.editor=null;S.dirty=false;}
function navigate(route,id='',tab='',anchor=''){
 if(S.reviewSession&&['document','paper'].includes(route))S.reviewSession=ReviewQueue.suspend(S.reviewSession,{route,id});
 const query=new URLSearchParams();if(['document','paper'].includes(route)){const origin=new URLSearchParams(location.hash.split('?')[1]||'').get('question');if(S.route==='projects'&&S.questionId||origin)query.set('question',origin||S.questionId);}if(id)query.set('id',id);if(tab)query.set('tab',tab);if(anchor)query.set('anchor',anchor);
 const next='#'+route+(query.size?'?'+query:'');
 if(['document','paper','run','knowledge-node'].includes(route)&&location.hash&&next!==location.hash){S.materialBack||=new Map();S.materialBack.set(next,{hash:location.hash,label:S.route==='knowledge-node'?'返回知识详情':S.route==='paper'?'返回论文':S.route==='document'?'返回上份资料':S.route==='knowledge'&&S.tab==='graph'?'返回关系图':S.route==='projects'?'返回项目':'返回上一页'});}
 if(S.editor)preserveEditor();const previous=S.materialBack?.get(next);if(previous)S.pendingMaterialBack={target:next,value:previous};if(location.hash===next)renderRoute();else location.hash=next;
}
async function renderRoute(){
 const token=++S.renderToken,hash=location.hash;
 S.discoverWorkspaceRefresh=null;S.knowledgeDetailController?.destroy();S.knowledgeDetailController=null;
 if(S.pendingMaterialBack?.target===hash){history.replaceState({...history.state,researchBack:S.pendingMaterialBack.value},'');S.pendingMaterialBack=null;}
 if(history.state?.researchBack){S.materialBack||=new Map();S.materialBack.set(hash,history.state.researchBack);}
 S.knowledgeGraphController?.destroy();S.knowledgeGraphController=null;S.graphRefresh=null;S.canvasCleanup?.();preserveEditor();
 if(S.graph){
  const topicView=S.topicViews?.global;
  if(topicView&&S.graphContext==='topic')topicView.positions[topicView.root]={pan:S.graph.pan(),zoom:S.graph.zoom(),nodes:Object.fromEntries(S.graph.nodes().map(n=>[n.id(),{...n.position()}]))};
  const remembered=S.graphViews?.global;if(remembered&&S.graphContext==='network')remembered.pan=S.graph.pan();
  if(remembered&&S.graphContext==='network')remembered.zoom=S.graph.zoom();
  S.graph.destroy();S.graph=null;
 }
 const [route,query='']=(hash.slice(1)||'projects').split('?'),params=new URLSearchParams(query);
 S.route=route;S.doc=null;updateCreateRecordLabel();
 const label={discover:'发现',knowledge:'知识',projects:'项目',lab:'实验',analyze:'分析',outputs:'产出',document:'资料详情',paper:'文献详情',run:'分析记录'}[route]||'发现';
 document.querySelectorAll('#primaryNav button').forEach(b=>{const owner=(route==='document'||route==='paper')&&params.has('question')?'projects':route==='document'||route==='paper'||route==='knowledge-node'?'knowledge':route==='run'?'analyze':route;const active=b.dataset.route===owner;b.classList.toggle('active',active);b.setAttribute('aria-current',active?'page':'false');});
 $('breadcrumbDetail').textContent=params.has('question')?'研究问题 / '+label:label;
 const view=$('view');view.replaceChildren();view.classList.remove('page-enter');void view.offsetWidth;view.classList.add('page-enter');
 try{
  if(route==='projects'&&!params.has('project')&&!params.has('view')){
   await renderProjectCollection();if(token!==S.renderToken)return;
   $('breadcrumb').textContent='全部项目';$('breadcrumbDetail').textContent='项目集合';decorateIcons();return;
  }
  const project=params.get('project');
  if(route==='projects'&&params.get('view')!=='question-history'&&project&&project!==S.project){
   await selectWorkspaceProject(project);if(token!==S.renderToken)return;
  }
  $('breadcrumb').textContent=projectLabel(S.project);
  if(WorkspaceLoading.requiresWorkspace(hash))await ensureWorkspace();
  else if(['knowledge','knowledge-node'].includes(route))prepareKnowledgeShell();
  else prepareIndependentShell();
  if(token!==S.renderToken)return;
  switch(route){
   case 'knowledge-node':await renderKnowledgeNode(params.get('id'));break;
   case 'knowledge':await renderKnowledge(params.get('tab')||'documents');break;
   case 'projects':if(params.get('view')==='question-history')await renderProjectQuestionHistory(params);else await renderProjects();break;
   case 'lab':await renderLab();break;
   case 'analyze':await renderAnalyze();if(params.get('id')){const saved=await api('/api/professional/record?id='+encodeURIComponent(params.get('id')));if(token===S.renderToken)showBibliometricResult(saved);}break;
   case 'outputs':await renderOutputs();break;
   case 'document':await renderDocument(params.get('id'));break;
   case 'paper':await renderPaper(params.get('id'));break;
   case 'run':await renderRun(params.get('id'));break;
   default:await renderDiscover();
  }
  if(token!==S.renderToken)return;
  updateCreateRecordLabel();updateAssistantContext();
 }catch(error){if(token!==S.renderToken)return;view.replaceChildren(empty('暂时没有打开这个页面',error.message,btn('重新读取',()=>renderRoute())));}
 decorateIcons();
}

function discoverProjectFocus(project,workspace,progress,work){
 const stages=progress?.stages||[],current=[...stages,...(progress?.history||[])].find(s=>s.id===progress?.current_stage_id)||null;
 const active=(work?.items||[]).filter(item=>(item.item_type||'work')==='work'&&!item.done&&item.status!=='完成'&&!item.removed&&!item.replacement).map((item,index)=>({...item,_order:index})).sort((a,b)=>(a.pin_rank??Infinity)-(b.pin_rank??Infinity)||(a.status==='进行中'?0:1)-(b.status==='进行中'?0:1)||a._order-b._order);
 return {projectTitle:workspace?.project_profiles?.find(p=>p.project===project)?.title||project,current,stages,work:active,currentWork:current&&!current.removed?active.filter(item=>(item.stage_ids||[]).includes(current.id)):[]};
}
async function renderDiscover(){
 const token=S.renderToken,project=S.project,view=$('view');
 const isCurrent=()=>token===S.renderToken&&project===S.project&&S.route==='discover';
 let summaryWorkspace=null,latestRadar=null,focusData=null,focusPending=null,focusError='';
 view.append(heading('DISCOVER','今日研究','关注的论文在这里汇合。收录后，后台接着登记、检索和整理。',[btn('雷达设置',showWatches,'','settings'),btn('添加论文',showIntake,'primary','plus')]));
 const metrics=el('div',null,'summary-strip');metrics.append(el('div','项目统计正在读取…','summary-label'));view.append(metrics,renderUsageGuide());
 const split=el('div',null,'split'),left=el('div'),right=el('aside',null,'card-stack'),focusSlot=el('div'),projectCards=el('div',null,'card-stack');left.append(focusSlot);
 const radar=section('新论文提醒','近期相关线索'),radarBox=el('div',null,'list');radarBox.append(el('div',null,'skeleton'),el('div',null,'skeleton'));radar.append(radarBox);left.append(radar);
 const recent=section('最近编辑','只显示科研正文'),list=el('div',null,'list');list.append(el('p','项目资料正在读取…','muted'));recent.append(list);recent.classList.add('section-space');left.append(recent);
 const auto=el('div',null,'soft-card');projectCards.hidden=true;right.append(auto,projectCards);split.append(left,right);view.append(split);
 function drawAutomation(workspace){
  auto.replaceChildren(el('span','IN THE BACKGROUND','overline'),el('h3','机械工作交给后台'),el('p','原文登记、索引和状态自动维护；研究判断集中等待你确认。','section-subtitle'));
  const values=workspace?.flow_settings?.values;
  for(const [i,t,d]of[['sync','文献与笔记同步',!values?'正在读取设置…':values.sync_enabled?'按已配置的同步计划检查':'定时同步已暂停'],['radar','每日新论文提醒',!values?'正在读取提醒设置…':values.daily_enabled&&values.discover_enabled?'北京时间 '+(values.daily_time||'08:30'):'自动发现已暂停'],['clock','每周研究简报',!values?'正在读取设置…':values.daily_enabled?'每周一生成；同周变化更新预览':'周报自动检查已暂停']]){const row=el('div',null,'pipeline-step'),mark=el('span');mark.append(ic(i));const copy=el('div');copy.append(el('span',t),el('small',d));row.append(mark,copy);auto.append(row);}
  auto.append(el('p','本机后台运行期间处理。','muted'));
 }
 function drawProjectFocus(){
  if(!isCurrent())return;const model=discoverProjectFocus(project,summaryWorkspace,focusData?.progress,focusData?.work),current=model.current,focus=el('div',null,'project-focus');focus.dataset.projectFocus=project;
  focus.append(el('span','当前项目 · '+model.projectTitle,'overline'),el('h2',focusData?(current?.title||'尚未选择当前节点'):(focusError?'当前节点暂未读取':'正在读取当前节点…')));
  const openProject=stage=>{location.hash='#projects?'+new URLSearchParams({project,view:'progress',...(stage?{stage}:{})});};
  if(current){focus.append(badge(current.removed?'已移除 · 历史节点':current.stage_status,current.removed?'':'green'),el('p',current.removed?'当前选择的节点已移除，可回看历史或在项目中重新选择。':current.goal||'此节点尚未填写目标。'));}
  else if(focusData)focus.append(el('p',model.stages.length?'已有 '+model.stages.length+' 个阶段；进入项目选择当前节点。':'尚未建立阶段，已有项目工作和原稿仍可在项目中继续。'));
  if(focusError)focus.append(el('p','当前进展读取失败：'+focusError,'muted'),btn('重新读取当前进展',requestProjectFocus,'quiet-button'));
  if(focusData){focus.append(el('h3','项目当前工作 · '+model.work.length),el('p',current&&!current.removed?'本节点 '+model.currentWork.length+' 项未完成工作。':'以下为整个项目的未完成工作。','section-subtitle'));
   for(const item of model.work.slice(0,3)){const stage=model.stages.find(s=>s.id===((item.stage_ids||[]).includes(current?.id)?current.id:(item.stage_ids||[]).find(id=>model.stages.some(s=>s.id===id))));const row=el('div');row.append(btn(item.title||item.text,()=>openProject(stage?.id),'text-link'),el('p',(stage?.title||'项目工作')+' · '+(item.status||'待定'),'muted'));focus.append(row);}
   if(!model.work.length)focus.append(el('p','暂无未完成工作。','muted'));if(model.work.length>3)focus.append(el('p','还有 '+(model.work.length-3)+' 项，进入项目查看。','muted'));
  }
  focus.append(btn(current?'打开当前节点':'进入项目',()=>openProject(current?.id),'quiet-button','arrow'));
  const questions=summaryWorkspace?.mainlines?.rows||[];if(questions.length){const references=el('details');references.append(el('summary','原研究问题 · '+questions.length));for(const question of questions)references.append(el('h4',question.title),el('p',question.goal||''));references.append(btn('打开项目总览',()=>{location.hash='#projects?'+new URLSearchParams({project,view:'overview'});},'text-link'));focus.append(references);}
  focusSlot.replaceChildren(focus);
 }
 function requestProjectFocus(){
  if(focusPending)return focusPending;focusError='';focusPending=Promise.all([api('/api/project-progress?project='+encodeURIComponent(project)),api('/api/project-work?project='+encodeURIComponent(project))]).then(([progress,work])=>{if(!isCurrent())return;if(progress.project&&progress.project!==project||work.project&&work.project!==project)throw Error('项目已切换，请重新读取');focusData={progress,work};drawProjectFocus();}).catch(error=>{if(isCurrent()){focusError=error.message;drawProjectFocus();}}).finally(()=>{focusPending=null;});return focusPending;
 }
 function drawWeeklyPreview(){
  const weekly=latestRadar?.weekly,card=right.querySelector('[data-weekly-card]');if(!card)return;card.querySelector('[data-weekly-preview]')?.remove();
  if(weekly?.proposal_id&&(weekly.proposal_pending||(summaryWorkspace?.pending||[]).some(p=>p.id===weekly.proposal_id))){const preview=btn('查看周报更新预览',()=>showProposal(weekly.proposal_id),'quiet-button','edit');preview.dataset.weeklyPreview='true';card.append(preview);}
 }
 function drawSummary(workspace){
  if(!isCurrent()||workspace===summaryWorkspace||workspace!==S.workspace)return;summaryWorkspace=workspace;
  const docs=workspace.documents.filter(d=>!d.archived&&d.visibility!=='system');metrics.replaceChildren();
  for(const [n,t]of[[workspace.papers.length,'已积累文献'],[docs.filter(d=>d.kind==='阅读笔记').length,'阅读笔记'],[workspace.pending.length,'修改待确认']]){const item=el('div');item.append(el('strong',n),el('span',t));metrics.append(item);}metrics.append(el('div',new Date().toLocaleDateString('zh-CN',{month:'long',day:'numeric',weekday:'long'}),'summary-label'));
  drawProjectFocus();
  list.replaceChildren();docs.filter(d=>d.visibility==='active').sort((a,b)=>b.file_modified-a.file_modified).slice(0,4).forEach(d=>list.append(docRow(d)));drawAutomation(workspace);projectCards.replaceChildren();
  if(workspace.tasks.items.length){const tasks=el('div',null,'card');tasks.append(el('h3','项目待办'),el('p',workspace.tasks.items.filter(t=>!t.done).length+' 项未完成，在项目区统一维护。','section-subtitle'));projectCards.append(tasks);}
  const changes=docs.filter(d=>d.needs_review);if(changes.length){const card=el('div',null,'card');card.append(el('h3','来源有更新'),el('p',changes.length+' 份资料引用的正文发生了变化。','section-subtitle'));changes.slice(0,3).forEach(d=>card.append(btn(docLabel(d),()=>navigate('document',d.id),'text-link')));projectCards.append(card);}projectCards.hidden=!projectCards.childElementCount;drawWeeklyPreview();
 }
 const requestSummary=()=>ensureWorkspace().then(drawSummary).catch(error=>{if(!isCurrent())return;metrics.replaceChildren(el('div','项目摘要暂未读取：'+error.message,'summary-label'),btn('重新读取项目摘要',requestSummary,'quiet-button'));});
 S.discoverWorkspaceRefresh=(workspace,loadedProject)=>{if(loadedProject===project){const hadSummary=!!summaryWorkspace;drawSummary(workspace);if(hadSummary)requestProjectFocus();}};drawAutomation(null);drawProjectFocus();
 const discoverActions=view.querySelector('.page-actions');if(discoverActions)discoverActions.prepend(btn('文献检索',showScholarlySearch,'','search'));
 radar.querySelector('.section-heading h2').textContent='今日推荐阅读';radar.querySelector('.section-heading span').textContent='主题、方法与课题背景，优先未推荐的论文；发表日期照实显示';
 for(const label of right.querySelectorAll('.pipeline-step span'))if(label.textContent==='每日文献雷达')label.textContent='每日新论文提醒';
 const radarStats=el('div',null,'radar-metrics'),radarState=el('p',null,'section-subtitle'),radarFooter=el('div',null,'toolbar');radarFooter.style.marginTop='13px';radar.insertBefore(radarStats,radar.querySelector('.list'));radar.append(radarState,radarFooter);
  let radarRequest=0;const drawRadar=async()=>{const request=++radarRequest;try{
   const data=await api('/api/radar/page?scope=reading&limit=30');if(!isCurrent()||request!==radarRequest)return;latestRadar=data;
  radarState.textContent=radarStatus(data);radarBox.replaceChildren();radarStats.replaceChildren();
  for(const [n,t]of[[data.counts?.reading,'今日推荐'],[data.reading?.first_seen_today,'推荐中今日发现'],[data.counts?.queue,'待获取'],[data.counts?.updates,'来源变化']]){const item=el('div');item.append(el('strong',n||0),el('span',t));radarStats.append(item);}
  const records=(data.candidates||[]).filter(p=>!p.selected&&p.reading);
  if(!records.length)radarBox.append(empty('暂缺有明确阅读依据的推荐','可先检查最新论文或调整关注；信息不足的题录不会用于填满推荐。'));
   records.forEach(p=>radarBox.append(radarRow(p)));
  radarFooter.replaceChildren(el('small',data.reading?.message||'阅读推荐与今日首次发现分别统计。'),btn('查看今日推荐 · '+(data.counts?.reading||0),()=>showRadar(data,'reading'),'quiet-button','book'),btn('查看近期未处理 · '+(data.counts?.recent_visible??data.counts?.focus??0),()=>showRadar(data,'recent'),'quiet-button','radar'));
  if(data.counts?.new)radarFooter.append(btn('今日首次发现 · '+data.counts.new,()=>showRadar(data,'new'),'quiet-button','book'));
  const background=data.counts?.background||0;if(background)radarFooter.append(btn('拓展阅读 · '+background,()=>showRadar(data,'background'),'quiet-button','folder'));
  if(data.counts?.queue)radarFooter.append(btn('获取队列 · '+data.counts.queue,()=>showRadar(data,'queue'),'quiet-button','download'));
  const unread=data.counts?.updates??(data.alerts||[]).filter(a=>!a.acknowledged).length;if(unread)radarFooter.append(btn('文献变化 · '+unread,()=>showRadar(data,'updates'),'quiet-button','activity'));
  let weeklyCard=right.querySelector('[data-weekly-card]');if(!weeklyCard){weeklyCard=el('div',null,'card');weeklyCard.dataset.weeklyCard='true';right.append(weeklyCard);}weeklyCard.replaceChildren(el('h3','每周研究简报'),el('p',data.weekly?.week?data.weekly.week+' · '+weeklySummary(data.weekly):'每周一汇总重点论文、来源变化和带证据候选。','section-subtitle'));
  if(data.weekly?.updated||data.weekly?.created)weeklyCard.append(el('p','最近整理：'+new Date(data.weekly.updated||data.weekly.created).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+' · 每周一08:30后自动生成','muted'));
  if(data.last_attempt?.errors?.length)weeklyCard.append(el('p','来源连接有异常，简报可能缺少最新论文。','muted'));
  if(data.weekly?.path)weeklyCard.append(btn('打开周报',()=>openWeeklyBrief(data.weekly),'quiet-button','book'));
  drawWeeklyPreview();
  if(data.weekly?.stale)weeklyCard.append(el('p','关注规则或来源已变化，后台将更新本周预览；已有正文保留。','section-subtitle'));
  if(data.weekly?.synthesis_status==='needs_attention')weeklyCard.append(el('p','证据整理有待检查，已有正文与来源保留。','section-subtitle'));
  weeklyCard.append(btn('整理最新线索',async()=>{await job('/api/weekly_refresh',{});await loadWorkspace();await drawRadar();notify('已整理最新线索；已有周报保留，修改预览在待处理中核对。');},'quiet-button','sparkles'));
  const requested=new URLSearchParams(location.hash.split('?')[1]||'').get('radar');if(requested&&S.openedRadarHash!==location.hash){S.openedRadarHash=location.hash;showRadar(data,requested);}
  }catch(error){if(!isCurrent()||request!==radarRequest)return;radarState.textContent='来源状态暂未读取，保留当前候选';if(!radarBox.querySelector('.list-row'))radarBox.replaceChildren(empty('雷达暂时没有连接',error.message));}};
 S.radarRefresh=drawRadar;const radarReady=drawRadar();requestProjectFocus();requestSummary();await radarReady;
}
function taskRow(item){const label=el('label',null,'task-row'),check=el('input');check.type='checkbox';check.checked=item.done;check.setAttribute('aria-label',item.text);check.onchange=async()=>{check.disabled=true;try{S.workspace.tasks=await api('/api/task',{project:S.project,index:item.index,done:check.checked,fingerprint:S.workspace.tasks.fingerprint});notify('任务状态已保存');}catch(error){check.checked=!check.checked;notify(error.message,true);}finally{check.disabled=false;}};label.append(check,el('span',item.text));return label;}
function weeklySummary(weekly){
 if(weekly.stale)return '规则或来源已变化，等待更新';
 return (weekly.proposal_pending?'更新预览 · ':'已保存正文 · ')+(weekly.focus??'待整理')+' 篇重点线索';
}
function radarHealthMessage(radar){
 if(radar.bounded_ok)return '本轮检查已完成；已到每日额度或本轮扫描范围，进度保留后接续。';
 if(radar.ok)return '近期有界增量查询已完成；上游覆盖仍受检索式和索引延迟限制。';
 return '当前没有可确认的近期提醒扫描；知识区文献库不受影响。';
}
async function openWeeklyBrief(receipt){await loadWorkspace();const doc=objectForPath(receipt.path);if(!doc)throw Error('周报索引尚未更新，请稍后重试');dismiss();navigate('document',doc.id);}
const radarTierLabels={direct:'主题相关',adjacent:'方法相关',background:'拓展阅读',pending:'题录待判断',noise:'噪声档案'};
const radarTierTones={direct:'green',adjacent:'blue',background:'orange',pending:'orange',noise:'red'};
const radarIrrelevantOptions=[['object_mismatch','研究对象不符'],['method_mismatch','研究方法不符'],['task_mismatch','研究任务不符'],['peer_review','同行评审材料'],['duplicate','重复线索'],['insufficient_evidence','题录信息不足'],['other','其他原因']];
function radarIrrelevantLabel(code){return radarIrrelevantOptions.find(([value])=>value===code)?.[1]||'其他原因';}
function radarTier(p){return p.priority?.tier||(p.priority?.band==='focus'?'direct':'background');}
function radarAiTier(p){const ai=p.ai_relevance||{};if(radarTierLabels[ai.tier])return ai.tier;const score=ai.score;return Number.isFinite(score)?score>=70?'direct':score>=45?'adjacent':score>=30?'background':'noise':null;}
function radarCandidateKey(p){return p.external_id||p.openalex_id||p.doi||p.id;}
function radarAcquisitionLabel(p){const state=p.acquisition?.status||p.collection?.status||'queued';return {downloaded:'全文已保存',already_saved:'全文已沿用',pdf_unavailable:'已有 XML，PDF 待补',no_open_fulltext:'未找到开放全文',metadata_saved:'仅题录',selected:'排队中',queued:'排队中'}[state]||'处理中';}
async function markRadarIrrelevant(p,changed){
 const body=modal('标记为不相关'),reason=select(radarIrrelevantOptions,'不相关原因分类'),note=el('textarea'),actions=el('div',null,'form-actions');
 note.rows=3;note.maxLength=400;note.placeholder='可选：补充对象、方法或任务为何不符。该说明只用于人工反馈和同类排除建议。';
 body.append(el('p','请选择主要原因。原因会用于汇总跨论文的排除建议，但不会自动删除或改写候选。','section-subtitle'),field('原因分类',reason),field('补充说明',note));
 actions.append(btn('取消',dismiss,'quiet-button'),btn('确认不相关',async()=>{
  const result=await api('/api/radar/decision',{id:p.id,candidate_id:radarCandidateKey(p),decision:'irrelevant',reason_code:reason.value,reason:note.value.trim()||radarIrrelevantLabel(reason.value)});
  dismiss();await changed();
  const suggestion=result.insights?.suggestions?.find(item=>item.reason_code===reason.value);
  notify('已移入人工记录 · '+radarIrrelevantLabel(reason.value)+(suggestion?'；已生成同类排除建议':''));
 },'primary','x'));
 body.append(actions);
}
function radarRow(p,options={}){
 const row=el('div',null,'list-row radar-row');row.style.cursor='default';const copy=el('div',null,'row-copy');
 const title=String(p.title||'题名待补').replace(/<[^>]+>/g,''),meta=el('div',null,'badge-row');
 meta.append(badge(radarTierLabels[radarTier(p)]||'待分层',radarTierTones[radarTier(p)]||''),badge(p.sources?.join(' / ')||p.source||'外部题录',''),el('span',(p.journal||p.venue||'期刊待补')+' · '+(p.year||p.publication_date||'日期待补'),'muted'));
 copy.append(p.url?extLink(title,p.url,'text-link'):el('strong',title),meta);
 copy.append(el('small','发表：'+(p.publication_date||p.year||'来源未提供')+' · 首次发现：'+(p.first_seen?date(p.first_seen):'未记录')+' · 最近扫描：'+(p.last_seen||p.discovered?date(p.last_seen||p.discovered):'未记录'),'muted'));
 if(p.priority?.reason)copy.append(el('small',p.priority.reason,'muted'));
 if(p.reading){copy.append(badge(p.reading.category+' · '+p.reading.freshness,'blue'),el('p','为什么推荐：'+p.reading.reason,'section-subtitle'),el('small','推荐依据：'+p.reading.evidence+'；全文尚需核对。','muted'));}
 const aiTier=radarAiTier(p);if(p.ai_relevance&&aiTier)copy.append(el('small','AI 研判：'+(radarTierLabels[aiTier]||aiTier)+(p.ai_relevance.confidence?' · '+({high:'高',medium:'中',low:'低'}[p.ai_relevance.confidence]||p.ai_relevance.confidence):'')));
 if(p.ai_relevance?.reason){const suggested=el('details');suggested.append(el('summary','查看 AI 分层理由'),el('p',p.ai_relevance.reason,'section-subtitle'),el('p','依据：'+(p.ai_relevance.scope||'题录或摘要，未核查全文')+(p.ai_relevance.quote?' · “'+p.ai_relevance.quote+'”':''),'muted'));copy.append(suggested);}
 if(p.abstract){const details=el('details');details.append(el('summary','查看来源摘要'),el('p',p.abstract,'section-subtitle'));copy.append(details);}
 if(p.journal_ranks)copy.append(compactJournalRanks(p.journal_ranks));
 const actions=el('div',null,'radar-actions'),changed=options.onChanged||(()=>S.radarRefresh?.());
 if(options.selection&&!p.selected&&!p.acquisition){
  const select=el('input');select.type='checkbox';select.checked=options.selection.has(radarCandidateKey(p));select.setAttribute('aria-label','选择 '+title);
  const label=el('label',null,'review-batch-check');label.append(select,el('span','纳入批量保存'));
  select.onchange=()=>{if(select.checked)options.selection.add(radarCandidateKey(p));else options.selection.delete(radarCandidateKey(p));options.onSelectionChange?.();};actions.prepend(label);
 }
 if(options.queue){
  actions.append(badge(radarAcquisitionLabel(p),/failed|no_open|metadata|unavailable/.test(p.acquisition?.status||'')?'orange':'blue'),btn('重试获取',async()=>{await job('/api/radar/retry',{id:p.id,project:S.project});await loadWorkspace();await changed();notify('获取流程已重新执行');},'quiet-button','download'));
 }else if(options.archive&&p.decision&&p.decision!=='new'){
  actions.append(badge(({later:'稍后处理',browsed:'已浏览推荐',skipped:'已略过推荐'})[p.decision]||'不相关 · '+radarIrrelevantLabel(p.decision_reason_code),p.decision==='irrelevant'?'red':'orange'),btn('恢复到待判断',async()=>{await api('/api/radar/decision',{id:p.id,candidate_id:radarCandidateKey(p),decision:'reset'});await changed();notify('已恢复到待判断');},'quiet-button','back'));
 }else{
  actions.append(
   btn('收录',async()=>{const result=await job('/api/radar/collect',{doi:p.doi,external_id:p.external_id,id:radarCandidateKey(p),project:S.project});await loadWorkspace();await changed();notify(result.message||'已加入获取队列');},'primary','plus'),
   btn('稍后',async()=>{await api('/api/radar/decision',{id:p.id,candidate_id:radarCandidateKey(p),decision:'later',reason:'人工选择稍后处理'});await changed();notify('已移到“稍后”');},'quiet-button','clock'));
  if(p.reading)for(const [decision,label]of[['browsed','已浏览'],['skipped','略过']])actions.append(btn(label,async()=>{await api('/api/radar/decision',{id:p.id,candidate_id:radarCandidateKey(p),decision,reason:'本人'+label+'此阅读推荐；不改变论文精读或科学核查状态'});await changed();notify(label+'；可从人工记录恢复');},'quiet-button'));
  else actions.append(btn('不相关',()=>markRadarIrrelevant(p,changed),'quiet-button','x'));
 }
 row.append(copy,actions);return row;
}
function compactJournalRanks(ranks){
 const details=el('details',null,'journal-rank-details'),summary=el('summary'),states={needs_source:'待提供年度来源',needs_issn:'待补 ISSN',missing:'未匹配',ambiguous:'来源待核对'};
 let shown=0;for(const [system,label]of [['CAS','中科院'],['JCR','JCR']]){const value=ranks[system]||{},entries=(value.entries||[]).filter(e=>system!=='CAS'||e.scope==='major');if(value.status==='matched'&&entries.length){const q=[...new Set(entries.map(e=>e.quartile))].join('/');summary.append(badge(label+' '+q+(system==='CAS'?'区':'')+' · '+value.year,'green'));shown++;}}
 if(!shown)summary.append(el('span','分区未匹配','muted'));details.append(summary);
 for(const [system,label]of [['CAS','中科院'],['JCR','JCR'],['XR','新锐']]){const value=ranks[system]||{status:'needs_source'};details.append(el('p',label+(value.year?' '+value.year:'')+' · '+(value.status==='matched'?'按 ISSN 匹配':states[value.status]||'待核对'),'muted'));for(const entry of value.entries||[]){const title=entry.category+' · '+(entry.scope==='major'?'大类':entry.scope==='minor'?'小类':'学科')+' · '+entry.quartile+(system==='JCR'?'':'区');details.append(el('p',title,'muted'));if(entry.uri)details.append(extLink(entry.source||'分区来源',entry.uri,'text-link'));}}
 return details;
}

function radarStatus(data){
 const attempt=data.last_attempt||{},pending=attempt.pending_pages?.length||0,errors=attempt.errors?.length||0,skipped=attempt.skipped?.length||0,budget=attempt.budget_deferred?.length||0;
 if(!attempt.checked)return '等待首次更新 · 本机后台运行时自动处理';
 const stamp=new Date(attempt.checked).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
 return '最近更新 '+stamp+' · '+(errors?'部分来源暂未连接，已保留进度':pending?'正在分批接续，现有提醒可先查看':budget?'今日来源已按设定上限检查；需要即时查论文请用“文献检索”':skipped?'部分关注未配置来源':attempt.status==='completed'?'本轮有界提醒已更新':'本轮尚未全部完成')+(data.index_status==='refreshing'?' · 索引正在后台更新':'')+(data.scheduler==='local_fallback'?' · 本机备用调度接续':'');
}
const radarAlertLabels={citation:'引用数量变化',retraction:'撤稿标记变化',metadata:'题录变化',publication_update:'出版更新线索'};
function radarAlertRow(alert,back){
 const row=btn('',()=>showRadarAlert(alert,back),'list-row'),copy=el('div',null,'row-copy');
 copy.append(el('strong',alert.title||alert.doi||'文献变化'),el('p',(radarAlertLabels[alert.kind]||'来源更新')+' · '+alert.source+' · '+date(alert.created)));
 row.append(copy,badge(alert.acknowledged?'已查看':'待查看',alert.acknowledged?'':'orange'),ic('arrow'));return row;
}
function showRadarAlert(alert,back){
 const body=modal('文献变化');body.append(el('h3',alert.title||alert.doi),badge(radarAlertLabels[alert.kind]||'来源更新','orange'),el('p','这是来源元数据变化线索。是否影响课题和已用结论，需要结合原文核对。','section-subtitle'));
 if(alert.kind==='citation')body.append(el('p','引用数量：'+(alert.before?.citation_count??'未记录')+' → '+(alert.after?.citation_count??'未提供')));
 if(alert.kind==='retraction')body.append(el('p','来源撤稿标记：'+(alert.before===null?'本系统首次发现':alert.before?.retracted?'已标记':'未标记')+' → '+(alert.after?.retracted?'已标记':'未标记')));
 if(alert.kind==='metadata'){body.append(el('p','此前题名：'+(alert.before?.title||'未记录')),el('p','当前题名：'+(alert.after?.title||'未提供')));}
 const links=el('div',null,'toolbar');links.append(extLink('核对来源',alert.url));if(alert.paper_id)links.append(btn('打开对应文献',()=>{dismiss();navigate('paper',alert.paper_id);},'quiet-button','book'));body.append(links);
 if(alert.kind==='publication_update'){
  const notices=alert.after?.notices||[];for(const notice of notices){const name=Array.isArray(notice.title)?notice.title.join(' '):notice.title;body.append(extLink(name||notice.doi||'更新说明','https://doi.org/'+notice.doi));}
  const details=el('details');details.append(el('summary','查看来源提交的更新关系'),el('pre',JSON.stringify({before:alert.before,after:alert.after},null,2),'code-text'));body.append(details);
 }
 const actions=el('div',null,'form-actions');actions.append(btn('返回提醒',back));if(!alert.acknowledged)actions.append(btn('标记已查看',async()=>{await api('/api/radar/acknowledge',{id:alert.id});await back();notify('已标记查看，科研影响仍需核对');},'primary','check'));body.append(actions);
}
function showRadar(data,initialTab='reading'){
 const alias={focus:'recent',candidates:'reading',supplementary:'background'},scopes=[['recent','近期未处理'],['direct','主题相关'],['adjacent','方法相关'],['new','今日首次发现（主题/方法）'],['pending','题录待判断'],['background','拓展阅读'],['later','稍后'],['archive','已处理记录'],['queue','获取队列'],['updates','文献变化']];
 let active=alias[initialTab]||initialTab;if(active!=='reading'&&!scopes.some(([id])=>id===active))active='reading';
 const body=modal('论文雷达与每日阅读'),{node,input:search}=searchField('筛选题名、摘要、DOI 或来源'),list=el('div',null,'list');
 let offset=0,revision=0,searchTimer,rapid=false,rapidIndex=0,currentCandidates=[];
 const selectedPapers=new Set(),batch=el('div',null,'review-batch'),batchText=el('strong'),selectPage=btn('选择本页','','quiet-button','check'),saveSelected=btn('保存所选论文','','primary','download');
 batch.append(batchText,selectPage,saveSelected);batch.hidden=true;
 const status=el('p',radarStatus(data),'section-subtitle'),includeRead=el('input');includeRead.type='checkbox';includeRead.setAttribute('aria-label','包括已查看的变化');
 const readLabel=el('label',null,'task-row');readLabel.append(includeRead,el('span','包括已查看'));
 const days=select([['7','近 7 天'],['30','近 30 天'],['90','近 90 天'],['365','近一年'],['all','全部时间']],'研判时间范围');days.value='90';
 const rankSystem=select([['CAS','中科院 · 大类'],['JCR','JCR · JIF学科']],'提醒分区体系'),rankQuartile=select([['','全部分区'],['1','1区 / Q1'],['2','2区 / Q2'],['3','3区 / Q3'],['4','4区 / Q4'],['unknown','分区未匹配']],'提醒分区筛选');
 const reminderLimit=select([[5,'每日最多 5 篇'],[10,'每日最多 10 篇'],[20,'每日最多 20 篇'],[50,'每日最多 50 篇'],[100,'每日最多 100 篇']],'每日提醒篇数');reminderLimit.value=String(data.reminder_limit??data.preferences?.reminder_limit??10);
 let readingCount=data.counts?.reading;
 const scope=select(scopes,'线索范围');scope.value=active==='reading'?'recent':active;
 const labels=()=>[['reading','今日阅读'+(Number.isFinite(readingCount)?' · '+readingCount:'')],['all','全部线索']];
 const tabbar=tabs(labels(),active==='reading'?'reading':'all',key=>{active=key==='reading'?'reading':scope.value;offset=0;rapidIndex=0;rapid=false;draw();}),pages=el('div',null,'pagination'),details=el('details'),guidance=el('p',null,'muted radar-guidance');tabbar.classList.add('radar-tabs');tabbar.setAttribute('aria-label','雷达主入口');
 scope.onchange=()=>{active=scope.value;offset=0;rapidIndex=0;rapid=false;draw();};
 function scopeLabels(counts){for(const option of scope.options){const name=scopes.find(([id])=>id===option.value)[1],count=option.value==='recent'?(counts?.recent_visible??counts?.focus):counts?.[option.value];option.textContent=name+(Number.isFinite(count)?' · '+count:'');}}
 const back=async()=>showRadar(await api('/api/radar/page?scope='+active+'&limit=5&days='+days.value+'&reminder_limit='+reminderLimit.value),active);
 function sourceDetails(attempt,attemptIndex,feedback){
  details.replaceChildren(el('summary','来源完整性与人工反馈'));const statusText={completed:'已检查',pending:'待接续',not_due:'本期已完成',needs_configuration:'待配置',failed:'连接失败'};
  if(attempt?.counts){const c=attempt.counts;details.append(el('p','本轮扫描 '+(c.scanned||0)+' · 重复 '+(c.duplicate||0)+' · 新题录 '+(c.new||0)+' · 条件命中 '+(c.matched||0)+' · 题录待判断 '+(c.pending||0)+' · 失败 '+(c.failed||0)+' · 初筛排除 '+(c.excluded||0),'muted'));}
  for(const [name,state]of Object.entries(attempt?.source_status||{})){const extra=Number.isFinite(state?.upstream_total)?' · 上游 '+state.upstream_total+' 条，已扫描 '+(state.scanned||0)+' 条':'';
   details.append(el('p',name+' · '+(statusText[state.status]||state.status||'未知')+extra+(state.truncated?' · 尚有页面待接续':'')+(state.error_type?' · '+state.error_type:'')+(state.http_status?' · HTTP '+state.http_status:'')+(state.message?' · '+state.message:'')+(state.retry_after?' · 建议等待 '+state.retry_after:''),'section-subtitle'));}
  for(const value of attempt?.pending_pages||[])details.append(el('p',value+' · 尚有页面待接续','section-subtitle'));
  for(const value of attempt?.skipped||[])details.append(el('p',value+' · 当前关注缺少可用来源配置','section-subtitle'));
  for(const value of attempt?.unavailable||[])details.append(el('p',value.doi+' · '+value.reason+' · 定期回查','section-subtitle'));
  if(attemptIndex?.status==='failed')details.append(el('p','候选索引刷新失败 · '+(attemptIndex.error_type||'未知错误')+'，旧索引继续可用','section-subtitle'));
  if(attemptIndex?.status==='running'&&attemptIndex?.message)details.append(el('p',attemptIndex.message,'section-subtitle'));
  for(const group of feedback?.groups||[])details.append(el('p','人工不相关 · '+group.label+' '+group.count+' 篇','section-subtitle'));
  for(const suggestion of feedback?.suggestions||[])details.append(el('p','同类排除建议 · '+suggestion.label+'已累计 '+suggestion.count+' 篇：'+suggestion.message,'section-subtitle'));
 }
 sourceDetails(data.last_attempt,data.last_index,data.feedback);
 const batchable=()=>currentCandidates.filter(p=>!p.selected&&!p.acquisition);
 function drawBatch(){
  const rows=batchable(),chosen=rows.filter(p=>selectedPapers.has(radarCandidateKey(p)));
  batch.hidden=rapid||['queue','archive','later','updates'].includes(active)||!rows.length;
  batchText.textContent='本页 '+rows.length+' 篇可保存 · 已选 '+chosen.length+' 篇';
  selectPage.disabled=!rows.length||chosen.length===rows.length;
  saveSelected.disabled=!chosen.length;saveSelected.textContent=chosen.length?'保存所选 '+chosen.length+' 篇':'保存所选论文';
 }
 selectPage.onclick=()=>{for(const p of batchable())selectedPapers.add(radarCandidateKey(p));drawBatch();};
 saveSelected.onclick=async()=>{const items=[...selectedPapers];if(!items.length)return;saveSelected.disabled=true;saveSelected.textContent='正在加入保存队列…';try{const result=await api('/api/radar/collect-batch',{project:S.project,items:items.map(id=>({id}))});selectedPapers.clear();notify(result.message+(result.not_found?'；'+result.not_found+' 篇已退出当前范围':'')+(result.job_id?'；后台任务已排队':''));await draw();S.radarRefresh?.();}finally{if(saveSelected.isConnected)saveSelected.disabled=false;}};
 async function draw(){
  const request=++revision;modeButton.textContent=rapid?'列表模式':'逐篇研判';tabbar.querySelectorAll('button').forEach((b,i)=>{const selected=i===(active==='reading'?0:1);b.classList.toggle('active',selected);b.setAttribute('aria-selected',String(selected));});scope.hidden=active==='reading';readLabel.hidden=active!=='updates';days.hidden=['reading','queue','later','archive','updates'].includes(active);reminderLimit.hidden=active!=='new';
  guidance.textContent=active==='reading'?'按已启用的关注和阅读设置推荐；依据为题录与可得摘要，发表日期照实显示。':active==='pending'?'信息不足的临时线索，无需逐条审核，不计入今日阅读。与主题/方法共用保留天数，从首次发现算；到期退出当前列表，历史保留。天数在“自动化设置 → 更多雷达选项”调整；已收录或人工处理的记录另行保留。':'今日首次发现、阅读补充和人工处理分别保留，可通过线索范围切换。';
  currentCandidates=[];batch.hidden=true;list.replaceChildren(el('p','正在读取这页线索…','muted'));pages.replaceChildren();
  try{
   const params=new URLSearchParams({scope:active,offset:String(offset),limit:'30',q:search.value,include_read:String(includeRead.checked),days:days.value,reminder_limit:reminderLimit.value,rank_system:rankSystem.value,rank_quartile:rankQuartile.value}),page=await api('/api/radar/page?'+params);
   if(request!==revision||!list.isConnected)return;
   if(Number.isFinite(page.counts?.reading))readingCount=page.counts.reading;
   currentCandidates=page.candidates||[];drawBatch();
   status.textContent=radarStatus(page);labels().forEach((pair,i)=>tabbar.children[i].textContent=pair[1]);scopeLabels(page.counts);sourceDetails(page.last_attempt,page.last_index,page.feedback);list.replaceChildren();
   if(rapid&&active!=='updates'&&rapidIndex>=page.candidates.length&&page.has_more){offset+=page.candidates.length;rapidIndex=0;draw();return;}
   if(rapid&&active!=='updates'&&rapidIndex>=page.candidates.length)rapidIndex=Math.max(0,page.candidates.length-1);
   const visible=rapid&&active!=='updates'?page.candidates.slice(rapidIndex,rapidIndex+1):page.candidates;
   const selectable=!['queue','archive','later','updates'].includes(active);
   for(const row of active==='updates'?page.alerts:visible)list.append(active==='updates'?radarAlertRow(row,back):radarRow(row,{queue:active==='queue',archive:['archive','later'].includes(active),onChanged:draw,selection:selectable?selectedPapers:null,onSelectionChange:drawBatch}));
   if(!page.total)list.append(empty(active==='updates'?'暂无相应文献变化':active==='queue'?'获取队列为空':'暂无相应候选','更换筛选内容，或等待下一次来源更新。'));
   if(rapid&&active!=='updates'){
    const previous=btn('上一条',()=>{if(rapidIndex>0)rapidIndex--;else if(offset>0){offset=Math.max(0,offset-30);rapidIndex=29;}draw();},'quiet-button'),next=btn('下一条',()=>{if(rapidIndex<page.candidates.length-1)rapidIndex++;else if(page.has_more){offset+=page.candidates.length;rapidIndex=0;}draw();},'quiet-button');
    previous.disabled=offset===0&&rapidIndex===0;next.disabled=!page.has_more&&rapidIndex>=page.candidates.length-1;
    pages.append(previous,el('span',page.total?'逐篇 '+(offset+rapidIndex+1)+' / '+page.total:'0 条'),next);
   }else{
    const previous=btn('上一页',()=>{offset=Math.max(0,offset-30);draw();},'quiet-button'),next=btn('下一页',()=>{offset+=30;draw();},'quiet-button');previous.disabled=offset===0;next.disabled=!page.has_more;
    pages.append(previous,el('span',page.total?(offset+1)+'–'+Math.min(offset+30,page.total)+' / '+page.total+' 条':'0 条'),next);
   }
  }catch(error){if(request!==revision)return;list.replaceChildren(empty('这页暂未读取',error.message,btn('重试',draw,'quiet-button')));}
 }
 search.oninput=()=>{offset=0;rapidIndex=0;++revision;clearTimeout(searchTimer);searchTimer=setTimeout(draw,250);};includeRead.onchange=()=>{offset=0;rapidIndex=0;draw();};days.onchange=()=>{offset=0;rapidIndex=0;draw();};reminderLimit.onchange=async()=>{try{await api('/api/radar/preferences',{reminder_limit:Number(reminderLimit.value)});offset=0;rapidIndex=0;await draw();notify('每日提醒上限已保存；只保留主题与方法相关线索，不凑数');}catch(error){notify(error.message,true);}};
 const modeButton=btn('',()=>{rapid=!rapid;rapidIndex=0;draw();},'quiet-button radar-mode-button'),updateButton=btn('检查最新论文',async()=>{if(S.radarUpdating)return;updateButton.disabled=true;try{S.radarUpdating=job('/api/discover',{manual:true});const result=await S.radarUpdating;offset=0;rapidIndex=0;await draw();const c=result.counts||{};notify('扫描 '+(c.scanned||0)+' · 重复 '+(c.duplicate||0)+' · 新题录 '+(c.new||0)+' · 命中 '+(c.matched||0)+' · 待判断 '+(c.pending||0)+(result.errors?.length?' · 来源有异常，请查看回执':result.budget_deferred?.length?' · 已达每日上限':''),Boolean(result.errors?.length));}finally{S.radarUpdating=null;updateButton.disabled=false;}},'','radar'),top=el('div',null,'toolbar radar-toolbar');top.append(scope,node,updateButton,btn('雷达设置',()=>showWatches({onSaved:back,onCancel:back}),'quiet-button','settings'));
 const preferences=el('details',null,'radar-display-settings'),filters=el('div',null,'toolbar');filters.append(rankSystem,rankQuartile,days,reminderLimit,modeButton);preferences.append(el('summary','筛选与显示'),filters);
 for(const control of [rankSystem,rankQuartile])control.onchange=()=>{offset=0;rapidIndex=0;draw();};
 body.append(tabbar,top,guidance,preferences,batch,readLabel,list,pages,status,details);draw();
}


async function renderLab(){return renderLabWorkspace();}

async function renderAnalyze(){
 const token=S.renderToken,view=$('view');
 view.append(heading('ANALYZE','数据分析','选择文件，检查数据，再生成可修改和回溯的分析。',[btn('打开 TeraAnalyzer',async()=>{const result=await api('/api/professional/teraanalyzer',{});notify(result.message);},'','chart'),btn('方法与 QC',showMethods,'','settings'),btn('文献计量',showBibliometrics,'','network')]));
 view.append(analysisFileControl(file=>showAnalysisForm(file)).element);
 const history=await api('/api/data-analysis/history?project='+encodeURIComponent(S.project));if(token!==S.renderToken)return;
 await renderReceivedData(view,token);await renderAutomaticProgress(view,token);if(token!==S.renderToken)return;
 const list=el('div',null,'list'),panel=section('已有分析',history.records.length+' 组 · 同一数据的版本集中显示');
 for(const row of history.records){const b=btn('',()=>navigate('run',row.id),'list-row'),copy=el('div',null,'row-copy');copy.append(el('strong',row.filename),el('p',analysisKinds[row.kind]+' · '+date(row.created)+(row.versions>1?' · '+row.versions+' 个版本':'')));b.append(ic('chart'),copy,ic('arrow'));list.append(b);}
 if(!history.records.length)list.append(empty('还没有分析记录','从上方选择文件开始。保存后，输入、图表和说明都会集中在这条分析中。'));
 panel.append(list);view.append(panel);
}
async function renderOutputs(){
 const view=$('view'),project=S.project,token=S.renderToken;let revision=0;view.append(heading('OUTPUTS','成果与归档','正式交付与项目复盘集中在这里。研究过程中的报告在对应项目中维护。'));
 const tabbar=tabs([['publications','论文与交付'],['figures','图与结果'],['closure','项目复盘']],'publications',draw),box=el('div',null,'list');view.append(tabbar,box);
 async function draw(tab){
  const turn=++revision,isCurrent=()=>turn===revision&&project===S.project&&token===S.renderToken&&box.isConnected;
  tabbar.querySelectorAll('button').forEach((b,i)=>b.classList.toggle('active',i===['publications','figures','closure'].indexOf(tab)));
  const kinds={figures:['图与谱系','结果'],publications:['论文输出','专利','数据集输出','软件输出','协议输出','演示输出','报告'],closure:['项目复盘','项目关闭']}[tab];
  const docs=visibleDocs().filter(d=>d.record_id&&kinds.includes(d.kind));box.replaceChildren();docs.forEach(d=>box.append(docRow(d)));
  if(tab==='closure'){const checks=el('div');box.append(checks);await renderProjectClosure(checks);return;}
  if(tab==='figures'){let data;try{data=await api('/api/research?section=figures&project='+encodeURIComponent(project));}catch(error){if(!isCurrent())return;throw error;}if(!isCurrent())return;for(const n of data.nodes.filter(n=>['Figure','Result'].includes(n.kind)&&n.owner==='Pipeline')){const row=el('div',null,'list-row'),copy=el('div',null,'row-copy');copy.append(el('strong',n.data.title||n.id),el('p',n.kind==='Figure'?'绘图规格 · 导出图片在分析运行中管理':'计算结果 · 关联到来源运行'));row.append(copy,btn('查看来源',()=>showRunTrace(n.data.run_id)));box.append(row);}}
  if(!box.childElementCount)box.append(empty('还没有这类正式成果','登记真实产物后，从这里查看其来源与版本。'));
 }await draw('publications');
}

function sourceSidebar(doc){
 const side=el('aside',null,'document-sidebar');
 const provenance=el('section');provenance.append(el('h3','来源与项目使用'),el('p',doc.source_project_title||projectLabel(doc.source_project)));
 if(doc.source_project_archived)provenance.append(badge('来源项目已归档'));
 if(doc.source_project&&(S.knowledge?.project_profiles||[]).some(p=>p.project===doc.source_project))provenance.append(btn('返回来源项目',()=>openProjectUsage({project:doc.source_project,document_id:doc.id}),'text-link'));
 for(const usage of doc.used_by||[])provenance.append(btn((usage.title||usage.project)+(usage.archived?' · 已归档':'')+' · '+(usage.reason||'明确选用'),()=>openProjectUsage({...usage,document_id:doc.id}),'source-card'));
 side.append(provenance);
 const referenceButton=ref=>{const b=btn('',()=>navigate('document',ref.id),'source-card');b.append(el('span',ref.kind+(ref.changed?' · 来源有更新':'')),el('strong',ref.title));return b;};
 for(const [key,title]of[['references','引用的资料'],['backlinks','使用这份资料']]){
   const refs=doc[key],shown=key==='backlinks'?refs.filter(ref=>{const source=(S.knowledge||S.workspace).documents.find(d=>d.id===ref.id);return source&&!source.archived&&source.visibility!=='system';}):refs;
   const sec=el('section');sec.append(el('h3',title+' · '+shown.length));if(!shown.length)sec.append(el('p','尚无明确的正文链接','muted'));
   shown.forEach(ref=>sec.append(referenceButton(ref)));
   const hidden=refs.filter(ref=>!shown.includes(ref));
   if(hidden.length){const history=el('details');history.append(el('summary','历史与系统引用 · '+hidden.length));hidden.forEach(ref=>history.append(referenceButton(ref)));sec.append(history);}
   side.append(sec);
 }
 if(doc.paper_ids.length){const sec=el('section');sec.append(el('h3','对应论文'));for(const id of doc.paper_ids){const paper=S.workspace.papers.find(p=>p.id===id);sec.append(btn(paper?.display_title||id,()=>navigate('paper',id),'source-card'));}side.append(sec);}
  if(doc.content_role==='knowledge'&&doc.global_knowledge&&!doc.archived)side.append(btn('查看资料关联',()=>navigate('knowledge','','graph','doc:'+doc.id),'quiet-button','link'));
 const location=el('div',null,'document-location');location.append(el('p','正文位置'),el('p',doc.path));side.append(location);return side;
}
async function renderDocumentHistory(doc,container){if(!doc.versions.length){container.append(empty('还没有正文修改历史','首次保存后，之前的正文会自动保留。'));return;}for(const v of doc.versions){const row=el('div',null,'history-row');const copy=el('div');copy.append(el('strong','修改前版本'),el('p',date(v.created),'muted'));row.append(copy,btn('查看与恢复',async()=>{const previous=await api('/api/workspace/version?id='+doc.id+'&version='+encodeURIComponent(v.id));const body=modal('历史正文 · '+date(v.created));const article=el('div',null,'document-body');article.append(markdown(previous.body,doc.id));body.append(el('p','恢复会先放进编辑器，核对后再保存；当前正文保留历史。','section-subtitle'),article,btn('放入编辑器',()=>{dismiss();editDocument(doc,{body:previous.body,title:doc.title});},'primary'));}));container.append(row);}}
function showDraftPrompt(doc){if(!doc.editable)return;const body=modal('AI 协助修改 · '+docLabel(doc));body.append(el('p','草稿会回到这份资料的编辑器，不额外创建一份难以对应的报告。','section-subtitle'));const instruction=el('textarea');instruction.rows=4;instruction.maxLength=8000;instruction.placeholder='例如：结合已更新的来源，修订背景说明并保留证据边界。';body.append(field('修改要求',instruction));const status=el('p',null,'muted'),actions=el('div',null,'form-actions'),submit=btn('准备修改草稿',async()=>{if(!instruction.value.trim())throw Error('请说明希望怎样修改');submit.disabled=true;status.textContent='正在生成，原稿保持可读；任务进度也保存在自动化中。';try{const result=await job('/api/workspace/draft',{id:doc.id,fingerprint:doc.fingerprint,instruction:instruction.value});const current=await api('/api/workspace/document?id='+doc.id);if(current.fingerprint!==result.fingerprint)throw Error('生成期间原稿已变化，草稿保留在任务结果中，请先核对');dismiss();S.pendingDraft={id:current.id,body:result.body};navigate('document',current.id);notify('AI 草稿已放进编辑器，核对后保存');}finally{submit.disabled=false;}},'primary','sparkles');actions.append(submit);body.append(status,actions);}
async function showSettings(){
 const body=modal('连接与设置');body.append(btn('技能与规则',showSkillsManager,'quiet-button','book'));body.append(el('p','专业软件负责各自的正式资料与分析，工作区集中索引和日常操作。','section-subtitle'));
 const tabsEl=tabs([['tools','软件连接'],['models','AI 模型'],['ranks','期刊分区'],['archive','归档与恢复']],'tools',draw);body.append(tabsEl);const slot=el('div');body.append(slot);
 async function draw(tab){
   const box=el('div');slot.replaceChildren(box);
   tabsEl.querySelectorAll('button').forEach((b,i)=>b.classList.toggle('active',i===['tools','models','ranks','archive'].indexOf(tab)));box.replaceChildren();
   if(tab==='ranks'){await drawJournalRanks(box);return;}
   if(tab==='archive'){
     box.append(el('p','正在读取归档资料…','loading-state'));
     try{await ensureWorkspace();}catch(error){box.replaceChildren(el('p',error.message,'notice'),btn('重新读取',()=>draw('archive')));return;}
     if(!box.isConnected)return;box.replaceChildren();
     box.append(el('p','归档只是退出日常列表，原始文件与引用不移动。项目记录在对应项目查看；管理历史在全部项目的资料入口查看。','section-subtitle'));
     for(const doc of S.workspace.documents.filter(d=>d.archived))box.append(docRow(doc));
     const trashed=await api('/api/trash?project='+encodeURIComponent(S.project));
     if(trashed.records.length){const h=el('h3','可恢复垃圾箱');h.style.marginTop='22px';box.append(h);for(const row of trashed.records){const item=el('div',null,'queue-row'),copy=el('div');copy.append(el('strong',row.title),el('p',row.kind+' · '+date(row.deleted)));item.append(copy,btn('恢复',async()=>{await api(row.direction?'/api/directions/restore':'/api/trash/restore',row.direction?{id:row.id,project:S.project}:{id:row.id});await loadWorkspace();notify('资料已恢复');draw('archive');}));box.append(item);}}return;
   }
   if(tab==='models'){
     const data=await api('/api/model-settings'),prefs=data.settings;
     const text=select(data.models.map(m=>[m.id,m.name||m.id]),'文字模型'),image=select(data.models.filter(m=>m.input_modalities.includes('image')).map(m=>[m.id,m.name||m.id]),'图片模型'),effort=select([['low','快速'],['high','深入'],['max','最大']],'思考强度');text.value=prefs.text_model;image.value=prefs.image_model;effort.value=prefs.effort;const think=el('input');think.type='checkbox';think.checked=prefs.thinking;const lab=el('label',null,'check-field');lab.append(think,el('span','交互问答启用思考'));box.append(field('文字模型',text),field('图片模型',image),lab,field('思考强度',effort),btn('保存模型偏好',async()=>{await api('/api/model-settings',{text_model:text.value,image_model:image.value,thinking:think.checked,effort:effort.value});notify('模型偏好已保存');},'primary'));
     box.append(el('hr',null,'divider'));const key=input('仅在本机输入 DeepSeek API Key');key.type='password';key.autocomplete='off';box.append(field('更新连接密钥',key),btn('保存并测试连接',async()=>{const value=key.value;key.value='';await job('/api/configure',{key:value});notify('连接测试已完成');}));
     box.append(el('p','密钥不会写入报告、对话记录或任务参数。检索沿用 Qwen3 Embedding 4B。','section-subtitle'));return;
   }
   box.append(el('div','正在检查本机服务…','section-subtitle'));let status,professional;try{[status,professional]=await Promise.all([api('/api/services'),api('/api/professional-tools')]);}catch(error){box.replaceChildren(el('div',error.message,'notice'));return;}
   if(!box.isConnected)return;
   box.replaceChildren();const schedulerIssues=Object.entries(status.schedulers||{}).filter(([,value])=>!value.ok);const catalogIssues=status.catalog_issues||[];if(schedulerIssues.length||catalogIssues.length)box.append(el('div','后台任务或资料索引有需要处理的状态：'+(schedulerIssues.map(([name])=>name).join('、')||'—')+(catalogIssues.length?'；资料索引问题 '+catalogIssues.length+' 项':''),'notice'));const radar=status.radar||{},radarCard=el('div',null,'card');radarCard.style.marginBottom='18px';radarCard.append(el('h3','新论文提醒状态'),el('p',radarHealthMessage(radar),'section-subtitle'),badge(radar.bounded_ok?'已按本轮范围检查':radar.ok?'提醒已更新':(radar.status||'尚未运行'),radar.ok||radar.bounded_ok?'green':'orange'));if(radar.last_success)radarCard.append(el('small','最近成功扫描：'+date(radar.last_success)+'；最近检查：'+date(radar.checked),'muted'));else radarCard.append(el('small','尚无成功扫描记录','muted'));if(radar.errors?.length||radar.pending_pages?.length)radarCard.append(el('p','来源异常 '+radar.errors.length+' 项；待接续 '+radar.pending_pages.length+' 页；'+((radar.next_retry_at)?'下次最早重试 '+date(radar.next_retry_at):''),'muted'));if(radar.unavailable?.length)radarCard.append(el('p','另有 '+radar.unavailable.length+' 个已登记 DOI 在来源侧暂未索引，按计划回查；不计作扫描错误。','muted'));if(radar.index?.status)radarCard.append(el('p','提醒索引：'+(radar.index_stale?'刷新超时 · 请重开提醒触发重试':radar.index.status==='failed'?'刷新失败 · '+(radar.index.error_type||'未知错误'):radar.index.status==='running'?'后台刷新中':'已就绪')+(radar.index.checked?' · '+date(radar.index.checked):''),'muted'));if(radar.storage)radarCard.append(el('small','任务 '+Object.values(radar.storage.jobs||{}).reduce((a,b)=>a+b,0)+' 项；去重身份 '+radar.storage.seen+' 条（冷历史 '+radar.storage.seen_compacted+' 条，不进入提醒）；业务库 '+(radar.storage.database_bytes/1024/1024).toFixed(0)+' MB','muted'));box.append(radarCard);const grid=el('div',null,'software-grid');
   for(const [name,purpose,ready,url]of[
     ['Zotero','书目、PDF、引用与批注',status.services.Zotero,'zotero://select/library'],
     ['Open Notebook','共享资料检索与阅读索引',status.services['Open Notebook'],'http://127.0.0.1:8502/notebooks'],
     ['n8n','后台编排与定时更新',status.services['自动流程'],'http://127.0.0.1:5678'],
     ['Cytoscape.js + fCoSE','当前关系图的交互与专业布局',true,null],
     ['Graphviz','定向来源链与矢量导出',true,null],
     ['Cytoscape Desktop','3.10.5 · 从关系图打开网络分析与精修',professional.cytoscape.installed,null],
     ['Bibliometrix / VOSviewer','5.5.0 / 1.6.21 · 在分析区统一使用文献计量',professional.bibliometrix.installed&&professional.vosviewer.installed,null],
     ['CCT-1800 配套格式',professional.cct.message,professional.cct.format_connected,null],
   ]){const card=el('div',null,'software-card');card.append(el('h3',name),el('p',purpose),badge(ready?(name.includes('Desktop')||name.includes('Bibliometrix')?'已安装 · 按需启动':'已连接'):name==='Zotero'?'本机 API 未就绪':'待接入',ready?'green':'orange'));if(url)card.append(extLink('打开',url,'quiet-button'));if(name==='CCT-1800 配套格式'&&professional.cct.available)card.append(btn('打开 TeraAnalyzer',async()=>{await api('/api/professional/teraanalyzer',{});notify('已打开配套分析软件');}));grid.append(card);}box.append(grid);
    async function connectionSection(title,render){const host=el('div',null,'card');host.style.marginTop='18px';host.append(el('p','正在读取'+title+'…','muted'));box.append(host);const run=async()=>{try{await render(host);}catch(error){if(host.isConnected)host.replaceChildren(el('h3',title),el('p',error.message,'notice'),btn('重新读取',run,'quiet-button'));}};return run();}
    const sections=[connectionSection('Zotero 自动收录',async connection=>{
    const zotero=await api('/api/zotero');if(!connection.isConnected)return;connection.replaceChildren(el('h3','Zotero 自动收录'),el('p',zotero.message,'section-subtitle'));
    if(!zotero.remembered){const connect=btn('连接自动收录',async()=>{connect.disabled=true;connection.append(el('p','请切到 Zotero，确认“研序科研工作区”并选择“总是允许”；授权只保存在本机。','notice'));try{await job('/api/zotero/authorize',{});await draw('tools');notify('Zotero 授权已保存，待收录任务会自动继续');}finally{connect.disabled=false;}},'primary','link');connect.disabled=!zotero.online;connection.append(connect);}
    const waiting=zotero.intake.filter(x=>x.status!=='completed');if(waiting.length)connection.append(el('p',waiting.length+' 项收录正在等待接续；原文与书目登记已保留。','section-subtitle'));
    }),connectionSection('原生笔记',renderNoteBoundary),connectionSection('RSpace',renderRSpaceConnection),connectionSection('文献检索',renderScholarlyConnection),connectionSection('数据远端',renderDataRemote)];
    await Promise.allSettled(sections);if(!box.isConnected)return;
    box.append(el('p','HyperSpy、MLflow 与仪器连接器仍按真实任务需要启用；安装或初始化不等同于科研功能已经验收。','section-subtitle'));
 }await draw('tools');
}
function journalRankCard(ranks){
 const card=el('div',null,'card');card.append(el('h3','年度期刊分区'));
 const states={needs_source:'等待年度数据来源',needs_issn:'题录缺少有效 ISSN',missing:'该年度来源中未匹配',ambiguous:'来源或刊名有歧义，待核对'};
 for(const [system,label]of[['CAS','中科院'],['JCR','JCR · JIF'],['XR','新锐']]){const value=ranks?.[system]||{status:'needs_source'};const title=el('p',label+(value.year?' · '+value.year:' · 年份待定'),'section-subtitle');card.append(title);
   if(value.status!=='matched')card.append(badge(states[value.status]||'待核对','orange'));
   for(const row of value.entries||[]){const detail=el('div',null,'rank-entry');detail.append(el('strong',(system!=='JCR'?row.quartile+' 区':row.quartile)+' · '+row.category),el('small',(row.scope==='major'?'大类':row.scope==='minor'?'小类':row.metric)+' · '+row.edition),extLink(row.source,row.uri));card.append(detail);}
 }card.append(el('p','以来源数据年度为准；多个学科分别显示。来源在连接与设置中统一维护。','muted'));return card;
}
async function drawJournalRanks(box){
 const data=await api('/api/journal-ranks');box.append(el('p','中科院、JCR 和新锐并列显示，分别保留年度、学科与来源。公开镜像作为补充；已有授权导出继续保留。按 ISSN 匹配，分区不参与论文内容的判断。','section-subtitle'));
 const publicStatus=data.public_refresh||{};box.append(el('p',(publicStatus.enabled?'公开来源补充已启用，后台运行时检查更新。':'可启用公开来源补充。')+(publicStatus.checked?' 最近检查：'+date(publicStatus.checked):'')+(publicStatus.status==='deferred'?'；本次连接失败，已保留旧数据并稍后重试。':''),'muted'),btn('更新公开分区来源',async()=>{await job('/api/journal-ranks/refresh',{});await loadWorkspace();box.replaceChildren();await drawJournalRanks(box);notify('分区来源已更新，年度与来源分别保留');},'quiet-button','refresh'));
 const sourceList=el('div',null,'list');for(const r of data.records.filter(r=>r.active)){const item=el('div',null,'history-row'),copy=el('div');copy.append(el('strong',({CAS:'中科院',JCR:'JCR',XR:'新锐'}[r.system])+' · '+r.year+' · '+r.edition+' · '+r.metric),el('p',r.rows+' 条学科记录 · '+date(r.created),'muted'),extLink(r.label,r.uri));item.append(copy);sourceList.append(item);}if(!sourceList.childElementCount)sourceList.append(empty('尚未提供年度分区数据','需要正式或已获使用权的数据来源；系统不会用搜索摘要冒充分区。'));box.append(sourceList);
 const details=el('details');details.style.marginTop='20px';details.append(el('summary','添加或更新年度来源'));const form=el('div');form.style.marginTop='18px';
 const system=select([['CAS','中科院'],['JCR','JCR'],['XR','新锐']],'分区体系'),year=input('数据年度'),edition=input('版本','升级版'),metric=select([['CAS','中科院分区'],['JIF','JIF 四分位'],['JCI','JCI 四分位'],['XR','新锐分区']],'评价指标'),label=input('例如：课题组订阅的年度分区导出'),uri=input('来源网页','https://www.fenqubiao.com/'),file=el('input');file.type='file';file.accept='.csv';file.setAttribute('aria-label','年度分区 CSV 文件');
 system.onchange=()=>{const code=system.value;edition.value={CAS:'升级版',JCR:'JCR',XR:'新锐'}[code];metric.value=code==='JCR'?'JIF':code;uri.value={CAS:'https://www.fenqubiao.com/',JCR:'https://jcr.clarivate.com/',XR:'https://www.xr-scholar.com/'}[code];};metric.value='CAS';
 form.append(field('分区体系',system),field('数据年度（不是论文发表年）',year),field('版本',edition),field('评价指标',metric),field('来源名称',label),field('来源网页',uri),field('年度 CSV',file));
 const specification=el('details');specification.append(el('summary','查看文件格式'));const pre=el('pre',data.template);specification.append(pre,el('p','每个学科一行。scope：中科院与新锐 major / minor，JCR category；quartile：中科院与新锐 1–4，JCR Q1–Q4。issn 和 eissn 至少填一项。','section-subtitle'));form.append(specification,btn('导入并更新索引',async()=>{if(!file.files.length)throw Error('请选择年度分区 CSV');if(file.files[0].size>20*1024*1024)throw Error('分区文件最多 20 MB');const payload={system:system.value,year:year.value,edition:edition.value,metric:metric.value,label:label.value,uri:uri.value,content:await file.files[0].text()};payload.expected_sources=data.records.filter(r=>r.active&&r.system===payload.system&&r.year===Number(payload.year)&&r.edition===payload.edition&&r.metric===payload.metric&&r.uri===payload.uri).map(r=>r.id);const r=await api('/api/journal-ranks/import',payload);await loadWorkspace();box.replaceChildren();await drawJournalRanks(box);notify((r.reused?'已复用现有来源':'已导入 '+r.rows+' 条记录')+'，文献分区自动更新');},'primary','upload'));details.append(form);box.append(details);
}
async function showSearch(){
 const projectScope=S.route==='projects'&&new URLSearchParams(location.hash.split('?')[1]).has('project');const workspace=projectScope?await api('/api/project/search-catalog?project='+encodeURIComponent(S.project)):await loadKnowledge();const body=modal(projectScope?'搜索本项目':'搜索全局知识'),search=input('输入题名、报告、笔记、ID 或关键词'),results=el('div',null,'command-results');search.className='command-search';search.setAttribute('aria-label','搜索整个工作区');const history=el('input');history.type='checkbox';const historyField=el('label',null,'check-field');historyField.append(history,el('span','包括历史和归档资料'));history.onchange=()=>draw();
 function draw(){results.replaceChildren();const q=search.value.trim().toLowerCase();const docs=workspace.documents.filter(d=>(history.checked||!d.archived&&d.visibility!=='system')&&(!q||[d.title,d.display_title,d.kind,d.project,d.source_project,d.source_project_title,d.path,...d.paper_ids].join(' ').toLowerCase().includes(q))).sort((a,b)=>b.file_modified-a.file_modified).slice(0,q?18:6);
   for(const doc of docs){const b=btn('',()=>{dismiss();navigate('document',doc.id);},'command-result');const copy=el('div');copy.append(el('strong',docLabel(doc)),el('small',doc.kind+' · '+doc.project+(doc.created?' · '+docTime(doc):'')+(doc.needs_review?' · 来源有更新':'')));b.append(ic('file'),copy,ic('arrow'));results.append(b);}
   if(q){for(const p of workspace.papers.filter(p=>[p.title,p.display_title,p.doi,p.id].join(' ').toLowerCase().includes(q)).slice(0,12)){const b=btn('',()=>{dismiss();navigate('paper',p.id);},'command-result'),copy=el('div');copy.append(el('strong',p.display_title||p.title),el('small','文献 · '+p.id));b.append(ic('book'),copy);results.append(b);}}
   if(!results.childElementCount)results.append(empty('没有匹配的资料',projectScope?'可以在本项目的记录与相关资料中查找。':'知识区可切换“已归档知识”；记录、背景和其他资料在项目中查看。'));
 }
 const retrievalStatus=el('small','标题与 ID 即时匹配；正文检索使用已接入的 Open Notebook。','muted');
 const retrieve=btn('检索已索引正文',async()=>{const query=search.value.trim();if(!query)throw Error('请先输入要找的内容');retrieve.disabled=true;retrievalStatus.textContent='正在检索全文与笔记…';
  try{const data=await api('/api/search',{query,include_notes:true,scope:projectScope?'project':'knowledge',project:projectScope?S.project:undefined});if(search.value.trim()!==query)return;const rows=Array.isArray(data)?data:data.results||[];results.replaceChildren();let shown=0,hidden=0;
   for(const item of rows){const source=item.parent_id||item.id,paper=workspace.papers.find(p=>p.open_notebook_source_id===source),documentId=workspace.retrieval_documents?.[source],doc=workspace.documents.find(d=>d.id===documentId);if(doc&&!history.checked&&(doc.archived||doc.visibility==='system')){hidden++;continue;}shown++;const card=el('div',null,'retrieval-result');card.append(el('strong',doc?.title||paper?.display_title||item.title||'索引片段'));if(doc)card.append(badge(doc.kind+(doc.visibility==='system'?' · 历史资料':'')));
    const text=(item.matches||[]).map(m=>typeof m==='string'?m:m.text||m.content||'').join('\n')||item.content||item.text||'';card.append(el('p',text.slice(0,560)+(text.length>560?'…':'')));
    if(paper)card.append(btn('打开对应文献',()=>{dismiss();navigate('paper',paper.id);},'quiet-button','book'));else if(documentId)card.append(btn('打开对应正文',()=>{dismiss();navigate('document',documentId);},'quiet-button','file'));else card.append(extLink('查看检索来源','http://127.0.0.1:8502/notebooks'));
    results.append(card);
   }if(!shown)results.append(empty('未找到当前范围内已索引的匹配内容','可勾选历史与归档资料扩大范围；尚未索引的材料不会自动算作全文命中。'));retrievalStatus.textContent='显示 '+shown+' 个索引结果'+(hidden?'，另有 '+hidden+' 个历史结果已收起':'')+'。命中片段不等于已核查原文。';
  }catch(error){retrievalStatus.textContent='正文检索暂不可用：'+error.message+'；标题与 ID 搜索仍可使用。';}finally{retrieve.disabled=false;}
 },'quiet-button','search');
 search.oninput=draw;search.onkeydown=e=>{if(e.key==='Enter')results.querySelector('button')?.click();};body.append(search,historyField,retrieve,retrievalStatus,results);draw();search.focus();
}
function updateAssistantContext(){
 const paper=S.route==='paper'?S.workspace?.papers?.find(p=>p.id===new URLSearchParams(location.hash.split('?')[1]).get('id')):null,material=S.doc||paper;
 $('assistantContext').textContent=['knowledge','knowledge-node'].includes(S.route)?'知识讨论 · 仅使用允许进入全局知识的资料':S.discussion?'只读资料讨论：'+S.discussion.title:'项目：'+projectLabel(S.project)+(material&&assistantSelection().document_id?' · 当前资料：'+docLabel(material):' · 仅使用项目范围内的材料');
 updateChatControls();
}
function assistantSelection(){
 if(S.discussion)return {context_mode:'selected_material',path:'',document_id:S.discussion.id};
 if(['knowledge','knowledge-node'].includes(S.route))return {context_mode:'knowledge',path:'',document_id:''};
 let doc=S.doc;
 if(!doc&&S.route==='paper'){const id=new URLSearchParams(location.hash.split('?')[1]).get('id');doc=S.workspace?.documents?.find(d=>d.paper_ids.includes(id)&&d.kind==='阅读笔记'&&!d.archived);}
 if(doc&&!(S.workspace?.assistant_document_ids||[]).includes(doc.id))doc=null;
 return {context_mode:'project',path:doc?.kb_path||'',document_id:doc?.id||''};
}
function renderChat(){
 const host=$('chatMessages');host.replaceChildren();
 if(!S.chat?.messages?.length){const welcome=el('div',null,'chat-welcome');welcome.append(ic('sparkles'),el('h3','从手边的问题开始'),el('p','查资料、理清证据，或帮你准备修改。普通对话保留在这里，不自动散成报告。'));
   for(const text of ['当前研究问题有哪些证据和缺口？','解释这份资料和其他笔记的关系','哪些机械工作已经在后台自动处理？'])welcome.append(btn(text,()=>{$('chatInput').value=text;$('chatInput').focus();}));host.append(welcome);return;
 }
 for(const message of S.chat.messages){const turn=el('article',null,'chat-turn '+message.role);turn.append(el('small',message.role==='user'?'我的消息':'科研助手'),markdown(message.content,S.doc?.id));if(message.proposal_id)turn.append(btn('核对修改预览',()=>showProposal(message.proposal_id),'','edit'));
   if(message.reasoning_content){const detail=el('details');detail.append(el('summary','查看模型思考'),el('p',message.reasoning_content));turn.append(detail);}host.append(turn);}
 const id=S.chat.id,project=S.project;
 if(id)host.append(btn('将最新回复保存为笔记',async()=>{await api('/api/administrator/chat/save-note',{id});if(S.project===project)await loadWorkspace();notify('已保存为一份笔记，重复保存会复用。');},'quiet-button','file'));host.scrollTop=host.scrollHeight;
}
function sameChatContext(selection){
 const current=assistantSelection();
 return current.context_mode===selection.context_mode&&current.document_id===selection.document_id;
}
function updateChatControls(){
 S.chatBusy=!!S.chatRequests?.has(S.project);
 $('sendChat').disabled=S.chatBusy;$('chatHistory').disabled=S.chatBusy;
}
async function refreshChat(){
 const project=S.project,epoch=S.chatEpoch;
 const history=await api('/api/administrator/chat?project='+encodeURIComponent(project));
 if(project!==S.project||epoch!==S.chatEpoch)return;
 const picker=$('chatHistory');picker.replaceChildren(el('option','新对话'));picker.firstChild.value='';for(const item of history.records){const o=el('option',item.title);o.value=item.id;picker.append(o);}picker.value=S.chat?.id||'';
}
async function openAssistant(){
 $('assistant').hidden=false;document.body.classList.add('assistant-open');updateAssistantContext();
 const project=S.project,epoch=S.chatEpoch,selection=assistantSelection(),active=()=>S.project===project&&S.chatEpoch===epoch&&sameChatContext(selection);
 if(!S.chat&&!S.discussion){const id=localStorage.getItem('research:chat:'+project);if(id){
  try{const saved=await api('/api/administrator/chat?id='+encodeURIComponent(id));if(active()&&saved.context_mode===selection.context_mode&&(saved.document_id||'')===selection.document_id)S.chat=saved;}
  catch(_){/* Preserve the last conversation pointer while the server is unavailable. */}
 }}
 if(!active()||$('assistant').hidden)return;
 renderChat();await refreshChat();$('chatInput').focus();if(S.graph)setTimeout(()=>S.graph?.resize(),260);
}
$('closeAssistant').onclick=()=>{$('assistant').hidden=true;document.body.classList.remove('assistant-open');if(S.graph)setTimeout(()=>S.graph?.resize(),260);};
$('assistantButton').onclick=()=>{S.discussion=null;if(S.chat?.context_mode==='selected_material')S.chat=null;openAssistant().catch(e=>notify(e.message,true));};
$('newConversation').onclick=()=>{if(S.chatBusy)return;S.chatEpoch=(S.chatEpoch||0)+1;S.chat=null;localStorage.removeItem('research:chat:'+S.project);renderChat();refreshChat().catch(e=>notify(e.message,true));};
$('researchTools').onclick=()=>ensureWorkspace().then(()=>showResearchTools()).catch(e=>notify(e.message,true));
$('chatHistory').onchange=async()=>{
 if(S.chatBusy)return;
 const project=S.project,epoch=S.chatEpoch=(S.chatEpoch||0)+1,id=$('chatHistory').value;
 try{
  const chat=id?await api('/api/administrator/chat?id='+encodeURIComponent(id)):null;
  if(project!==S.project||epoch!==S.chatEpoch)return;
  S.chat=chat;S.discussion=chat?.context_mode==='selected_material'?{id:chat.document_id,title:chat.title}:null;
  updateAssistantContext();renderChat();
 }catch(error){if(project===S.project&&epoch===S.chatEpoch)notify(error.message,true);}
};
$('chatInput').onkeydown=e=>{if(e.ctrlKey&&e.key==='Enter'){e.preventDefault();$('chatForm').requestSubmit();}};
$('chatForm').onsubmit=async e=>{
 e.preventDefault();
 const project=S.project,epoch=S.chatEpoch,selection=assistantSelection(),input=$('chatInput'),draft=input.value,message=draft.trim();
 const requests=S.chatRequests||=new Map();
 if(!message||requests.has(project))return;
 const chat=S.chat?.context_mode===selection.context_mode&&(S.chat.document_id||'')===selection.document_id?S.chat:null;
 const active=()=>project===S.project&&epoch===S.chatEpoch&&sameChatContext(selection);
 requests.set(project,true);updateChatControls();$('chatStatus').textContent='正在结合当前资料讨论…';
 try{
  const result=await job('/api/administrator_chat',{project,message,id:chat?.id,fingerprint:chat?.fingerprint,...selection});
  localStorage.setItem('research:chat:'+project,result.id);
  if(S.chatInputs?.get(project)===draft)S.chatInputs.delete(project);
  if(!active())return;
  S.chat=result;if(input.value===draft)input.value='';
  renderChat();$('chatStatus').textContent=result.proposal_id?'修改预览已准备好，核对后保存。':'对话已保存。';
  await refreshChat().catch(()=>{});
  if(active())await loadWorkspace().catch(()=>{});
 }catch(error){if(active())$('chatStatus').textContent=error.message+'；输入保留。';}
 finally{requests.delete(project);updateChatControls();}
};
$('searchButton').onclick=()=>showSearch().catch(e=>notify(e.message,true));
$('createRecord').onclick=()=>{
 const target=projectCreationTarget();
 if(target==='record'){S.openProjectRecord?.();return;}
 if(target)return;
 return ensureWorkspace().then(()=>{const context=recordCreationContext(S.route,S.doc);showNewRecord(context.kind,{entry:context.entry});}).catch(e=>notify(e.message,true));
};
$('automationButton').onclick=()=>showAutomation().catch(e=>notify(e.message,true));
$('settingsButton').onclick=()=>showSettings().catch(e=>notify(e.message,true));
$('closeOverlay').onclick=dismiss;
$('overlay').addEventListener('click',e=>{if(e.target===$('overlay')){const r=$('overlay').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dismiss();}});
document.querySelectorAll('#primaryNav button').forEach(b=>{b.onclick=()=>navigate(b.dataset.route);b.setAttribute('title',b.textContent.trim());});
$('projectContext').onchange=async()=>{
 const picker=$('projectContext'),project=picker.value;
 picker.disabled=true;
 try{
  if(!await selectWorkspaceProject(project))return;
  const [route,query='']=location.hash.slice(1).split('?');
  const parameters=new URLSearchParams(query);
  // Keep global browse views; project-specific bookmarks belong to the old project.
  const next=route==='discover'||route==='knowledge'&&!parameters.has('compare_project')?location.hash:projectHomeHash(project);
  if(next===location.hash)await renderRoute();else location.hash=next;
 }catch(error){picker.value=S.project;notify(error.message,true);}
 finally{picker.disabled=false;}
};
$('projectManage').onclick=()=>showProjectManager().catch(e=>notify(e.message,true));
window.addEventListener('hashchange',renderRoute);
document.querySelector('.skip-link').onclick=e=>{e.preventDefault();$('view').setAttribute('tabindex','-1');$('view').focus();};
window.addEventListener('beforeunload',e=>{if(S.editor&&S.doc){localStorage.setItem('research:draft:'+S.doc.id,JSON.stringify({body:S.editor.getMarkdown(),title:$('editorTitle')?.value||S.doc.title,fingerprint:S.doc.fingerprint}));if(S.dirty){e.preventDefault();e.returnValue='';}}});
window.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();showSearch();}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'&&S.editor){e.preventDefault();[...document.querySelectorAll('main button')].find(b=>b.textContent==='保存正文')?.click();}});
let graphViewportWidth=0;
new ResizeObserver(()=>{const graph=S.graph;if(!graph)return;const width=graph.container().clientWidth;graph.resize();if(width!==graphViewportWidth){graphViewportWidth=width;graph.fit(undefined,38);}}).observe($('view'));
decorateIcons();
async function startWorkspace(){
 try{
  const old=new URLSearchParams(location.search);
  if(old.get('note')){await ensureWorkspace();const doc=objectForPath(old.get('note'));if(doc)history.replaceState(null,'','#document?id='+encodeURIComponent(doc.id));}
  if(old.get('paper'))history.replaceState(null,'','#paper?id='+encodeURIComponent(old.get('paper')));
  if(!location.hash){
   const {records}=await api('/api/projects');
   if(!location.hash){
    const current=records.find(row=>row.project===S.project&&!row.archived)||records.find(row=>!row.archived);
    if(current)S.project=current.project;
    updateProjectPicker({project_profiles:records});
    history.replaceState(null,'',current?projectHomeHash(current.project):'#projects');
   }
  }
  await renderRoute();
 }catch(error){$('connectionStatus').textContent='连接待恢复';$('view').replaceChildren(empty('工作区暂时没有连上',error.message,btn('重试',()=>location.reload())));}
}
startWorkspace();
function openOriginalComparison(id){
 location.hash='#knowledge?'+new URLSearchParams({tab:'graph',compare_claim:id});
}

async function renderFullKnowledgeGraph(){
 const token=S.renderToken,params=new URLSearchParams(location.hash.split('?')[1]||'');
 const project=params.get('compare_project'),question=params.get('compare_question'),claim=params.get('compare_claim');
 if(project&&question)return renderQuestionComparison(project,question,token);
 if(claim)return renderQuestionComparison('','',token,claim);
 S.graphContext='network';
 const graphFocus=/^(doc|paper):/.test(params.get('anchor')||'')?params.get('anchor'):'';
 const controller=WorkspaceKnowledgeGraph.mount($('view'),{api,graphFocus,compareOriginal:openOriginalComparison,icon:ic,transition:replaceWorkspaceLayer,loadKnowledge,navigate,openGraphMaterial,openKnowledgeNode:id=>navigate('knowledge-node',id),showRelationEditor,showProfessionalGraph,notify,project:S.project});
 S.knowledgeGraphController=controller;S.graphRefresh=controller.refresh;
}

async function renderQuestionComparison(project,question,token,claim=''){
 const view=$('view'),panel=el('section',null,'card'),notice=el('p','正在读取可选原文论断…','section-subtitle');
 const back=()=>claim?navigate('knowledge-node',claim):(location.hash='#projects?'+new URLSearchParams({project,view:'overview',question}));
 panel.append(btn(claim?'返回论断详情':'返回研究问题',back,'quiet-button'),el('h2','比对原文'),notice);view.append(panel);
 const current=()=>S.renderToken===token&&panel.isConnected;
 const endpoint='/api/knowledge/comparison?';
 const params=claim?{anchor:claim}:{project,question};
 let data;
 try{data=await api(endpoint+new URLSearchParams(params));}
 catch(error){if(current())notice.textContent=error.message;return;}
 if(!current())return;
 notice.remove();
 if(data.title)panel.append(el('h3',data.title));
 if(!claim)panel.append(el('p','已明确关联 '+data.papers.length+' 篇论文，选择两条来自不同原文的论断。','section-subtitle'));
 if(!claim&&new Set(data.claims.map(row=>row.paper_id)).size<2){
  panel.append(el('p',data.papers.length?'当前有可选论断的论文不足两篇。':'这个问题尚无明确关联的论文。'),
   btn('打开全局知识图',()=>navigate('knowledge','','graph'),'quiet-button'));return;
 }
 const claimLabel=row=>row.label+' · '+row.paper_title;
 const search=(label)=>{const control=input('按论断或论文标题查找','');control.type='search';control.setAttribute('aria-label',label);return control;};
 const leftQuery=claim?null:search('查找第一条原文论断'),rightQuery=search('查找第二条原文论断');
 const left=claim?null:select([['','选择第一条原文论断']],'第一条原文论断');
 const right=select([['','选择第二条原文论断']],'第二条原文论断');
 const result=el('p');result.setAttribute('role','status');
 let candidates=data.claims,after=data.after||'',retry='',searchRequest=0,searchTimer=null,busy=false;
 const chosenLeft=()=>data.anchor||data.claims.find(row=>row.id===left?.value);
 const chosenRight=()=>candidates.find(row=>row.id===right.value);
 const find=(rows,text)=>{const term=text.trim().normalize('NFKC').toLowerCase();return rows.filter(row=>claimLabel(row).normalize('NFKC').toLowerCase().includes(term));};
 const fill=(control,rows,label)=>{
  const previous=control.value;
  control.replaceChildren(new Option(label,''),...rows.slice(0,20).map(row=>new Option(claimLabel(row),row.id)));
  if([...control.options].some(option=>option.value===previous))control.value=previous;
 };
 const pairKey=()=>[chosenLeft()?.id,chosenRight()?.id].join('|');
 const update=()=>{
  run.disabled=busy||!chosenLeft()||!chosenRight();
  run.textContent=retry&&retry===pairKey()?'重试所选比对':'比对所选原文';
 };
 const refreshRight=()=>{
  const first=chosenLeft(),rows=candidates.filter(row=>row.paper_id!==first?.paper_id);
  fill(right,claim?rows:find(rows,rightQuery.value),'选择第二条原文论断');
  more.hidden=!claim||!after;update();
 };
 const lookup=async(cursor='')=>{
  const request=++searchRequest;
  try{
   const next=await api(endpoint+new URLSearchParams({anchor:claim,q:rightQuery.value.trim().slice(0,120),after:cursor}));
   if(!current()||request!==searchRequest)return;
   candidates=next.claims;after=next.after;right.value='';result.textContent='';refreshRight();
   if(!candidates.length)result.textContent=after?'本页暂无可比论断，可继续查看。':'没有符合条件的当前论断。';
  }catch(error){if(current()&&request===searchRequest)result.textContent=error.message;}
 };
 const more=btn('继续查看',()=>lookup(after),'quiet-button');
 const run=btn('比对所选原文',async()=>{
  const first=chosenLeft(),second=chosenRight();if(busy||!first||!second||first.paper_id===second.paper_id)return;
  const key=pairKey();busy=true;update();result.textContent='正在比对两条原文…';
  try{
   const saved=await job('/api/knowledge/comparison',{left:{id:first.id,revision:first.revision},
      right:{id:second.id,revision:second.revision},retry_failed:retry===key});
   if(!current())return;
   if(saved.status==='needs_attention'){retry=key;result.textContent=saved.message;return;}
   if(saved.status==='busy'){result.textContent='已有原文比对正在处理，请稍后重试。';return;}
   retry='';result.replaceChildren(el('span',saved.relations?'已保存 '+saved.relations+' 条原文比对结果。':'两端原文暂无可记录的科研关系。'),
      btn('查看第一条论断与关系',()=>navigate('knowledge-node',first.id),'quiet-button'),
      btn('查看第二条论断与关系',()=>navigate('knowledge-node',second.id),'quiet-button'));
  }catch(error){if(current())result.textContent=error.message;}
  finally{busy=false;if(current())update();}
 },'primary');
 if(left){
  leftQuery.oninput=()=>{fill(left,find(data.claims,leftQuery.value),'选择第一条原文论断');refreshRight();};
  left.onchange=()=>{right.value='';result.textContent='';refreshRight();};leftQuery.oninput();
  panel.append(field('查找第一条论断',leftQuery),field('第一条原文论断',left));
 }else panel.append(el('p','第一条原文论断 · '+claimLabel(data.anchor)));
 rightQuery.oninput=()=>{
  if(!claim){refreshRight();return;}
  clearTimeout(searchTimer);searchRequest++;candidates=[];after='';right.value='';refreshRight();
  searchTimer=setTimeout(()=>{if(current())lookup();},250);
 };
 right.onchange=()=>{result.textContent='';update();};
 panel.append(field('查找第二条论断',rightQuery),field('第二条原文论断',right),more,run,result);refreshRight();
}

async function renderKnowledgeNode(id){
 S.tab='graph';$('breadcrumbDetail').textContent='知识详情';const host=$('view');host.append(materialBackButton(()=>navigate('knowledge','','graph'),'返回知识图'));
 S.knowledgeDetailController=WorkspaceKnowledgeDetail.mount(host,{api,navigate,openGraphMaterial,notify,showRelationEditor,compareOriginal:()=>openOriginalComparison(id),openNode:target=>navigate('knowledge-node',target)},id);
}

function professionalFile(kind,id,name,label=name){
 const a=el('a',label,'quiet-button');a.href='/api/professional/file?'+new URLSearchParams({kind,id,file:name});a.download=name;return a;
}
function professionalVectorPreview(url,label){
 const box=el('div'),viewport=el('div',null,'professional-preview'),stage=el('div',null,'professional-preview-stage'),preview=el('img');preview.alt=label;viewport.tabIndex=0;viewport.setAttribute('aria-label',label+' · 可滚动预览');stage.append(preview);viewport.append(stage);
 let scale=1;const zoom=amount=>{if(!preview.naturalWidth)return;const x=(viewport.scrollLeft+viewport.clientWidth/2)/(stage.offsetWidth||viewport.clientWidth),y=(viewport.scrollTop+viewport.clientHeight/2)/(stage.offsetHeight||viewport.clientHeight);scale=Math.max(1,Math.min(8,amount));const width=Math.min(viewport.clientWidth,viewport.clientHeight*preview.naturalWidth/preview.naturalHeight)*scale;preview.style.width=width+'px';stage.style.width=Math.max(viewport.clientWidth,width)+'px';stage.style.height=Math.max(viewport.clientHeight,width*preview.naturalHeight/preview.naturalWidth)+'px';viewport.scrollLeft=x*stage.offsetWidth-viewport.clientWidth/2;viewport.scrollTop=y*stage.offsetHeight-viewport.clientHeight/2;};
 preview.onload=()=>zoom(scale);preview.src=url;
 const controls=el('div',null,'professional-preview-controls');controls.append(el('span','矢量预览 · 放大后可滚动查看','muted'),btn('缩小',()=>zoom(scale-.5),'quiet-button'),btn('放大',()=>zoom(scale+.5),'quiet-button'),btn('适应',()=>zoom(1),'quiet-button'),extLink('原图查看',url,'quiet-button'));box.append(controls,viewport);return box;
}
async function showProfessionalFigure(record,row,title){
 const body=modal(title+' · Bibliometrix'),generation=S.overlayGeneration;$('overlay').classList.add('professional-dialog');
 const url='/api/professional/file?'+new URLSearchParams({kind:'bibliometrics',id:record.id,file:row.figure}),actions=el('div',null,'toolbar');actions.append(btn('返回这次分析',()=>showBibliometricResult(record),'quiet-button','back'),professionalFile('bibliometrics',record.id,row.figure,'保存专业图'));body.append(el('p','归属：'+(record.project||'共享资料'),'muted'),actions);
 if(row.figure.endsWith('.plotly.json')){
  const loading=el('p','正在读取图表…','loading-state');body.append(loading);
  try{
   const [spec,plotly]=await Promise.all([api(url),WorkspaceLoading.loadPlotly()]);
   if(generation!==S.overlayGeneration||!$('overlay').open)return;
   const plot=el('div',null,'professional-plot');loading.replaceWith(plot);
   await plotly.newPlot(plot,spec.data,spec.layout,{responsive:true,displaylogo:false});
  }catch(error){if(generation===S.overlayGeneration)body.append(el('p',error.message,'notice'),btn('重试图表',()=>showProfessionalFigure(record,row,title)));loading.remove();}
 }
 else body.append(professionalVectorPreview(url,title+' · Bibliometrix 原生图'));
}
function showProfessionalGraph(snapshot,parent=null,autoload=false){
 const body=modal('专业网络 · Cytoscape Desktop'),status=el('p',null,'section-subtitle'),result=el('div');
 $('overlay').classList.add('professional-dialog');
 body.append(el('p','当前范围保留来源和关系状态。桌面版可继续聚类、筛选和精修；精修后请另存会话，自动版和原始资料会保留。','section-subtitle'));
 if(parent)body.append(btn('返回原网络',()=>showProfessionalGraph(parent,null,true),'quiet-button','back'));
 const open=btn('打开并生成专业图',async()=>{
   open.disabled=true;status.textContent='正在准备专业网络与矢量图…';
   try{let r=await api('/api/professional/cytoscape',snapshot);result.replaceChildren();
     if(r.status==='starting'||r.status==='running'){
       status.textContent='桌面版正在启动，就绪后会自动生成专业图…';
       const deadline=Date.now()+120000;
       while(Date.now()<deadline){
         await new Promise(resolve=>setTimeout(resolve,1500));
         if(!result.isConnected||!$('overlay').open)return;
         const tools=await api('/api/professional-tools');
         if(tools.cytoscape.online){r=await api('/api/professional/cytoscape',snapshot);break;}
       }
     }
     if(r.status!=='exported'){status.textContent=r.message||'专业软件正在启动，稍后再次打开。';return;}
     status.textContent=r.nodes+' 个对象 · '+r.edges+' 条关系 · '+r.tool+(r.reused?' · 已复用保存结果':'')+(r.native_status==='starting'?' · 桌面版正在启动':r.native_status==='unavailable'?' · 已保存图可继续查看':'');
     const links=el('div',null,'toolbar');for(const [name,label]of[['自动布局.cys','可编辑会话'],['自动布局.svg','矢量图'],['自动布局.png','图片'],['source.cyjs','带来源的网络']])links.append(professionalFile('cytoscape',r.id,name,label));
     links.append(btn('返回交互图查看资料',dismiss,'quiet-button','back'));result.append(links);
     result.append(professionalVectorPreview('/api/professional/file?'+new URLSearchParams({kind:'cytoscape',id:r.id,file:'自动布局.svg'}),'Cytoscape Desktop 保存的专业网络'));
     if(r.analysis?.status==='completed'){
       const check=el('details',null,'source-change');check.append(el('summary','网络检查 · '+r.analysis.components+' 个连通部分 · '+r.analysis.isolated.length+' 个无关联对象'),el('p',r.analysis.scope,'section-subtitle'));
       const files=el('div',null,'toolbar');for(const [name,label]of[['网络分析.cys','含指标的专业会话'],['节点指标.csv','对象指标'],['关系指标.csv','关系指标'],['网络分析.json','原生分析记录']])files.append(professionalFile('cytoscape',r.id,name,label));check.append(files);
       for(const n of r.analysis.isolated){const node=snapshot.elements.nodes.find(v=>v.data.id===n.id)?.data;check.append(ResearchGraph.destination(node,S.workspace)?btn(node.full_label||n.label,()=>openGraphMaterial(node),'text-link'):el('p',n.label,'section-subtitle'));}result.append(check);
     }else if(r.analysis)result.append(el('p',r.analysis.message||'网络检查暂未完成。','section-subtitle'));
     const grouping=el('section',null,'soft-card'),choice=select([['glay','按关联分组 · GLay'],['mcode','查找密集关联 · MCODE']],'专业分组方法'),groupStatus=el('p',null,'section-subtitle'),groupResult=el('div');
     grouping.append(el('h3','关联分组'),el('p','用本机专业算法梳理当前网络。组内可直接打开原资料；分组结果和原图分别保留。','section-subtitle'),choice);
     const groupButton=btn('生成分组',async()=>{groupButton.disabled=true;groupStatus.textContent='正在本机分析，进度也会保存在后台任务中…';try{
       const clustered=await job('/api/professional/cluster',{id:r.id,algorithm:choice.value});
       if(!groupResult.isConnected)return;groupResult.replaceChildren();
       if(clustered.status!=='completed'){groupStatus.textContent=clustered.message||'原生分组尚未完成，原图与全部对象保留。';groupResult.append(professionalFile('cytoscape',clustered.id,'聚类分析.json','查看原生处理记录'));return;}
       groupStatus.textContent=clustered.groups.length+' 个关联组 · '+clustered.unassigned.length+' 个未归组对象 · '+clustered.tool+(clustered.reused?' · 已复用保存结果':'');
       groupResult.append(el('p',clustered.scope,'section-subtitle'));
       const files=el('div',null,'toolbar');for(const [name,label]of[['聚类分析.cys','可编辑分组会话'],['聚类分析.svg','分组矢量图'],['分组对象.csv','对象与分组'],['聚类分析.json','方法与原生结果']])files.append(professionalFile('cytoscape',clustered.id,name,label));groupResult.append(files);
       const material=id=>{const node=snapshot.elements.nodes.find(n=>n.data.id===id)?.data;if(!node)return;const available=ResearchGraph.destination(node,S.workspace),item=available?btn('',()=>openGraphMaterial(node),'list-row'):el('div',null,'list-row'),mark=el('span',null,'row-icon '+(node.paper_id?'paper':'note')),copy=el('div',null,'row-copy');mark.append(ic(node.paper_id?'book':'file'));copy.append(el('strong',node.full_label||node.label||id),el('p',node.kind||'网络对象'));item.append(mark,copy);if(available)item.append(ic('arrow'));return item;};
       for(const group of [...clustered.groups,...(clustered.unassigned.length?[{number:null,members:clustered.unassigned}]:[])]){const details=el('details',null,'source-change');details.append(el('summary',(group.number===null?'未归组':'关联组 '+group.number)+' · '+group.members.length+' 个对象'));if(group.members.length>1)details.append(btn('只看这组关系',()=>{const ids=new Set(group.members),edges=snapshot.elements.edges.filter(e=>ids.has(e.data.source)&&ids.has(e.data.target)),edgeIds=new Set(edges.map(e=>e.data.id));showProfessionalGraph({...snapshot,mode:'focus',layout:'fcose',root:group.members[0],elements:{nodes:snapshot.elements.nodes.filter(n=>ids.has(n.data.id)),edges},source_relations:(snapshot.source_relations||[]).filter(e=>edgeIds.has(e.id))},snapshot,true);},'quiet-button','network'));for(const id of group.members){const item=material(id);if(item)details.append(item);}groupResult.append(details);}
       const method=el('details');method.append(el('summary','方法与参数'),el('pre',JSON.stringify(clustered.parameters,null,2)));groupResult.append(method,professionalVectorPreview('/api/professional/file?'+new URLSearchParams({kind:'cytoscape',id:clustered.id,file:'聚类分析.svg'}),'Cytoscape 本机聚类分组图'));
     }catch(error){groupStatus.textContent='暂未完成：'+error.message+'。原图与已保存分组保留。';throw error;}finally{groupButton.disabled=false;}},'quiet-button','network');
     grouping.append(groupButton,groupStatus,groupResult);result.append(grouping);
   }catch(error){status.textContent='暂未完成：'+error.message+'。已保存的来源与旧图继续保留。';throw error;}finally{open.disabled=false;}
 },'primary','network');body.append(open,status,result);if(autoload)open.click();
}

async function showBibliometrics(){
 const body=modal('文献计量'),source=select([['zotero','当前项目与共享 Zotero 文献'],['wos','Web of Science · 完整记录与参考文献'],['scopus','Scopus · CSV 导出'],['pubmed','PubMed · 文本导出']],'题录来源'),file=el('input');file.type='file';file.accept='.txt,.csv,.bib';file.setAttribute('aria-label','专业题录导出文件');file.hidden=true;source.onchange=()=>{file.hidden=source.value==='zotero';};
 const status=el('p',null,'section-subtitle'),list=el('div',null,'list');
 body.append(el('p','Bibliometrix 负责文献计量，VOSviewer 负责网络呈现。分析绑定输入题录；缺失字段会显示出来，不会自动补成科研结论。','section-subtitle'),field('分析范围',source),file);
 const actions=el('div',null,'form-actions'),run=btn('分析题录',async()=>{run.disabled=true;status.textContent='正在运行 Bibliometrix…';try{const data={project:S.project,source:source.value};if(source.value!=='zotero'){if(!file.files.length)throw Error('请选择相应数据库导出的题录文件');if(file.files[0].size>20*1024*1024)throw Error('题录最多 20 MB');data.content=await file.files[0].text();}const r=await job('/api/professional/bibliometrics',data);showBibliometricResult(r);}finally{run.disabled=false;}},'primary','chart');
 actions.append(run,btn('高级分析 · Biblioshiny',async()=>{const r=await api('/api/professional/biblioshiny',{});status.replaceChildren(document.createTextNode(r.status==='starting'?'正在启动，可稍后打开高级分析。':'高级分析已就绪。'),extLink('打开 Biblioshiny',r.url));},'quiet-button','external'));body.append(actions,status,el('h3','已保存分析'),list);
 const history=await api('/api/professional/history?project='+encodeURIComponent(S.project));for(const r of history.records){const row=btn('',()=>showBibliometricResult(r),'list-row'),copy=el('div',null,'row-copy');copy.append(el('strong',r.analysis.records+' 篇 · '+({zotero:'Zotero',wos:'Web of Science',scopus:'Scopus',pubmed:'PubMed'}[r.source]||r.source)),el('p',date(r.created)+' · '+Object.values(r.analysis.networks||{}).filter(n=>n.status==='exported').length+' 类可用网络'));row.append(ic('network'),copy,ic('arrow'));list.append(row);}if(!history.records.length)list.append(empty('还没有文献计量结果','选择题录来源后开始分析，同样输入会复用成功结果。'));
}
function showBibliometricResult(r){
 const body=modal('文献计量 · '+r.analysis.records+' 篇'),a=r.analysis,coverage=el('div',null,'summary-strip');
 body.append(el('p','归属：'+(r.project||'共享资料'),'muted'),extLink('固定链接',location.origin+'/#analyze?id='+encodeURIComponent(r.id),'quiet-button'));
 body.append(el('p','当前选定语料的分析。Zotero 管理标签已排除；作者、机构、关键词与参考文献均依赖原题录。','section-subtitle'));
 for(const [key,label]of[['AU','作者'],['PY','年份'],['SO','期刊'],['DE','作者关键词'],['CR','参考文献'],['C1','机构']]){const item=el('div');item.append(el('strong',(a.fields[key]||0)+' / '+a.records),el('span',label));coverage.append(item);}body.append(coverage);
 const names={'author-collaboration':'作者合作','keyword-cooccurrence':'关键词共现','keywordplus-cooccurrence':'Keywords Plus 共现','institution-collaboration':'机构合作','paper-coupling':'文献耦合','reference-cocitation':'共引网络','historiograph':'历史引文脉络','thematic_map':'主题地图','thematic_evolution':'主题演化'};
 const fields={AU:'作者',PY:'出版年份',SO:'期刊',DE:'作者关键词',ID:'Keywords Plus',CR:'参考文献',C1:'作者机构',years:'至少三个不同出版年份'};
 for(const [key,row]of Object.entries({...a.networks,historiograph:a.historiograph,thematic_map:a.thematic_map,thematic_evolution:a.thematic_evolution,trends:a.trends})){if(!row)continue;const title=names[key]||(key==='trends'?'研究趋势':key),card=el('div',null,'history-row'),copy=el('div');copy.append(el('strong',title),el('p',row.status==='exported'?(row.nodes?row.nodes+' 个节点 · '+row.edges+' 条关系':'已保存原生分析结果'):row.status==='missing_metadata'?'资料不足 · 缺少 '+[row.required].flat().map(f=>fields[f]||f).join(' / '):'未完成 · '+(row.message||'需核对输入'),'muted'));card.append(copy);if(row.figure)card.append(btn('查看图',()=>showProfessionalFigure(r,row,title),'quiet-button','chart'));if(row.gml)card.append(btn('在 VOSviewer 中精修',async()=>{const opened=await api('/api/professional/vosviewer',{id:r.id,network:key});notify(opened.reused?'已打开保存的网络':'VOSviewer 正在准备网络，图与可编辑文件会保存在同一分析下');},'quiet-button','network'));body.append(card);}
 const files=el('details');files.append(el('summary','输入与专业产物 · '+r.files.length));const links=el('div',null,'toolbar');for(const name of r.files)links.append(professionalFile('bibliometrics',r.id,name));files.append(links);body.append(files,btn('返回文献计量',showBibliometrics,'quiet-button','back'));
 if(r.previous_versions?.length){const previous=el('details');previous.style.marginTop='18px';previous.append(el('summary','历史分析与精修产物 · '+r.previous_versions.length));for(const version of r.previous_versions){const row=el('div',null,'history-row'),copy=el('div');copy.append(el('strong',date(version.created)),el('p',version.files.filter(name=>name.startsWith('VOSviewer-')).length?'包含 VOSviewer 保存产物':'保留该次输入与专业产物','muted'));row.append(copy,btn('查看这次分析',()=>showBibliometricResult(version),'quiet-button'));previous.append(row);}body.append(previous);}
}

const jobLabels={change_followup:'关联修改建议',change_group:'来源组批量准备',change_group_apply:'来源组批量采纳',document_repair:'PDF全文重新解析',sync:'文献与笔记同步',discover:'文献雷达',weekly:'每周简报',weekly_refresh:'周报更新预览',collect:'论文收录',acquire:'获取论文',organize:'资料整理',analyze:'科研分析',notes:'阅读笔记整理',background:'背景更新草稿',ai_update:'修改预览',maintain:'统一维护',versions:'版本快照',administrator_chat:'科研助手对话',catalog_update:'正文修改草稿',relations:'跨资料关联分析',knowledge_comparison:'比对原文',bibliometrics:'专业文献计量',professional_cluster:'专业网络分组',run_registration:'分析运行登记与恢复',administrator_tick:'自动整理与项目更新',relation_tick:'自动关联检查',zotero_authorize:'Zotero 自动收录授权',rspace_sync:'正式实验状态同步',formal_analysis_update:'实验完成后的自动分析',data_remote_sync:'数据远程备份',data_remote_verify:'数据备份恢复检查',memory_reuse:'历史方法与经验检索'};
jobLabels.discover='新论文提醒';
Object.assign(jobLabels,{scholarly_search:'文献检索',scholarly_plan:'准备检索式',scholarly_check:'文献接口检查',ask:'原页问答',configure:'连接配置',acquire_candidates:'获取已选论文',directions:'研究方向候选',knowledge_extraction:'知识图提取与关系比对',journal_ranks_refresh:'期刊分区资料更新',canvas_organize:'项目研究图整理'});
const jobStates={completed:'已完成',done:'已完成',partial:'部分完成',waiting:'等待依赖',skipped:'已跳过',running:'处理中',queued:'等待处理',failed:'未完成',needs_review:'结果待核查'};

function showCallRecovery(row){
 const body=modal('核查模型请求'),reason=el('textarea');reason.rows=3;reason.maxLength=1000;reason.placeholder='记录已检查的结果、服务状态或用量，以及允许重新调用的原因。';const consent=el('input');consent.type='checkbox';const check=el('label',null,'check-field');check.append(consent,el('span','已核查这次请求，允许下一次相同调用；可能再次产生费用。'));const release=btn('保存核查并解除阻塞',async()=>{if(!consent.checked)throw Error('请先核查并勾选允许重新调用');await api('/api/research/release-call',{id:row.id,updated:row.updated,reason:reason.value,allow_new_charge:true});await showAutomation('jobs');notify('核查已保存；返回原功能再次提交时才会调用');},'primary','check');
 body.append(el('p','网络中断时，服务可能已经完成并计费。工作区不会自动重复这次请求。此操作只解除阻塞，保留原账本和核查记录。','section-subtitle'),el('p','请求记录：'+row.id,'muted'),field('核查说明',reason),check,release);
}
async function showNoteSync(id){
 const body=modal('笔记稿件对照'),generation=S.overlayGeneration;body.append(el('p','正在读取对应稿件…','section-subtitle'));
 const record=await api('/api/note-sync/refresh',{id});if(generation!==S.overlayGeneration||!$('overlay').open)return;body.replaceChildren();
 if(record.status==='retired_history'){
  body.append(el('h3',record.title),el('p','旧同步已解除。以下是保留的两端历史快照；现在的知识在主稿维护，后续修改不会再产生旧同步差异审核。','notice info'));
  const columns=el('div',null,'split'),local=el('div',null,'note-comparison-pane'),native=el('div',null,'note-comparison-pane');local.append(el('h3','保留的 Markdown 历史稿'),markdown(record.local_body,record.document_id));native.append(el('h3','保留的 Zotero 历史稿'),el('pre',record.native_text,'code-text'));columns.append(local,native);body.append(columns,btn('打开当前知识主稿',()=>{dismiss();navigate('document',record.document_id);},'primary','edit'),extLink('查看 Zotero 笔记','zotero://select/library/items/'+record.native_key,'quiet-button'));return;
 }
 if(record.plain_same){body.append(empty('两端当前文字一致','这项比较已完成，无需重复审核。'),btn('返回待确认',()=>showAutomation(),'primary'));return;}
 body.append(el('h3',record.title),el('p','左侧是当前 Markdown 主稿，日常修改以它为准。右侧是刚读取的 Zotero 旧同步稿。检查右侧是否有尚未补入的内容；此操作不会用旧稿覆盖你已经更新的正文。','section-subtitle'));
 const columns=el('div',null,'split'),local=el('div'),native=el('div');local.append(el('h3','当前知识主稿'),markdown(record.local_body,record.document_id));native.append(el('h3','Zotero 旧同步稿'),el('pre',record.native_text,'code-text'));local.className=native.className='note-comparison-pane';columns.append(local,native);body.append(columns);
 const reason=el('textarea');reason.rows=3;reason.placeholder='例如：已将右侧新增内容合入主稿；或旧稿没有需要补入的信息。';body.append(field('本次处理结果',reason));
 const actions=el('div',null,'form-actions');actions.append(btn('去主稿补充内容',()=>{dismiss();navigate('document',record.document_id);},'quiet-button','edit'),extLink('查看 Zotero 笔记','zotero://select/library/items/'+record.native_key,'quiet-button'),btn('以当前主稿为准，完成核对',async()=>{await api('/api/note-sync/review',{id:record.id,reason:reason.value});if(await finishReview('sync',record.id))return;await showAutomation();notify('当前两端版本已核对；后续新增差异仍会提示');},'primary','check'));body.append(actions,el('p',record.boundary_status==='completed'?'历史快照仅用于恢复。上次已核验本工作区旧双向同步取消；当前知识在主稿维护。':'历史快照仅用于恢复。原生同步边界在“连接与设置 → 软件连接”核验，此次正文核对不会取消同步注册。','muted'));
}
async function renderSchedule(box){
 const project=S.project,admin=structuredClone(S.workspace.settings),automatic={};
 const generation=S.overlayGeneration,active=()=>generation===S.overlayGeneration&&project===S.project&&box.isConnected!==false;
 box.append(el('p','自动任务在本机后台运行。关注方向和首页阅读推荐在雷达设置中调整。','section-subtitle'));
 const areas=el('div',null,'toolbar');areas.setAttribute('aria-label','自动化区域');
 for(const [id,label]of [['discovery','发现区'],['knowledge','知识区'],['projects','项目区'],['lab','实验区'],['analysis','分析区'],['outputs','产出区'],['shared','文献同步'],['backup','数据备份']]){
  areas.append(btn(label,()=>{
   const target=box.querySelector('[data-automation-area="'+id+'"]');if(!target)return;
   const parent=target.closest('details');if(parent&&!parent.open)parent.open=true;
   target.scrollIntoView({block:'start',behavior:'smooth'});
  },'quiet-button'));
 }
 box.append(areas);
 const group=(title,description,fold=false)=>{const panel=el(fold?'details':'section',null,'reading-settings');panel.style.marginBottom='16px';panel.append(el(fold?'summary':'h3',title));if(description)panel.append(el('p',description,'muted'));return panel;};
 const toggle=(host,target,key,label,checked)=>{const c=el('input'),line=el('label',null,'check-field');c.type='checkbox';c.checked=!!checked;target[key]=c;line.append(c,el('span',label));host.append(line);return c;};
 function addSave(host,label,fields,submit){
  const status=el('p',null,'muted');status.setAttribute('role','status');
  const save=btn(label,async()=>{
   if(!active())return;
   save.disabled=true;
   const disabled=fields.map(c=>c.disabled);fields.forEach(c=>c.disabled=true);
   status.textContent='正在保存…';
   try{const result=await submit();if(active())status.textContent=result;}
   catch(error){if(active())status.textContent='保存未完成，输入已保留。'+error.message;}
   finally{fields.forEach((c,i)=>c.disabled=disabled[i]);save.disabled=false;}
  },'primary');
  const actions=el('div',null,'form-actions');actions.append(save);host.append(status,actions);
 }
 const projectPanel=group('项目自动整理 · '+projectLabel(project),'这些设置只作用于当前项目。');
 projectPanel.setAttribute('data-automation-area','projects');
 toggle(projectPanel,automatic,'enabled','启用后台科研整理',admin.enabled);
 toggle(projectPanel,automatic,'auto_project','为项目过程变化准备一张确认卡',admin.auto_project);
 toggle(projectPanel,automatic,'auto_relations','新增或改稿后分析普通资料关联',admin.auto_relations);
 toggle(projectPanel,automatic,'auto_analysis','分析项目思路与证据缺口',admin.auto_analysis);
 const projectOptions=group('其他项目整理','',true);
 toggle(projectOptions,automatic,'auto_canvas','项目研究图自动归类并连线',admin.auto_canvas);
 toggle(projectOptions,automatic,'auto_discovery','发现研究方向候选',admin.auto_discovery);
 const refreshProject=()=>{for(const [key,c]of Object.entries(automatic))if(key!=='enabled')c.disabled=!automatic.enabled.checked;};
 automatic.enabled.onchange=refreshProject;refreshProject();projectPanel.append(projectOptions);
 addSave(projectPanel,'保存项目自动整理设置',Object.values(automatic),async()=>{
  const changed=Object.fromEntries(Object.entries(automatic).filter(([key,c])=>c.checked!==!!admin[key]).map(([key,c])=>[key,c.checked]));
  if(!Object.keys(changed).length)return '项目设置没有变化。';
  await api('/api/administrator/settings',{project,select_project:false,...changed,expected:Object.fromEntries(Object.keys(changed).map(key=>[key,!!admin[key]]))});
  Object.assign(admin,changed);S.workspaceStale=true;
  if(active())Object.assign(S.workspace.settings,changed);
  return '已保存当前项目设置。';
 });
 const flowPanel=el('div'),connections=el('div');box.append(projectPanel,flowPanel,connections);
 const maintenance=group('手动同步与维护','',true);
 maintenance.append(btn('现在同步',async()=>{
  const result=await job('/api/sync',{});await loadWorkspace();
  const outcome={partial:'本轮部分完成',waiting:'同步等待依赖恢复',skipped:'本轮同步已跳过'}[result?.status];
  notify(result?.message||outcome||'同步已完成',!!outcome);
 }),btn('完整维护',async()=>{await job('/api/maintain',{project});await loadWorkspace();notify('维护步骤已执行；详细结果在任务记录中。');}));box.append(maintenance);
 async function readFlow(){
  if(!active())return;
  flowPanel.replaceChildren(el('p','正在读取论文与同步设置…','loading-state'));
  let flow;
  try{flow=await api('/api/flow-settings');}
  catch(error){if(active())flowPanel.replaceChildren(el('h3','论文与同步设置暂不可用'),el('p',error.message,'notice'),btn('重新读取论文与同步设置',readFlow,'quiet-button'));return;}
  if(!active())return;
  const controls={};
  const time=input('',flow.values.daily_time);time.type='time';
  const number=(value,min,max)=>{const control=input('',value);control.type='number';control.min=min;control.max=max;return control;};
  const interval=number(flow.values.sync_minutes,'1','60'),sourceLimit=number(flow.values.radar_source_limit??200,'10','200');
  const recentDays=number(flow.values.radar_recent_days??90,'7','365'),backgroundDays=number(flow.values.radar_background_days??90,'7','365');
  const sync=group('文献与笔记同步 · 全局','把 Zotero 论文与笔记接入工作区。');sync.setAttribute('data-automation-area','shared');
  toggle(sync,controls,'sync_enabled','自动同步论文与笔记',flow.values.sync_enabled);sync.append(field('每隔几分钟同步',interval));
  const daily=group('论文自动更新 · 全局','控制每日查新、已选论文全文获取和周报。');daily.setAttribute('data-automation-area','discovery');
  toggle(daily,controls,'daily_enabled','启用论文自动更新',flow.values.daily_enabled);daily.append(field('每日运行时间 · 北京时间',time));
  for(const [key,label]of [['discover_enabled','自动检查新论文'],['acquire_enabled','自动获取我已选择收录的论文'],['ai_enabled','AI 整理雷达线索']])toggle(daily,controls,key,label,flow.values[key]);
  const dailyState=el('p',null,'muted');
  const refreshDaily=()=>{
   const enabled=controls.daily_enabled.checked;
   for(const key of ['discover_enabled','acquire_enabled','ai_enabled'])controls[key].disabled=!enabled;
   time.disabled=!enabled;
   dailyState.textContent=enabled?(controls.ai_enabled.checked?'AI 整理会使用已配置的模型。':'AI 整理已暂停。'):'论文自动更新已暂停，原选择已保留。';
  };
  controls.daily_enabled.onchange=controls.ai_enabled.onchange=refreshDaily;refreshDaily();
  daily.append(dailyState,btn('修改关注方向与阅读推荐',()=>showWatches(),'quiet-button','settings'));
  const limits=group('更多雷达选项','',true),radarGrid=el('div',null,'form-grid');
  radarGrid.append(field('每个来源、每条关注每天最多检查几条题录',sourceLimit),field('主题/方法/待判断线索保留天数 · 从首次发现算',recentDays),field('拓展阅读线索保留天数 · 从首次发现算',backgroundDays));limits.append(radarGrid);
  const otherTasks=group('其他后台任务 · 同步、论文更新、雷达','',true);otherTasks.append(sync,daily,limits);
  addSave(otherTasks,'保存论文与同步设置',[time,interval,sourceLimit,recentDays,backgroundDays,...Object.values(controls)],async()=>{
   const values={...flow.values,daily_time:time.value,sync_minutes:Number(interval.value),radar_source_limit:Number(sourceLimit.value),radar_recent_days:Number(recentDays.value),radar_background_days:Number(backgroundDays.value),...Object.fromEntries(Object.entries(controls).map(([key,c])=>[key,c.checked]))};
   if(Object.entries(values).every(([key,value])=>value===flow.values[key]))return '论文与同步设置没有变化。';
   const updated=await api('/api/flow-settings/save',{values,fingerprint:flow.fingerprint});
   if(updated.values)flow=updated;S.workspaceStale=true;
   return '已保存论文与同步设置。';
  });
  flowPanel.replaceChildren(otherTasks);
 }
 await Promise.all([readFlow(),renderAutomationConnections(connections)]);
}

async function showReview(candidate,returnTab='review'){
 const body=modal('核对科研候选'),generation=S.overlayGeneration;
 if(candidate.evidence_deferred){const project=S.project;body.append(el('p','正在读取原始依据…','loading-state'));try{const full=await api('/api/research/review-item?'+new URLSearchParams({project:candidate.reviewProject||project,id:candidate.id}));if(generation!==S.overlayGeneration||!$('overlay').open||S.project!==project)return;candidate={...candidate,...full,evidence_deferred:false};}catch(error){if(generation===S.overlayGeneration)body.replaceChildren(el('p',error.message,'notice'),btn('重新读取',()=>showReview(candidate,returnTab)));return;}body.replaceChildren();}
 body.append(el('h3',candidate.title),el('p','确认表示你已核查这份判断的证据和适用条件；不采纳会保留审核历史。','section-subtitle'));
 const material=id=>{const p=S.workspace.papers.find(p=>p.id===id),d=S.workspace.documents.find(d=>d.id===id||d.record_id===id);return p?{label:p.display_title||p.title,route:'paper',id:p.id}:d?{label:docLabel(d),route:'document',id:d.id}:null;};
 for(const id of [candidate.source,candidate.target,candidate.id].filter(Boolean)){const m=material(id);if(m)body.append(btn('打开原资料 · '+m.label,()=>{dismiss();navigate(m.route,m.id);},'text-link'));}
 if(candidate.conditions)body.append(el('h4','关系说明与适用条件'),el('p',candidate.conditions));if(candidate.stale)body.append(el('div','引用依据已改变，需重新分析后才能确认。','notice'));
 if(candidate.evidence?.length){body.append(el('h4','已保存的证据'));for(const item of candidate.evidence){const card=el('div',null,'card');card.style.marginBottom='12px';if(item.id){const m=material(item.id);card.append(el('strong',m?.label||item.id));}if(item.location)card.append(el('p',item.location,'muted'));if(item.quote)card.append(el('blockquote',item.quote));if(item.scope)card.append(el('p',item.scope,'section-subtitle'));if(!item.location&&!item.quote)card.append(el('p','尚未提供可核查的证据位置','section-subtitle'));body.append(card);}}
 else body.append(el('p','请打开原资料核对完整正文；没有依据时保持待确认。','notice'));
 const reason=el('textarea');reason.rows=3;body.append(reviewReasonChoices(reason),field('审核依据与理由',reason));const actions=el('div',null,'form-actions');
 for(const [action,label,cls]of[['REJECTED','不采纳',''],['VERIFIED','确认已核查','primary']])actions.append(btn(label,async()=>{if(!reason.value.trim())throw Error('请填写核查依据与理由');await api('/api/research/review',{id:candidate.id,revision:candidate.revision,action,reason:reason.value});if(await finishReview('candidate',candidate.id))return;await showAutomation(returnTab);notify('审核记录已保存');},cls));body.append(actions);
}

async function showWatches(options={}){
 const [data,flow]=await Promise.all([api('/api/watch-rules'),api('/api/flow-settings').catch(()=>null)]);if(!data.reading)throw Error('看板服务尚未加载新阅读设置，请等待受管重载后重试。');
 const body=modal('论文雷达设置'),rules=structuredClone(data.rules),reading=structuredClone(data.reading),list=el('div'),readingPanel=el('section',null,'reading-settings'),grid=el('div',null,'reading-settings-grid');
 const enabled=flow?.values?.daily_enabled&&flow?.values?.discover_enabled;
 body.append(el('h3','1 · 关注哪些方向'),el('p','启用的方向用于查新；点开可修改或暂停，也可描述需求建立新关注。','muted'),btn('描述需求，建立关注',()=>showScholarlySearch({watch:true}),'quiet-button','sparkles'),list);
 const total=input('',reading.daily_limit);total.type='number';total.min=1;total.max=30;total.step=1;grid.append(field('首页每天最多推荐几篇',total));
 const dates=[['all','不限发表时间'],['7','只看近7天发表'],['30','只看近30天发表'],['90','只看近90天发表'],['365','只看近一年发表']];if(!dates.some(([value])=>value===String(reading.recent_days)))dates.push([String(reading.recent_days),'只看近'+reading.recent_days+'天发表']);
 const publication=select(dates,'论文发表时间');publication.value=reading.include_older?'all':String(reading.recent_days);grid.append(field('论文发表时间',publication));
 const summary=el('p',null,'muted');function describeReading(){summary.textContent='首页每天最多 '+reading.daily_limit+' 篇，'+(reading.include_older?'不限发表时间':'只选近 '+reading.recent_days+' 天发表的论文')+'。从符合关注的已发现论文中挑选，不足时少推荐；这项只影响首页阅读。';}
 total.oninput=()=>{reading.daily_limit=Number(total.value);describeReading();};publication.onchange=()=>{reading.include_older=publication.value==='all';if(!reading.include_older)reading.recent_days=Number(publication.value);describeReading();};describeReading();
 readingPanel.append(el('h3','2 · 首页推荐怎么选'),grid,summary);
 const more=el('details'),moreGrid=el('div',null,'reading-settings-grid');more.append(el('summary','更多阅读选项'));
 for(const [key,label]of [['method_limit','方法参考最多几篇'],['background_limit','背景阅读最多几篇']]){const control=input('',reading[key]);control.type='number';control.min=0;control.max=30;control.step=1;control.oninput=()=>reading[key]=Number(control.value);moreGrid.append(field(label,control));}
 const repeat=select([['no','7天内不重复推荐'],['yes','允许再次推荐']],'已推荐过的论文');repeat.value=reading.allow_repeat?'yes':'no';repeat.onchange=()=>reading.allow_repeat=repeat.value==='yes';more.append(moreGrid,field('已推荐过的论文',repeat),el('p','方法和背景篇数包含在每日总篇数内，不是额外增加。','muted'));readingPanel.append(more);body.append(readingPanel);
 const running=el('section',null,'reading-settings');running.append(el('h3','3 · 什么时候自动查新'),el('p',flow?.values?(enabled?'每天 '+flow.values.daily_time+'（北京时间）自动检查，后台运行时接续。':flow.values.daily_enabled?'自动查新已暂停。':'论文自动更新总开关已暂停。'):'当前自动查新状态暂未读取到，请查看自动化设置。','muted'),el('p','自动查新按第1项关注方向执行；发表时间只用于第2项首页推荐。','muted'),btn('设置自动查新时间与开关',()=>showAutomation('schedule'),'quiet-button','clock'));body.append(running);
 const types={topic:'研究主题',project:'项目问题',paper:'具体论文',author:'作者',institution:'机构',lab:'实验室 / PI',citation:'论文引用',retraction:'撤稿与更正'};
 const textField=(label,value,placeholder,change)=>{const control=input(placeholder,value||'');control.oninput=()=>change(control.value.trim());return field(label,control);};
 function draw(){list.replaceChildren();rules.forEach((r,index)=>{
  const card=el('details',null,'card');card.style.marginBottom='12px';card.append(el('summary',(r.enabled===false?'已暂停 · ':'')+(r.name||r.query||types[r.type]||r.id)));const type=select(Object.entries(types),'关注类型');card.append(textField('关注名称',r.name,'例如 山药品种与THz',v=>r.name=v));type.value=r.type;
  type.onchange=()=>{r.type=type.value;for(const key of ['author_id','coauthor_ids','institution_id','work_id','doi'])delete r[key];draw();};
  card.append(field('关注类型',type));
  if(['topic','project'].includes(r.type)){
   if(r.original_intent)card.append(el('p','原始想法：'+r.original_intent,'section-subtitle'));
    const criteria=r.criteria||{required:r.include_groups||[],priority:[],optional:[],exclusion:[]},matching=el('details');matching.append(el('summary','高级匹配条件'));card.append(matching);
    for(const [key,label]of [['required','必须同时命中的概念'],['priority','优先考虑的概念'],['optional','方法参考'],['exclusion','排除条件']]){const control=el('textarea');control.rows=2;control.value=(criteria[key]||[]).map(group=>group.join(' / ')).join('\n');control.placeholder='一行一组；同义词用 / 分隔';control.oninput=()=>{r.criteria={...criteria,...r.criteria,[key]:control.value.split(/[\n;；]/).map(g=>g.split(/[\/／]/).map(t=>t.trim()).filter(Boolean)).filter(g=>g.length)};r.relevance_mode='watch';};matching.append(field(label,control));}
    matching.append(el('small','必须条件至少一组，组间同时命中；优先条件不作门槛。方法参考和排除分别保存。修改必须概念后，未手工改写的来源检索式一并更新。','muted'));
   const sourceBox=el('div',null,'toolbar');for(const [id,name]of [['wos','WoS'],['openalex','OpenAlex'],['crossref','Crossref']]){const check=el('input'),label=el('label',null,'check-field');check.type='checkbox';check.checked=(r.sources||['wos','openalex','crossref']).includes(id);check.onchange=()=>{r.sources=Array.from(sourceBox.querySelectorAll('input')).filter(c=>c.checked).map(c=>c.value);};check.value=id;label.append(check,el('span',name));sourceBox.append(label);}matching.append(sourceBox);
    const advanced=el('details');advanced.append(el('summary','高级来源检索式'),textField('开放来源检索词',r.query,'按必须概念自动更新，也可手动填写',v=>r.query=v),textField('WoS 检索式',r.wos_query,'TS=(concept A) AND TS=(concept B)',v=>r.wos_query=v));matching.append(advanced);
   const relevance=select([['direct','主题相关'],['adjacent','方法相关'],['background','拓展阅读'],['noise','噪声档案']],'推荐用途');relevance.value=r.relevance_tier||'direct';relevance.onchange=()=>r.relevance_tier=relevance.value;card.append(field('推荐用途',relevance));
    card.append(el('small','AI仅整理相关性，不会修改你的关注条件。','muted'));
  }else if(['author','lab'].includes(r.type)){
   card.append(textField(r.type==='lab'?'团队 PI 的 OpenAlex Author ID':'OpenAlex Author ID',r.author_id,'A123456',v=>r.author_id=v.replace(/^https:\/\/openalex.org\//,'')));
   if(r.type==='lab'){
    card.append(textField('合作作者 ID · 可选',(r.coauthor_ids||[]).join(', '),'多个 A 开头的 ID，用逗号分隔',v=>r.coauthor_ids=v.split(/[,，\s]+/).filter(Boolean)));
    card.append(textField('限定机构 ID · 可选',r.institution_id,'I123456',v=>r.institution_id=v.replace(/^https:\/\/openalex.org\//,'')));
    card.append(el('small','团队范围按 PI／合作作者与机构查询，不猜测不存在的实验室身份。','muted'));
   }
   card.append(textField('限定检索词 · 可选',r.query,'只关注该作者的某类研究',v=>r.query=v));
  }else if(r.type==='institution'){
   card.append(textField('OpenAlex Institution ID',r.institution_id,'I123456',v=>r.institution_id=v.replace(/^https:\/\/openalex.org\//,'')));
   card.append(textField('限定检索词 · 可选',r.query,'只关注该机构的某类研究',v=>r.query=v));
  }else if(r.type==='citation'){
   card.append(textField('被引用论文的 OpenAlex Work ID',r.work_id,'W123456',v=>r.work_id=v.replace(/^https:\/\/openalex.org\//,'')));
  }else{
   card.append(textField(r.type==='retraction'?'另加关注的 DOI 或 Work ID · 可选':'论文 DOI 或 OpenAlex Work ID',r.work_id||r.doi,'10.xxxx/xxx 或 W123456',v=>{delete r.work_id;delete r.doi;v=v.replace(/^https:\/\/openalex.org\//,'');r[/^W\d+$/.test(v)?'work_id':'doi']=v;}));
   if(r.type==='retraction')card.append(el('small','正式文献库中有 DOI 的论文始终检查 Crossref 出版更新；这里可额外指定论文。','muted'));
  }
  const on=el('input');on.type='checkbox';on.checked=r.enabled!==false;on.onchange=()=>r.enabled=on.checked;const label=el('label',null,'check-field');label.append(on,el('span','启用这条关注 · 用于查新'));
   const participate=el('input'),participation=el('label',null,'check-field');participate.type='checkbox';participate.checked=r.reading_enabled!==false;participate.onchange=()=>r.reading_enabled=participate.checked;participation.append(participate,el('span','纳入首页推荐'));
   card.append(label,participation,btn('移除这条关注',()=>{rules.splice(index,1);draw();},'quiet-button'));list.append(card);
 });}
 draw();const actions=el('div',null,'form-actions');actions.append(btn('新增关注',()=>{rules.push({id:'watch-'+crypto.randomUUID().slice(0,12),type:'topic',query:'',project:S.project,enabled:true,relevance_tier:'direct',relevance_mode:'watch'});draw();},'','plus'),btn('取消',()=>options.onCancel?options.onCancel():dismiss(),'quiet-button'),btn('保存雷达设置',async()=>{if(rules.some(r=>['topic','project'].includes(r.type)&&r.criteria&&r.criteria.required?.length===0))throw Error('主题和项目关注至少保留一组必须概念。');await api('/api/watch-rules/save',{revision:data.revision,rules,reading});dismiss();await S.radarRefresh?.();if(options.onSaved)await options.onSaved();notify('关注与阅读设置已保存，推荐已按新设置更新');},'primary'));body.append(actions);
}

async function renderPaper(id){
 const token=S.renderToken,project=S.project;
 if(S.route!=='paper')return;
 const knowledge=await loadKnowledge();if(S.route!=='paper'||token!==S.renderToken||project!==S.project)return;
 $('view').replaceChildren();const p=S.workspace.papers.find(p=>p.id===id)||knowledge.papers.find(p=>p.id===id);if(!p)throw Error('文献未登记或已隐藏');
  const view=$('view');view.append(materialBackButton(()=>navigate('knowledge'),'返回文献'));const reviewBack=reviewReturnButton();if(reviewBack)view.append(reviewBack);const h=heading('LITERATURE',p.display_title||p.title,'');h.style.marginTop='22px';view.append(h);
  if(p.display_title!==p.title)view.append(el('p',p.title,'section-subtitle'));
  const meta=el('div',null,'object-meta');meta.append(badge(p.zotero_key?'Zotero 文献':'本地文献登记','blue'),el('span',p.doi||'无 DOI'),badge(paperAvailabilityLabel(p),p.has_original?'green':'orange'));view.append(meta);
 const linkedIds=[...new Set(p.related_paper_ids||[])].filter(other=>other&&other!==p.id);
 if(linkedIds.length){
  const related=el('div',null,'form-actions');related.append(el('span','同一原文的其他登记','muted'));
  for(const other of linkedIds)related.append(btn('同一论文登记 · '+other,()=>navigate('paper',other),'text-link','book'));
  view.append(related);
 }
  const actions=el('div',null,'object-toolbar');actions.style.marginTop='20px';
  if(p.zotero_key)actions.append(extLink('在 Zotero 中打开','zotero://select/library/items/'+p.zotero_key));
  actions.append(btn('维护阅读状态',()=>showReadingStatus(p),'quiet-button'));
  if(knowledge.papers.some(row=>row.id===id))actions.append(btn('查看资料关联',()=>navigate('knowledge','','graph','paper:'+id),'quiet-button','link'));
  actions.append(btn('新建笔记',()=>showNewRecord('PaperNote',{paper_ids:[id],title:(p.display_title||p.title)+' · 我的笔记'}),'primary','plus'),btn('关联已有资料',()=>showExistingPaperDocuments(p),'quiet-button','link'));
  view.append(actions);
  const params=new URLSearchParams(location.hash.split('?')[1]),initialTab=params.get('tab')==='original'?'original':'notes',anchor=params.get('anchor')||'',pageMatch=anchor.match(/^(?:page=)?(\d+)$/),initialPage=pageMatch?Math.max(1,Number(pageMatch[1])):1;const tabbar=tabs([['notes','笔记与来源'],['original','原文']],initialTab,draw);view.append(tabbar);const box=el('div');view.append(box);
  function draw(tab){
    tabbar.querySelectorAll('button').forEach((b,i)=>b.classList.toggle('active',i===(tab==='notes'?0:1)));box.replaceChildren();
    if(tab==='original'){
      if(p.has_original&&p.original_kind==='pdf'){
        const toolbar=el('div',null,'pdf-toolbar'),page=input('页码',String(initialPage));page.type='number';page.min='1';page.style.width='70px';page.setAttribute('aria-label','PDF 页码');
        const question=input('想核查这页的什么？','请解释这页图表的坐标、单位和证据边界。');question.style.flex='1';question.setAttribute('aria-label','原页核查问题');
        const image=el('img');image.alt='论文 PDF 原页';image.style.width='100%';image.style.border='1px solid var(--line)';image.src='/api/page?paper='+encodeURIComponent(id)+'&page='+initialPage;
        const change=()=>image.src='/api/page?paper='+encodeURIComponent(id)+'&page='+page.value;page.onchange=change;
        toolbar.append(field('PDF 页码',page),extLink('打开 PDF 文件','/api/original?paper='+encodeURIComponent(id),'quiet-button'),question,btn('问这一页',async()=>{const result=await job('/api/ask',{paper:id,pages:[Number(page.value)],question:question.value,project:S.project});await loadWorkspace();const doc=objectForPath(result.saved);if(doc)navigate('document',doc.id);},'','sparkles'));box.append(toolbar,image);
      }else{
        const card=el('div',null,'soft-card'),links=el('div',null,'form-actions');
        const missing=p.availability==='original_missing';
        card.append(el('h3',p.has_original?'已保存 XML，PDF 待补':paperAvailabilityLabel(p)),el('p',p.has_original?'当前附件为 XML。补齐 PDF 后，会使用同一原文页显示 PDF 原页；原附件与阅读记录保留。':missing?'已登记的 PDF/XML 路径当前不可用。文献登记与阅读资料已保留，可在 Zotero 核对附件路径或补齐全文。':'文献登记与阅读资料已保留。可查看已有笔记，或获取开放 PDF、从发现区导入已有文件。','section-subtitle'));
        if(p.doi){const acquire=btn(p.has_original?'补齐 PDF':'获取 PDF',async()=>{acquire.disabled=true;acquire.textContent='正在获取 PDF…';try{const result=await job('/api/acquire',{doi:p.doi,project:S.project});await loadWorkspace();if(S.route==='paper'&&new URLSearchParams(location.hash.split('?')[1]).get('id')===id)await renderPaper(id);notify(result.message||'全文获取已结束',result.has_pdf===false);}finally{acquire.disabled=false;}},'primary','download');links.append(acquire);}
        if(/^PMC\d+$/.test(p.pmcid||''))links.append(extLink('阅读开放全文','https://pmc.ncbi.nlm.nih.gov/articles/'+p.pmcid+'/','quiet-button'));
        else if(p.url&&/^https?:\/\//i.test(p.url))links.append(extLink('打开原文来源',p.url,'quiet-button'));
        if(p.doi)links.append(extLink('打开出版页面','https://doi.org/'+p.doi,'quiet-button'));
        if(p.has_original){const download=extLink('下载已保存的 XML','/api/attachment?paper='+encodeURIComponent(id)+'&kind=jats_xml','quiet-button');download.download=id+'.xml';links.append(download);}
        if(p.zotero_key)links.append(extLink('查看 Zotero 正式附件','zotero://select/library/items/'+p.zotero_key,'quiet-button'));
        card.append(links);box.append(card);
      }return;
    }
    const layout=el('div',null,'document-layout'),left=el('section'),right=el('aside',null,'document-sidebar');left.append(el('h3','笔记与相关资料 · '+p.documents.length),el('p','一篇论文可以有多篇笔记；同一份笔记也可以关联多篇论文。','section-subtitle'));const list=el('div',null,'list');list.style.marginTop='14px';
    for(const d of knowledge.documents.filter(d=>p.documents.some(x=>x.id===d.id)&&!d.archived))list.append(docRow(d));
    if(!list.childElementCount)list.append(empty('还没有对应笔记','创建阅读笔记后，正文、证据位置和批注在同一个入口维护。'));
    left.append(list);const info=el('div',null,'card');info.append(el('h3','文献信息'),el('p','阅读状态：'+(p.reading_status||'未读'),'section-subtitle'),el('p','主题：'+(p.topic||'待补'),'section-subtitle'),el('p','书目、PDF 与批注由 Zotero 管理。阅读笔记与报告在工作区编辑。','section-subtitle'));
    right.append(info,journalRankCard(p.journal_ranks));layout.append(left,right);box.append(layout);
  }draw(initialTab);
}
async function showReadingStatus(p){
 const doc=await api('/api/document?path='+encodeURIComponent('文献/条目/'+p.id+'.md')),body=modal('维护阅读状态');
 const status=select(doc.status_options.map(s=>[s,s]),'阅读状态');status.value=doc.status;const scope=el('textarea');scope.rows=3;scope.value=doc.reading_scope;scope.placeholder='实际核对的 PDF 页码、章节或图号';
 body.append(field('阅读状态',status),field('实际核查范围',scope),el('p','索引与 AI 分析不会自动算作已核查。','section-subtitle'),btn('保存状态',async()=>{await api('/api/document/status',{path:doc.path,status:status.value,scope:scope.value,fingerprint:doc.fingerprint});dismiss();await loadWorkspace();renderPaper(p.id);notify('阅读状态已保存');},'primary'));
}
const analysisKinds={line:'光谱与曲线',scatter:'散点图',pca:'PCA 得分图',regression:'线性拟合',heatmap:'相关性热图',classification:'按独立样品验证分类',thz:'THz 配对波形与质量检查'};
async function renderRun(id){
  const token=S.renderToken,run=await api('/api/data-analysis?id='+encodeURIComponent(id));if(token!==S.renderToken)return;const view=$('view');view.replaceChildren();
  view.append(btn('返回分析',()=>navigate('analyze'),'text-link','back'),heading('ANALYSIS RUN',analysisKinds[run.kind]+' · '+run.filename,'输入、参数与图表规格保存于同一分析记录。'));
  const files=el('div',null,'analysis-file-location');files.append(el('h3','输入文件与分析说明'),el('p','输入版本保存位置','section-subtitle'),el('p',run.input_location||run.source,'code-text'));
  const fileActions=el('div',null,'form-actions');fileActions.append(btn('复制文件位置',async()=>{await navigator.clipboard.writeText(run.input_location||run.source);notify('输入文件位置已复制');},'quiet-button','copy'));
  if(run.input_available){const download=extLink('下载本次输入文件','/api/data-analysis/input?id='+encodeURIComponent(run.id),'quiet-button');download.download=run.filename;fileActions.append(download);}else files.append(el('p','保存的输入暂不可读取或已变化，已保存的结果仍可查看。','notice'));
  const report=objectForPath(run.path);if(report)fileActions.append(btn('编辑分析说明',()=>navigate('document',report.id),'quiet-button','edit'));
  files.append(fileActions,el('p','图表标题与坐标在下方“调整图表”修改；更换输入时返回分析首页选择新文件。','section-subtitle'));view.append(files);
  const host=el('div',null,'analysis-figure');view.append(host);
  host.append(el('p','正在读取图表…','loading-state'));
  const fig=run.figure,plotly=await WorkspaceLoading.loadPlotly();if(token!==S.renderToken)return;
  host.replaceChildren();await plotly.newPlot(host,fig.data,{...fig.layout,height:520,autosize:true,paper_bgcolor:'#fff',plot_bgcolor:'#fff',font:{family:'Segoe UI, Microsoft YaHei',color:'#535f54'},colorway:['#5f877e','#be8c66','#6f89a5','#a09c64'],margin:{t:55,l:70,r:30,b:60}},{responsive:true,displaylogo:false});
  if(token!==S.renderToken)return;const actions=el('div',null,'object-toolbar');actions.style.marginTop='16px';actions.append(btn('调整图表',()=>showFigureOptions(run),'','edit'));
  if(run.provenance?.artifacts?.length){for(const suffix of ['svg','png','pdf']){const link=el('a','下载 '+suffix.toUpperCase(),'quiet-button');link.href='/api/research/artifact?'+new URLSearchParams({id:run.provenance.run_id,file:'figure.'+suffix});link.download=run.provenance.figure_id+'.'+suffix;actions.append(link);}}
  else actions.append(btn('导出 SVG',()=>plotly.downloadImage(host,{format:'svg',filename:run.filename.replace(/\.csv$/i,'')}),'','download'),btn('导出 PNG',()=>plotly.downloadImage(host,{format:'png',scale:3,filename:run.filename.replace(/\.csv$/i,'')})));
  if(run.provenance?.run_id)actions.append(btn('检查复跑与来源',()=>showRunTrace(run.provenance.run_id),'','network'));view.append(actions);
  const metrics=el('div',null,'card');metrics.append(el('h3','计算摘要'));if(run.kind==='classification'){const m=run.metrics,u=m.uncertainty;metrics.append(el('p','独立测试样品：'+m.test_samples.length+' · 平衡准确率：'+(m.balanced_accuracy*100).toFixed(1)+'% · 基线：'+(m.baseline_balanced_accuracy*100).toFixed(1)+'%'),el('p',u.status==='estimated'?'当前留出集的 95% 区间：'+u.interval.map(v=>(v*100).toFixed(1)+'%').join(' — '):'区间暂不能估计：'+u.reason,'section-subtitle'),el('p',m.scope,'section-subtitle'));const details=el('details');details.append(el('summary','查看数据划分、调参与逐样品预测'),el('pre',JSON.stringify(m,null,2),'code-text'));metrics.append(details);if(run.provenance?.run_id)metrics.append(extLink('下载完整验证记录','/api/research/artifact?'+new URLSearchParams({id:run.provenance.run_id,file:'metrics.json'}),'quiet-button'));}else if(run.kind==='thz'){renderTHzSummary(metrics,run);}else for(const [key,value]of Object.entries(run.metrics||{})){metrics.append(el('p',key+'：'+(typeof value==='object'?JSON.stringify(value):value),'section-subtitle'));}view.append(metrics);
  const history=await api('/api/data-analysis/history?project='+encodeURIComponent(S.project));const family=history.records.find(r=>r.id===run.id||r.previous.some(p=>p.id===run.id));if(family?.versions>1){const versions=el('details');versions.style.marginTop='18px';versions.append(el('summary','分析版本 · '+family.versions));for(const r of [family,...family.previous])versions.append(btn(date(r.created)+(r.id===run.id?' · 当前查看':''),()=>navigate('run',r.id),'quiet-button'));view.append(versions);}
}
function showFigureOptions(run){
 const body=modal('调整图表'),options=run.options||{},title=input('图标题',options.title||run.figure.layout.title?.text||''),x=input('横轴与单位',options.xlabel||run.figure.layout.xaxis?.title?.text||''),y=input('纵轴与单位',options.ylabel||run.figure.layout.yaxis?.title?.text||'');
 body.append(el('p','沿用这份原始数据，保留原分析与说明，生成新的分析版本；同一数据的版本会集中显示。','section-subtitle'),field('图标题',title));if(run.kind!=='thz')body.append(field('横轴与单位',x),field('纵轴与单位',y));else body.append(el('p','坐标单位来自本次物理计算，切换展示量时自动对应。','section-subtitle'));
 const thzPlot=run.kind==='thz'?select([['absorption','吸收系数'],['refractive_index','折射率'],['transfer','场传输幅值']],'THz 图类型'):null;if(thzPlot){thzPlot.value=options.thz_plot||'absorption';body.append(field('展示量',thzPlot));}body.append(btn('保存新版本',async()=>{const r=await api('/api/data-analysis/revise',{id:run.id,source_sha256:run.source_sha256,options:{...options,title:title.value,xlabel:x.value,ylabel:y.value,...(thzPlot?{thz_plot:thzPlot.value}:{})}});dismiss();await loadWorkspace();navigate('run',r.id);notify('图表和来源已保存为新版本');},'primary','check'));
}
async function showRunTrace(id){
 const trace=await api('/api/research/trace?id='+encodeURIComponent(id)),body=modal('来源回溯');drawProvenanceTrace(body,trace);
 const runs=trace.nodes.filter(n=>n.kind==='RUN'&&n.data.analysis_id&&n.data.purpose!=='software_validation');if(runs.length){const choose=select(runs.map(n=>[n.id,n.data.title||n.id]),'分析运行'),versions=el('div');body.append(field('分析运行',choose),btn('在当前环境检查复跑',async()=>{const result=await api('/api/research/reproduce',{id:choose.value});notify(result.metrics_match?'复跑指标一致。'+result.scope:'复跑指标不一致，请核查。');}),versions);
  function drawVersion(){versions.replaceChildren();const run=runs.find(n=>n.id===choose.value),saved=run.data.version_freeze;versions.append(el('h3','版本冻结'),el('p','固定当前输入、代码、环境锁与图产物。科研判断和 QC 沿用原审核；修改输入、方法或图表时，从分析详情保存新版本。','section-subtitle'));if(saved){versions.append(badge('已冻结 · '+saved.git_tag,'green'),el('p','冻结时间：'+new Date(saved.created).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})),el('p','Git：'+saved.git_commit,'muted'));const download=extLink('查看冻结清单','/api/research/version-seal?id='+encodeURIComponent(run.id),'quiet-button');download.download=run.id+'-version.json';versions.append(download);}else{const freeze=btn('冻结这次运行的版本',async()=>{freeze.disabled=true;try{const result=await api('/api/research/freeze',{id:run.id,revision:run.revision});run.revision=result.revision;run.data.version_freeze=result.version_freeze;drawVersion();notify('版本已冻结，原运行与科研审核状态保留');}finally{freeze.disabled=false;}},'quiet-button','check');versions.append(freeze);}}choose.onchange=drawVersion;drawVersion();}
 body.append(btn('导出 Graphviz 来源图',async()=>{const result=await api('/api/research/graph',{id});if(result.status!=='exported')throw Error('Graphviz 暂未连接，来源记录保留');body.append(extLink('查看矢量来源图','/api/research/graph.svg?id='+result.id));}));
}

async function showAnalysisForm(initialFile=null){
 const body=modal('分析设置'),project=S.project,generation=S.overlayGeneration,token=S.renderToken,isCurrent=()=>generation===S.overlayGeneration&&$('overlay').open&&project===S.project&&token===S.renderToken;let selectedFile=initialFile,inspectedFile=null,inspection=0,submitting=false;
 body.append(el('p','2 · 检查数据并选择分析。UTF-8 CSV 第一行填写列名；曲线每行一个坐标点，PCA 每行一个观测。','section-subtitle'));
 const picker=analysisFileControl(file=>{if(submitting||!isCurrent())return;selectedFile=file;return inspectFile(file);},initialFile);picker.element.inert=true;
 const kind=select(Object.entries(analysisKinds),'分析方式'),title=input('图标题'),x=input('横轴名称与单位'),y=input('纵轴名称与单位'),standard=el('input');standard.type='checkbox';standard.checked=true;
 const grid=el('div',null,'form-grid'),xField=field('横轴',x),yField=field('纵轴',y);grid.append(field('分析方式',kind),field('图标题',title),xField,yField);body.append(picker.element,grid);
 const check=el('label',null,'check-field');check.append(standard,el('span','PCA 按特征标准化'));body.append(check);const status=el('p',null,'muted'),model=el('div'),sample=select([['','先选择 CSV']],'独立样品 ID 列'),label=select([['','先选择 CSV']],'已知类别列'),batch=select([['','不使用批次划分']],'材料批次列'),split=select([['sample','按独立样品留出'],['batch','按材料批次留出']],'留出单位'),features=el('div',null,'classification-features');let featureInputs=[];
 model.append(el('h3','验证设计'),el('p','类别、独立样品与批次必须来自实际记录；重复扫描不能当作独立样品。标准化与调参在训练折内完成，逻辑回归与多数类基线共用保存的划分。','section-subtitle'),field('独立样品 ID 列',sample),field('已知类别列',label),field('留出单位',split),field('材料批次列',batch),el('h4','用于预测的数值特征'),features);body.append(model);model.hidden=true;
 const thzHost=el('div'),thz=await thzAnalysisControls(thzHost);if(!isCurrent())return;body.append(thzHost);picker.element.inert=false;kind.onchange=()=>{xField.hidden=yField.hidden=kind.value==='thz';model.hidden=kind.value!=='classification';check.hidden=kind.value!=='pca';thz.panel.hidden=kind.value!=='thz';};kind.onchange();
 async function inspectFile(file){if(!file||!isCurrent())return;const revision=++inspection;inspectedFile=null;save.disabled=true;try{status.textContent='正在检查 CSV 列名…';const csv=await file.text();if(!isCurrent()||revision!==inspection)return;const preview=await api('/api/data-analysis/columns',{csv});if(!isCurrent()||revision!==inspection)return;for(const [control,hint] of [[sample,'选择独立样品 ID'],[label,'选择已知类别'],[batch,'不使用批次划分']]){control.replaceChildren(...[['',hint],...preview.columns.map(c=>[c,c])].map(([value,text])=>{const o=el('option',text);o.value=value;return o;}));}features.replaceChildren();featureInputs=[];for(const name of preview.numeric){const c=el('input');c.type='checkbox';c.value=name;const row=el('label',null,'check-field');row.append(c,el('span',name));features.append(row);featureInputs.push(c);}thz.update(preview);inspectedFile=file;save.disabled=false;status.textContent=preview.rows+' 行 · '+preview.numeric.length+' 个数值列；列名：'+preview.columns.join('、');}catch(error){if(isCurrent()&&revision===inspection)status.textContent=error.message;}}
 for(const control of [sample,label,batch])control.onchange=()=>{for(const c of featureInputs){c.disabled=[sample.value,label.value,batch.value].includes(c.value);if(c.disabled)c.checked=false;}};
 const save=btn('分析并保存',async()=>{if(submitting||!isCurrent())return;if(!selectedFile)throw Error('请先选择 CSV 数据');if(inspectedFile!==selectedFile)throw Error('请等待当前 CSV 检查通过后再分析');submitting=true;save.disabled=true;picker.element.inert=true;try{status.textContent='正在计算与登记来源…';const file=selectedFile,analysisKind=kind.value,options={title:title.value,xlabel:x.value,ylabel:y.value,standardize:standard.checked};if(analysisKind==='classification')Object.assign(options,{sample_column:sample.value,label_column:label.value,batch_column:batch.value||null,split_by:split.value,feature_columns:featureInputs.filter(c=>c.checked&&!c.disabled).map(c=>c.value),seed:42,bootstrap_resamples:2000});if(analysisKind==='thz')Object.assign(options,thz.options());const csv=await file.text();if(!isCurrent())return;const result=await api('/api/data-analysis',{project,csv,filename:file.name,kind:analysisKind,options});if(!isCurrent())return;await loadWorkspace();if(!isCurrent())return;dismiss();navigate('run',result.id);}finally{submitting=false;if(isCurrent()){save.disabled=inspectedFile!==selectedFile;picker.element.inert=false;}}},'primary','chart');save.disabled=true;body.append(status,el('p','3 · 分析后自动保存输入版本、图表和可编辑说明。结果页直接显示文件位置。','section-subtitle'),save);
 if(initialFile)await inspectFile(initialFile);
}
function recordCreationContext(route,doc=null){
 if(['knowledge','knowledge-node','paper'].includes(route)||(route==='document'&&doc?.content_role==='knowledge'))return {entry:'knowledge',kind:'PaperNote',label:'新建知识笔记'};
 if(route==='outputs')return {entry:'output',kind:'Paper',label:'新建产出记录'};
 return {entry:'project',kind:'Decision',label:'新建项目记录'};
}
function projectCreationTarget(){
 if(S.route!=='projects')return '';
 const params=new URLSearchParams(location.hash.split('?')[1]);
 if(params.get('view')==='question-history')return 'history';
 return params.has('project')||params.has('view')?'record':'collection';
}
function updateCreateRecordLabel(){
 const target=projectCreationTarget(),label=$('createRecordLabel'),button=$('createRecord');
 if(button)button.hidden=target==='history'||target==='collection';
 if(label)label.textContent=recordCreationContext(S.route,S.doc).label;
}
function recordTemplates(templates,entry){
 if(entry==='knowledge')return templates.filter(t=>t.knowledge===true);
 if(entry==='output')return templates.filter(t=>['Paper','Patent','DatasetOutput','Software','Protocol','Presentation','Report'].includes(t.kind));
 return templates;
}
function showNewRecord(defaultKind='Idea',context={}){
 const entry=context.entry||recordCreationContext(S.route,S.doc).entry;
  if(entry==='project'&&defaultKind==='Decision')return showProjectRecord(context.project||S.project);
 const body=modal(entry==='knowledge'?'新建知识笔记':entry==='output'?'新建产出记录':'新建项目记录');
 const kinds=recordTemplates(S.workspace.templates,entry);if(!kinds.length)throw Error('当前入口暂无可用模板，请刷新工作区。');
 const kind=select(kinds.map(t=>[t.kind,t.label]),'记录类型');kind.value=kinds.some(t=>t.kind===defaultKind)?defaultKind:kinds[0].kind;
 const projects=[...new Set(['共享',...(S.workspace.projects||[]),S.project])];
 const project=select(projects.map(p=>[p,projectLabel(p)||p]),'所属项目');project.value=context.project||(entry==='knowledge'?'共享':S.project);project.disabled=!!context.question_id;
 const title=input('简洁、具体的标题',context.title||''),text=el('textarea');text.rows=12;text.value=kinds.find(t=>t.kind===kind.value)?.body||'';kind.onchange=()=>{text.value=kinds.find(t=>t.kind===kind.value)?.body||'';};
 body.append(field('所属项目',project),field('记录类型',kind),field('标题',title),field('正文',text),el('p',entry==='knowledge'?'保存为知识主稿；科学判断与来源继续保留待核状态。':'过程记录在所属项目中查阅。','section-subtitle'),btn(entry==='knowledge'?'创建知识笔记':'创建记录',async()=>{const result=await api('/api/research/create',{entry,project:project.value,kind:kind.value,title:title.value,body:text.value,paper_ids:context.paper_ids||[]});dismiss();await loadWorkspace();const doc=objectForPath(result.path);if(doc){if(context.question_id){const listing=await api('/api/project/questions?project='+encodeURIComponent(project.value)),question=listing.questions.find(q=>q.id===context.question_id);if(question)await api('/api/project/question-reference',{project:project.value,id:question.id,fingerprint:question.fingerprint,material:'doc:'+doc.id,mode:'add'});}navigate('document',doc.id);}notify('记录已创建');},'primary','plus'));
}
function showProjectRecord(project){
 const body=modal('新建项目记录'),title=input('记录标题'),text=el('textarea');text.rows=10;text.setAttribute('aria-label','记录正文');
 let request=crypto.randomUUID(),busy=false;title.oninput=text.oninput=()=>{request=crypto.randomUUID();};
 const save=btn('保存',async()=>{if(busy)return;if(!title.value.trim()||!text.value.trim())throw Error('请填写标题与正文。');busy=true;save.disabled=title.disabled=text.disabled=true;try{
  const result=await api('/api/project-decision',{project,title:title.value,body:text.value,confirm:false,request_id:request});
  dismiss();await loadWorkspace();const doc=objectForPath(result.path);if(doc)navigate('document',doc.id);else await renderRoute();notify('项目记录已保存');
 }finally{busy=false;save.disabled=title.disabled=text.disabled=false;}},'primary','check');
 body.append(field('记录标题',title),field('记录正文',text),btn('取消',dismiss,'quiet-button'),save);
}
async function showIntake(){
 const body=modal('添加论文');const file=el('input');file.type='file';file.multiple=true;file.accept='.pdf,application/pdf';file.hidden=true;
 const drop=el('div',null,'drop-zone');drop.setAttribute('role','button');drop.setAttribute('tabindex','0');drop.append(ic('upload'),el('h3','把 PDF 拖到这里'),el('p','或点击选择文件 · 已有附件会复用'));
 drop.onclick=()=>file.click();drop.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();file.click();}};
 for(const type of ['dragenter','dragover'])drop.addEventListener(type,e=>{e.preventDefault();drop.classList.add('dragover');});
 drop.ondragleave=()=>drop.classList.remove('dragover');const progress=el('p',null,'section-subtitle');
 async function importFiles(files){drop.classList.remove('dragover');for(const f of files){progress.textContent='正在登记 '+f.name;const response=await fetch('/api/import-pdf',{method:'POST',headers:{'Content-Type':'application/pdf','X-Filename':encodeURIComponent(f.name),'X-Project':encodeURIComponent(S.project)},body:f});const result=await response.json();if(!response.ok)throw Error(result.error||'导入未完成');}progress.textContent='文件已登记，后台会接着索引和整理。';await loadWorkspace();notify('论文已登记');}
 drop.ondrop=e=>{e.preventDefault();importFiles(e.dataTransfer.files).catch(e=>notify(e.message,true));};file.onchange=()=>importFiles(file.files).catch(e=>notify(e.message,true));
 body.append(drop,file,progress,el('hr',null,'divider'));const doi=input('例如 10.xxxx/xxxxx');const row=el('div',null,'toolbar');row.append(doi,btn('通过 DOI 获取',async()=>{progress.textContent='正在核对题录和开放全文…';const result=await job('/api/acquire',{doi:doi.value,project:S.project});await loadWorkspace();progress.textContent=result.message||'本次处理已完成。';notify(result.message||'论文获取流程已完成',result.has_pdf===false);},'primary'));body.append(field('论文 DOI',row));
}
async function showRelationEditor(nodes,initial=null){
 const workspace=await loadKnowledge();
 const body=modal(initial?'编辑已登记关系':'新增关系');
 const choices=[...new Map(nodes.map(node=>{
  const id=node.record_id||node.paper_id||node.doc_id;
  const label=node.label||node.title||id;
  return [id,label+(node.kind&&!label?.endsWith(node.kind)?' · '+node.kind:'')];
 }).filter(([id])=>id)).entries()];
 if(choices.length<2){body.append(empty('当前图没有两份可登记的资料'));return;}
 const from=select([['','请选择起点'],...choices],'起点资料');
 const to=select([['','请选择目标'],...choices],'目标资料');
 const kind=select([['CorrespondsTo','对应论文 · 资料索引']],'关系类型');
 const vocabulary=workspace.relation_types||[],evidence=el('textarea'),conditions=el('textarea');
 evidence.rows=3;conditions.rows=2;
 for(const group of new Set(vocabulary.map(row=>row.group))){
  const options=el('optgroup');options.label=group;
  for(const row of vocabulary.filter(row=>row.group===group)){const option=el('option',row.label);option.value=row.id;options.append(option);}
  kind.append(options);
 }
 if(initial){
  from.value=initial.source;to.value=initial.target;kind.value=initial.kind;from.disabled=to.disabled=kind.disabled=true;
  conditions.value=initial.conditions||'';
  const previous=el('details');previous.append(el('summary','已有出处'));
  for(const ref of initial.evidence||[])previous.append(el('p',ref.location||ref.quote||''));
  body.append(previous);
 }
 const hint=el('p',null,'section-subtitle'),fields=el('div'),direction=el('p',null,'relation-direction');
 fields.append(field(initial?'补充证据位置与出处':'证据位置与出处',evidence),field('适用条件与限制',conditions));
 const updateDirection=()=>{direction.textContent=(from.selectedOptions[0]?.textContent||'起点')+' → '+(kind.selectedOptions[0]?.textContent||'关系')+' → '+(to.selectedOptions[0]?.textContent||'目标');};
 const fill=(control,items,placeholder)=>{
  const old=control.value;
  control.replaceChildren(...[['',placeholder],...items].map(([id,label])=>{const option=el('option',label);option.value=id;return option;}));
  if(items.some(([id])=>id===old))control.value=old;
 };
 kind.onchange=()=>{
  const paper=kind.value==='CorrespondsTo';
  if(!initial){
   fill(from,paper?choices.filter(([id])=>workspace.documents.some(d=>[d.id,d.record_id].includes(id)&&d.editable)):choices,'请选择起点');
   fill(to,paper?choices.filter(([id])=>workspace.papers.some(p=>p.id===id)):choices,'请选择目标');
  }
  fields.hidden=paper;
  hint.textContent=paper?'起点选笔记，目标选论文。':vocabulary.find(row=>row.id===kind.value)?.description||'填写实际出处和适用条件。';
  updateDirection();
 };
 from.onchange=to.onchange=updateDirection;kind.onchange();
 body.append(direction,field('起点资料',from),field('关系类型',kind),field('目标资料',to),hint,fields,
  btn(initial?'保存依据修改':'保存关系',async()=>{
   if(!from.value||!to.value||from.value===to.value)throw Error('请选择两份不同的资料');
   if(kind.value==='CorrespondsTo'){
    const doc=workspace.documents.find(d=>[d.id,d.record_id].includes(from.value)),paper=workspace.papers.find(p=>p.id===to.value);
    if(!doc||!paper)throw Error('对应论文需要一份笔记和一篇论文');
    const current=await api('/api/workspace/document?id='+doc.id);
    await api('/api/workspace/metadata',{id:doc.id,fingerprint:current.fingerprint,paper_ids:[...new Set([...current.paper_ids,paper.id])]});
   }else{
    const refs=[...(initial?.evidence||[])],location=evidence.value.trim();
    if(location)refs.push({location,...(initial?{source:'human-edit'}:{})});
    if(!refs.length)throw Error('请填写证据位置');
    await api('/api/research/relation',{project:S.project,source:from.value,target:to.value,kind:kind.value,
                                     evidence:refs,conditions:conditions.value,...(initial?{revision:initial.revision}:{})});
   }
   dismiss();await loadWorkspace();await S.graphRefresh?.();await S.knowledgeDetailController?.refresh();
   notify(kind.value==='CorrespondsTo'?'对应论文已保存':'关系已登记');
  },'primary'));
}

let refreshBusy=false,lastRefresh=Date.now();
async function showReferencePicker(source){
 const editor=S.editor;if(!editor)throw Error('请先打开正文编辑器');const selection=editor.getSelection(),knowledge=await loadKnowledge();
 const body=modal('插入资料引用'),search=searchField('查找要引用的笔记、背景或报告'),list=el('div',null,'list');body.append(el('p','选中后插入正文链接。保存时，引用与反向引用自动登记。','section-subtitle'),search.node,list);list.style.marginTop='16px';
 function draw(){list.replaceChildren();const q=search.input.value.toLowerCase();const docs=knowledge.documents.filter(d=>!d.archived&&d.visibility!=='system').filter(d=>d.id!==source.id&&[d.title,d.display_title,d.kind,d.path].join(' ').toLowerCase().includes(q)).sort((a,b)=>(a.visibility==='active'?0:1)-(b.visibility==='active'?0:1)||b.file_modified-a.file_modified).slice(0,30);
  for(const target of docs){const button=btn('',()=>{if(S.editor!==editor)throw Error('编辑器已关闭，请重新打开正文');const from=source.path.split('/').slice(0,-1),to=target.path.split('/');while(from.length&&to.length&&from[0]===to[0]){from.shift();to.shift();}const relative='../'.repeat(from.length)+to.map(encodeURIComponent).join('/');dismiss();editor.focus();if(selection[0]===0||selection[1]===0)editor.moveCursorToEnd();else editor.setSelection(selection[1],selection[1]);editor.exec('addLink',{linkUrl:relative,linkText:target.title});},'list-row');const copy=el('div',null,'row-copy');copy.append(el('strong',target.title),el('p',target.kind+' · '+target.project));button.append(ic('link'),copy);list.append(button);}
  if(!docs.length)list.append(empty('没有找到匹配资料','可以先创建正文，再在这里连接。'));
 }search.input.oninput=draw;draw();search.input.focus();
}
async function showResearchTools(){
 const config=await api('/api/administrator?project='+encodeURIComponent(S.project)),body=modal('科研分析工具');body.append(btn('技能与规则',showSkillsManager,'quiet-button','book'));
 body.append(el('p','选择实际要做的分析。结果保存为可编辑报告，带输入链接；任务进度集中在自动化中。','section-subtitle'));
 const skill=select(config.skills.map(s=>[s.id,s.label]),'分析工具'),instruction=el('textarea');instruction.rows=4;instruction.placeholder='说明研究问题、要检查的材料和你希望得到什么。';
 let maxPapers=config.skills[0]?.max_papers||8; const selected=new Set(),papers=el('details'),paperSummary=el('summary','指定文献（可选，最多 '+maxPapers+' 篇）');papers.append(paperSummary);
 skill.onchange=()=>{maxPapers=config.skills.find(row=>row.id===skill.value)?.max_papers||8;paperSummary.textContent='指定文献（可选，最多 '+maxPapers+' 篇）';};
 for(const p of S.workspace.papers){const label=el('label',null,'check-field'),check=el('input');check.type='checkbox';check.onchange=()=>check.checked?selected.add(p.id):selected.delete(p.id);label.append(check,el('span',p.display_title||p.title));papers.append(label);}
 body.append(field('分析工具',skill),field('分析要求',instruction),papers);
 const current=el('input'),currentDocument=S.doc?.kb_path&&(S.workspace?.assistant_document_ids||[]).includes(S.doc.id)?S.doc:null;current.type='checkbox';current.checked=!!currentDocument;current.disabled=!currentDocument;
 const currentLabel=el('label',null,'check-field');currentLabel.append(current,el('span',currentDocument?'同时分析当前正文：'+currentDocument.title:S.doc?.kb_path?'当前正文尚未选入项目；可先选用或仅讨论此资料':'当前未选中知识库正文'));body.append(currentLabel);
 const status=el('p',null,'section-subtitle'),run=btn('开始分析',async()=>{if(!instruction.value.trim())throw Error('请填写具体分析要求');if(selected.size>(config.skills.find(row=>row.id===skill.value)?.max_papers||maxPapers))throw Error('最多指定 '+(config.skills.find(row=>row.id===skill.value)?.max_papers||maxPapers)+' 篇文献');run.disabled=true;status.textContent='正在分析，保留来源与阅读边界…';
  try{const result=await job('/api/analyze',{project:S.project,skill:skill.value,instruction:instruction.value,...(selected.size?{paper_ids:[...selected]}:{}),...(current.checked&&currentDocument?{path:currentDocument.kb_path}:{})});if(!result.path)throw Error(result.message||'本次没有生成分析正文');dismiss();await loadWorkspace();const doc=objectForPath(result.path);if(doc)navigate('document',doc.id);}finally{run.disabled=false;}
 },'primary','sparkles');body.append(status,run);
 const extra=el('details');extra.style.marginTop='22px';extra.append(el('summary','资料整理与方向候选'));
 extra.append(btn('整理已登记资料',async()=>{const result=await job('/api/organize',{project:S.project});notify('本次整理已完成；科研判断仍需核查。');await loadWorkspace();}),btn('查看方向候选',()=>showDirectionCandidates(config.discovery)),btn('检查新方向线索',async()=>{await job('/api/directions',{project:S.project});await showResearchTools();notify('候选已更新，未改变当前主线。');}));body.append(extra);
}
function showDirectionCandidates(data){
 const body=modal('方向候选');body.append(el('p','候选不自动改变课题；选择状态后按同一主线记录更新。','section-subtitle'));
 for(const item of data?.directions||[]){const card=el('div',null,'card');card.style.marginBottom='14px';card.append(el('h3',item.title),el('p',item.question||item.summary||'','section-subtitle'),badge(item.status||'待核查'));
 const state=select(['待选择','调研中','已采用','暂缓','不采用'].map(s=>[s,s]),'候选状态');state.value=['待选择','调研中','已采用','暂缓','不采用'].includes(item.status)?item.status:'待选择';
 card.append(state,btn('保存选择',async()=>{await api('/api/directions/status',{project:S.project,id:item.id,status:state.value,fingerprint:data.choice_fingerprint});await loadWorkspace();dismiss();notify('方向选择已保存，相关视图将更新');}));body.append(card);}
 if(!data?.directions?.length)body.append(empty('当前没有方向候选','保留已选择的研究问题；需要时再检查新线索。'));
}
function showPaperOrganization(){
 const body=modal('整理文献'),selected=new Set(),list=el('div',null,'paper-selection'),search=searchField('筛选要整理的论文');
 const count=el('p','请选择论文；保存只作用于勾选的条目。','section-subtitle');body.append(count,search.node,list);
 function draw(){list.replaceChildren();const q=search.input.value.toLowerCase();for(const p of S.workspace.papers.filter(p=>[p.title,p.display_title,p.id].join(' ').toLowerCase().includes(q))){const label=el('label',null,'check-field'),check=el('input');check.type='checkbox';check.checked=selected.has(p.id);check.onchange=()=>{check.checked?selected.add(p.id):selected.delete(p.id);count.textContent='已选择 '+selected.size+' 篇；保存只作用于这些条目。';};label.append(check,el('span',p.display_title||p.title));list.append(label);}}
 search.input.oninput=draw;draw();const tabbar=tabs([['relation','分类与研究用途'],['status','归属与阅读状态']],'relation',render),box=el('div');body.append(tabbar,box);
 function render(tab){box.replaceChildren();tabbar.querySelectorAll('button').forEach((b,i)=>b.classList.toggle('active',i===(tab==='relation'?0:1)));const ids=()=>{if(!selected.size)throw Error('请先勾选论文');return [...selected];};
  if(tab==='status'){const project=select([['','保持项目归属'],...S.workspace.projects.map(p=>[p,p]),['共享','共享'],['待归类','待归类']],'项目归属'),state=select([['','保持阅读状态'],['未读','未读'],['阅读中','阅读中']],'阅读状态');box.append(field('项目归属',project),field('阅读状态',state),el('p','已核查状态与实际阅读范围在单篇文献中登记。','section-subtitle'),btn('保存所选更改',async()=>{await api('/api/papers/bulk',{paper_ids:ids(),project:project.value||null,status:state.value||null,fingerprint:S.workspace.library_fingerprint,confirmed:true});dismiss();await loadWorkspace();renderRoute();notify('所选文献已更新');},'primary'));return;}
  const topic=input('不填写则保持分类'),line=select([['','保持主线关联'],...S.workspace.mainlines.rows.map(l=>[l.id,l.title])],'研究主线'),mode=select([['add','关联到主线'],['remove','从主线移除']],'关联方式'),role=select(['待判断','背景依据','方法参考','支持证据','限制或反例'].map(v=>[v,v]),'研究用途'),reason=el('textarea'),scope=input('PDF 页码或 XML 章节');reason.rows=2;
  box.append(field('主题分类',topic),field('研究主线',line),field('关联方式',mode),field('研究用途',role),field('用途说明',reason),field('实际依据范围',scope),el('p','所选条目归入当前项目：'+S.project+'。这项关联不自动提升阅读或科学核查等级。','section-subtitle'),btn('保存分类与关联',async()=>{await api('/api/papers/associate',{project:S.project,paper_ids:ids(),mainline_ids:line.value?[line.value]:[],...(topic.value.trim()?{topic:topic.value.trim()}:{}),mode:mode.value,role:role.value,reason:reason.value,scope:scope.value,fingerprint:S.workspace.library_fingerprint,lines_fingerprint:S.workspace.mainlines.fingerprint});dismiss();await loadWorkspace();renderRoute();notify('分类与关联已更新');},'primary'));
 }render('relation');
}
async function refreshInBackground(){
 if(refreshBusy||S.chatBusy||S.editor||S.dirty||$('overlay').open||document.hidden)return;
 const direct=S.route==='knowledge'&&S.tab==='graph'?S.graphRefresh:S.route==='discover'?S.radarRefresh:S.route==='projects'?S.projectReferencesRefresh:null;
 if(direct){refreshBusy=true;try{await direct();lastRefresh=Date.now();}catch(_){/* Preserve the current view during a temporary read failure. */}finally{refreshBusy=false;}return;}
 if(!['document','paper'].includes(S.route)||!S.workspace)return;
 refreshBusy=true;try{
  const before=S.doc;await loadWorkspace();lastRefresh=Date.now();
  if(S.route==='discover')await S.radarRefresh?.();if(S.route==='projects')await S.projectReferencesRefresh?.();
  if(S.route==='knowledge'&&S.tab==='graph'){try{await S.graphRefresh?.();}catch(_){/* Keep the saved graph; a graph refresh failure does not disconnect the workspace. */}}
  if(before&&!S.editor){const updated=S.workspace.documents.find(d=>d.id===before.id);if(updated&&(updated.sha!==before.sha||updated.needs_review!==before.needs_review)&&!$('refreshDocument')){const b=btn('资料有更新 · 重新读取',()=>renderDocument(before.id),'quiet-button');b.id='refreshDocument';$('view').querySelector('.object-toolbar')?.append(b);}}
 }catch(_){$('connectionStatus').textContent='连接待恢复';}finally{refreshBusy=false;}
}
setInterval(refreshInBackground,45000);
let projectLiveBusy=false;setInterval(async()=>{if(S.route!=='projects'||document.hidden||$('overlay').open||projectLiveBusy)return;projectLiveBusy=true;try{await S.projectReferencesRefresh?.();}catch(_){/* A saved view remains usable during a transient read failure. */}finally{projectLiveBusy=false;}},5000);
window.addEventListener('focus',()=>{if(Date.now()-lastRefresh>30000)refreshInBackground();});

function openGraphMaterial(node){
 if(['knowledge','knowledge-node'].includes(S.route)){if(node?.paper_id){dismiss();navigate('paper',node.paper_id);return;}if(node?.doc_id){dismiss();navigate('document',node.doc_id);return;}}
 const target=ResearchGraph.destination(node,S.route==='knowledge'&&S.knowledge?{...S.knowledge,include_history:true}:S.workspace);if(!target){notify('这是一组导航对象，请选择其中的具体资料');return;}dismiss();
 if(target.route)navigate(target.route,target.id||'');else if(target.action==='rawdata')navigateRawData(target.id);else if(target.action==='mainlines')location.hash='#projects?'+new URLSearchParams({project:S.project,view:'overview'});else showRunTrace(target.id);
}
async function showDocumentPapers(doc){
 const current=await api('/api/workspace/document?id='+doc.id),body=modal('关联论文 · '+docLabel(current)),selected=new Set(current.paper_ids),search=searchField('查找对应论文'),list=el('div',null,'paper-selection');body.append(el('p','一份资料可关联多篇论文。取消勾选只移除索引；正文中的引用与原有阅读卡片登记仍会保留。','section-subtitle'),search.node,list);
 function draw(){list.replaceChildren();for(const p of S.workspace.papers.filter(p=>[p.display_title,p.title,p.id].join(' ').toLowerCase().includes(search.input.value.toLowerCase()))){const c=el('input');c.type='checkbox';c.checked=selected.has(p.id);c.onchange=()=>c.checked?selected.add(p.id):selected.delete(p.id);const label=el('label',null,'check-field');label.append(c,el('span',p.display_title||p.title));list.append(label);}}search.input.oninput=draw;draw();
 body.append(btn('保存论文关联',async()=>{await api('/api/workspace/metadata',{id:current.id,fingerprint:current.fingerprint,paper_ids:[...selected]});dismiss();await loadWorkspace();renderRoute();notify('论文与资料的对应索引已更新');},'primary'));
}
async function showExistingPaperDocuments(paper){
 const body=modal('关联已有资料 · '+(paper.display_title||paper.title)),search=searchField('查找要关联的笔记或报告'),list=el('div',null,'list');body.append(search.node,list);
 function draw(){list.replaceChildren();for(const doc of visibleDocs().filter(d=>d.editable&&[d.title,d.kind,d.path].join(' ').toLowerCase().includes(search.input.value.toLowerCase()))){const row=el('div',null,'queue-row');row.append(el('strong',docLabel(doc)));const linked=doc.paper_ids.includes(paper.id),action=btn(linked?'已关联':'关联',async()=>{const current=await api('/api/workspace/document?id='+doc.id);await api('/api/workspace/metadata',{id:doc.id,fingerprint:current.fingerprint,paper_ids:[...new Set([...current.paper_ids,paper.id])]});await loadWorkspace();if(S.route==='paper')await renderPaper(paper.id);action.disabled=true;action.textContent='已关联';notify('资料已关联到这篇论文');},'quiet-button');action.disabled=linked;row.append(action);list.append(row);}}search.input.oninput=draw;draw();
 body.append(btn('完成并返回论文',()=>{dismiss();renderPaper(paper.id);},'primary'));
}

function materialBackButton(fallback,label){const previous=S.materialBack?.get(location.hash)||history.state?.researchBack;return btn(previous?.label||label,()=>{if(previous)location.hash=previous.hash;else fallback();},'text-link','back');}


function renderUsageGuide(){
 const guide=el('details',null,'usage-guide');guide.id='usage-guide';
 let preference;try{preference=localStorage.getItem('research:usage-guide');}catch(_){}
 guide.open=preference==='open';
 const summary=el('summary'),title=el('div');title.append(el('strong','使用指南'),el('span','操作流程与修改位置'));summary.append(title,ic('arrow'));guide.append(summary);
 const body=el('div',null,'usage-guide-body');body.append(el('p','按当前任务使用相应步骤，内容只在主稿或专业软件里修改一次。','muted'));
 const flow=el('ol',null,'usage-flow');
 for(const [name,action]of[['发现','选论文并收录'],['知识','读原文、写笔记'],['项目','定问题、计划与待办'],['实验','在 RSpace 记事实'],['分析','导入数据、检查与计算'],['产出','核对来源、整理交付']]){
  const item=el('li');item.append(el('strong',name),el('span',action));flow.append(item);
 }body.append(flow);
 const table=el('table',null,'usage-table'),head=el('thead'),labels=el('tr');for(const label of ['功能','怎么用','在哪里修改'])labels.append(el('th',label));head.append(labels);table.append(head);
 const rows=[
  ['论文提醒与检索','在发现区按关注规则找论文，选“收录”；已有论文从知识 → 文献打开。','题录、PDF、批注在 Zotero；原文页可打开 PDF，缺 PDF 时点补齐。'],
  ['知识与项目资料','知识 → 资料查找知识笔记；记录、背景和其他资料在项目中查看。论文详情可“新建笔记”或关联已有资料。','资料详情 → 编辑正文；同一主稿的修改历史可查看与恢复。'],
  ['关系图','知识 → 关系图，选节点查看详情、打开原稿；用“维护科研关系”增改关系。','对应论文在资料的“关联论文”维护；正文引用改原稿链接，科研关系附依据后审核。'],
  ['项目与待办','项目区查看主线、当前主稿、任务及历史经验。采购与预实验在同一方案维护。','项目设置改主线；编辑任务清单改待办；正文从对应主稿编辑。'],
  ['正式实验','实验区查看实验、样品批次、仪器校准与 QC；打开记录跳到原平台。','事实在 RSpace 编辑，状态自动同步到看板；QC 沿分析方法与实际测量生成。'],
  ['数据与绘图','分析区选择或拖入 CSV，检查列与分析方式后保存；按独立样品分类时先指定类别和分组。','已有分析中改说明与图表；输入位置、下载、版本、复跑及来源均在同一记录。'],
  ['方法与 QC','分析 → 方法与 QC，维护模型、条件、阈值、验证证据及自动分析规则。','在同一方法主稿和配置中修改；核对后启用，方法变化重新核对。'],
  ['成果与关闭','产出区查看论文交付、图与结果；项目复盘逐项关联证据后关闭。','成果打开主稿编辑；图在来源分析中修改；关闭前检查数据、代码、环境与恢复。'],
  ['科研助手','右上科研助手问已有资料或说明希望怎样修改；研究工具用于专项分析。','AI 协助修改先给预览，可改候选内容，再确认保存到原主稿。'],
  ['自动化与审核','待处理集中核对资料变化与修改建议；关联建议按需查看；运行记录看错误与接续。','自动化设置集中改日程、启停与范围。机械整理自动完成，正式修改核对后保存；后台运行时才执行。'],
  ['周报与专业图','主页打开周报；分析 → 文献计量做 Bibliometrix/VOSviewer，关系图 → 专业精修用 Cytoscape。','周报在原正文或更新预览修改；专业图保留自动版与精修版，图源和导出在原任务中管理。'],
  ['搜索、归档与连接','顶部搜索支持 Ctrl K；资料范围选“已归档”可看历史，旧资料能打开当前主稿。','归档恢复回到日常列表；连接与设置统一维护软件、AI、年度分区、备份与恢复。']
 ];
 const content=el('tbody');for(const row of rows){const tr=el('tr');for(const [index,text]of row.entries()){const cell=el(index?'td':'th',text);if(!index)cell.scope='row';tr.append(cell);}content.append(tr);}table.append(content);body.append(table);guide.append(body);
 const remember=open=>{try{localStorage.setItem('research:usage-guide',open?'open':'closed');}catch(_){}};
 summary.onclick=()=>remember(!guide.open);
 guide.ontoggle=()=>remember(guide.open);
 return guide;
}
