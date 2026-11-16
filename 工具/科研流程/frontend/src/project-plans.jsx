import React,{useState} from 'react';
import {Button} from './canvas-components.jsx';
import {WorkDialog} from './project-work.jsx';
import {workView,plainInline,itemsOfType} from './project-work-model.mjs';

// Plan checklists and work items share storage, with distinct immutable types.
export function ProjectPlans({data,project,bridge,onRefresh,visibleIds=null,onStage}){
 const [query,setQuery]=useState(''),[history,setHistory]=useState(false),[completion,setCompletion]=useState(''),[dialog,setDialog]=useState(null),[busy,setBusy]=useState(false),[optimistic,setOptimistic]=useState({}),[error,setError]=useState('');
 const plans=itemsOfType(data.work.items,'plan');
 const rows=visibleIds?plans.filter(r=>visibleIds.includes(r.id)):plans;
 const view=workView(rows,{query,history});
 const shown=view.filtered.filter(r=>!completion||(completion==='done'?r.done:!r.done));
 const archived=data.project_profile.archived;
 async function check(row,done){setOptimistic(old=>({...old,[row.id]:done}));setBusy(true);setError('');try{await bridge.api('/api/project-work/change',{project,op:'update',task_id:row.id,fields:{done},fingerprint:data.work.fingerprint,request_id:crypto.randomUUID(),lifecycle_revision:data.project_profile.lifecycle_revision});await onRefresh();}catch(e){setError(e.message);await onRefresh();}finally{setOptimistic({});setBusy(false);}}
 return <section className="ps-panel ps-plans" aria-label="全部计划"><header><div><h2>{visibleIds?'待归入阶段的计划':'全部计划'}</h2><p className="ps-muted">{shown.filter(r=>r.done).length}/{shown.length} 项计划已勾选完成</p></div><Button disabled={archived||busy} onClick={()=>setDialog({})}>新增计划</Button></header>
  <p className="ps-muted">写下准备做的事项，完成后勾选。具体工作的状态、下一步与执行结果，在当前工作或全部工作中管理。</p>
  <div className="ps-filters"><input aria-label="搜索计划" placeholder="搜索计划标题" value={query} onChange={e=>setQuery(e.target.value)}/><select aria-label="筛选计划完成状态" value={completion} onChange={e=>setCompletion(e.target.value)}><option value="">全部完成状态</option><option value="open">未完成</option><option value="done">已完成</option></select><label className="ps-check"><input type="checkbox" checked={history} onChange={e=>setHistory(e.target.checked)}/>包含已移除或被替代的计划</label></div>
  {error&&<p role="alert" className="cv-error">{error}</p>}
  {shown.map(row=><article className="ps-plan-row" key={row.id}><input type="checkbox" aria-label={'完成计划：'+plainInline(row.title)} checked={optimistic[row.id]??row.done} disabled={archived||busy||row.removed||!!row.replacement} onChange={e=>check(row,e.target.checked)}/><button className={'ps-plan-title'+(row.done?' done':'')} disabled={busy} onClick={()=>setDialog(row)}>{plainInline(row.title)}</button><span className="ps-muted">{row.removed?'已移除':row.replacement?'已被替代':row.stage_ids?.length?row.stage_ids.length+' 个阶段共用':'待归入阶段'}{row.due_on&&<> · <time dateTime={row.due_on}>{row.due_on}</time></>}{row.due_date_rule&&' · 日期跟随'}</span><Button disabled={busy} onClick={()=>setDialog(row)}>计划详情</Button></article>)}
  {!shown.length&&<p className="ps-muted">这里暂时没有匹配的计划。</p>}
  {dialog&&<WorkDialog key={dialog.id||'new'} noun="计划" row={dialog} data={data} project={project} bridge={bridge} onRefresh={onRefresh} onClose={()=>setDialog(null)} onMap={onStage}/>}
 </section>;
}
