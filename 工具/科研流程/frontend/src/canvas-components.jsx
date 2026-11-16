import React,{useEffect,useRef,useState,memo} from 'react';
import {createPortal} from 'react-dom';
import {Handle,Position,NodeToolbar,useUpdateNodeInternals,useViewport} from '@xyflow/react';
import {Lightbulb,MessageCircle,CheckSquare,FlaskConical,NotebookPen,ChartNoAxesCombined,BookOpen,
 ChevronDown,ChevronRight,Check,ArrowUpRight,X,Plus,Trash2,Link2,FileText,Sparkles,FolderOpen,SlidersHorizontal} from 'lucide-react';

export const kindInfo={question:{Icon:MessageCircle,color:'#7662b1',label:'研究问题'},idea:{Icon:Lightbulb,color:'#c18c35',label:'想法'},
 task:{Icon:CheckSquare,color:'#4b8c9b',label:'任务'},experiment:{Icon:FlaskConical,color:'#5d9b7a',label:'实验计划'},
 note:{Icon:NotebookPen,color:'#6c84b7',label:'笔记'},result:{Icon:ChartNoAxesCombined,color:'#b77997',label:'结果记录'},
 paper:{Icon:BookOpen,color:'#7c8d6d',label:'文献'}};
export function Button({icon:Icon,children,variant='',...props}){return <button type="button" className={'cv-button '+variant} {...props}>{Icon&&<Icon size={16}/>}<span>{children}</span></button>;}
export function Pill({status}){return <span className={'cv-status '+(status==='已完成'?'done':status==='进行中'?'active':status==='待核查'?'review':'')}><i/>{status}</span>;}
function Ports(){return <>{[['left',Position.Left],['right',Position.Right],['top',Position.Top],['bottom',Position.Bottom]].map(([id,position])=><Handle key={id} id={id} type="source" position={position}/>)}</>;}

export const ResearchNode=memo(function ResearchNode({id,data,selected}){
 const {node,compact,dim}=data,{Icon,color}=kindInfo[node.kind]||kindInfo.note,label=(node.document_kind||kindInfo[node.kind]?.label||'资料')+(node.source_archived?' · 历史':'');
 const {zoom}=useViewport(),small=zoom<.65;
 const [hovered,setHovered]=useState(false);
 const open=e=>{e.stopPropagation();data.open(node);};
 const update=useUpdateNodeInternals();useEffect(()=>{const frame=requestAnimationFrame(()=>update(id));return()=>cancelAnimationFrame(frame);},[id,compact,update]);
 return <div className={'cv-node '+(compact?'compact ':'')+(selected?'selected ':'')+(dim?'dim ':'')+'kind-'+node.kind}
  style={{'--node-color':color}} onMouseEnter={()=>setHovered(true)} onMouseLeave={()=>setHovered(false)}>
  <button type="button" className="cv-node-inspect nodrag nopan" aria-label={'节点设置：'+node.title} title="节点设置" onClick={e=>{e.stopPropagation();data.inspect(node.id);}}><SlidersHorizontal size={14}/></button>
  {!compact&&<Ports/>}
  <NodeToolbar isVisible={selected} position={Position.Top} offset={14}><div className="cv-node-tools nodrag"><span>{label}</span><span>拖动连接点可连线</span></div></NodeToolbar>
  <div className="cv-node-top"><span className="cv-node-icon"><Icon size={compact?25:18} strokeWidth={1.7}/>{compact&&<Ports/>}</span><span className="cv-node-kind">{label}</span><Pill status={node.status}/></div>
  <button type="button" className='cv-node-title cv-source-title nodrag nopan' aria-label={'查看资料：'+node.title} onClick={open}>{node.title}</button>
  <NodeToolbar isVisible={small&&(selected||hovered)} position={Position.Bottom} offset={4}><button type="button" className="cv-zoom-label nodrag nopan" aria-label={'查看资料：'+node.title} onClick={open}>{node.title}</button></NodeToolbar>
  {!compact&&<><p className="cv-node-excerpt">{node.excerpt||node.goal||'写下思路，连接下一步。'}</p><div className="cv-node-bottom"><span><BookOpen size={12}/>{node.paper_ids.length?node.paper_ids.length+' 篇文献':'待补资料'}</span><span>{node.origin==='ai-draft'?<><Sparkles size={12}/>AI 草稿</>:<><FileText size={12}/>打开笔记</>}<ArrowUpRight size={12}/></span></div></>}
  {compact&&<span className={'cv-orbit-status '+(node.status==='已完成'?'done':node.status==='进行中'?'active':'')}>{node.status==='已完成'?<Check size={11}/>:<i/>}</span>}
 </div>;
});

export const ResearchGroup=memo(function ResearchGroup({data}){
 const {group,count,completed,collapsed,toggle,edit}=data;
 return <div className={'cv-group '+(collapsed?'collapsed':'')} style={{'--group-color':group.color}}>
  <Ports/>
  <div className="canvas-group-title"><button className="cv-collapse nodrag" aria-label={(collapsed?'展开':'收起')+group.title} onClick={()=>toggle(group.id)}>{collapsed?<ChevronRight size={16}/>:<ChevronDown size={16}/>}</button><FolderOpen size={15}/><strong>{group.title}</strong><span>{count}</span><button className="cv-group-edit nodrag" aria-label={'编辑分组'+group.title} onClick={()=>edit(group)}>···</button></div>
  {collapsed&&<div className="cv-group-summary">{completed} / {count} 已完成<div><i style={{width:(completed/Math.max(1,count)*100)+'%'}}/></div></div>}
 </div>;
});

export const ResearchDirection=memo(function ResearchDirection({id,data,selected}){
 const {direction:d,expanded,toggle,edit}=data;
 const {zoom}=useViewport(),small=zoom<.65;
 const [hovered,setHovered]=useState(false);
 const update=useUpdateNodeInternals();useEffect(()=>{const frame=requestAnimationFrame(()=>update(id));return()=>cancelAnimationFrame(frame);},[id,d.title,expanded,update]);
 return <div className={'cv-direction '+(expanded?'expanded':'')} style={{'--direction-color':d.color}} onMouseEnter={()=>setHovered(true)} onMouseLeave={()=>setHovered(false)}>
  <div className="cv-direction-main" role="button" tabIndex={0} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();e.stopPropagation();toggle(d.id);}}} aria-label={(expanded?'收起':'展开')+'方向：'+d.title}>
   <span className="cv-direction-symbol"><FolderOpen size={28} strokeWidth={1.5}/><i>{d.node_ids.length}</i><Ports/></span>
   <strong className='cv-inline-label'>{d.title}</strong><small className='cv-inline-label'>{expanded?'收起笔记':'展开 '+d.node_ids.length+' 份笔记'}{expanded?<ChevronDown size={12}/>:<ChevronRight size={12}/>}</small>
  </div><button className="cv-direction-edit nodrag" aria-label={'调整方向：'+d.title} onClick={e=>{e.stopPropagation();edit(d);}}>···</button>
  <NodeToolbar isVisible={small&&(selected||hovered)} position={Position.Bottom} offset={5}><button type="button" className="cv-zoom-label cv-zoom-direction nodrag nopan" onClick={e=>{e.stopPropagation();toggle(d.id);}}><strong>{d.title}</strong><small>{d.node_ids.length} 份资料 · {expanded?'收起':'展开'}</small></button></NodeToolbar>
 </div>;
});

export function Modal({title,subtitle,onClose,children,wide=false}){
 const dialog=useRef(null),closeHandler=useRef(onClose);
 closeHandler.current=onClose;
 useEffect(()=>{const n=dialog.current;n.showModal();const close=e=>{e.preventDefault();closeHandler.current();};n.addEventListener('cancel',close);return()=>n.removeEventListener('cancel',close);},[]);
 return createPortal(<dialog ref={dialog} className={'cv-dialog '+(wide?'wide':'')} aria-label={title}><header><div><h2>{title}</h2>{subtitle&&<p>{subtitle}</p>}</div><Button icon={X} aria-label="关闭" onClick={onClose}/></header><div className="cv-dialog-body">{children}</div></dialog>,document.body);
}

export function Markdown({body,base,bridge}){
 const ref=useRef(null);useEffect(()=>{if(ref.current)ref.current.replaceChildren(bridge.markdown(body,base));},[body,base]);
 return <div className="cv-markdown document-body" ref={ref}/>;
}

export function NoteEditor({node,project,bridge,onSave,onClose,papers}){
 const cacheKey='research:canvas-draft:'+project+':'+node.id,host=useRef(null),editor=useRef(null),latest=useRef({}),[busy,setBusy]=useState(false),[error,setError]=useState(''),[citation,setCitation]=useState(false);
 const [cached]=useState(()=>{try{return JSON.parse(localStorage.getItem(cacheKey));}catch{return null;}});
 const [title,setTitle]=useState(cached?.title||node.title),[baseline,setBaseline]=useState(cached?.fingerprint||node.source_fingerprint),[comparison,setComparison]=useState(null);latest.current.title=title;latest.current.fingerprint=baseline;
 useEffect(()=>{
  const e=new window.toastui.Editor({el:host.current,height:'420px',initialEditType:'wysiwyg',previewStyle:'vertical',language:'zh-CN',usageStatistics:false,
   initialValue:cached?.body??node.body,toolbarItems:[['heading','bold','italic','strike'],['hr','quote'],['ul','ol','task'],['table','link'],['code','codeblock']]});
  editor.current=e;e.moveCursorToEnd(false);let timer;const stash=()=>{try{localStorage.setItem(cacheKey,JSON.stringify({body:e.getMarkdown(),title:latest.current.title,fingerprint:latest.current.fingerprint}));}catch{}};latest.current.stash=stash;
  e.on('change',()=>{clearTimeout(timer);timer=setTimeout(stash,300);});return()=>{clearTimeout(timer);if(!latest.current.saved)stash();e.destroy();};
 },[]);
 async function save(){setBusy(true);setError('');try{const body=editor.current.getMarkdown();if(body.length>node.max_body)throw Error('这份旧进展字段最多 '+node.max_body+' 字；长篇内容请新建笔记节点。');
  await onSave({title,body},baseline);latest.current.saved=true;localStorage.removeItem(cacheKey);onClose();}catch(e){setError(e.message);}finally{setBusy(false);}}
 async function compare(){try{const fresh=await bridge.api('/api/project/canvas-node?'+new URLSearchParams({project,id:node.id}));setComparison(fresh);}catch(e){setError(e.message);}}
 return <Modal title="节点笔记" subtitle="沿原稿保存，保留修改历史；未保存内容在本机保留。" onClose={()=>{if(!busy)onClose();}} wide>
  {baseline!==node.source_fingerprint&&<p className="cv-notice">发现本机草稿，同时来源也有变化。可查看当前原稿，合并需要的内容后再保存。</p>}
  <label className="cv-field">标题<input value={title} disabled={busy} onChange={e=>{setTitle(e.target.value);latest.current.title=e.target.value;latest.current.stash?.();}} maxLength={200}/></label>
  <div className="cv-editor-host" inert={busy} ref={host}/>
  {comparison&&<details className="cv-comparison" open><summary>当前原稿 · {comparison.title}</summary><Markdown body={comparison.body} base={comparison.document_id} bridge={bridge}/><p className="cv-notice">编辑区保留你的草稿。请先合并需要的内容，再更新保存基线。</p><Button disabled={busy} onClick={()=>{setBaseline(comparison.source_fingerprint);latest.current.fingerprint=comparison.source_fingerprint;latest.current.stash?.();setComparison(null);setError('');}}>已核对差异，保留编辑继续保存</Button></details>}
  {error&&<p className="cv-error" role="alert">{error}</p>}
  <div className="cv-dialog-actions"><Button icon={BookOpen} disabled={busy} onClick={()=>setCitation(true)}>插入文献引用</Button><Button disabled={busy} onClick={compare}>查看当前原稿</Button><small>{node.max_body<100000?'原进展字段 · 最多 '+node.max_body+' 字':'Markdown 主稿'}</small><Button icon={Check} variant="primary" onClick={save} disabled={busy}>{busy?'正在保存…':'保存笔记'}</Button></div>
  {citation&&<CitationPicker papers={papers} onClose={()=>setCitation(false)} onInsert={text=>{const e=editor.current;e.focus();e.insertText(text);setCitation(false);}}/>}
 </Modal>;
}

export function CitationPicker({papers,onClose,onInsert}){
 const [query,setQuery]=useState(''),[selected,setSelected]=useState(''),[kind,setKind]=useState('reference'),[location,setLocation]=useState(''),[error,setError]=useState('');
 const choices=papers.filter(p=>(p.title+' '+p.id).toLowerCase().includes(query.toLowerCase()));
 function insert(){if(!selected){setError('请选择一篇文献。');return;}if(kind==='pdf'&&!/^\d+(?:\s*[-–,，]\s*\d+)*$/.test(location)){setError('PDF 页码请填写实际页序，例如 3 或 3–5。');return;}if(kind!=='reference'&&!location.trim()){setError('填写实际来源位置，或选择只引用文献。');return;}
  onInsert('[[文献/条目/'+selected+']]'+(kind==='reference'?'':kind==='pdf'?' · PDF 第 '+location.trim()+' 页':' · '+location.trim()));}
 return <Modal title="引用项目文献" subtitle="填写实际核对的位置；引用不会改变阅读等级。" onClose={onClose}>
  <input className="cv-search" aria-label="搜索引用文献" placeholder="搜索题名或文献 ID" value={query} onChange={e=>setQuery(e.target.value)}/>
  <div className="cv-pick-list">{choices.map(p=><label key={p.id} className={'cv-pick-row '+(p.id===selected?'picked':'')}><input type="radio" name="citation" value={p.id} checked={p.id===selected} onChange={()=>setSelected(p.id)}/><span><strong>{p.title}</strong><small>{p.id}</small></span></label>)}{!choices.length&&<p className="cv-empty">项目文献池暂无匹配项，先把所需论文加入文献池。</p>}</div>
  <div className="cv-two-fields"><label className="cv-field">引用范围<select value={kind} onChange={e=>setKind(e.target.value)}><option value="reference">只引用文献</option><option value="pdf">PDF 页码</option><option value="section">章节或图号</option></select></label>{kind!=='reference'&&<label className="cv-field">实际位置<input value={location} onChange={e=>setLocation(e.target.value)} placeholder={kind==='pdf'?'例如 3–5':'例如 Results / Figure 2'}/></label>}</div>
  {error&&<p className="cv-error">{error}</p>}<div className="cv-dialog-actions"><Button icon={Link2} variant="primary" onClick={insert}>插入引用</Button></div>
 </Modal>;
}
