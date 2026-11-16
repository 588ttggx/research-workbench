import React,{useEffect,useRef,useState} from 'react';
import {Button,Markdown,Pill} from './canvas-components.jsx';
import {StageDetail} from './stage-detail.jsx';
import {ProjectKnowledge} from './project-knowledge.jsx';
import {ProgressGraph} from './project-progress-graph.jsx';
import {ProjectPlans} from './project-plans.jsx';
import {WorkSection} from './project-work-section.jsx';
import {CurrentStage,ProjectRecords} from './project-records.jsx';
import {itemsOfType} from './project-work-model.mjs';
import {EditForm} from './project-forms.jsx';
import {QuestionDialog,ProjectLibrary} from './project-overview.jsx';
import './project-workspace.css';

export function ProjectWorkspace({project,bridge,setHandle,initialView='progress',initialStage='',initialDocument='',initialQuestion=''}){
 const initial=({'work':'progress','current':'progress','records':'overview','legacy-overview':'overview'})[initialView]||initialView;const [view,setView]=useState(['progress','overview','knowledge','materials'].includes(initial)?initial:'progress'),[stage,setStage]=useState(initialStage),[data,setData]=useState(null),[knowledge,setKnowledge]=useState(null),[overview,setOverview]=useState(null),[error,setError]=useState(''),[graph,setGraph]=useState(['map','progress-map'].includes(initialView)),[allPlans,setAllPlans]=useState(false),[unassignedOnly,setUnassignedOnly]=useState(false),[history,setHistory]=useState(false),[query,setQuery]=useState(''),[filter,setFilter]=useState(''),[form,setForm]=useState(null),[organizing,setOrganizing]=useState(false);
 const alive=useRef(true),drag=useRef(null),pending=useRef(new Map()),context=useRef(null);
 const [recordRequested,setRecordRequested]=useState(false);
 const needsKnowledge=view==='knowledge'||view==='overview'||!!stage||history;
 context.current={project,view,needsKnowledge,archived:data?.project_profile.archived};
 function read(section,apply){
  const path='/api/'+section+'?project='+encodeURIComponent(project);
  if(pending.current.has(path))return pending.current.get(path);
  const request=bridge.api(path).then(value=>{if(alive.current&&context.current.project===project)apply(value);return value;}).finally(()=>{if(pending.current.get(path)===request)pending.current.delete(path);});
  pending.current.set(path,request);return request;
 }
 async function refresh(){
  const requests=[read('project-entry',setData)];
  if(context.current.needsKnowledge)requests.push(read('project/knowledge',setKnowledge));
  if(context.current.view==='overview')requests.push(read('project/overview',setOverview));
  const values=await Promise.all(requests);if(alive.current)setError('');return values;
 }
 useEffect(()=>{alive.current=true;refresh().catch(e=>setError(e.message));setHandle({refresh,newRecord:()=>{
  if(context.current.archived){bridge.notify('已归档项目可查看现有记录。');return;}
  setRecordRequested(true);setView('overview');setStage('');remember('overview');
 }});return()=>{alive.current=false;setHandle(null);};},[project]);
 useEffect(()=>{
  const requests=[];
  if(needsKnowledge&&!knowledge)requests.push(read('project/knowledge',setKnowledge));
  if(view==='overview'&&!overview)requests.push(read('project/overview',setOverview));
  Promise.all(requests).catch(e=>{if(alive.current)setError(e.message);});
 },[project,view,stage,history]);
 useEffect(()=>{
  if(!initialQuestion||view!=='overview'||!data||!knowledge||!overview)return;
  const frame=requestAnimationFrame(()=>{
   const card=document.getElementById('project-question-'+initialQuestion);
   card?.scrollIntoView({block:'center'});card?.focus({preventScroll:true});
  });
  return ()=>cancelAnimationFrame(frame);
 },[initialQuestion,view,Boolean(data&&knowledge&&overview)]);
 function remember(nextView,nextStage=''){const params=new URLSearchParams({project,view:nextView});if(nextStage)params.set('stage',nextStage);window.history.replaceState(null,'','#projects?'+params);}
 function openStage(id){setView('progress');setAllPlans(false);setStage(id);remember('progress',id);}
 function chooseView(next){setView(next);setStage('');setAllPlans(false);remember(next);}
 async function organize(op,payload){if(organizing)return;setOrganizing(true);try{const progress=await bridge.api('/api/project-progress/change',{project,op,...payload,fingerprint:data.progress.fingerprint,request_id:crypto.randomUUID(),lifecycle_revision:data.project_profile.lifecycle_revision});setData(old=>({...old,progress}));return progress;}catch(e){setError(e.message);await refresh();throw e;}finally{setOrganizing(false);}}
 if(!data||(needsKnowledge&&!knowledge)||(view==='overview'&&!overview))return <div className="ps-loading">{error||'正在读取项目…'}{error&&<Button onClick={()=>refresh().catch(e=>setError(e.message))}>重新读取</Button>}</div>;
 const profile=data.project_profile,progress=data.progress,archived=profile.archived;
  const plan=data.project_overview.plan_document;
  const planOptions=[{value:'',label:'清除当前方案指定'},...(data.plan_candidates||[]).map(d=>({value:d.id,label:d.title}))];
  if(plan.document_id&&!planOptions.some(option=>option.value===plan.document_id))planOptions.push({value:plan.document_id,label:plan.title||'原方案原稿暂时不可用'});
 const byId=Object.fromEntries([...progress.stages,...progress.history].map(s=>[s.id,s]));
 const active=new Set(progress.stages.map(s=>s.id));
 const shown=s=>s&&(!query||[s.title,s.goal].join(' ').toLowerCase().includes(query.toLowerCase()))&&(!filter||s.stage_status===filter);
 function lane(ids,depth=0,seen=new Set()){
  return ids.filter(id=>active.has(id)).map(id=>{const s=byId[id];if(!s||seen.has(id))return null;const next=new Set([...seen,id]);const branches=progress.branches.filter(b=>b.anchor_stage_id===id);return <React.Fragment key={id}>{shown(s)&&<article draggable={!archived} onDragStart={e=>{drag.current={id,lane:ids};e.dataTransfer.setData('text/plain',id);}} onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();const source=drag.current;if(!source||source.lane!==ids)return;const ordered=[...ids],from=ordered.indexOf(source.id),to=ordered.indexOf(id);ordered.splice(from,1);ordered.splice(to,0,source.id);const branch=progress.branches.find(b=>b.stage_ids===ids);organize('reorder',{stage_ids:ordered,branch_id:branch?.id}).catch(()=>{});}} className={'ps-stage-card status-'+s.stage_status} style={{marginLeft:depth*28}}><span className="ps-stage-dot"/><div className="ps-stage-content"><div className="ps-inline"><button className="ps-text-link" onClick={()=>openStage(id)}>{s.title}</button><Pill status={s.stage_status}/></div><p>{s.goal||'尚未填写阶段目标'}</p><footer><span>{s.current_work_count} 项当前工作 / {s.work_count} 项工作</span><span>{s.done_count}/{s.task_count} 项计划</span><span>{s.open_problems} 个待处理问题</span><Button onClick={()=>openStage(id)}>打开阶段</Button><Button disabled={archived} onClick={()=>setForm({kind:'organize',item:s})}>调整位置</Button></footer></div></article>}{branches.map(b=><div key={b.id} className="ps-branch"><small style={{marginLeft:(depth+1)*28}}>支线</small>{lane(b.stage_ids,depth+1,next)}</div>)}</React.Fragment>;});
 }
 const planItems=itemsOfType(data.work.items,'plan');
 const unattached=planItems.filter(t=>!t.removed&&!t.replacement&&!(t.stage_ids||[]).some(id=>active.has(id)));
 const projectTasks=planItems.filter(t=>!t.removed&&!t.replacement);
 return <div className="ps-workspace">
  <header className="ps-workspace-heading"><div><button className="ps-breadcrumb" onClick={bridge.projects}>全部项目 <span> / </span></button><h1>{profile.title}</h1><p>{profile.topic||'阶段推进与知识积累'}</p></div><div className="ps-actions"><Button onClick={()=>bridge.openProjectChanges?.(project)}>项目变化</Button><Button onClick={()=>bridge.manageProject?.(profile)}>项目设置</Button></div></header>
  <nav className="ps-tabs" aria-label="项目入口">{[['progress','进展'],['overview','总览'],['knowledge','项目知识库'],['materials','项目资料']].map(([id,label])=><button key={id} aria-current={view===id?'page':undefined} className={view===id?'active':''} onClick={()=>chooseView(id)}>{label}</button>)}</nav>
  {view==='progress'&&bridge.openProjectArea&&<div className="ps-actions" aria-label="当前项目的实验、分析和产出">{[['lab','实验'],['analyze','分析'],['outputs','产出']].map(([route,label])=><Button key={route} onClick={()=>bridge.openProjectArea(route)}>{label}</Button>)}</div>}
  {archived&&<div className="ps-warning">项目已归档，当前只读；原记录与自动化偏好保留。<Button onClick={()=>bridge.manageProject?.(profile)}>查看项目设置</Button></div>}
  {error&&<div className="ps-warning" role="alert">{error}<Button onClick={()=>refresh().then(()=>setError('')).catch(e=>setError(e.message))}>重新读取</Button></div>}
  {view==='progress'&&(stage?<StageDetail key={stage} project={project} id={stage} bridge={bridge} knowledge={knowledge} entry={data} onBack={()=>{setStage('');remember('progress');refresh().catch(e=>setError(e.message));}} onSaved={refresh} onCurrent={id=>organize('set_current',{stage_id:id}).catch(()=>{})}/>:<>
   <div className="ps-progress-toolbar"><div><h2>研究进展</h2><p>{progress.stages.length} 个阶段 · {projectTasks.filter(t=>t.done).length}/{projectTasks.length} 项计划已完成</p></div><div className="ps-actions"><Button onClick={()=>{setAllPlans(!allPlans);setUnassignedOnly(false);}}>{allPlans?'返回阶段':'全部计划'}</Button><Button onClick={()=>{setAllPlans(true);setUnassignedOnly(true);setFilter('');}}>待归入阶段 · {unattached.length}</Button><Button onClick={()=>setGraph(!graph)}>{graph?'阶段列表':'进展关系图'}</Button><Button onClick={()=>setHistory(!history)}>{history?'收起记录':'项目记录'}</Button></div></div>
   <CurrentStage progress={progress} archived={archived} onOpen={openStage} onChange={id=>organize('set_current',{stage_id:id}).catch(()=>{})}/>
   <WorkSection data={data} project={project} bridge={bridge} onRefresh={refresh}/>
   {allPlans?<><p className="ps-muted">准备做的事项集中列在这里，具体工作在上方独立管理。待归入阶段 {unattached.length} 项。</p><ProjectPlans data={data} visibleIds={unassignedOnly?unattached.map(t=>t.id):null} project={project} bridge={bridge} onRefresh={refresh} onStage={id=>{const task=projectTasks.find(t=>t.id===id),target=task?.stage_ids?.find(s=>active.has(s));if(target)openStage(target);else bridge.notify("这项计划尚未归入阶段，可在阶段详情中关联。",false);}}/></>:<div className="ps-progress-layout"><div className="ps-progress-main"><div className="ps-filters"><input aria-label="搜索阶段" placeholder="搜索阶段名称或目标" value={query} onChange={e=>setQuery(e.target.value)}/><select aria-label="筛选阶段状态" value={filter} onChange={e=>setFilter(e.target.value)}><option value="">全部阶段状态</option>{['未开始','进行中','受阻','暂缓','已完成'].map(s=><option key={s}>{s}</option>)}</select></div>
    {graph?<ProgressGraph project={project} progress={progress} bridge={bridge} onOpen={openStage} onChange={organize} archived={archived}/>:<div className="ps-timeline">{lane(progress.mainline)}{progress.branches.filter(b=>!active.has(b.anchor_stage_id)&&b.stage_ids.some(id=>active.has(id))).map(b=><section key={b.id}><p className="ps-muted">支线 · 原锚点已移除</p>{lane(b.stage_ids)}</section>)}{!progress.stages.length&&<div className="ps-empty"><span className="ps-empty-symbol">＋</span><h3>从一个研究阶段开始</h3><p>写下阶段名称和目标。计划、问题和记录随后逐步积累。</p></div>}{progress.stages.length>0&&!progress.stages.some(shown)&&<div className="ps-empty">没有匹配阶段。<Button onClick={()=>{setQuery('');setFilter('');}}>清空筛选</Button></div>}</div>}
   </div><NewStagePanel project={project} bridge={bridge} progress={progress} archived={archived} onCreated={async id=>{await refresh();openStage(id);}}/></div>}
   {history&&<ProjectRecords project={project} data={data} knowledge={knowledge} bridge={bridge} onOpen={openStage} onRefresh={refresh}/>}
  </>)}
   {view==='materials'&&<ProjectLibrary project={project} bridge={bridge} archived={archived} lifecycleRevision={profile.lifecycle_revision}/>}{view==='overview'&&<div className="ps-overview"><section className="ps-panel"><header><h2>总想法</h2><Button disabled={archived} onClick={()=>setForm({kind:'overview',section:'总想法'})}>编辑总想法</Button></header><Markdown body={overview.sections['总想法']||'写下这个项目的总体设想。'} bridge={bridge}/></section><section className="ps-panel"><header><h2>研究目标</h2><Button disabled={archived} onClick={()=>setForm({kind:'overview',section:'研究目标'})}>编辑研究目标</Button></header><Markdown body={overview.sections['研究目标']||'写下希望回答的问题与目标。'} bridge={bridge}/></section>
    <section className="ps-panel" aria-label="项目目标与方案"><header><h2>当前方案</h2><Button disabled={archived} onClick={()=>setForm({kind:'plan'})}>选择或更换方案</Button></header><CurrentPlan project={project} plan={plan} bridge={bridge} archived={archived}/></section>
   <section className="ps-panel"><h2>阶段概况</h2>{progress.stages.map(s=><div key={s.id} className="ps-reference"><Button onClick={()=>openStage(s.id)}>{s.title}</Button><Pill status={s.stage_status}/><span>{s.open_problems} 个待处理问题</span></div>)}{!progress.stages.length&&<p>尚无阶段。</p>}</section>
    <section className="ps-panel"><h2>项目背景</h2><Button disabled={archived||!data.project_overview.state_document?.document_id} onClick={()=>bridge.editDocument(data.project_overview.state_document.document_id)}>编辑项目背景</Button><details><summary>查看完整项目背景</summary><Markdown body={overview.body} bridge={bridge}/></details></section>
    <section className="ps-panel" aria-label="研究问题"><header><h2>研究问题</h2><div className="ps-actions"><Button onClick={()=>bridge.openQuestionHistory()}>研究问题历史</Button><Button disabled={archived} onClick={()=>setForm({kind:'question'})}>新增研究问题</Button></div></header>{data.project_overview.questions.map(q=><article className="ps-record" key={q.id} id={'project-question-'+q.id} tabIndex={-1}><header><strong>{q.title}</strong><Button disabled={archived} onClick={()=>setForm({kind:'question',item:q})}>编辑解决方法</Button></header><Markdown body={q.goal||''} bridge={bridge}/>{q.solution&&<><h3>解决方法</h3><Markdown body={q.solution} bridge={bridge}/></>}<div className="ps-actions">{q.document_id&&<Button onClick={()=>bridge.openDocument(q.document_id)}>查看问题原稿</Button>}<Button onClick={()=>bridge.openQuestionHistory(q.id)}>查看问题历史</Button><a href={'#knowledge?'+new URLSearchParams({tab:'graph',compare_project:project,compare_question:q.id})}>比对原文</a></div></article>)}</section>
   <ProjectRecords project={project} data={data} bridge={bridge} onRefresh={refresh} requested={recordRequested} onRequestClosed={()=>setRecordRequested(false)}/>
  </div>}
  {view==='knowledge'&&<ProjectKnowledge project={project} bridge={bridge} data={knowledge} onRefresh={refresh} archived={archived} focusDocument={initialDocument}/>}
  {form?.kind==='question'&&<QuestionDialog project={project} question={form.item} fingerprint={data.project_overview.mainlines_fingerprint} bridge={bridge} lifecycleRevision={profile.lifecycle_revision} onSave={async payload=>{await bridge.api('/api/project/question-save',payload);await refresh();}} onClose={()=>setForm(null)}/>}
  {form?.kind==='overview'&&<EditForm project={project} id={'overview:'+form.section} title={'编辑'+form.section} version={overview.fingerprint} latestBody={overview.sections[form.section]||''} initial={{body:overview.sections[form.section]||''}} fields={[{name:'body',label:form.section,rows:12}]} bridge={bridge} onClose={()=>setForm(null)} onSubmit={async(v)=>{await bridge.api('/api/project/overview',{project,fingerprint:v.__fingerprint,sections:{[form.section]:v.body}});await refresh();}}/>}
   {form?.kind==='plan'&&<EditForm project={project} id="project-plan" title="项目当前方案" version={profile.fingerprint} initial={{document_id:profile.plan_document_id||''}} fields={[{name:'document_id',label:'方案原稿',type:'select',options:planOptions}]} onClose={()=>setForm(null)} onSubmit={async(v)=>{if((v.document_id||null)===(profile.plan_document_id||null))return;await bridge.api('/api/project/profile',{project,op:'update',fingerprint:v.__fingerprint,plan_document_id:v.document_id||null});await refresh();}}/>}
  {form?.kind==='organize'&&<EditForm project={project} id={'organize:'+form.item.id} title="调整阶段位置" initial={{anchor:''}} fields={[{name:'anchor',label:'位置',type:'select',options:[{value:'',label:'移到主线末尾'},...progress.stages.filter(s=>s.id!==form.item.id).map(s=>({value:s.id,label:'作为「'+s.title+'」的支线'}))]}]} onClose={()=>setForm(null)} onSubmit={v=>organize(v.anchor?'branch':'move_mainline',{stage_ids:[form.item.id],anchor_stage_id:v.anchor})}/>}
 </div>;
}

function CurrentPlan({project,plan,bridge,archived}){
 if(plan.state==='missing')return <p>方案原稿暂时找不到，可选择其他方案。</p>;
 if(plan.state==='unspecified')return <p>尚未指定方案，可以选择本项目已有资料。</p>;
 const status=plan.state==='archived'?'方案已归档':plan.state==='out_of_scope'?'方案已退出本项目选用':'';
 const editable=plan.state==='active'&&!archived&&plan.path?.startsWith('科研知识库/项目/'+project+'/');
 return <div className="ps-inline"><Button onClick={()=>bridge.openDocument(plan.document_id)}>{plan.title||'查看方案原稿'}</Button>{status&&<span className="ps-muted">{status}</span>}{editable&&<Button onClick={()=>bridge.editDocument(plan.document_id)}>编辑方案</Button>}</div>;
}

function NewStagePanel({project,bridge,progress,archived,onCreated}){
 const key='research:new-stage:'+project;
 const [value,setValue]=useState(()=>{try{return JSON.parse(localStorage.getItem(key))||{title:'',goal:'',anchor:''};}catch{return {title:'',goal:'',anchor:''};}}),[draft,setDraft]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[generating,setGenerating]=useState(false),[mobileOpen,setMobileOpen]=useState(false);
 const [chosenDraft,setChosenDraft]=useState(null);
 const request=useRef(crypto.randomUUID()),anchor=useRef(value.anchor),draftGeneration=useRef(0);
 function clearDraft(){draftGeneration.current++;setDraft(null);setChosenDraft(null);request.current=crypto.randomUUID();}
 function update(name,next){
  if(name==='anchor'&&anchor.current!==next){anchor.current=next;clearDraft();}
  setValue(old=>{const v={...old,[name]:next};localStorage.setItem(key,JSON.stringify(v));return v;});request.current=crypto.randomUUID();
 }
 async function generateDraft(){
  const source=anchor.current, generation=++draftGeneration.current;
  setGenerating(true);setError('');
  try{
   const result=await bridge.api('/api/project-progress/propose',{project,stage_id:source||undefined});
   if(draftGeneration.current===generation)setDraft({result,source});
  }catch(e){if(draftGeneration.current===generation)setError(e.message);}
  finally{setGenerating(false);}
 }
 async function create(){if(busy)return;setBusy(true);setError('');try{const result=await bridge.api('/api/project-stage/change',{project,op:'create',title:value.title,goal:value.goal,fingerprint:progress.fingerprint,request_id:request.current,lifecycle_revision:progress.lifecycle_revision,...(chosenDraft?{draft_id:chosenDraft.result.id,draft_stage_id:chosenDraft.source||undefined}:{})});
   if(value.anchor){try{const current=await bridge.api('/api/project-progress?project='+encodeURIComponent(project));await bridge.api('/api/project-progress/change',{project,op:'branch',anchor_stage_id:value.anchor,stage_ids:[result.id],fingerprint:current.fingerprint,request_id:'branch-'+result.id,lifecycle_revision:progress.lifecycle_revision});}catch(e){bridge.notify('阶段已保存，支线设置未完成：'+e.message,true);}}
   localStorage.removeItem(key);anchor.current='';setValue({title:'',goal:'',anchor:''});clearDraft();await onCreated(result.id);
  }catch(e){setError(e.message);}finally{setBusy(false);}}
 return <aside className={"ps-new-stage"+(mobileOpen?" is-open":"")} aria-label="新增节点">
  <Button className="ps-mobile-new" onClick={()=>setMobileOpen(!mobileOpen)}>{mobileOpen?"收起新增阶段":"＋ 新增阶段或查看建议"}</Button>
  <div className="ps-new-stage-body"><small>继续推进</small><h2>新增阶段</h2><p>自己填写，或先看看下一步建议。</p>
   <label className="cv-field">阶段名称<input aria-label="新阶段名称" value={value.title} maxLength={200} onChange={e=>update('title',e.target.value)}/></label>
   <label className="cv-field">阶段目标<textarea aria-label="新阶段目标" rows={4} value={value.goal} onChange={e=>update('goal',e.target.value)}/></label>
   <label className="cv-field">放在哪里<select aria-label="新阶段位置" value={value.anchor} onChange={e=>update('anchor',e.target.value)}><option value="">主线末尾</option>{progress.stages.map(s=><option key={s.id} value={s.id}>「{s.title}」的支线</option>)}</select></label>
   <Button variant="primary" disabled={archived||busy||!value.title.trim()} onClick={create}>{busy?'正在建立…':'建立阶段'}</Button><hr/>
   <Button disabled={archived||generating} onClick={generateDraft}>{generating?'正在生成建议…':'生成扩展建议'}</Button>
   <p className="ps-muted">选择候选后仅带入名称与目标，计划随后自己填写。</p>
   {(draft||chosenDraft)&&<details className="ps-muted"><summary>建议使用的来源</summary>{(chosenDraft||draft).result.sources.map(s=><p key={s.id}>{s.title}</p>)}<Button onClick={clearDraft}>清除建议，手动创建</Button></details>}
   {draft?.result.candidates.map((c,i)=><article className="ps-suggestion" key={i}><strong>{c.title}</strong><p>{c.goal}</p><small>{c.reason}</small><Button disabled={archived||busy} onClick={()=>{setChosenDraft(draft);update('title',c.title);update('goal',c.goal);}}>选用并填写</Button></article>)}
   {error&&<p className="cv-error" role="alert">{error}</p>}
  </div>
 </aside>;
}
