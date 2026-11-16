import React,{useEffect,useRef,useState} from 'react';
import {Button,Modal,Markdown} from './canvas-components.jsx';

export function EditForm({project,id,title,initial={},fields=[],version='',onSubmit,onClose,extra,bridge,latestBody=''}){
 const key=`research:project-form:${project}:${id}`;
 const [value,setValue]=useState(()=>{try{return JSON.parse(localStorage.getItem(key))||{...initial,__fingerprint:version};}catch{return {...initial,__fingerprint:version};}});
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[preview,setPreview]=useState(false);
 const request=useRef(crypto.randomUUID()),dirty=useRef(false),session=useRef({active:true,revision:0,epoch:0,saving:false});
 useEffect(()=>{session.current.active=true;return()=>{session.current.active=false;session.current.epoch++;};},[key]);
 useEffect(()=>{const leave=e=>{if(dirty.current){e.preventDefault();e.returnValue='';}};window.addEventListener('beforeunload',leave);return()=>window.removeEventListener('beforeunload',leave);},[]);
 function update(name,next){if(!session.current.active||session.current.saving)return;session.current.revision++;setValue(old=>{const v={...old,[name]:next};localStorage.setItem(key,JSON.stringify(v));return v;});dirty.current=true;request.current=crypto.randomUUID();}
 function close(){if(dirty.current&&!window.confirm('放弃这次尚未保存的修改？'))return;session.current.active=false;session.current.epoch++;localStorage.removeItem(key);onClose();}
 async function save(){if(session.current.saving||!session.current.active)return;session.current.saving=true;session.current.epoch++;setBusy(true);setError('');try{await onSubmit(value,request.current);if(!session.current.active)return;dirty.current=false;localStorage.removeItem(key);session.current.active=false;onClose();}catch(e){if(session.current.active)setError(e.message);}finally{session.current.saving=false;if(session.current.active)setBusy(false);}}
 return <Modal title={title} onClose={close} wide>
  <div className="ps-form">{fields.map(f=><label key={f.name} className="cv-field">{f.label}{f.type==='select'?<select aria-label={f.label} disabled={busy} value={value[f.name]||''} onChange={e=>update(f.name,e.target.value)}>{f.options.map(o=><option key={o.value} value={o.value}>{o.label}</option>)}</select>:f.type==='checkbox'?<input aria-label={f.label} disabled={busy} type="checkbox" checked={!!value[f.name]} onChange={e=>update(f.name,e.target.checked)}/>:f.type==='text'?<input aria-label={f.label} disabled={busy} value={value[f.name]||''} maxLength={f.maxLength||200} onChange={e=>update(f.name,e.target.value)} autoFocus={f.autoFocus}/>:<textarea aria-label={f.label} disabled={busy} rows={f.rows||8} value={value[f.name]||''} maxLength={100000} onChange={e=>update(f.name,e.target.value)}/>}</label>)}</div>
  {extra?.(value,update,setError,setBusy,session.current)}
  {value.body&&bridge&&<><Button onClick={()=>setPreview(!preview)}>{preview?'收起预览':'预览正文'}</Button>{preview&&<Markdown body={value.body} bridge={bridge}/>}</>}
  {version&&value.__fingerprint!==version&&<div className="ps-warning"><p>原稿已变化。请核对当前内容，再将输入合并到当前版本。</p>{latestBody&&<details><summary>查看当前内容</summary><pre>{latestBody}</pre></details>}<Button onClick={()=>update('__fingerprint',version)}>保留输入，采用当前版本继续合并</Button></div>}
  {error&&<p className="cv-error" role="alert">{error}</p>}
  <div className="cv-dialog-actions"><Button disabled={busy} onClick={close}>取消</Button><Button variant="primary" disabled={busy} onClick={save}>{busy?'正在保存…':'保存'}</Button></div>
 </Modal>;
}

export function KnowledgeForm({project,bridge,knowledge,source,summaryModule,existing,onSaved,onClose}){
 const [module,setModule]=useState(summaryModule?.id||''),[draftBusy,setDraftBusy]=useState(false);
 const [current,setCurrent]=useState(null),[draftId,setDraftId]=useState(''),[draftInfo,setDraftInfo]=useState(null),[loadError,setLoadError]=useState('');
 const [candidate,setCandidate]=useState(null);
 useEffect(()=>{let active=true;if(existing)bridge.api('/api/workspace/document?id='+encodeURIComponent(existing.id)).then(value=>{if(active)setCurrent(value);}).catch(e=>{if(active)setLoadError(e.message);});return()=>{active=false;};},[existing?.id]);
 const sourceData=source?{source_document_id:source.document_id,block_id:source.block_id,block_sha:source.block_sha}:{};
 if(existing&&!current)return <Modal title="读取模块综述" onClose={onClose}><p>{loadError||'正在读取原稿…'}</p></Modal>;
 return <EditForm key={project+':'+(source?.document_id||existing?.id||'')+':'+(source?.block_id||summaryModule?.id||'new')} project={project} id={'knowledge:'+ (source?.block_id||summaryModule?.id||'new')} title={summaryModule?'撰写模块综述':source?'提炼为知识':'新建知识笔记'}
  initial={{title:current?.title||(summaryModule?summaryModule.title+' · 综述':''),body:current?.body||'',global_knowledge:current?.global_knowledge||false}} version={current?.fingerprint||''} latestBody={current?.body||''} bridge={bridge}
   fields={[{name:'title',label:'知识标题',type:'text',autoFocus:true},{name:'body',label:'知识正文',rows:12},...(!existing?[{name:'global_knowledge',label:'关联到全局知识区',type:'checkbox'}]:[])]}
  extra={(value,update,setError,_setBusy,session)=> <div className="ps-form-extra"><label className="cv-field">所属模块<select aria-label="所属模块" disabled={session.saving} value={module} onChange={e=>setModule(e.target.value)}><option value="">未分类知识</option>{knowledge.modules.map(m=><option key={m.id} value={m.id}>{m.title}</option>)}</select></label>
   {(source||summaryModule)&&<Button disabled={draftBusy||session.saving} onClick={async()=>{if(!session.active||session.saving)return;const epoch=session.epoch,revision=session.revision;setDraftBusy(true);setCandidate(null);setError('');try{const draft=await bridge.api('/api/project/knowledge/draft',{project,...sourceData,purpose:source?'extract':'overview',module_id:summaryModule?.id});if(!session.active||session.epoch!==epoch)return;if(session.revision!==revision){setCandidate(draft);return;}setDraftId(draft.id);setDraftInfo(draft);update('title',draft.title);update('body',draft.body);}catch(e){if(session.active&&session.epoch===epoch)setError(e.message);}finally{if(session.active)setDraftBusy(false);}}}>{draftBusy?'正在起草…':'让 AI 起草，再由我核对'}</Button>}
   {candidate&&<section className="ps-warning"><p>起草期间你修改了内容，编辑区保留你的输入。AI 候选可查看后再采用。</p><details><summary>查看 AI 候选</summary><strong>{candidate.title}</strong><Markdown body={candidate.body} bridge={bridge}/></details><Button disabled={session.saving} onClick={()=>{if(!session.active||session.saving)return;setDraftId(candidate.id);setDraftInfo(candidate);update('title',candidate.title);update('body',candidate.body);setCandidate(null);}}>采用 AI 候选替换编辑内容</Button><Button onClick={()=>setCandidate(null)}>保留我的内容</Button></section>}
   {draftInfo&&<details className="ps-muted"><summary>本次起草的实际来源 · {draftInfo.sources.length} 份{draftInfo.coverage_truncated?'（已按上限截取）':''}</summary>{draftInfo.sources.map(s=><p key={s.id}>{s.title} · {s.kind}</p>)}<Button onClick={()=>{setDraftId('');setDraftInfo(null);}}>保留文字，转为手动核对稿</Button></details>}
   {source&&<p className="ps-muted">来源保留为记录链接与当时版本，过程原稿保持在项目内。</p>}</div>}
  onSubmit={async(v,request)=>{const common={project,...sourceData,request_id:request,title:v.title,body:v.body,draft_id:draftId||undefined,draft_purpose:source?'extract':'overview',module_id:summaryModule?.id,source_signature:summaryModule?.source_signature};
    if(current)await bridge.api('/api/project/knowledge/summary',{...common,id:current.id,fingerprint:v.__fingerprint});
   else await bridge.api('/api/project/knowledge/extract',{...common,global_knowledge:v.global_knowledge,module_ids:module?[module]:[],summary_module_id:summaryModule?.id});await onSaved();}} onClose={onClose}/>;
}

export function HistoryDialog({documentId,bridge,onClose}){
 const [data,setData]=useState({records:[],next_cursor:''}),[error,setError]=useState(''),[chosen,setChosen]=useState(null);
 async function load(cursor=''){try{const value=await bridge.api('/api/workspace/versions?'+new URLSearchParams({id:documentId,cursor,limit:'20'}));setData(old=>({records:cursor?[...old.records,...value.records]:value.records,next_cursor:value.next_cursor}));}catch(e){setError(e.message);}}
 useEffect(()=>{load();},[documentId]);
 return <Modal title="修改历史" onClose={onClose} wide><p className="ps-muted">查看对应时间的原稿，当前正文保持不变。</p>{error&&<p role="alert">{error}</p>}{data.records.map(v=><Button key={v.id} onClick={async()=>{try{setChosen(await bridge.api('/api/workspace/version?'+new URLSearchParams({id:documentId,version:v.id})));}catch(e){setError(e.message);}}}>{new Date(v.created).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}</Button>)}{!data.records.length&&<p>暂时没有修改历史。</p>}{data.next_cursor&&<Button onClick={()=>load(data.next_cursor)}>加载更早历史</Button>}{chosen&&<div className="ps-history"><Markdown body={chosen.body} bridge={bridge}/></div>}</Modal>;
}
