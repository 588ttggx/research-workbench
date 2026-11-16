import React,{useState} from 'react';
import {Button} from './canvas-components.jsx';
import {DecisionDialog} from './project-overview.jsx';

export function CurrentStage({progress,archived,onOpen,onChange}){
 const current=[...progress.stages,...progress.history].find(s=>s.id===progress.current_stage_id);
 return <section className="ps-current-stage ps-panel" aria-label="当前节点"><header><div><small>当前节点</small><h3>{current?current.title:'尚未选择当前节点'}</h3>{current&&<p>{current.removed?'该节点已移除，可查看历史或重新选择。':current.goal}</p>}</div><div className="ps-actions">{current&&<Button onClick={()=>onOpen(current.id)}>打开当前节点</Button>}<label>选择当前节点<select aria-label="选择当前节点" disabled={archived} value={current?.removed?'':progress.current_stage_id||''} onChange={e=>onChange(e.target.value||null)}><option value="">尚未选择</option>{progress.stages.map(s=><option key={s.id} value={s.id}>{s.title}</option>)}</select></label></div></header>{!progress.stages.length&&<p className="ps-muted">先在右侧建立阶段，再选择当前节点。原有工作可继续使用并关联到新阶段。</p>}</section>;
}

export function ProjectRecords({project,data,bridge,onRefresh,requested=false,onRequestClosed}){
 const [editing,setEditing]=useState(null);
 return <section className="ps-panel" aria-label="项目记录"><header><h2>项目记录</h2><Button disabled={data.project_profile.archived} onClick={()=>setEditing({})}>新增项目记录</Button></header>
  {data.decisions.map(d=><article className="ps-record" key={d.id}><header><strong>{d.data.title}</strong></header><div className="ps-actions"><Button onClick={()=>bridge.openDocument(d.document_id)}>打开原稿</Button><Button disabled={data.project_profile.archived} onClick={()=>setEditing(d)}>编辑记录</Button></div></article>)}
  {(editing||requested&&!data.project_profile.archived)&&<DecisionDialog project={project} node={editing?.id?editing:null} bridge={bridge} onRefresh={onRefresh} onClose={()=>{setEditing(null);onRequestClosed?.();}}/>}
 </section>;
}
