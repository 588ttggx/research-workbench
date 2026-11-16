import React,{useEffect,useMemo,useRef,useState} from 'react';
import {ReactFlow,Background,Controls,MiniMap,ConnectionMode,applyNodeChanges} from '@xyflow/react';
import ELK from 'elkjs/lib/elk.bundled.js';
import {Button,ResearchNode,ResearchDirection,Modal} from './canvas-components.jsx';
import {toFlow,arrange} from './canvas-model.mjs';
import {knowledgeGraph} from './project-knowledge-graph-model.mjs';
import {DirectionDialog} from './canvas-panels.jsx';

const types={research:ResearchNode,researchDirection:ResearchDirection},elk=new ELK();
export function KnowledgeGraph({project,knowledge,bridge,archived}){
 const [raw,setRaw]=useState(null),[nodes,setNodes]=useState([]),[edges,setEdges]=useState([]),[expanded,setExpanded]=useState(new Set()),[selected,setSelected]=useState(''),[query,setQuery]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false),[hiddenDialog,setHiddenDialog]=useState(false),[edge,setEdge]=useState(null),[undo,setUndo]=useState(null);
 const [direction,setDirection]=useState(null);
 const flow=useRef(null),board=useRef(null),flight=useRef(false),data=useMemo(()=>raw?knowledgeGraph(raw,knowledge):null,[raw,knowledge]);
 const viewKey='research:knowledge-viewport:'+project;
 async function refresh(){const value=await bridge.api('/api/project/canvas?'+new URLSearchParams({project,scope:'knowledge'}));setRaw(value);return value;}
 useEffect(()=>{refresh().catch(e=>setError(e.message));},[project,knowledge]);
 async function change(op,payload){if(flight.current||archived)return;flight.current=true;setBusy(true);setError('');if(op==='visibility')setRaw(old=>({...old,hidden_node_ids:payload.hidden_node_ids}));try{const value=await bridge.api('/api/project/canvas',{project,op,scope:'knowledge',fingerprint:raw.fingerprint,...payload});setRaw(value);return value;}catch(e){setError(e.message);await refresh();throw e;}finally{flight.current=false;setBusy(false);}}
 function toggle(id){setExpanded(old=>{const next=new Set(old);next.has(id)?next.delete(id):next.add(id);return next;});}
 function open(node){return node.source.kind==='paper'?bridge.openPaper(node.source.paper_id):bridge.openDocument(node.document_id);}
 useEffect(()=>{if(!data)return;const next=toFlow(data,{compact:data.display==='compact',expanded,selected,query});setNodes(next.nodes.map(n=>({...n,data:{...n.data,toggle,edit:d=>{if(!archived)setDirection(d);},inspect:setSelected,open}})));setEdges(next.edges);},[data,expanded,selected,query]);
 async function layout(){if(!data||busy)return;const original=Object.fromEntries(data.nodes.map(n=>[n.id,n.position])),directions=Object.fromEntries(data.directions.map(d=>[d.id,d.position]));try{const points=await arrange(elk,data,data.display==='compact');await change('move',{positions:Object.fromEntries(data.nodes.map(n=>[n.id,points[n.id]])),direction_positions:Object.fromEntries(data.directions.map(d=>[d.id,points['direction:'+d.id]])),manual:true});setUndo({positions:original,direction_positions:directions});requestAnimationFrame(()=>flow.current?.fitView({padding:.15,maxZoom:1}));}catch(e){setError(e.message);}}
 if(!data)return <p role="status">{error||'正在读取项目知识关系图…'}</p>;
 const node=data.nodes.find(n=>n.id===selected),hidden=new Set(raw.hidden_node_ids||[]);
 let viewport;try{viewport=JSON.parse(sessionStorage.getItem(viewKey));}catch{}
 return <section className="ps-graph-section cv-root ps-knowledge-graph" ref={board} aria-busy={busy}>
  <div className="ps-inline"><div className="cv-segments" aria-label="节点显示方式">{[['cards','卡片'],['compact','圆点']].map(([id,label])=><button disabled={archived||busy} key={id} className={data.display===id?'active':''} onClick={()=>change('display',{display:id}).catch(()=>{})}>{label}</button>)}</div><Button onClick={()=>setExpanded(old=>old.size?new Set():new Set(data.directions.map(d=>d.id)))}>{expanded.size?'方向概览':'展开全部笔记'}</Button><Button onClick={()=>setHiddenDialog(true)}>显示资料</Button><input aria-label="搜索知识图节点" placeholder="搜索节点" value={query} onChange={e=>setQuery(e.target.value)}/><Button disabled={archived||busy} onClick={layout}>重新排版</Button>{undo&&<Button disabled={archived||busy} onClick={()=>change('move',undo).then(()=>setUndo(null)).catch(()=>{})}>撤销排版</Button>}<Button onClick={()=>document.fullscreenElement?document.exitFullscreen():board.current.requestFullscreen()}>全屏</Button></div>
  <p className="ps-muted">{data.nodes.length} 份当前研究资料 · 点击打开原稿；右上角调整节点。方向可展开，拖动空白平移。</p>{error&&<p role="alert" className="cv-error">{error}</p>}
  <div className="ps-graph"><ReactFlow nodes={nodes} edges={edges} nodeTypes={types} connectionMode={ConnectionMode.Loose} onInit={value=>{flow.current=value;}} nodesDraggable={!archived&&!busy} nodesConnectable={!archived&&!busy} deleteKeyCode={null} minZoom={.08} maxZoom={2.5} zoomOnDoubleClick={false} panOnDrag panOnScroll fitView={!viewport} defaultViewport={viewport||{x:0,y:0,zoom:1}} fitViewOptions={{padding:.15,maxZoom:1}} onMoveEnd={(_,v)=>sessionStorage.setItem(viewKey,JSON.stringify(v))}
   onNodesChange={changes=>setNodes(old=>applyNodeChanges(changes.filter(c=>c.type!=='remove'),old))} onNodeClick={(_,n)=>n.type==='researchDirection'?toggle(n.data.direction.id):Promise.resolve(open(n.data.node)).catch(e=>setError(e.message))}
   onNodeDragStop={(_,n)=>change('move',n.type==='researchDirection'?{direction_positions:{[n.data.direction.id]:n.position},positions:{},manual:true}:{positions:{[n.id]:n.position},manual:true}).catch(()=>{})}
   onConnect={c=>change('edge',{source:c.source,target:c.target,label:'关联'}).catch(()=>{})} onEdgeClick={(_,e)=>{if(e.data.original.kind!=='membership')setEdge(e.data.original);}}>
   <Background gap={24}/><Controls showInteractive={false}/><MiniMap pannable zoomable/>
  </ReactFlow></div>
  {!nodes.length&&<p className="ps-empty">暂无可见知识节点，可从“选择相关知识”纳入资料，或在“显示资料”恢复隐藏节点。</p>}
  {node&&<Modal title={node.title} onClose={()=>setSelected('')}><p>{node.excerpt}</p><label className="cv-field">研究方向<select aria-label="知识节点研究方向" disabled={archived||busy} value={node.direction||''} onChange={e=>change('update',{node_id:node.id,fields:{direction:e.target.value},source_fingerprint:node.source_fingerprint}).catch(()=>{})}>{raw.directions.map(d=><option key={d.id} value={d.id}>{d.title}</option>)}</select></label><div className="ps-actions"><Button onClick={()=>open(node)}>打开原稿</Button>{node.document_id&&node.editable&&<Button disabled={archived} onClick={()=>bridge.editDocument(node.document_id)}>编辑原稿</Button>}<Button disabled={archived||busy} onClick={()=>change('visibility',{hidden_node_ids:[...hidden,node.id]}).then(()=>setSelected('')).catch(()=>{})}>隐藏图中节点</Button></div></Modal>}
  {direction&&<DirectionDialog direction={direction} onSave={payload=>change('direction',payload)} onClose={()=>setDirection(null)}/>}
  {hiddenDialog&&<Modal title="显示知识资料" onClose={()=>setHiddenDialog(false)}>{data.nodes.map(n=><label className="ps-task-select" key={n.id}><input type="checkbox" disabled={archived||busy} checked={!hidden.has(n.id)} onChange={e=>{const next=new Set(hidden);e.target.checked?next.delete(n.id):next.add(n.id);change('visibility',{hidden_node_ids:[...next]}).catch(()=>{});}}/>{n.title}</label>)}</Modal>}
  {edge&&<Modal title={edge.label||'资料关联'} onClose={()=>setEdge(null)}><p>{edge.reason||'组织关联，可沿两端资料查看来源。'}</p>{!['direction-link','membership'].includes(edge.kind)&&<Button disabled={archived||busy} onClick={()=>change(edge.organization?'remove_auto_edge':'remove_edge',{edge_id:edge.id}).then(()=>setEdge(null)).catch(()=>{})}>移除连线</Button>}</Modal>}
 </section>;
}
