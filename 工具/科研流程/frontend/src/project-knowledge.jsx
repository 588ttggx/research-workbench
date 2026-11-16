import React,{useState} from 'react';
import {Button,Markdown,Modal} from './canvas-components.jsx';
import {EditForm,KnowledgeForm} from './project-forms.jsx';
import {KnowledgeGraph} from './project-knowledge-graph.jsx';
import {ProjectPapers} from './project-papers.jsx';

export function ProjectKnowledge({project,bridge,data,onRefresh,archived,initialModule='',focusDocument=''}){
 const [moduleId,setModule]=useState(initialModule),[form,setForm]=useState(null),[error,setError]=useState(''),[query,setQuery]=useState(''),[graph,setGraph]=useState(false);
 const [changing,setChanging]=useState(false);
 const module=data.modules.find(m=>m.id===moduleId),docs=data.documents.filter(d=>(!moduleId||moduleId==='uncategorized'?moduleId!=='uncategorized'||data.uncategorized.includes(d.id):data.assignments[d.id]?.includes(moduleId))&&[d.title,d.excerpt].join(' ').toLowerCase().includes(query.toLowerCase()));
 React.useEffect(()=>{if(focusDocument){setModule('');setGraph(false);requestAnimationFrame(()=>document.getElementById('knowledge-'+focusDocument)?.scrollIntoView({block:'center'}));}},[focusDocument,data]);
 const review=module&&data.documents.find(d=>d.id===module.review_document_id);
 const [reviewBody,setReviewBody]=useState(null),[reviewError,setReviewError]=useState('');
 React.useEffect(()=>{let alive=true;setReviewBody(null);setReviewError('');if(review)bridge.api('/api/workspace/document?id='+encodeURIComponent(review.id)).then(v=>{if(alive)setReviewBody(v.body);}).catch(e=>{if(alive)setReviewError(e.message);});return()=>{alive=false;};},[review?.id,review?.sha]);
 async function change(op,payload,request=crypto.randomUUID(),fingerprint=data.fingerprint){setChanging(true);setError('');try{await bridge.api('/api/project/knowledge/change',{project,op,request_id:request,fingerprint,lifecycle_revision:data.lifecycle_revision,...payload});await onRefresh();}catch(e){setError(e.message);throw e;}finally{setChanging(false);}}
 function tree(parent='',depth=0){return data.modules.filter(m=>(m.parent_id||'')===parent).map(m=><React.Fragment key={m.id}><button className={'ps-module'+(moduleId===m.id?' active':'')} style={{paddingLeft:14+depth*18}} onClick={()=>{setModule(m.id);setGraph(false);}}>{m.title}<small>{Object.values(data.assignments).filter(ms=>ms.includes(m.id)).length}</small></button>{tree(m.id,depth+1)}</React.Fragment>);}
 async function publish(doc){try{const current=await bridge.api('/api/workspace/document?id='+encodeURIComponent(doc.id));await change('share',{id:doc.id,document_fingerprint:current.fingerprint,global_knowledge:!doc.global_knowledge});setForm(null);}catch(e){setError(e.message);}}
 return <div className={"ps-knowledge"+(graph?" is-graph":"")} aria-label="项目知识库">
   <header className="ps-page-heading"><div><h2>{module?.title||(moduleId==='uncategorized'?'未分类知识':'项目知识库')}</h2><p>显示当前研究引用和本人选入的知识。</p></div><div className="ps-actions"><Button variant="primary" disabled={archived||changing} onClick={()=>setForm({kind:'selection'})}>选择相关知识</Button><Button onClick={()=>setGraph(!graph)}>{graph?'模块目录':'知识关系图'}</Button><Button disabled={archived} onClick={()=>setForm({kind:'note'})}>新建知识笔记</Button>{module&&!graph&&<><Button disabled={archived} onClick={()=>setForm({kind:'module',item:module})}>调整模块</Button><Button disabled={archived} onClick={()=>{if(window.confirm('移除模块？子模块提升到上级，综述与笔记保留。'))change('remove_module',{id:module.id}).then(()=>setModule('')).catch(()=>{});}}>移除模块</Button></>}</div></header>
   {!graph&&<aside className="ps-modules"><div className="ps-inline"><h2>知识模块</h2><Button disabled={archived} onClick={()=>setForm({kind:'module'})}>新增</Button></div><button className={'ps-module'+(!moduleId?' active':'')} onClick={()=>setModule('')}>全部知识<small>{data.documents.length}</small></button>{tree()}<button className={'ps-module'+(moduleId==='uncategorized'?' active':'')} onClick={()=>setModule('uncategorized')}>未分类知识<small>{data.uncategorized.length}</small></button></aside>}
   <div className="ps-knowledge-content">
    {error&&<p className="cv-error" role="alert">{error}</p>}
    {graph?<KnowledgeGraph project={project} bridge={bridge} knowledge={data} archived={archived}/>:<>
    <ProjectPapers project={project} data={data} bridge={bridge} onRefresh={onRefresh} archived={archived}/>
    {module&&<section className="ps-panel" aria-label="模块综述"><header><h3>模块综述</h3><div className="ps-actions">{review?(review.project_owned?<Button disabled={archived} onClick={()=>setForm({kind:"summary",item:review})}>编辑综述</Button>:<Button onClick={()=>bridge.openDocument(review.id)}>查看综述原稿</Button>):<Button disabled={archived} onClick={()=>setForm({kind:'summary'})}>撰写综述</Button>}<Button disabled={archived} onClick={()=>setForm({kind:'bind'})}>{review?'更换或清除综述':'选择已有综述'}</Button></div></header>{reviewError&&<p role="alert">{reviewError}</p>}{review?(reviewBody===null?<p>正在读取综述…</p>:<><Markdown body={reviewBody} base={review.id} bridge={bridge}/><small className={module.review_stale?"ps-warning":"ps-muted"}>{module.review_stale?"模块内的详细笔记已变化，请核对是否需要修订综述。":"综述已记录当前模块资料版本。"}</small></>):<p className="ps-muted">可以先积累详细笔记，再手写或让 AI 起草综述。</p>}</section>}
    {!module&&!data.modules.length&&<div className="ps-empty"><h3>把项目中学到的知识分模块积累</h3><p>建立模块后，先读综述，再查详细笔记；过程记录留在进展阶段中。</p><Button disabled={archived} onClick={()=>setForm({kind:'module'})}>建立第一个模块</Button></div>}
    {module&&data.modules.some(m=>m.parent_id===module.id)&&<div className="ps-submodules">{data.modules.filter(m=>m.parent_id===module.id).map(m=><Button key={m.id} onClick={()=>setModule(m.id)}>{m.title}</Button>)}</div>}
    <section className="ps-panel"><header><h3>详细笔记 <small>{docs.filter(d=>d.id!==review?.id).length}</small></h3><input aria-label="搜索项目知识" placeholder="搜索知识标题和摘要" value={query} onChange={e=>setQuery(e.target.value)}/></header>
     {docs.filter(d=>d.id!==review?.id).map(doc=><article className={"ps-knowledge-note"+(focusDocument===doc.id?" focused":"")} id={"knowledge-"+doc.id} key={doc.id}><button className="ps-text-link" onClick={()=>bridge.openDocument(doc.id)}>{doc.display_title||doc.title}</button><p>{doc.excerpt}</p><div className="ps-actions"><small>{doc.project_owned?'本项目原稿':doc.global_knowledge?'全局知识引用':'外部原稿引用'}{doc.knowledge_scope_reason?' · '+doc.knowledge_scope_reason:''}</small>{doc.project_owned&&<><Button disabled={archived} onClick={()=>bridge.editDocument(doc.id)}>编辑原稿</Button><Button disabled={archived||changing} onClick={()=>setForm({kind:'share',item:doc})}>全局可见性</Button></>}<Button disabled={archived} onClick={()=>setForm({kind:'assign',item:doc})}>所属模块</Button><Button disabled={archived||changing} onClick={()=>change('select',{document_ids:[doc.id],selected:false}).catch(()=>{})}>移出本项目知识库</Button>{doc.knowledge_sources?.length>0&&<Button onClick={async()=>{try{setForm({kind:'sources',sources:await bridge.api('/api/project/knowledge/sources?id='+encodeURIComponent(doc.id))});}catch(e){setError(e.message);}}}>核对来源</Button>}</div></article>)}
     {!docs.filter(d=>d.id!==review?.id).length&&<p className="ps-muted">这里还没有详细笔记，可以新建，或从阶段记录中提炼。</p>}
    </section>
    </>}
   </div>
   {form?.kind==='module'&&<EditForm project={project} id={'module:'+(form.item?.id||moduleId||'new')} title={form.item?'调整知识模块':'新建知识模块'} version={data.fingerprint} initial={{title:form.item?.title||'',parent_id:form.item?(form.item.parent_id||''):(module?.id||''),order:form.item?.order??data.modules.length}}
     fields={[{name:'title',label:'模块名称',type:'text'},{name:'parent_id',label:'上级模块',type:'select',options:[{value:'',label:'顶级模块'},...data.modules.filter(m=>m.id!==form.item?.id).map(m=>({value:m.id,label:m.title}))]}]} onClose={()=>setForm(null)} onSubmit={(v,r)=>change(form.item?'update_module':'create_module',{id:form.item?.id,title:v.title,parent_id:v.parent_id,order:Number(v.order)},r,v.__fingerprint)}/>}
   {['note','summary'].includes(form?.kind)&&<KnowledgeForm project={project} bridge={bridge} knowledge={data} existing={form.item} summaryModule={form.kind==='summary'?module:null} onSaved={onRefresh} onClose={()=>setForm(null)}/>}
   {form?.kind==='bind'&&<EditForm project={project} id={'bind:'+module.id} title="绑定模块综述" version={data.fingerprint} initial={{document_id:module.review_document_id||''}} fields={[{name:'document_id',label:'知识稿',type:'select',options:[{value:'',label:'暂不指定综述'},...data.documents.map(d=>({value:d.id,label:d.title}))]}]} onClose={()=>setForm(null)} onSubmit={(v,r)=>change('bind_summary',{id:module.id,document_id:v.document_id||null},r,v.__fingerprint)}/>}
   {form?.kind==='assign'&&<AssignModules project={project} data={data} doc={form.item} onClose={()=>setForm(null)} onSubmit={ids=>change('assign',{document_ids:[form.item.id],module_ids:ids})}/>}
   {form?.kind==='selection'&&<SelectKnowledge data={data} onClose={()=>setForm(null)} onSave={(add_ids,remove_ids)=>change('change_selection',{add_ids,remove_ids})}/>}
   {form?.kind==='share'&&<Modal title="知识原稿的全局可见性" onClose={()=>setForm(null)}><p>{form.item.title}</p><p>{form.item.global_knowledge?'这份原稿目前在全局知识区显示。':'这份原稿目前仅在采用它的项目中显示。'}</p><Button disabled={changing} onClick={()=>publish(form.item)}>{form.item.global_knowledge?'从全局知识区撤下':'在全局知识区显示'}</Button></Modal>}
   {form?.kind==='sources'&&<Modal title="知识来源核对" onClose={()=>setForm(null)}>{form.sources.map((s,i)=><article key={i}><strong>{s.title}</strong><p>{s.missing?'来源记录已移除或无法读取':s.changed?'来源记录已变化，请核对知识是否需要修订':'来源记录内容未变化'}</p><Button onClick={()=>s.stage_id?location.assign('#projects?'+new URLSearchParams({project,view:'progress',stage:s.stage_id})):bridge.openDocument(s.document_id)}>打开当前来源</Button><Button onClick={async()=>{try{const value=await bridge.api('/api/project/knowledge/source-version?'+new URLSearchParams({id:s.document_id,sha:s.document_sha}));setForm({kind:'source-version',body:value.body});}catch(e){setError(e.message);}}}>查看当时版本</Button></article>)}</Modal>}
   {form?.kind==='source-version'&&<Modal title="提炼时的来源版本" wide onClose={()=>setForm(null)}><Markdown body={form.body} bridge={bridge}/></Modal>}
  </div>;
}

function SelectKnowledge({data,onClose,onSave}){
 const [initial]=useState(()=>new Set(data.documents.map(d=>d.id))),[chosen,setChosen]=useState(initial);
 const [query,setQuery]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const matches=(data.candidates||[]).filter(d=>[d.title,d.display_title,d.source_project].join(' ').toLowerCase().includes(query.trim().toLowerCase()));
 const added=[...chosen].filter(id=>!initial.has(id)),removed=[...initial].filter(id=>!chosen.has(id));
 async function save(){setBusy(true);setError('');try{await onSave(added,removed);onClose();}catch(e){setError(e.message);}finally{setBusy(false);}}
 return <Modal title="选择与当前研究相关的知识" wide onClose={busy?()=>{}:onClose}>
   <input aria-label="查找知识原稿" placeholder="搜索知识标题或来源项目" value={query} onChange={e=>setQuery(e.target.value)}/>
   <div className="ps-knowledge-picker">{matches.slice(0,100).map(doc=><label key={doc.id} className="ps-task-select"><input type="checkbox" aria-label={doc.display_title||doc.title} disabled={busy} checked={chosen.has(doc.id)} onChange={e=>{const next=new Set(chosen);e.target.checked?next.add(doc.id):next.delete(doc.id);setChosen(next);}}/>{doc.display_title||doc.title}</label>)}</div>
   {matches.length>100&&<p className="ps-muted">显示前 100 份，可按标题缩小范围。</p>}{!matches.length&&<p>没有匹配的知识。</p>}
   {error&&<p role="alert">{error}</p>}
   <div className="cv-dialog-actions"><Button disabled={busy} onClick={onClose}>取消</Button><Button disabled={busy||!(added.length||removed.length)} onClick={save}>保存相关知识范围</Button></div>
 </Modal>;
}

function AssignModules({project,data,doc,onClose,onSubmit}){
 const [chosen,setChosen]=useState(new Set(data.assignments[doc.id]||[])),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 return <Modal title="知识所属模块" onClose={onClose}><p>可以在多个模块引用同一篇知识。</p>{data.modules.map(m=><label key={m.id} className="ps-task-select"><input type="checkbox" checked={chosen.has(m.id)} onChange={e=>setChosen(old=>{const n=new Set(old);e.target.checked?n.add(m.id):n.delete(m.id);return n;})}/>{m.title}</label>)}{error&&<p role="alert">{error}</p>}<div className="cv-dialog-actions"><Button onClick={onClose}>取消</Button><Button disabled={busy} onClick={async()=>{setBusy(true);try{await onSubmit([...chosen]);onClose();}catch(e){setError(e.message);}finally{setBusy(false);}}}>保存模块归属</Button></div></Modal>;
}
