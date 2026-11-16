'use strict';

// Edit the files actually loaded by the assistant; no parallel prompt copies.
async function showSkillsManager(){
 const catalog=await api('/api/skills/manage'),body=modal('技能与规则');
 $('overlay').classList.add('skills-dialog');
 body.append(el('p','选择一个技能来设置使用范围或更新内容。任务规则可在同一处编辑。','section-subtitle'));
 const top=el('div',null,'toolbar'),search=searchField('搜索技能或任务规则'),create=btn('新建科研技能',()=>{if(canLeave())showNewResearchSkill();},'primary','plus');top.append(search.node,create);body.append(top);
 const layout=el('div',null,'skills-layout'),list=el('nav',null,'skills-list'),editor=el('section',null,'skills-editor');list.setAttribute('aria-label','技能与任务规则');layout.append(list,editor);body.append(layout);
 let selected=null,dirty=false,loadNumber=0,error=null;
 const entries=[...(catalog.skills||[]).map(row=>({...row,file:'SKILL.md',kind:'skill'})),...(catalog.rules||[]).map(row=>({...row,id:row.id||'rules',kind:'rule'}))];
 function canLeave(){if(!dirty)return true;if(error)error.textContent='有未保存的修改，请先保存或取消修改。';return false;}
 function drawList(){list.replaceChildren();const query=search.input.value.toLowerCase();
  for(const [kind,label] of [['skill','科研技能'],['rule','AI 任务规则']]){
   const rows=entries.filter(row=>row.kind===kind&&[row.label,row.description,row.id,row.file,...(row.used_by||[])].join(' ').toLowerCase().includes(query));
   if(!rows.length)continue;list.append(el('h3',label));
   for(const row of rows){const button=btn('',()=>{if(canLeave())return open(row.id,row.file);},'skill-entry'+(selected?.id===row.id&&selected.file===row.file?' active':''));
    const usage=row.usage;
    const status=usage?'外部 '+(usage.external?'开':'关')+' · 看板 '+(usage.dashboard_available?(usage.dashboard?'开':'关'):'未接入'):'待检查';
    button.append(el('strong',row.label||row.title||row.id),el('small',kind==='rule'?(row.used_by||['按对应任务加载']).join('、'):status));
    list.append(button);
   }
  }
  if(!list.childElementCount)list.append(el('p','没有匹配的技能或规则。','muted'));
 }
 async function open(id,file){
  const token=++loadNumber;editor.replaceChildren(el('p','正在打开实际文件…','muted'));
  const detail=await api('/api/skills/detail?id='+encodeURIComponent(id)+'&file='+encodeURIComponent(file));if(token!==loadNumber)return;
  const entry=entries.find(row=>row.id===id&&row.kind==='skill');
  if(entry)Object.assign(entry,{label:detail.label,description:detail.description,usage:detail.usage});
  selected=detail;selected.id=id;selected.file=file;dirty=false;drawList();editor.replaceChildren();
  const isCurrent=()=>editor.isConnected!==false&&$('overlay').open!==false&&token===loadNumber&&selected?.id===id&&selected.file===file;
  const isSkill=id!=='rules';
  const header=el('div',null,'skills-editor-heading'),copy=el('div'),source=el('p',detail.source_path||file,'skill-source');
  copy.append(el('h3',detail.title||detail.label||id),source);
  const files=detail.files||[{path:file,label:file}],picker=select(files.map(row=>[typeof row==='string'?row:row.path,typeof row==='string'?row:row.label||row.path]),'编辑技能文件');picker.value=file;
  picker.onchange=()=>{if(canLeave())open(id,picker.value).catch(e=>notify(e.message,true));else picker.value=file;};
  header.append(copy,picker);editor.append(header);
  if(detail.notice)editor.append(el('p',detail.notice,'notice info'));
  const currentError=el('p',null,'skills-error');currentError.setAttribute('role','alert');error=currentError;
  if(isSkill&&detail.usage){
   const scope=el('section',null,'skills-usage');
   scope.append(el('h4','使用范围'));
   let switching=false;
   const buttons=new Map();
   function drawUsage(){
    for(const [channel,button] of buttons){
     const available=channel!=='dashboard'||detail.usage.dashboard_available;
     button.setAttribute('aria-checked',String(detail.usage[channel]));
     button.disabled=switching||!available;
     button.textContent=button.title+' · '+(available?(detail.usage[channel]?'开启':'关闭'):'未接入');
    }
   }
   for(const [channel,label] of [['external','外部 AI'],['dashboard','看板内置 AI']]){
    const control=btn(label,async()=>{
     if(switching||!isCurrent())return;
     switching=true;drawUsage();currentError.textContent='';
     try{
      const expected=detail.usage[channel];
      const saved=await api('/api/skills/usage',{id,channel,enabled:!expected,expected});
      if(!isCurrent())return;
      detail.usage=saved.usage;
      if(file==='SKILL.md')source.textContent=saved.source_path||file;
      const item=entries.find(row=>row.id===id);
      if(item)item.usage=saved.usage;
      drawList();
     }catch(e){if(isCurrent())currentError.textContent=e.message;}
     finally{switching=false;if(isCurrent())drawUsage();}
    },'quiet-button');
    control.title=label;control.setAttribute('role','switch');control.setAttribute('aria-label',label);
    buttons.set(channel,control);
   }
   const toggles=el('div',null,'toolbar');toggles.append(...buttons.values());
   scope.append(toggles,el('p','外部助手重新加载项目时读取开关。看板开关用于研究工具和对应的后台技能分析。','section-subtitle'));
   drawUsage();editor.append(scope);
  }
  if(id==='rules'){
   const scope=el('div',null,'notice info');
   if(detail.used_by?.length)scope.append(el('p','用于：'+detail.used_by.join('、')));
   if(detail.audiences?.length)scope.append(el('p','执行者：'+detail.audiences.join('、')));
   if(detail.effect)scope.append(el('p',detail.effect));
   if(detail.reprocessing)scope.append(el('p',detail.reprocessing));
   if(detail.version)scope.append(el('p','当前版本：'+detail.version));
   editor.append(scope);
  }
  editor.append(el('p',id==='rules'?'共用规则在各任务中使用，任务规则仅在对应任务中加载。':'编辑下方原稿或导入 Markdown。保存后新调用使用新版。','section-subtitle'));
  const textarea=el('textarea',null,'skill-content');textarea.value=detail.content||'';textarea.spellcheck=false;textarea.setAttribute('aria-label','技能或规则正文');textarea.readOnly=detail.editable===false;
  const state=el('span',detail.version?'当前版本 '+detail.version:'已读取原文件','muted');state.setAttribute('aria-live','polite');
  const changes=el('section',null,'skills-update-preview');changes.hidden=true;
  let reviewed=null,saving=false;
  function refreshSave(){save.disabled=detail.editable===false||saving||(isSkill&&(!reviewed||reviewed.content!==textarea.value||reviewed.fingerprint!==detail.fingerprint));}
  function changed(){
   dirty=textarea.value!==detail.content;reviewed=null;changes.hidden=true;
   state.textContent=dirty?'有未保存修改':detail.version?'当前版本 '+detail.version:'已读取原文件';refreshSave();
  }
  textarea.oninput=changed;
  if(isSkill){
   const upload=el('input');upload.type='file';upload.accept='.md,.markdown,text/markdown';upload.disabled=detail.editable===false;
   upload.onchange=async()=>{
    const incoming=upload.files?.[0];upload.value='';
    if(!incoming||!canLeave())return;
    const previous=textarea.value;
    try{
     if(incoming.size>200000)throw Error('请导入最多 48000 字符的 Markdown。');
     const content=(await incoming.text()).replace(/^\uFEFF/,'').replace(/\r\n/g,'\n');
     if(!isCurrent()||textarea.value!==previous)return;
     if(!content.trim()||content.length>48000||content.includes('\0'))throw Error('请导入有效的 Markdown，最多 48000 字符。');
     textarea.value=content;changed();currentError.textContent='';
    }catch(e){if(isCurrent())currentError.textContent=e.message;}
   };
   editor.append(field('导入新版 Markdown',upload));
  }
  editor.append(textarea,currentError,changes);
  const actions=el('div',null,'form-actions'),save=btn(isSkill?'保存此技能更新':'保存修改',async()=>{
   if(save.disabled)return;
   saving=true;refreshSave();currentError.textContent='';const submitted=textarea.value;
   try{const saved=await api('/api/skills/save',{id,file,content:submitted,fingerprint:detail.fingerprint});if(!isCurrent())return;
    if(textarea.value!==submitted){detail.content=saved.content;detail.fingerprint=saved.fingerprint;detail.version=saved.version;changed();state.textContent='上一稿已保存；当前修改尚未保存';return;}
    dirty=false;await open(id,file);notify('已保存到实际文件，下次使用时加载。');}
   catch(e){if(isCurrent()){currentError.textContent=e.message;reviewed=null;}}
   finally{saving=false;if(isCurrent())refreshSave();}
  },'primary','check');
  refreshSave();
  if(isSkill)actions.append(btn('对照更新',async()=>{
   if(saving||detail.editable===false)return;
   currentError.textContent='';const content=textarea.value,fingerprint=detail.fingerprint;
   try{
    const preview=await api('/api/skills/preview',{id,file,content,fingerprint});
    if(!isCurrent()||textarea.value!==content||detail.fingerprint!==preview.fingerprint)return;
    reviewed=preview.diff?{content,fingerprint}:null;
    changes.replaceChildren(el('h4','本次改动'),el(preview.diff?'pre':'p',preview.diff||'与当前版本一致。'));
    changes.hidden=false;refreshSave();
   }catch(e){if(isCurrent())currentError.textContent=e.message;}
  },'quiet-button'));
  const cancel=btn('取消修改',()=>{textarea.value=detail.content||'';changed();state.textContent='已取消修改';currentError.textContent='';},'quiet-button');
  actions.append(save,cancel,btn('修改历史',()=>showHistory(id,file),'quiet-button','clock'),state);editor.append(actions);
  const history=el('div',null,'skills-history');history.hidden=true;editor.append(history);
  async function showHistory(skillId,sourceFile){
   const data=await api('/api/skills/history?id='+encodeURIComponent(skillId)+'&file='+encodeURIComponent(sourceFile));if(!isCurrent())return;history.replaceChildren(el('h4','历史版本'));history.hidden=false;
   for(const version of data.versions||[]){const row=el('div',null,'history-row');row.append(el('span',date(version.time||version.created)),btn('加载这个版本',async()=>{
    if(!canLeave())return;const before=textarea.value,previous=await api('/api/skills/version?id='+encodeURIComponent(skillId)+'&file='+encodeURIComponent(sourceFile)+'&version='+encodeURIComponent(version.id));
    if(!isCurrent())return;if(textarea.value!==before){currentError.textContent='加载期间已有新修改，已保留当前内容。';return;}
    textarea.value=previous.content;changed();state.textContent='历史版本已载入，保存后才替换当前文件';history.hidden=true;
   },'quiet-button'));history.append(row);}
   if(!data.versions?.length)history.append(el('p','还没有保存过的旧版本。','muted'));
  }
 }
 search.input.oninput=drawList;drawList();editor.append(empty('选择一份技能或规则','可以查看和编辑实际内容，也可以新增自己的科研技能。'));
}

function showNewResearchSkill(){
 const body=modal('新建科研技能');$('overlay').classList.add('skills-dialog');
 body.append(el('p','写下适用任务、方法和输出要求。新增后在“研究工具”中手动选择，不会自动接管普通聊天。','section-subtitle'));
 const id=input('例如 spectral-comparison'),label=input('例如 光谱比较方法'),description=el('textarea'),content=el('textarea',null,'skill-content');description.rows=2;content.rows=12;
 content.placeholder='说明这个技能适用于什么问题，如何分析材料，以及希望得到怎样的输出。';
 body.append(field('技能标识（英文小写与连字符）',id),field('技能名称',label),field('什么时候使用',description),field('技能说明',content));
 const error=el('p',null,'skills-error');error.setAttribute('role','alert');body.append(error);
 const create=btn('创建技能',async()=>{create.disabled=true;error.textContent='';try{await api('/api/skills/create',{id:id.value.trim(),label:label.value.trim(),description:description.value.trim(),content:content.value});await showSkillsManager();notify('科研技能已创建，可以在研究工具中选用。');}catch(e){error.textContent=e.message;}finally{create.disabled=false;}},'primary','plus');
 body.append(create,btn('取消',showSkillsManager,'quiet-button'));
}
