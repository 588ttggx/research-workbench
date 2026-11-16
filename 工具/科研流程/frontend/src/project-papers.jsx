import React,{useState} from 'react';
import {Button,Modal} from './canvas-components.jsx';

export function ProjectPapers({project,data,bridge,onRefresh,archived,initialAdd=false}){
 const [query,setQuery]=useState(''),[adding,setAdding]=useState(initialAdd),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const selected=new Set(data.selected_paper_ids);
 const rows=data.papers.filter(p=>[p.title,p.display_title,p.id,p.doi,...(Array.isArray(p.authors)?p.authors:[])].join(' ').toLowerCase().includes(query.toLowerCase()));
 async function change(op,ids,request=crypto.randomUUID(),versions={paper:data.paper_fingerprint,organization:data.fingerprint,lifecycle:data.lifecycle_revision}){
  await bridge.api('/api/project/knowledge/change',{project,op,paper_ids:ids,request_id:request,fingerprint:versions.organization,paper_fingerprint:versions.paper,lifecycle_revision:versions.lifecycle});
  await onRefresh();
 }
 return <section className="ps-panel ps-paper-list" aria-label="项目文献"><header><div><h2>项目文献 <small>{data.papers.length}</small></h2><p className="ps-muted">本项目明确选用及当前资料引用的论文，直接打开同一文献与原文。</p></div><Button disabled={archived||busy} onClick={()=>setAdding(true)}>添加论文</Button></header>
  <input className="ps-paper-search" aria-label="搜索项目文献" placeholder="搜索题名、作者、DOI 或文献编号" value={query} onChange={e=>setQuery(e.target.value)}/>
  {error&&<p role="alert" className="cv-error">{error}</p>}
  {rows.map(p=><article className="ps-paper-row" key={p.id}><small>{p.year||'年份未登记'} · {p.id}{p.availability==='original_missing'?' · 原文路径失效':p.availability==='metadata_only'?' · 原文待补':''}</small><button className="ps-text-link" onClick={()=>bridge.openPaper(p.id)}>{p.display_title||p.title}</button><p className="ps-muted">{p.reading_status||'阅读范围未登记'}{p.reading_scope?' · '+p.reading_scope:''}</p><p className="ps-muted">{p.reasons?.join(' · ')||'当前资料引用'}</p><div className="ps-actions"><Button onClick={()=>bridge.openPaper(p.id)}>打开文献与原文</Button>{selected.has(p.id)&&<Button disabled={archived||busy} onClick={async()=>{setBusy(true);setError('');try{await change('remove_papers',[p.id]);}catch(e){setError(e.message);}finally{setBusy(false);}}}>取消直接选用</Button>}</div></article>)}
  {!rows.length&&<p className="ps-muted">{query?'没有匹配文献。':'还没有项目论文，可从已登记文献中添加。'}</p>}
  <p className="ps-muted">取消直接选用后，仍被当前资料引用的论文继续显示；文献登记、附件与阅读记录保留。</p>
  {adding&&<AddProjectPapers project={project} data={data} bridge={bridge} onClose={()=>setAdding(false)} onSubmit={(ids,request,fingerprint)=>change('add_papers',ids,request,fingerprint)}/>}
 </section>;
}

function AddProjectPapers({project,data,bridge,onClose,onSubmit}){
 const [chosen,setChosen]=useState(new Set()),[query,setQuery]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[versions,setVersions]=useState({paper:data.paper_fingerprint,organization:data.fingerprint,lifecycle:data.lifecycle_revision}),[request,setRequest]=useState(crypto.randomUUID());
 function select(id,value){setChosen(old=>{const next=new Set(old);value?next.add(id):next.delete(id);return next;});setRequest(crypto.randomUUID());}
 const rows=data.paper_candidates.filter(p=>[p.title,p.id,p.doi,...(Array.isArray(p.authors)?p.authors:[])].join(' ').toLowerCase().includes(query.toLowerCase()));
 return <Modal title="添加项目论文" wide onClose={()=>{if(!busy)onClose();}}><p>从已有文献登记中选择，沿用原文献编号、附件与阅读记录。新论文可先在“发现”收录。</p><input aria-label="查找已登记论文" placeholder="题名、作者、DOI 或文献编号" value={query} onChange={e=>setQuery(e.target.value)}/><p>已选 {chosen.size} 篇</p><div className="ps-knowledge-picker">{rows.map(p=><label className="ps-task-select" key={p.id}><input type="checkbox" aria-label={p.display_title||p.title} disabled={busy} checked={chosen.has(p.id)} onChange={e=>select(p.id,e.target.checked)}/><span>{p.display_title||p.title}<small className="ps-paper-caption">{p.year||''} · {p.id}{data.selected_paper_ids.includes(p.id)?' · 已直接选用':''}{p.availability==='original_missing'?' · 原文路径失效':p.availability==='metadata_only'?' · 原文待补':''}</small></span></label>)}</div>
 {error&&<div role="alert" className="cv-error"><p>{error}</p><Button disabled={busy} onClick={async()=>{try{const fresh=await bridge.api('/api/project/knowledge?project='+encodeURIComponent(project));setVersions({paper:fresh.paper_fingerprint,organization:fresh.fingerprint,lifecycle:fresh.lifecycle_revision});setError('已重读文献选择，请核对所选论文后再次添加。');}catch(e){setError(e.message);}}}>重读项目文献并保留选择</Button></div>}
 <div className="cv-dialog-actions"><Button disabled={busy} onClick={onClose}>取消</Button><Button variant="primary" disabled={busy||!chosen.size} onClick={async()=>{setBusy(true);try{await onSubmit([...chosen],request,versions);onClose();}catch(e){setError(e.message);}finally{setBusy(false);}}}>添加所选论文</Button></div></Modal>;
}
