/* Read-only view of the earlier project question records. */

async function renderProjectQuestionHistory(params){
 const token=S.renderToken,project=params.get('project')||S.project,id=params.get('question'),view=$('view');
 const listURL='/api/project/questions?'+new URLSearchParams({project});
 const listing=await api(listURL);
 if(token!==S.renderToken)return;
 $('breadcrumb').textContent=projectLabel(project);
 const questions=[...listing.questions,...listing.deleted],current=questions.find(row=>row.id===id);
 const navigateTo=(question,history,step='')=>{location.hash=projectQuestionRoute(project,question,history,step);};
 const actions=[btn('返回项目总览',()=>navigateTo(current?.id||'',false),'quiet-button','back')];
 if(current)actions.push(btn('全部问题历史',()=>navigateTo('',true),'quiet-button','layers'));
 view.append(heading('研究问题历史',current?.title||'研究问题历史','只读查看原有进展、步骤、资料和记录。',actions));
 if(!current){
  if(id)view.append(el('p','该问题的历史暂未找到。','notice'));
  const list=el('div',null,'list');
  for(const row of questions)list.append(btn(row.title+(row.deleted?' · 已移除':''),()=>navigateTo(row.id,true),'list-row'));
  if(!questions.length)list.append(el('p','当前项目没有研究问题历史。','muted'));
  view.append(list);return;
 }
 const original=el('section',null,'card'),summary=el('div');
 original.append(el('h2','原有进展'),summary);
 for(const [label,value]of[['研究目标',current.goal],['当时阶段',current.phase],['当时进展',current.progress],['当时下一步',current.next_step],['解决方法',current.solution]])
  if(value)summary.append(el('h3',label),markdown(value));
 view.append(original);
 if(current.progress_records?.length){
  const rounds=el('details',null,'card');rounds.append(el('summary','连续进展记录 · '+current.progress_records.length));
  for(const record of [...current.progress_records].reverse()){
   const item=el('article');item.append(el('h3',date(record.recorded_at)),markdown(record.progress));
   if(record.next_step)item.append(el('p','当时的下一步','muted'),markdown(record.next_step));
   rounds.append(item);
  }view.append(rounds);
 }
 const plan=current.plan_document;
 if(plan?.document_id){
  const source=el('section',null,'card');source.append(el('h2','原有方案'));
  if(plan.state==='missing')source.append(el('p','方案原稿暂时找不到。','muted'));
  else source.append(btn(plan.title||'查看方案原稿',()=>navigate('document',plan.document_id),'text-link'));
  view.append(source);
 }
 if(current.references?.length){
  const sources=el('details',null,'card');sources.append(el('summary','问题资料 · '+current.references.length));
  for(const source of current.references)appendQuestionHistorySource(sources,source);
  view.append(sources);
 }
 const steps=[...(current.steps||[]),...(current.deleted_steps||[])];
 if(steps.length){
  const section=el('section',null,'card');section.append(el('h2','原有步骤'));
  for(const step of steps){
   const item=el('details');item.id='question-history-step-'+step.id;item.open=step.id===params.get('step');
   item.append(el('summary',step.title+(step.deleted?' · 已移除':'')));
   for(const value of [step.status,step.progress,step.next_step])if(value)item.append(markdown(value));
   for(const source of step.references||[])appendQuestionHistorySource(item,source);
   section.append(item);
  }view.append(section);
  document.getElementById('question-history-step-'+params.get('step'))?.scrollIntoView({block:'center'});
 }
 if(current.tasks?.length){
  const tasks=el('details',null,'card');tasks.append(el('summary','原有待办 · '+current.tasks.length));
  for(const item of current.tasks)tasks.append(el('p',(item.done?'已完成 · ':'未完成 · ')+item.text));
  view.append(tasks);
 }
 if(current.suggestions?.length){
  const suggestions=el('details',null,'card');suggestions.append(el('summary','原有建议 · '+current.suggestions.length));
  for(const item of current.suggestions)suggestions.append(el('h3',item.title),markdown(item.action));
  view.append(suggestions);
 }
 const audit=el('section',null,'card');audit.append(el('h2','工作记录'));view.append(audit);
 try{
  const result=await api('/api/project/question-history?'+new URLSearchParams({project,id}));
  if(token===S.renderToken)drawQuestionHistory(audit,result);
 }catch(error){if(token===S.renderToken)audit.append(el('p',error.message,'notice'));}
}

function appendQuestionHistorySource(host,source){
 const id=source.paper_id||source.doc_id;if(!id)return;
 const row=el('div',null,'history-event');
 row.append(btn(source.title||id,()=>navigate(source.paper_id?'paper':'document',id),'text-link'));
 for(const value of [source.step_location,source.step_purpose])if(value)row.append(el('small',value));
 host.append(row);
}

function drawQuestionHistory(host,result){
 const days=new Map();for(const event of result.events){const day=new Date(event.time).toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai'});if(!days.has(day))days.set(day,[]);days.get(day).push(event);}
 for(const [day,events]of days){const details=el('details',null,'work-day'),summary=el('summary');const titles=[...new Set(events.map(e=>e.title))];summary.append(el('strong',day),el('span',titles.slice(0,2).join('；')+(titles.length>2?' 等 '+titles.length+' 类工作':'')));details.append(summary);for(const event of events){const row=el('div',null,'history-event');row.append(el('span',event.title),el('small',event.detail||new Date(event.time).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai'})));if(event.doc_id)row.append(btn('打开原记录',()=>navigate('document',event.doc_id),'text-link'));details.append(row);}host.append(details);}
 if(!days.size)host.append(el('p','尚无单独登记的修改事件。以下是已经积累的资料，未据此推断实验完成。','muted'));
 const records=el('details');records.append(el('summary','已有工作资料 · '+result.sources.length));for(const source of result.sources)records.append(btn(source.title,()=>navigate('document',source.id),'text-link'));host.append(records);
}

