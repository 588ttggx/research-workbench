/* Shared topic paths and material cards. No scientific relation is inferred here. */
(function(root){
 'use strict';
 function children(nodes,parent){return nodes.filter(n=>n.parent===parent).sort((a,b)=>(a.order||0)-(b.order||0)||a.title.localeCompare(b.title,'zh-CN'));}
 function path(nodes,id){const map=new Map(nodes.map(n=>[n.id,n])),result=[],seen=new Set();while(id&&map.has(id)&&!seen.has(id)){seen.add(id);const n=map.get(id);result.unshift(n);id=n.parent;}return result;}
 function descendants(nodes,id){const found=new Set(id?[id]:[]);let changed=true;while(changed){changed=false;for(const n of nodes)if(found.has(n.parent)&&!found.has(n.id)){found.add(n.id);changed=true;}}return found;}
 function isKnowledge(document){return document.content_role==='knowledge'&&document.global_knowledge!==false;}
 function cards(workspace,classification,{topic='',usage='',query='',scope='current',paperOnly=false,kind='',source_project=''}={}){
  scope=scope==='archived'?'archived':'current';
  const topics=descendants(classification.nodes,topic),uses=descendants(classification.nodes,usage),q=query.trim().toLowerCase();
  const assignment=id=>classification.assignments[id]||{topics:[],usage:''};
  const origin=row=>row.source_project||(row.project==='共享'?'':row.project)||'__unknown__';
  const sourceMatches=row=>!source_project||origin(row)===source_project;
  const matches=(id,row)=>{const a=assignment(id);return (!topic||a.topics.some(t=>topics.has(t)))&&(!usage||uses.has(a.usage))&&(!q||[row.title,row.display_title,row.path,row.id,row.doi,row.kind,row.topic,row.project,row.source_project,row.source_project_title,...a.topics.map(t=>path(classification.nodes,t).map(n=>n.title).join(' '))].join(' ').toLowerCase().includes(q));};
  const visible=d=>isKnowledge(d)&&!d.question_deleted&&!d.question_id&&d.visibility!=='system'&&(scope==='archived'?d.archived:!d.archived);
  const documents=workspace.documents.filter(d=>visible(d)&&(!kind||d.kind===kind)&&sourceMatches(d)),owned=new Set(),result=[];
  for(const paper of workspace.papers){
   const notes=documents.filter(d=>d.paper_ids?.length===1&&d.paper_ids[0]===paper.id);notes.forEach(d=>owned.add(d.id));
   const matched_notes=notes.filter(d=>matches('doc:'+d.id,d));
   if((!source_project||sourceMatches(paper)||notes.length)&&(!kind||notes.length)&&(scope==='current'||notes.length)&&(matches('paper:'+paper.id,paper)||matched_notes.length))result.push({id:'paper:'+paper.id,title:paper.display_title||paper.title,paper,notes,matched_notes:q?matched_notes:[],assignment:assignment('paper:'+paper.id)});
  }
  if(!paperOnly)for(const doc of documents)if(!owned.has(doc.id)&&matches('doc:'+doc.id,doc))result.push({id:'doc:'+doc.id,title:doc.display_title||doc.title,doc,notes:[],assignment:assignment('doc:'+doc.id)});
  return result;
 }
 function graphLevel(workspace,classification,root,page=0,filters={}){
  const themes=children(classification.nodes,root).filter(n=>n.dimension==='topic'&&(REVIEW_THEMES.has(n.id)||cards(workspace,classification,{...filters,topic:n.id}).length>0)),all=cards(workspace,classification,filters);
  const materials=root?all.filter(card=>[card.id,...card.notes.map(d=>'doc:'+d.id)].some(id=>classification.assignments[id]?.topics.includes(root))):[];
  const topic=n=>({id:n.id,label:n.title,kind:n.kind==='question'?'主线':'主题',topic_id:n.id,question_id:n.question_id,step_id:n.step_id,project:n.project,status:'分类导航'});
  const parent=classification.nodes.find(n=>n.id===root),reviewId=classification.reviews?.[root]?.document_id,satellites=[];if(!root){const seenPapers=new Set();for(const theme of themes){const descendantsOf=descendants(classification.nodes,theme.id),picks=all.filter(card=>card.paper&&card.assignment.topics.some(topic=>descendantsOf.has(topic))).sort((a,b)=>(b.paper.documents?.length||0)-(a.paper.documents?.length||0)||b.notes.length-a.notes.length).slice(0,2);for(const card of picks){if(seenPapers.has(card.paper.id))continue;seenPapers.add(card.paper.id);satellites.push({id:'paper:'+card.paper.id,label:card.title,kind:'论文',paper_id:card.paper.id,topic_id:theme.id});}}}
  const nodes=[...(parent?[topic(parent)]:[]),...themes.map(topic),...satellites,...materials.slice(page*12,(page+1)*12).map(card=>({id:card.paper?'paper:'+card.paper.id:card.doc.id,label:card.doc?.id===reviewId?card.title+'（主题综述）':card.title,kind:card.paper?'论文':card.doc.kind,paper_id:card.paper?.id,doc_id:card.doc?.id,summary:card.doc?.excerpt||card.paper?.title,card}))];
  const edges=[...(parent?nodes.filter(n=>n.id!==root).map(n=>({id:'navigation:'+root+':'+n.id,from:root,to:n.id,label:n.topic_id?'下级主题':'归属资料',source:'分类导航',group:true,navigation:true,explanation:'用于分类浏览，不代表科研支持或证据关系。'})):[]),...satellites.map(n=>({id:'skeleton:'+n.topic_id+':'+n.paper_id,from:n.topic_id,to:n.id,label:'代表论文',source:'分类导航',group:true,navigation:true,explanation:'主题骨架的代表论文，不代表科研支持或证据关系。'}))];
  return {nodes,edges,isolated:0,total:materials.length};
 }
 const api={children,path,descendants,cards,graphLevel,isKnowledge};root.TopicNavigation=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);

async function loadKnowledge(fresh=false){
 if(!fresh&&S.knowledge)return S.knowledge;
 if(!fresh&&S.knowledgeRequest)return S.knowledgeRequest;
 const request=api('/api/knowledge/catalog');S.knowledgeRequest=request;
 try{const data=await request;if(S.knowledgeRequest===request)S.knowledge={...data,include_history:true};return data;}finally{if(S.knowledgeRequest===request)S.knowledgeRequest=null;}
}
async function navigationData(){return (await loadKnowledge()).classification;}
function knowledgeView(){return S.knowledgeView||=( {topic:localStorage.getItem('research:knowledge:topic')||'',usage:'',query:'',scope:'current',source_project:'',limit:24});}
function projectLabel(id){return (S.projectProfiles||S.knowledge?.project_profiles||S.workspace?.project_profiles||[]).find(p=>p.project===id)?.title||id||'来源未确定';}
async function openProjectUsage(usage){await selectWorkspaceProject(usage.project);await loadWorkspace();location.hash='#projects?'+new URLSearchParams({project:usage.project,view:usage.document_id?'knowledge':'progress',...(usage.document_id?{document:usage.document_id}:{})});}
async function selectKnowledgeMaterial(material){
 const project=S.project,current=await api('/api/project/canvas?project='+encodeURIComponent(project));
 await api('/api/project/canvas',{project,fingerprint:current.fingerprint,op:'attach',material:material.id?.startsWith('paper:')?material.id:'doc:'+(material.document_id||material.id),include_archived:!!material.archived&&/报告/.test(material.kind||'')});
 S.knowledge=null;if(project===S.project)await loadKnowledge();notify('已选入 '+projectLabel(project)+'，沿用同一份原稿');
}
function knowledgeFilterControls(workspace,state,draw){
 state.scope=state.scope==='archived'?'archived':'current';state.source_project='';
 const kinds=[...new Set(workspace.documents.filter(TopicNavigation.isKnowledge).map(d=>d.kind))].sort();if(!kinds.includes(state.kind))state.kind='';
 const scope=select([['current','当前知识'],['archived','已归档知识']],'资料范围');scope.value=state.scope;
 const use=select([['','全部用途'],...workspace.classification.nodes.filter(n=>n.dimension==='usage').map(n=>[n.id,topicLabel(workspace.classification,n.id)])],'用途分类');use.value=state.usage;
 const kind=select([['','全部类型'],...kinds.map(k=>[k,k])],'资料类型');kind.value=state.kind||'';
 for(const [control,name]of[[scope,'scope'],[use,'usage'],[kind,'kind']])control.onchange=()=>{state[name]=control.value;state.limit=24;draw();};
 return [use,kind,scope];
}
async function replaceWorkspaceLayer(host,draw,direction=1){
 const version=(host.layerVersion||0)+1;host.layerVersion=version;
 host.getAnimations?.().forEach(a=>a.cancel());
 const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches||!host.animate||direction===0;
 host.inert=true;
 try{
  if(host.childElementCount&&!reduced)await host.animate([{opacity:1,transform:'translateX(0) scale(1)',filter:'blur(0)'},{opacity:0,transform:`translateX(${-direction*24}px) scale(.98)`,filter:'blur(3px)'}],{duration:150,easing:'cubic-bezier(.4,0,1,1)',fill:'both'}).finished.catch(()=>{});
  if(version!==host.layerVersion||!host.isConnected)return;
  host.getAnimations?.().forEach(a=>a.cancel());draw();
  if(!reduced)await host.animate([{opacity:0,transform:`translateX(${direction*44}px) scale(.98)`,filter:'blur(3px)'},{opacity:1,transform:'translateX(0) scale(1)',filter:'blur(0)'}],{duration:340,easing:'cubic-bezier(.16,1,.3,1)'}).finished.catch(()=>{});
 }finally{if(version===host.layerVersion)host.inert=false;}
}
function knowledgeTabs(tab){return tabs([['documents','资料'],['papers','文献'],['graph','主题关系图']],tab,key=>navigate('knowledge','',key));}
function topicLabel(data,id){return TopicNavigation.path(data.nodes,id).map(n=>n.title).join(' / ');}
function rememberTopic(id){localStorage.setItem('research:knowledge:topic',id);knowledgeView().topic=id;}
function topicBreadcrumb(data,id,choose){const row=el('nav',null,'topic-breadcrumb');row.setAttribute('aria-label','主题路径');row.append(btn('全部主题',()=>choose(''),'quiet-button'));for(const n of TopicNavigation.path(data.nodes,id)){row.append(el('span','›','muted'),btn(n.title,()=>choose(n.id),'quiet-button'));}return row;}

const REVIEW_THEMES=new Set(['topic-yam','topic-thz','topic-ml','topic-starch']);

async function renderKnowledge(requested='documents'){
 if(requested==='graph'){await renderTopicGraph();return;}
 if(requested==='network'){await renderTopicGraph();return;}
 const token=S.renderToken,workspace=await loadKnowledge(),data=workspace.classification;if(token!==S.renderToken)return;S.tab=requested==='papers'?'papers':'documents';
 const state=knowledgeView();if(!data.nodes.some(n=>n.id===state.topic))state.topic='';
 const view=$('view');view.append(heading('KNOWLEDGE','全局知识','按主题查积累，保留来源项目；查看资料不会将它加入当前项目。',[btn('管理分类',()=>showClassificationManager(data),'quiet-button','settings')]),knowledgeTabs(S.tab));
 const search=searchField(S.tab==='papers'?'搜索文献、DOI 或主题':'搜索资料标题、来源项目或类型');search.input.value=state.query;
 const toolbar=el('div',null,'toolbar knowledge-toolbar');toolbar.append(search.node,...knowledgeFilterControls(workspace,state,draw));const flat=btn(state.flat?'按主题浏览':'查看全部资料',()=>{state.flat=!state.flat;flat.textContent=state.flat?'按主题浏览':'查看全部资料';draw();},'quiet-button');toolbar.append(flat);if(S.tab==='papers')toolbar.append(btn('整理题录',showPaperOrganization,'quiet-button'));view.append(toolbar);
 const selected=new Set(),bulk=btn('修改所选分类',()=>showMaterialClassification(data,[...selected]),'quiet-button');bulk.hidden=true;toolbar.append(bulk);
 const trail=el('div'),space=el('section',null,'knowledge-space');view.append(trail,space);
 async function choose(id){const previous=state.topic;state.topic=id;state.flat=false;flat.textContent='查看全部资料';state.limit=24;selected.clear();bulk.hidden=true;rememberTopic(id);const backwards=!id||TopicNavigation.path(data.nodes,previous).some(n=>n.id===id);await replaceWorkspaceLayer(space,draw,backwards?-1:1);}
 function draw(){
  trail.replaceChildren(topicBreadcrumb(data,state.topic,choose));space.replaceChildren();
  const filtered=!!(state.flat||state.kind||state.query||state.usage||state.source_project||state.scope!=='current'),all=TopicNavigation.cards(workspace,data,{...state,paperOnly:S.tab==='papers'});
  // A saved direction remains navigable before its first material is assigned.
  const children=filtered?[]:TopicNavigation.children(data.nodes,state.topic).filter(n=>n.dimension==='topic');
  const current=data.nodes.find(n=>n.id===state.topic);
  if(current&&['question','step'].includes(current.kind)){const callout=el('div',null,'knowledge-question-link');const history=current.kind==='step';callout.append(btn(history?'查看历史步骤':'打开研究问题',()=>{location.hash=projectQuestionRoute(current.project,current.question_id,history,current.step_id);},'primary','arrow'));space.append(callout);}
  const review=current&&data.reviews?.[current.id];
  if(current&&review){const excerpt=review.excerpt&&review.excerpt.startsWith(review.title)?review.excerpt.slice(review.title.length).replace(/^[ #\n]+/,''):(review.excerpt||'打开查看正文。');const box=el('section',null,'topic-review');box.append(el('span','主题综述','overline'),el('h2',review.title),el('p',excerpt,'section-subtitle'));const actions=el('div',null,'topic-review-actions');actions.append(btn('打开综述',()=>navigate('document',review.document_id),'primary','book'),btn('更换综述',()=>showTopicReviewPicker(workspace,data,current),'quiet-button','edit'));box.append(actions);space.append(box);}
  else if(current&&REVIEW_THEMES.has(current.id)){const box=el('section',null,'topic-review is-missing');box.append(el('span','主题综述','overline'),el('h2','这个主题还没有领域综述'),el('p','先写一篇覆盖当前证据、边界和阅读路径的综述，再绑定到这个主题。','section-subtitle'),btn('设置主题综述',()=>showTopicReviewPicker(workspace,data,current),'primary','plus'));space.append(box);}
  if(children.length){const grid=el('div',null,'topic-card-grid');for(const [index,node]of children.entries()){
   const card=btn('',()=>choose(node.id),'topic-entry'),count=TopicNavigation.cards(workspace,data,{...state,topic:node.id,paperOnly:S.tab==='papers'}).length,sub=TopicNavigation.children(data.nodes,node.id).filter(n=>n.dimension==='topic').length;
   card.append(el('span',node.kind==='question'?'研究问题':String(index+1).padStart(2,'0'),'overline'),el('h2',node.title),el('span',(sub?sub+' 个下级分类 · ':'')+count+' 项资料','muted'));
   if(REVIEW_THEMES.has(node.id))card.append(el('span',data.reviews?.[node.id]?'主题综述已设':'缺主题综述','topic-review-state'+(data.reviews?.[node.id]?'':' missing')));
   card.append(ic('arrow'));grid.append(card);
  }space.append(grid);}
  const rows=(filtered?all:all.filter(card=>state.topic&&[card.id,...card.notes.map(d=>'doc:'+d.id)].some(id=>data.assignments[id]?.topics.includes(state.topic)))).filter(card=>!review||card.doc?.id!==review.document_id);
  if(rows.length){space.append(el('p',filtered?rows.length+' 项匹配资料':rows.length+' 项直接归属资料','knowledge-results'));const grid=el('div',null,'material-grid');for(const card of rows.slice(0,state.limit)){
   const box=materialCard(card,data),check=el('input');check.type='checkbox';check.checked=selected.has(card.id);check.setAttribute('aria-label','选择 '+card.title);check.onchange=()=>{check.checked?selected.add(card.id):selected.delete(card.id);bulk.hidden=!selected.size;bulk.textContent='修改 '+selected.size+' 项分类';};box.prepend(check);grid.append(box);
  }space.append(grid);if(state.limit<rows.length)space.append(btn('继续显示',()=>{state.limit+=24;draw();},'quiet-button'));}
  if(!rows.length&&!children.length)space.append(empty('这个范围还没有资料','可以调整分类，或返回上一层继续找。',btn('查看全部主题',()=>choose(''),'quiet-button')));
 }
 search.input.oninput=()=>{state.query=search.input.value;state.limit=24;draw();};draw();
}

function showTopicReviewPicker(workspace,data,topic){
 const body=modal('设置主题综述 · '+topic.title),docs=(workspace.documents||[]).filter(d=>!d.archived&&d.visibility!=='system'&&d.content_role==='knowledge'&&d.global_knowledge);
 const search=searchField('搜索知识稿标题或路径'),list=el('div',null,'classification-choices');let selected=data.reviews?.[topic.id]?.document_id||'';
 function draw(){list.replaceChildren();const clear=el('label',null,'check-field'),radio=el('input');radio.type='radio';radio.name='topic-review';radio.checked=!selected;radio.onchange=()=>selected='';clear.append(radio,el('span','不设综述'));list.append(clear);const q=search.input.value.trim().toLowerCase();for(const doc of docs.filter(d=>!q||[d.title,d.display_title,d.path].join(' ').toLowerCase().includes(q))){const row=el('label',null,'check-field'),input=el('input');input.type='radio';input.name='topic-review';input.checked=selected===doc.id;input.onchange=()=>selected=doc.id;const label=doc.display_title||doc.title||'',suffix=doc.kind&&!label.endsWith(doc.kind)?' · '+doc.kind:'';row.append(input,el('span',label+suffix));list.append(row);}}
 search.input.oninput=draw;draw();
 body.append(el('p','每个顶层主题应有一篇覆盖当前证据、边界和阅读路径的综述；更换只改绑定，不改原稿。','section-subtitle'),search.node,list,
  btn('保存综述绑定',async()=>{await api('/api/knowledge/classification/change',{project:S.project,fingerprint:data.fingerprint,op:'review',id:topic.id,document_id:selected||null});dismiss();await renderRoute();notify('主题综述已保存');},'primary','check'));
}

function materialCard(card,data){
 const box=el('article',null,'material-card'),title=btn(card.title,()=>openMaterialCard(card),'material-title');box.append(title);
 const meta=el('div',null,'material-meta');meta.append(badge(card.paper?'论文资料':card.doc.kind),el('span',data.nodes.find(n=>n.id===card.assignment.usage)?.title||'待归类'));box.append(meta);
 if(card.paper){box.append(el('p',card.notes.length+' 份知识笔记 · '+(card.paper.has_original?'原文已保存':'原文待补'),'section-subtitle'));}
 else box.append(el('p',card.doc.excerpt||'打开查看正文。','section-subtitle'));
 const paths=el('div',null,'material-topics');for(const id of card.assignment.topics.slice(0,3)){const tag=btn(data.nodes.find(n=>n.id===id)?.title||'主题',()=>{rememberTopic(id);if(S.libraryView?.[S.project])S.libraryView[S.project].topic=id;navigate('knowledge');},'topic-tag');tag.title=topicLabel(data,id);paths.append(tag);}box.append(paths);
 if(card.doc)box.append(el('p','来源：'+(card.doc.source_project_title||projectLabel(card.doc.source_project))+(card.doc.source_project_archived?' · 原项目已归档':''),'material-provenance'));
 if(card.matched_notes?.length){const hits=el('div',null,'material-note-hits');for(const note of card.matched_notes)hits.append(btn('笔记 · '+docLabel(note),()=>navigate('document',note.id),'text-link'));box.append(hits);}
 const actions=el('div',null,'material-actions');actions.append(btn('打开资料',()=>openMaterialCard(card),'quiet-button','book'),btn('修改分类',()=>showMaterialClassification(data,[card.id]),'quiet-button','edit'));
 const used=(card.doc||card.paper).used_by||[];if(!used.some(p=>p.project===S.project)&&!(card.doc?.archived&&!/报告/.test(card.doc.kind)))actions.append(btn('选入当前项目',async()=>{await selectKnowledgeMaterial(card.doc||{...card.paper,id:card.id});await renderRoute();},'quiet-button','plus'));
 box.append(actions);return box;
}

function openMaterialCard(card){
 if(card.doc){dismiss();navigate('document',card.doc.id);return;}
 const body=modal(card.title);body.append(el('p','原文和知识笔记集中在同一篇论文下。','section-subtitle'),btn('打开论文与原文',()=>{dismiss();navigate('paper',card.paper.id);},'primary','book'));
 if(card.notes.length){const list=el('div',null,'list');card.notes.slice().sort((a,b)=>(a.kind==='阅读记录')-(b.kind==='阅读记录')||b.file_modified-a.file_modified).forEach(d=>list.append(docRow(d)));body.append(el('h3','知识笔记'),list);}else body.append(el('p','还没有阅读笔记，可在论文详情新建。','muted'));
}

async function showClassificationManager(data,dimension='topic'){
 const body=modal('管理分类'),bar=tabs([['topic','研究主题'],['usage','用途大类']],dimension,key=>showClassificationManager(data,key));body.append(bar,btn('新建'+(dimension==='topic'?'主题':'用途分类'),()=>showClassificationEditor(data,null,dimension),'primary','plus'));
 const list=el('div',null,'list');for(const n of data.nodes.filter(n=>n.dimension===dimension)){const row=el('div',null,'queue-row');row.append(el('span',topicLabel(data,n.id)));if(['question','step'].includes(n.kind)){const history=n.kind==='step';row.append(btn(history?'查看历史步骤':'打开研究问题',()=>{dismiss();location.hash=projectQuestionRoute(n.project,n.question_id,history,n.step_id);},'quiet-button'));}else if(!n.id.endsWith('-unassigned'))row.append(btn('修改',()=>showClassificationEditor(data,n,dimension),'quiet-button'));list.append(row);}body.append(list);
}

function showClassificationEditor(data,node,dimension='topic'){
 dimension=node?.dimension||dimension;const body=modal(node?'修改分类':'新建分类'),title=input('分类名称',node?.title||''),parent=select([['','顶层分类'],...data.nodes.filter(n=>n.dimension===dimension&&n.id!==node?.id).map(n=>[n.id,topicLabel(data,n.id)])],'上级分类');parent.value=node?.parent||'';
 const order=input('',node?.order??data.nodes.length);order.type='number';body.append(field('名称',title),field('放在谁下面',parent),field('排序位置',order));
 const submit=btn('保存分类',async()=>{let result=await api('/api/knowledge/classification/change',{project:S.project,fingerprint:data.fingerprint,op:node?'update':'create',id:node?.id,dimension,title:title.value,parent:parent.value});if(node&&Number(order.value)!==node.order)result=await api('/api/knowledge/classification/change',{project:S.project,fingerprint:result.fingerprint,op:'reorder',id:node.id,order:Number(order.value)});dismiss();await renderRoute();notify('分类已保存，资料原稿保留');},'primary');body.append(submit);
 if(node){const target=select([['','选择合并目标'],...data.nodes.filter(n=>n.dimension===dimension&&n.id!==node.id).map(n=>[n.id,topicLabel(data,n.id)])],'合并到');body.append(el('hr',null,'divider'),field('合并到现有分类',target),btn('合并分类',async()=>{await api('/api/knowledge/classification/change',{project:S.project,fingerprint:data.fingerprint,op:'merge',id:node.id,target:target.value});dismiss();await renderRoute();notify('分类已合并，资料身份保留');},'quiet-button'),btn('删除分类，保留资料',async()=>{await api('/api/knowledge/classification/change',{project:S.project,fingerprint:data.fingerprint,op:'delete',id:node.id});dismiss();await renderRoute();notify('分类已移除，资料仍可从待归类或其他主题找到');},'quiet-button'));}
}

function showMaterialClassification(data,ids){
 const body=modal('修改资料分类'),first=data.assignments[ids[0]]||{},use=select([['','保持用途不变'],...data.nodes.filter(n=>n.dimension==='usage').map(n=>[n.id,topicLabel(data,n.id)])],'用途分类');if(ids.length===1)use.value=first.usage;
 const changeTopics=el('input');changeTopics.type='checkbox';changeTopics.checked=ids.length===1;const label=el('label',null,'check-field');label.append(changeTopics,el('span','同时修改主题（下面所选主题将成为完整归属）'));body.append(field('用途：一项资料一个用途',use),label);
 const search=searchField('筛选主题'),list=el('div',null,'classification-choices'),selected=new Set(ids.length===1?first.topics:[]);body.append(search.node,list);
 function draw(){list.replaceChildren();for(const n of data.nodes.filter(n=>n.dimension==='topic'&&topicLabel(data,n.id).includes(search.input.value))){const row=el('label',null,'check-field'),check=el('input');check.type='checkbox';check.checked=selected.has(n.id);check.onchange=()=>check.checked?selected.add(n.id):selected.delete(n.id);row.append(check,el('span',topicLabel(data,n.id)));list.append(row);}}search.input.oninput=draw;draw();
 body.append(btn('保存归属',async()=>{if(!use.value&&!changeTopics.checked)throw Error('请指定需要修改的用途或主题');await api('/api/knowledge/classification/assign',{project:S.project,fingerprint:data.fingerprint,ids,...(use.value?{usage:use.value}:{}),...(changeTopics.checked?{topics:[...selected]}:{})});dismiss();await renderRoute();notify('资料分类已保存');},'primary'));
}

async function renderTopicGraph(){
 S.tab='graph';$('view').append(heading('KNOWLEDGE','关系图','跨项目查看主题、原稿引用和已有科研关系，分别保留含义与依据。',[btn('管理分类',async()=>showClassificationManager(await navigationData()),'quiet-button','settings')]),knowledgeTabs('graph'));await renderFullKnowledgeGraph();
}
