import React,{useState,useEffect,useRef,useCallback} from 'react';
import {Plus,Check,Search,FileText} from 'lucide-react';
import {Button,Modal,Markdown} from './canvas-components.jsx';

function questionValues(question){return question?.id?{solution:question.solution||''}:{title:question?.title||'研究问题',goal:question?.goal||''};}

export function QuestionDialog({project,question,fingerprint,onSave,onClose,bridge,lifecycleRevision,operation='update'}){
 const draftKey='research:question-draft:'+project+':'+(question?.id||'new')+':solution-v2';
 const [draft]=useState(()=>{try{return JSON.parse(localStorage.getItem(draftKey));}catch{return null;}});
 const [baseline,setBaseline]=useState(draft?.baseline||questionValues(question));
 const [values,setValues]=useState(draft?.values||questionValues(question));
 const [version,setVersion]=useState(draft?.fingerprint||question?.fingerprint||fingerprint);
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[latest,setLatest]=useState(null),[recovered,setRecovered]=useState(!!draft);
 const active=useRef(null),inFlight=useRef(false),request=useRef(draft?.request_id||crypto.randomUUID()),pending=useRef(draft?.pending||null);
 const changed=Object.fromEntries(Object.entries(values).filter(([key,value])=>value!==baseline[key]));
 const modified=question?changed:values;
 const dirty=Object.keys(changed).length>0;
 active.current={values,baseline,fingerprint:version,dirty};
 function storeDraft(){const current=active.current;try{if(current?.dirty||pending.current)localStorage.setItem(draftKey,JSON.stringify({values:current.values,baseline:current.baseline,fingerprint:current.fingerprint,request_id:request.current,pending:pending.current}));}catch{setError('本机草稿存储不可用，请保持编辑窗口并保存到原记录。');}}
 useEffect(()=>{storeDraft();},[values,baseline,version]);
 useEffect(()=>{const protect=e=>{if(active.current?.dirty){storeDraft();e.preventDefault();e.returnValue='';}};window.addEventListener('beforeunload',protect);return()=>window.removeEventListener('beforeunload',protect);},[]);
 function close(){if(busy)return;if(dirty&&!window.confirm('修改尚未保存。关闭并保留本机草稿？'))return;storeDraft();onClose();}
 async function save(fields=modified,expected=version){
  if(inFlight.current)return;inFlight.current=true;setBusy(true);setError('');
  try{if(Object.keys(fields).length||operation==='record_progress'||pending.current){pending.current=pending.current||{project,id:question?.id,op:operation,request_id:request.current,fingerprint:expected,fields,...(lifecycleRevision!==undefined?{lifecycle_revision:lifecycleRevision}:{})};storeDraft();await onSave(pending.current);}localStorage.removeItem(draftKey);pending.current=null;active.current.dirty=false;onClose();}
  catch(e){storeDraft();setError(e.message);}
  finally{inFlight.current=false;setBusy(false);}
 }
 async function compare(){if(!bridge||!question?.id)return;setBusy(true);try{setLatest(await bridge.api('/api/project/question?'+new URLSearchParams({project,id:question.id})));}catch(e){setError(e.message);}finally{setBusy(false);}}
 return <Modal title={question?'编辑解决方法':'新增研究问题'} subtitle="保存到原研究问题；未保存的编辑保留为本机草稿。" onClose={close}>
  <form className="pq-form" onSubmit={e=>{e.preventDefault();save();}} onKeyDown={e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){e.preventDefault();save();}}}>
  {recovered&&<p className="cv-notice">已恢复未保存的草稿，原记录尚未改变。</p>}
  {(question?[['solution','解决方法',7,4000]]:[['title','问题名称',1,120],['goal','研究问题',3,2000]]).map(([name,label,rows,maxLength])=><label className="cv-field" key={name}>{label}{rows===1?<input aria-label={label} value={values[name]} maxLength={maxLength} disabled={busy} onChange={e=>{pending.current=null;request.current=crypto.randomUUID();setValues({...values,[name]:e.target.value});}}/>:<textarea aria-label={label} rows={rows} value={values[name]} maxLength={maxLength} disabled={busy} onChange={e=>{pending.current=null;request.current=crypto.randomUUID();setValues({...values,[name]:e.target.value});}}/>}</label>)}
  {error&&<div className="cv-error" role="alert"><p>{error}</p>{bridge&&question?.id&&<Button disabled={busy} onClick={compare}>查看最新记录</Button>}</div>}
  {latest&&<section className="pq-comparison"><h3>最新原记录</h3><p>只合并你修改过的字段，其他窗口的新内容保留。请核对后提交。</p>{(question?[['solution','解决方法']]:[['title','问题名称'],['goal','研究问题']]).map(([key,label])=><div key={key}><strong>{label}</strong><p>{latest[key]||'尚未填写'}</p>{key in modified&&<p>我的修改：{modified[key]||'清空此项'}</p>}</div>)}<Button disabled={busy} onClick={()=>{const fields=pending.current?.fields||modified;pending.current=null;setVersion(latest.fingerprint);setBaseline(questionValues(latest));setValues({...questionValues(latest),...fields});setLatest(null);save(fields,latest.fingerprint);}}>合并我的修改并保存</Button></section>}
  <div className="cv-dialog-actions"><small>{busy?'正在保存…':dirty?'有未保存修改 · 草稿已保留':'已与原记录一致'}</small>{recovered&&<Button disabled={busy} onClick={()=>{if(!window.confirm('丢弃本机草稿？原记录保留。'))return;pending.current=null;request.current=crypto.randomUUID();localStorage.removeItem(draftKey);const original=questionValues(question);setValues(original);setBaseline(original);setVersion(question?.fingerprint||fingerprint);setRecovered(false);setLatest(null);setError('');}}>丢弃草稿</Button>}<Button disabled={busy} onClick={close}>取消</Button><Button type="submit" icon={Check} variant="primary" disabled={busy}>保存</Button></div>
  </form>
 </Modal>;
}

const LIBRARY_TYPES=['操作卡','方案','采购与样品','背景','记录','其他'];

export function ProjectLibrary({project,bridge,archived=false,lifecycleRevision}){
 const [data,setData]=useState(null),[error,setError]=useState(''),[query,setQuery]=useState(''),[type,setType]=useState('全部'),[dialog,setDialog]=useState(false);
 const load=useCallback(async()=>{const fresh=await bridge.api('/api/project/materials?project='+encodeURIComponent(project));setData(fresh);setError('');return fresh;},[project]);
 useEffect(()=>{let live=true;load().catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[load]);
 const items=data?.items||[],types=LIBRARY_TYPES.filter(name=>(data?.counts||{})[name]),rows=items.filter(row=>(type==='全部'||row.type===type)&&[row.title,row.excerpt,row.path,row.type].join(' ').toLowerCase().includes(query.toLowerCase()));
 async function created(result){setDialog(false);try{await load();}catch(e){setError(e.message);}if(result?.document_id)bridge.openDocument(result.document_id);}
 return <section className="cv-project-materials" aria-label="项目资料">
   <header><div><span className="cv-eyebrow">PROJECT MATERIALS</span><h2>项目资料</h2><p>操作卡、方案、采购与样品、背景和记录都从这里打开同一份原稿；这里只做入口，不改变知识区准入。</p></div><Button icon={Plus} disabled={data===null||archived} onClick={()=>setDialog(true)}>新建资料</Button></header>
  <div className="cv-search-wrap"><Search size={15}/><input aria-label="搜索项目资料" value={query} onChange={e=>setQuery(e.target.value)} placeholder="搜索标题、类型或原稿路径"/></div>
  <div className="cv-type-chips" role="group" aria-label="按资料类型筛选">{['全部',...types].map(name=><button key={name} aria-pressed={type===name} className={type===name?'active':''} onClick={()=>setType(name)}>{name}<small>{data===null?'…':name==='全部'?(data.total||0):(data.counts||{})[name]}</small></button>)}</div>
  {error&&<p className="cv-error" role="alert">{error}<Button onClick={()=>load().catch(e=>setError(e.message))}>重新读取</Button></p>}
  {data===null&&!error&&<p className="cv-empty">正在读取项目资料…</p>}
  <div className="cv-record-grid">{rows.map(row=><article key={row.id}>
   <small>{row.type}{row.record_type?' · '+row.record_type:''}{row.path.endsWith('/当前课题状态.md')?' · 项目主稿':''}</small>
   <button className="cv-record-title" onClick={()=>bridge.openDocument(row.id)}>{row.title}</button>
   {row.excerpt&&<p className="cv-record-excerpt">{row.excerpt}</p>}
    <footer><Button icon={FileText} onClick={()=>bridge.openDocument(row.id)}>打开原稿</Button>{row.editable&&!archived&&typeof bridge.editDocument==='function'&&<Button onClick={()=>bridge.editDocument(row.id)}>编辑</Button>}</footer>
  </article>)}</div>
  {data!==null&&!rows.length&&<p className="cv-empty">{items.length?'这个类型下没有匹配的资料，换个筛选或清空搜索。':'这个项目还没有非知识资料，可以用「新建资料」写下操作卡、方案或记录。'}</p>}
   {dialog&&!archived&&<MaterialDialog project={project} bridge={bridge} lifecycleRevision={lifecycleRevision} onSaved={created} onClose={()=>setDialog(false)}/>}
 </section>;
}

function MaterialDialog({project,bridge,lifecycleRevision,onSaved,onClose}){
 const [type,setType]=useState('操作卡'),[title,setTitle]=useState(''),[body,setBody]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const request=useRef(crypto.randomUUID());
 async function save(){
  if(busy)return;if(!title.trim()||!body.trim()){setError('请填写标题和正文。');return;}
  setBusy(true);setError('');
  try{const result=await bridge.api('/api/project/materials',{project,type,title:title.trim(),body,request_id:request.current,lifecycle_revision:lifecycleRevision});await onSaved(result);}
  catch(e){setError(e.message);}
  finally{setBusy(false);}
 }
 return <Modal title="新建项目资料" subtitle="保存为项目内的独立原稿，可在资料库和搜索里找到；不会自动进入知识区。" onClose={onClose}>
  <label className="cv-field">资料类型<select aria-label="资料类型" value={type} disabled={busy} onChange={e=>setType(e.target.value)}>{LIBRARY_TYPES.map(name=><option key={name} value={name}>{name}</option>)}</select></label>
  <label className="cv-field">标题<input aria-label="资料标题" value={title} maxLength={200} disabled={busy} onChange={e=>setTitle(e.target.value)} placeholder="例如：铁棍200目粉压片操作卡"/></label>
  <label className="cv-field">正文<textarea aria-label="资料正文" rows={10} value={body} maxLength={100000} disabled={busy} onChange={e=>setBody(e.target.value)} placeholder="写清条件、步骤、数量或判断依据。"/></label>
  {error&&<p className="cv-error" role="alert">{error}</p>}
  <div className="cv-dialog-actions"><Button disabled={busy} onClick={onClose}>取消</Button><Button variant="primary" icon={Check} disabled={busy||!title.trim()||!body.trim()} onClick={save}>{busy?'正在保存…':'保存资料'}</Button></div>
 </Modal>;
}

export function DecisionDialog({project,node,bridge,onRefresh,onClose}){
 const [title,setTitle]=useState(node?.data.title||''),[body,setBody]=useState(''),[base,setBase]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[latest,setLatest]=useState(null),[dirty,setDirty]=useState(false);
 const request=useRef(crypto.randomUUID());
 useEffect(()=>{let live=true;if(node)bridge.api('/api/project-decision?'+new URLSearchParams({project,id:node.id})).then(d=>{if(live){setBase(d);setTitle(d.title);setBody(d.body);}}).catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[project,node?.id]);
 useEffect(()=>{const leave=e=>{if(dirty){e.preventDefault();e.returnValue='';}};window.addEventListener('beforeunload',leave);return()=>window.removeEventListener('beforeunload',leave);},[dirty]);
 function touch(){request.current=crypto.randomUUID();setDirty(true);}
 function close(){if(dirty&&!window.confirm('放弃尚未保存的修改？'))return;onClose();}
 async function readLatest(){try{setLatest(await bridge.api('/api/project-decision?'+new URLSearchParams({project,id:node.id})));}catch(e){setError(e.message);}}
 async function save(){if(busy)return;setBusy(true);setError('');try{const context=base?.data.context;await bridge.api('/api/project-decision',{project,id:node?.id,revision:base?.revision,fingerprint:base?.fingerprint,title,body,confirm:false,context,request_id:request.current});setDirty(false);await onRefresh();onClose();}catch(e){setError(e.message);}finally{setBusy(false);}}
 return <Modal title={node?'编辑项目记录':'新增项目记录'} onClose={close}>
  <label className="cv-field">记录标题<input aria-label="记录标题" disabled={!!node&&!base} value={title} maxLength={200} onChange={e=>{setTitle(e.target.value);touch();}}/></label>
  <label className="cv-field">记录正文<textarea aria-label="记录正文" disabled={!!node&&!base} rows={9} value={body} maxLength={100000} onChange={e=>{setBody(e.target.value);touch();}} placeholder="记下当前想法、选择、过程或结果。"/></label>
  {error&&<p role="alert" className="cv-error">{error}{node&&<Button disabled={busy} onClick={readLatest}>读取最新原稿</Button>}</p>}{latest&&<div className="ps-warning"><h3>最新原稿</h3><strong>{latest.title}</strong><Markdown body={latest.body} bridge={bridge}/><Button disabled={busy} onClick={()=>{setBase(latest);setLatest(null);setError('已采用最新版本，检查输入后再保存。');touch();}}>保留我的输入，合并到此版本</Button></div>}
  <div className="cv-dialog-actions"><Button disabled={busy} onClick={close}>取消</Button><Button variant="primary" disabled={busy||!!node&&!base||!title.trim()||!body.trim()} onClick={save}>{busy?'正在保存…':'保存'}</Button></div></Modal>;
}
