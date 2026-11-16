/* Projects keep stable source identities while names and work archives can change. */
function projectHomeHash(project){return '#projects?'+new URLSearchParams({project,view:'progress'});}
async function renderProjectCollection(){
 const token=S.renderToken; $('view').append(el('p','正在读取项目列表…','loading-state'));
 const data=await api('/api/projects');if(token!==S.renderToken)return;
 updateProjectPicker({project_profiles:data.records});
 const host=$('view');host.replaceChildren();
 host.append(heading('PROJECTS','全部项目','研究各自推进，知识逐步积累。选择一个项目继续。',[btn('新建项目',showCreateProject,'primary','plus')]));
 const tools=el('div',null,'project-hub-tools'),search=input('搜索项目名称、方向或想法'),history=el('input'),historyLabel=el('label',null,'check-field');history.type='checkbox';historyLabel.append(history,el('span','包含已归档项目'));tools.append(search,historyLabel);host.append(tools);
 const cards=el('div',null,'project-hub-grid');host.append(cards);
 function draw(){cards.replaceChildren();const query=search.value.trim().toLowerCase();const records=data.records.filter(p=>(history.checked||!p.archived)&&(!query||[p.title,p.topic,p.description].join(' ').toLowerCase().includes(query)));
  for(const project of records){const card=el('article',null,'project-hub-card'),top=el('div',null,'project-hub-card-top'),mark=el('span',null,'project-hub-icon');mark.append(ic('project'));top.append(mark,badge(project.status==='CLOSED'?'已正式关闭':project.archived?'已归档':'进行中',project.archived?'':'green'));const name=btn(project.title,()=>enter(project),'project-hub-title');card.append(top,name,el('p',project.topic||'研究方向尚未填写','project-hub-topic'),el('p',project.description||'进入项目，记录阶段推进、总体设想和知识。','project-hub-description'));
    const stage=el('div',null,'project-hub-progress'),current=project.current_stage;
    stage.append(el('small','当前节点'),el('strong',current?current.title+(current.removed?' · 历史节点':''):(project.stage_count?'尚未选择当前节点':'尚未建立阶段')));
    const active=(project.current_stages||[]).filter(s=>s.id!==current?.id);
    if(active.length)stage.append(el('small',(current?'其他':'')+'进行中或受阻 · '+active.map(s=>s.title).join(' / ')));
    card.append(stage);
   const footer=el('footer');footer.append(el('small',project.stage_count+' 个阶段'+(project.recent_update?' · '+date(project.recent_update):'')),btn('项目设置',()=>showProjectProfile(project),'quiet-button','settings'),btn('进入项目',()=>enter(project),'primary','arrow'));card.append(footer);cards.append(card);}
  if(!records.length)cards.append(empty(query?'没有匹配的项目':'从第一个项目开始',query?'换一个关键词，或包含已归档项目。':'新建后从空白阶段和知识模块开始。'));
 }
 async function enter(project){await selectWorkspaceProject(project.project);location.hash='#projects?'+new URLSearchParams({project:project.project,view:'progress'});}
 search.oninput=draw;history.onchange=draw;draw();
 const old=el('details',null,'project-hub-history');old.append(el('summary','项目资料与管理历史'));
 let loaded=false;old.ontoggle=async()=>{if(!old.open||loaded)return;loaded=true;try{const value=await api('/api/project/material-history');for(const d of value.documents){const row=el('div',null,'list-row');row.append(btn(d.title,()=>navigate('document',d.id),'text-link'),el('small',({'project_reference':'背景与参考资料','project_process':'项目记录','system_record':'管理与历史资料'})[d.content_role]||'待整理资料'));old.append(row);}if(!value.documents.length)old.append(el('p','暂无其他项目资料。','muted'));}catch(e){loaded=false;old.append(el('p',e.message,'error'));}};host.append(old);
 $('connectionStatus').textContent='本机工作区已连接';for(const id of ['searchButton','createRecord','assistantButton'])$(id).disabled=false;decorateIcons();
}

async function showProjectManager(){dismiss();if(location.hash==='#projects')await renderRoute();else location.hash='#projects';}

function showCreateProject(){
 const body=modal('新建项目'),name=input('例如：品种分类、淀粉热状态研究');
 body.append(field('项目名称',name),el('p','新项目从空白进展开始，知识模块按需建立；需要的文献和共享笔记由你选择，原项目的资料与布局保留。','section-subtitle'),btn('创建并进入',async()=>{
  const created=await api('/api/project',{name:name.value});await selectWorkspaceProject(created.project);dismiss();location.hash='#projects?'+new URLSearchParams({project:created.project,view:'progress'});
 },'primary','plus'));
}

function showProjectProfile(project){
 const body=modal('管理项目 · '+project.title),title=input('',project.title),topic=input('例如：山药、太赫兹光谱',project.topic);
 const save=async(op,extra={})=>api('/api/project/profile',{project:project.project,fingerprint:project.fingerprint,op,...extra});
 const refresh=async()=>{dismiss();await loadWorkspace();await renderRoute();};
 body.append(field('项目名称',title),field('研究方向（可选）',topic),btn('保存项目名称',async()=>{await save('update',{title:title.value,topic:topic.value});await refresh();},'primary','check'));
 if(project.summary)body.append(el('p',project.summary,'notice info'));
 body.append(el('hr',null,'divider'));
 if(project.status==='CLOSED')body.append(el('p','此项目已正式关闭，原稿及结项依据保留；可以新建接续项目。','notice info'),btn('新建接续项目',showCreateProject,'quiet-button','plus'));
 else if(project.archived)body.append(el('p','自动维护已暂停。恢复后沿原设置继续，图、笔记和文献选择保持原样。','section-subtitle'),btn('恢复为进行中',async()=>{await save('restore');await refresh();},'primary','arrow'));
 else body.append(el('p','结束归档后暂停本项目的自动整理，全部原稿、研究图和文献选择保留；以后可以恢复。归档记录不改变科研核查状态。','section-subtitle'),btn('结束并归档',()=>{
  const form=modal('结束并归档 · '+project.title),summary=el('textarea');summary.rows=4;summary.maxLength=10000;
  form.append(field('结果或结束原因（可选）',summary),el('p','归档后仍可查看项目，或新建下一个项目。','section-subtitle'),btn('归档项目',async()=>{await save('archive',{summary:summary.value});await refresh();notify('项目已归档，资料与连线保留');},'primary','archive'));
 },'quiet-button','archive'));
 body.append(btn('返回项目列表',showProjectManager,'text-link'));
}
