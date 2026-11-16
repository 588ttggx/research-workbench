import React,{useState,useRef} from 'react';
import {Button,Modal} from './canvas-components.jsx';
import {statuses,workView,blockedBy,plainInline,itemsOfType,workForm,workFields,rebaseWorkForm} from './project-work-model.mjs';

const workFieldLabels={title:'标题',status:'状态',kind:'类型',next_step:'下一步',execution_notes:'执行过程与结果',due_on:'日期',due_date_rule:'日期跟随规则',question_id:'关联问题',depends_on:'依赖',references:'资料引用',stage_ids:'关联阶段'};

export function ProjectWork({data,project,bridge,onRefresh,compact=false,onAll,onMap,question='',onQuestion,visibleIds=null,stageId=''}){
 const work=data.work,rows=itemsOfType(work.items,'work',stageId),archived=data.project_profile.archived;
 const [dialog,setDialog]=useState(null),[query,setQuery]=useState(''),[kind,setKind]=useState(''),[history,setHistory]=useState(false),[columns,setColumns]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const inFlight=useRef(false);
 async function change(op,task_id,fields){if(inFlight.current)return;inFlight.current=true;setBusy(true);setError('');try{
  await bridge.api('/api/project-work/change',{project,op,task_id,fields,fingerprint:work.fingerprint,request_id:crypto.randomUUID(),lifecycle_revision:data.project_profile.lifecycle_revision});await onRefresh();
 }catch(e){setError(e.message);}finally{inFlight.current=false;setBusy(false);}}
 const view=workView(visibleIds?rows.filter(r=>visibleIds.includes(r.id)):rows,{compact,history,kind,question,query});const shown=view.shown;
 const questions=data.project_overview.questions||[];
 const filtering=!!(query||kind||history||(question&&question!==''));
 const statText=Object.entries(view.stats).map(([s,n])=>s+' '+n).join(' · ');
 function reset(){setQuery('');setKind('');setHistory(false);onQuestion?.('');}
 function open(row){setDialog(row);}
 function rowLine(row){
  const blocked=blockedBy(row,data.work.items);const waiting=row.status==='等待';
  return <article key={row.id} className={'pw-row'+(row.removed?' removed':'')+(row.replacement?' replaced':'')}>
   <button className="pw-row-title" title={row.title} onClick={()=>open(row)}>{plainInline(row.title)}</button>
   {row.kind&&<small className="pw-tag">{plainInline(row.kind)}</small>}
   {row.due_on&&<small className="pw-tag">{row.due_on}</small>}
   {row.pin_rank!=null&&<small className="pw-tag">置顶</small>}
   {row.removed&&<small className="pw-tag">已移除</small>}
   {row.replacement&&<small className="pw-tag">已被{row.replacement.kind==='split'?'拆分':'合并'}</small>}
   <span className="pw-row-next">{row.next_step?<>{waiting?'等待：':'下一步：'}{plainInline(row.next_step)}</>:''}</span>
   {stageId&&<Button disabled={archived||busy} onClick={()=>change('update',row.id,{stage_ids:row.stage_ids.filter(id=>id!==stageId)})}>移出本节点</Button>}
   {!!blocked.length&&<span className="pw-row-blocked">待解决：{blocked.map(r=>plainInline(r.title)).join('、')}</span>}
   <span className="pw-row-actions">
    <select className={'pw-status s-'+(statuses.indexOf(row.status)+1)} aria-label={'修改状态：'+row.title} disabled={archived||busy||row.removed||row.replacement} value={row.status} onChange={e=>change('update',row.id,{status:e.target.value})}>{statuses.map(s=><option key={s}>{s}</option>)}</select>
    <Button onClick={()=>open(row)}>详情</Button>
   </span>
  </article>;}
 function card(row){return rowLine(row);}
 return <section className="pw-work" aria-label={compact?'当前工作':'全部工作'}>
  <header><div><h2>{compact?'当前工作':'全部工作'}</h2>
   {compact?<p>共 {view.scope} 项未完成{view.hidden?` · 显示前 ${shown.length} 项`:''}{view.completed?` · ${view.completed} 项已完成`:''}</p>:<p>{statText} · 共 {view.total} 项{history&&view.historyShown?`（含 ${view.historyShown} 项历史记录）`:''}</p>}</div>
   <div><Button disabled={archived} onClick={()=>setDialog({})}>新建工作</Button>{compact&&onAll&&<Button onClick={onAll}>查看全部 {view.total}</Button>}</div></header>
  {archived&&<p className="pw-warning">项目已归档，恢复项目后可以继续调整工作。</p>}
  {error&&<p className="cv-error" role="alert">{error}<Button onClick={onRefresh}>读取最新记录</Button></p>}
  {work.warnings.map((v,i)=><p key={i} className="pw-warning">{v}</p>)}
  {!compact&&<div className="pw-filters">
   <input aria-label="搜索工作" placeholder="搜索工作或下一步" value={query} onChange={e=>setQuery(e.target.value)}/>
   <select aria-label="筛选工作类型" value={kind} onChange={e=>setKind(e.target.value)}><option value="">所有类型</option>{[...new Set(rows.map(r=>r.kind).filter(Boolean))].map(v=><option key={v}>{v}</option>)}</select>
   <select aria-label="筛选关联问题" value={question||''} onChange={e=>onQuestion?.(e.target.value)}><option value="">所有问题</option><option value="independent">独立工作</option>{questions.map(q=><option key={q.id} value={q.id}>{q.title}</option>)}</select>
   <label><input type="checkbox" checked={history} onChange={e=>setHistory(e.target.checked)}/>包含已移除/被替代项</label>
   <Button onClick={()=>setColumns(!columns)}>{columns?'改成逐行列表':'按状态分列'}</Button>
   {filtering&&<Button onClick={reset}>清空筛选</Button>}
  </div>}
  {!!filtering&&!compact&&<p className="pw-scope">当前显示 {view.total} 项{view.total?`：${statText}`:''}</p>}
  {!shown.length?<p className="cv-empty">{filtering?'没有符合条件的工作，可以清空筛选再试。':(view.completed?'当前工作已全部完成，可查看全部工作回顾。':'还没有工作。只写标题就可以开始。')}</p>
   :compact||!columns?<div className="pw-rows">{shown.map(card)}</div>
   :<div className="pw-columns">{statuses.map(s=><section key={s} className="pw-column" aria-label={s+'工作'} onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();const id=e.dataTransfer.getData('text/project-work');if(id&&!archived)change('update',id,{status:s});}}><h3>{s} <small>{view.stats[s]||0}</small></h3>{shown.filter(r=>r.status===s).map(row=><div key={row.id} draggable={!archived&&!busy&&!row.removed} onDragStart={e=>e.dataTransfer.setData('text/project-work',row.id)}>{rowLine(row)}</div>)}</section>)}</div>}
  {dialog&&<WorkDialog key={dialog.id||'new'} row={dialog.id?dialog:{...dialog,stage_ids:stageId?[stageId]:[]}} data={data} project={project} bridge={bridge} onRefresh={onRefresh} onClose={()=>setDialog(null)} onMap={onMap}/>}
 </section>;
}

export function WorkDialog({row,data,project,bridge,onRefresh,onClose,onMap,noun='工作'}){
 const t=text=>noun==='计划'?String(text).replaceAll('工作','计划'):text;
 const rows=itemsOfType(data.work.items,noun==='计划'?'plan':'work'),questions=data.project_overview.questions,archived=data.project_profile.archived;
  const [base,setBase]=useState(()=>workForm(row,noun)),[v,setV]=useState(base),[fingerprint,setFingerprint]=useState(data.work.fingerprint),[busy,setBusy]=useState(false),[error,setError]=useState(''),[latest,setLatest]=useState(null),[mode,setMode]=useState(''),[titles,setTitles]=useState(''),[mergeIds,setMergeIds]=useState([]),[preview,setPreview]=useState(null);
  const [choices,setChoices]=useState({});
 const request=useRef(crypto.randomUUID()),structure=useRef(null),pending=useRef(null);
  function resetRequest(){pending.current=null;request.current=crypto.randomUUID();}
  function field(name,value){if(busy)return;setV(old=>{
   const next={...old,[name]:value};
   if(name==='depends_on'&&old.due_date_rule&&!value.includes(old.due_date_rule.task_id))next.due_date_rule=null;
   if(name==='due_date_rule'&&value&&!old.depends_on.includes(value.task_id))next.depends_on=[...old.depends_on,value.task_id];
   return next;
  });resetRequest();setChoices({});}
  function close(){if(busy||Object.keys(workFields(v,base)).length&&!window.confirm('放弃尚未保存的修改？'))return;onClose();}
 async function send(payload){setBusy(true);setError('');try{await bridge.api('/api/project-work/change',payload);await onRefresh();onClose();}catch(e){setError(t(e.message));}finally{setBusy(false);}}
  const liveRow=latest?.items.find(item=>item.id===row.id);
  const liveForm=liveRow&&workForm(liveRow,noun);
  const rebase=liveForm&&rebaseWorkForm(base,v,liveForm);
  const unavailable=!!(latest&&row.id&&(!liveRow||liveRow.removed||liveRow.replacement));
  async function readLatest(){try{setLatest(await bridge.api('/api/project-work?project='+encodeURIComponent(project)));setChoices({});}catch(e){setError(t(e.message));}}
  function acceptLatest(){
   if(unavailable||rebase?.conflicts.some(field=>!choices[field]))return;
   if(rebase){const values={...rebase.values};for(const field of rebase.conflicts)if(choices[field]==='current')values[field]=liveForm[field];setBase(liveForm);setV(values);}
   setFingerprint(latest.fingerprint);resetRequest();setPreview(null);setLatest(null);setError('');
  }
  function save(){
   const fields=workFields(v,row.id?base:null);
   if(!Object.keys(fields).length){onClose();return;}
   if(!pending.current)pending.current={project,op:row.id?'update':'add',task_id:row.id,fields,fingerprint,request_id:request.current,lifecycle_revision:data.project_profile.lifecycle_revision};
   send(pending.current);
  }
 const materials=[...(data.project_materials.documents||[]).map(d=>({id:'doc:'+d.id,title:d.display_title||d.title})),...data.papers.map(p=>({id:'paper:'+p.id,title:p.title}))];
  const dateSources=rows.filter(source=>source.id!==row.id&&!source.legacy&&(!source.removed&&!source.replacement||source.id===v.due_date_rule?.task_id));
 return <Modal title={row.id?noun+'详情':noun==='计划'?'新增计划':'新建工作'} onClose={close} wide>
  <label className="cv-field">{noun}标题<input autoFocus aria-label={noun+"标题"} value={v.title} maxLength={1000} disabled={archived} onChange={e=>field('title',e.target.value)}/></label>
  <div className="pw-form-grid"><label className="cv-field">{noun}状态<select aria-label={noun+"状态"} value={v.status} disabled={archived} onChange={e=>field('status',e.target.value)}>{statuses.map(s=><option key={s}>{s}</option>)}</select></label></div>
   <div className="pw-form-grid">
    <label className="cv-field">日期<input aria-label={noun+'日期'} type="date" value={v.due_on} disabled={archived||busy||!!v.due_date_rule} onChange={e=>field('due_on',e.target.value)}/></label>
    <label className="cv-field">日期跟随<select aria-label="日期跟随" disabled={archived||busy||!dateSources.length} value={v.due_date_rule?.task_id||''} onChange={e=>field('due_date_rule',e.target.value?{task_id:e.target.value,offset_days:v.due_date_rule?.offset_days??0}:null)}><option value="">{dateSources.length?'手动填写日期':'暂无可跟随的'+noun}</option>{dateSources.map(source=><option key={source.id} value={source.id}>{plainInline(source.title)}</option>)}</select></label>
    {v.due_date_rule&&<label className="cv-field">偏移天数<input aria-label="偏移天数" type="number" min={-3650} max={3650} step={1} disabled={archived||busy} value={v.due_date_rule.offset_days} onChange={e=>field('due_date_rule',{...v.due_date_rule,offset_days:Number(e.target.value)})}/></label>}
   </div>
   {dateSources.length>0&&<p className="ps-muted">选择来源会同时建立依赖。来源日期空白时保留现有日期。</p>}
  <label className="cv-field">下一步／等待什么（可空）<textarea aria-label="下一步／等待什么（可空）" value={v.next_step} maxLength={4000} rows={3} disabled={archived} onChange={e=>field('next_step',e.target.value)}/></label>
  {noun==='工作'&&<label className="cv-field">执行过程与结果<textarea aria-label="执行过程与结果" value={v.execution_notes} maxLength={50000} rows={7} disabled={archived} onChange={e=>field('execution_notes',e.target.value)}/></label>}
    <details className="pw-more"><summary>类型与关联问题</summary><div className="pw-form-grid"><label className="cv-field">类型（可空）<input value={v.kind} maxLength={120} disabled={archived} onChange={e=>field('kind',e.target.value)}/></label><label className="cv-field">关联问题（可空）<select aria-label="关联问题" value={v.question_id} disabled={archived} onChange={e=>field('question_id',e.target.value)}><option value="">独立{noun}</option>{row.question_id&&!questions.some(q=>q.id===row.question_id)&&<option value={row.question_id}>原关联已失效 · {row.question_id}</option>}{questions.map(q=><option key={q.id} value={q.id}>{q.title}</option>)}</select></label></div></details>
  <details><summary>关联阶段</summary><p className="ps-muted">可关联多个阶段，共用同一{noun==='计划'?'勾选':'工作'}状态。</p>{(data.progress?.stages||[]).map(stage=><label className="ps-task-select" key={stage.id}><input type="checkbox" disabled={archived} checked={v.stage_ids.includes(stage.id)} onChange={e=>field('stage_ids',e.target.checked?[...v.stage_ids,stage.id]:v.stage_ids.filter(id=>id!==stage.id))}/>{stage.title}</label>)}</details>
  <details><summary>依赖与资料引用</summary><div className="pw-pick">{rows.filter(r=>r.id!==row.id&&!r.legacy&&!r.removed).map(r=><label key={r.id}><input type="checkbox" disabled={archived} checked={v.depends_on.includes(r.id)} onChange={e=>field('depends_on',e.target.checked?[...v.depends_on,r.id]:v.depends_on.filter(i=>i!==r.id))}/>{plainInline(r.title)} · {r.status}</label>)}</div>
   <select aria-label="添加引用资料" disabled={archived} value="" onChange={e=>{if(e.target.value&&!v.references.some(r=>r.material_id===e.target.value))field('references',[...v.references,{material_id:e.target.value,location:'',purpose:''}]);}}><option value="">选择本项目已有资料</option>{materials.map(r=><option key={r.id} value={r.id}>{r.title}</option>)}</select>
   {v.references.map((ref,i)=><div className="pw-reference" key={ref.material_id}><strong>{materials.find(m=>m.id===ref.material_id)?.title||ref.material_id+' · 当前范围已失效'}</strong>{['location','purpose'].map(n=><input key={n} aria-label={n==='location'?'引用位置':'引用用途'} placeholder={n==='location'?'页码／章节／位置':'选用目的'} value={ref[n]||''} maxLength={n==='location'?500:1500} disabled={archived} onChange={e=>field('references',v.references.map((r,j)=>j===i?{...r,[n]:e.target.value}:r))}/>)}<Button disabled={archived} onClick={()=>field('references',v.references.filter((_,j)=>j!==i))}>移除引用</Button></div>)}
  </details>
  {row.id&&<div className="pw-provenance"><small>{noun} ID：{row.id}</small>{rows.filter(r=>r.replacement?.targets?.includes(row.id)).map(r=><p key={r.id}>来自：{plainInline(r.title)}（{r.id}）</p>)}{row.replacement&&<p>替代去向：{row.replacement.targets.map(id=>rows.find(r=>r.id===id)?.title||id).join('、')}</p>}{data.project_overview.task_document?.document_id&&<Button onClick={()=>bridge.openDocument(data.project_overview.task_document.document_id)}>打开{noun}原稿</Button>}{onMap&&<Button onClick={()=>onMap(row.id)}>{noun==='计划'?'查看关联阶段':'在研究图中查找'}</Button>}</div>}
   {error&&<div className="cv-error" role="alert"><p>{error}</p><Button disabled={busy} onClick={readLatest}>查看最新稿（保留输入）</Button>{latest&&(unavailable?<p>这项{noun}已移除、替代或变更编号。关闭后可从最新列表重新打开。</p>:<>
    {rebase?.conflicts.map(field=><label className="cv-field" key={field}>{workFieldLabels[field]||field}已在其他窗口修改<select aria-label={(workFieldLabels[field]||field)+'合并选择'} value={choices[field]||''} onChange={event=>setChoices({...choices,[field]:event.target.value})}><option value="">选择要保留的值</option><option value="current">最新稿：{JSON.stringify(liveForm[field])}</option><option value="draft">本次输入：{JSON.stringify(v[field])}</option></select></label>)}
    <Button disabled={busy||rebase?.conflicts.some(field=>!choices[field])} onClick={acceptLatest}>按最新稿合并本次输入</Button>
   </>)}</div>}
  {!archived&&row.id&&!row.removed&&<details><summary>拆分、合并和移除</summary><Button onClick={()=>{setMode('split');setPreview(null);}}>拆分{noun}</Button><Button onClick={()=>{setMode('merge');setPreview(null);}}>合并{noun}</Button><Button disabled={busy} onClick={()=>send({project,op:'remove',task_id:row.id,fields:{},fingerprint,request_id:request.current})}>移除并保留原记录</Button>
   {mode&&<div className="pw-structure">{mode==='merge'&&rows.filter(r=>r.id!==row.id&&!r.legacy&&!r.removed&&!r.replacement).map(r=><label key={r.id}><input type="checkbox" checked={mergeIds.includes(r.id)} onChange={e=>{setMergeIds(e.target.checked?[...mergeIds,r.id]:mergeIds.filter(id=>id!==r.id));setPreview(null);}}/>{plainInline(r.title)}</label>)}<label className="cv-field">{mode==='split'?'新'+noun+'标题（每行一项，至少两项）':'合并后的标题'}<textarea aria-label={mode==='split'?'新'+noun+'标题（每行一项，至少两项）':'合并后的标题'} value={titles} rows={3} onChange={e=>{setTitles(e.target.value);setPreview(null);}}/></label><Button disabled={busy} onClick={async()=>{setBusy(true);try{structure.current={project,op:mode,task_ids:[row.id,...(mode==='merge'?mergeIds:[])],...(mode==='split'?{children:titles.split('\n').filter(t=>t.trim()).map(title=>({title}))}:{title:titles}),fingerprint,request_id:crypto.randomUUID()};setPreview(await bridge.api('/api/project-work/preview',structure.current));setError('');}catch(e){setError(t(e.message));}finally{setBusy(false);}}}>预览全部影响</Button>{preview&&<div><p>{t(preview.notice)}</p><ul>{preview.after.map(r=><li key={r.id}>{plainInline(r.title)} · {r.status}{r.replacement?' · 被替代，原勾选保留':''}</li>)}</ul><p>原有依赖保持原目标，请核对需要改连的{noun}。</p><Button disabled={busy} onClick={async()=>{setBusy(true);try{await bridge.api('/api/project-work/commit',{...structure.current,preview_token:preview.preview_token});await onRefresh();onClose();}catch(e){setError(t(e.message));}finally{setBusy(false);}}}>确认一次提交</Button><Button onClick={()=>setPreview(null)}>取消预览</Button></div>}</div>}
  </details>}
   <div className="cv-dialog-actions"><Button disabled={busy} onClick={close}>取消</Button>{row.removed&&!archived&&<Button disabled={busy} onClick={()=>send({project,op:'restore',task_id:row.id,fields:{},fingerprint,request_id:request.current,lifecycle_revision:data.project_profile.lifecycle_revision})}>恢复{noun}</Button>}{!archived&&<Button variant="primary" disabled={busy||!!latest||row.removed||!!row.replacement} onClick={save}>保存{noun}</Button>}</div>
 </Modal>;
}
