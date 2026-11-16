export const nodeSize=compact=>compact?{width:145,height:155}:{width:260,height:174};

export function toFlow(data,{compact=false,collapsed=new Set(),selected='',query='',expanded=null}={}){
 const hidden=new Set(data.hidden_node_ids||[]);
 if(hidden.size){
  const directions=(data.directions||[]).map(d=>({...d,node_ids:d.node_ids.filter(id=>!hidden.has(id))})).filter(d=>!data.directions.find(old=>old.id===d.id).node_ids.length||d.node_ids.length);
  data={...data,nodes:data.nodes.filter(n=>!hidden.has(n.id)),directions,
   edges:data.edges.filter(e=>!hidden.has(e.source)&&!hidden.has(e.target)),auto_edges:(data.auto_edges||[]).filter(e=>!hidden.has(e.source)&&!hidden.has(e.target))};
 }
 const size=nodeSize(compact),frames=new Map(),groups=data.groups||[],members=new Map();
 for(const group of groups)members.set(group.id,(data.nodes||[]).filter(n=>n.group===group.id));
 const nodes=[];
 for(const group of groups){
  if(data.show_frames===false)continue;
  const children=members.get(group.id);if(!children.length)continue;
  const x=Math.min(...children.map(n=>n.position.x))-28,y=Math.min(...children.map(n=>n.position.y))-62;
  const closed=collapsed.has(group.id),width=closed?282:Math.max(...children.map(n=>n.position.x+size.width))-x+28;
  const height=closed?106:Math.max(...children.map(n=>n.position.y+size.height))-y+28;
  frames.set(group.id,{x,y});
  nodes.push({id:'group:'+group.id,type:'researchGroup',position:{x,y},style:{width,height},
   data:{group,count:children.length,completed:children.filter(n=>n.status==='已完成').length,collapsed:closed,
    origin:{x,y},members:children.map(n=>({id:n.id,position:{...n.position}}))},
   selectable:false,dragHandle:'.canvas-group-title',zIndex:-1});
 }
 const directions=data.directions||[],visible=new Set();
 for(const [i,d] of directions.entries()){
  const all=expanded===null||expanded.has(d.id),peek=(d.node_ids||[]).slice(-2);
  for(const id of d.node_ids||[]){const n=data.nodes.find(n=>n.id===id),active=n?.source?.kind==='question'&&!['已完成','不采用','暂停','暂缓'].includes(n.status);if(all||active||peek.includes(id)||id===selected||query&&n?.title.toLowerCase().includes(query.toLowerCase()))visible.add(id);}
  nodes.push({id:'direction:'+d.id,type:'researchDirection',position:d.position||{x:i*520,y:0},
   style:{width:200,height:160},data:{direction:d,expanded:all},ariaLabel:'研究方向：'+d.title});
 }
 for(const node of data.nodes||[]){
  if(directions.length&&!visible.has(node.id))continue;
  if(collapsed.has(node.group))continue;
  const frame=frames.get(node.group),position=frame?{x:node.position.x-frame.x,y:node.position.y-frame.y}:node.position;
  const dim=!!query&&!`${node.title} ${node.body||''} ${node.status} ${(node.paper_ids||[]).join(' ')}`.toLowerCase().includes(query.toLowerCase());
  nodes.push({id:node.id,type:'research',position,parentId:frame?'group:'+node.group:undefined,
   selected:node.id===selected,style:{width:size.width,height:size.height},
   data:{node,compact,dim},ariaLabel:node.title});
 }
 const live=new Set(nodes.map(n=>n.id));
 const destination=id=>{const n=data.nodes.find(n=>n.id===id);return n&&collapsed.has(n.group)&&frames.has(n.group)?'group:'+n.group:n&&directions.length&&!visible.has(id)?'direction:'+n.direction:id;};
 const membership=data.nodes.filter(n=>visible.has(n.id)).map(n=>({id:'member:'+n.id,source:'direction:'+n.direction,target:n.id,label:'',organization:true,kind:'membership'}));
 const cross=new Map();
 for(const edge of [...(data.edges||[]),...(data.auto_edges||[])]){
  const a=data.nodes.find(n=>n.id===edge.source)?.direction,b=data.nodes.find(n=>n.id===edge.target)?.direction;
  if(!a||!b||a===b)continue;const ids=[a,b].sort(),key=ids.join('|'),old=cross.get(key);
  if(old)old.count++;else cross.set(key,{id:'cross:'+key,source:'direction:'+ids[0],target:'direction:'+ids[1],count:1,kind:'direction-link',organization:true});
 }
 const aggregate=[...cross.values()].map(e=>({...e,label:e.count+' 条跨方向关联',reason:'汇总两个方向笔记之间的实际引用和内容线索。'}));
 const original=[...(data.edges||[]),...(data.auto_edges||[]),...membership,...aggregate],seen=new Set();
 const centers=new Map(nodes.map(n=>[n.id,{x:n.position.x+Number(n.style?.width||0)/2,y:n.position.y+Number(n.style?.height||0)/2}]));
 function ports(a,b){const from=centers.get(a),to=centers.get(b);if(!from||!to)return {};const dx=to.x-from.x,dy=to.y-from.y;return Math.abs(dx)>Math.abs(dy)?{sourceHandle:dx>=0?'right':'left',targetHandle:dx>=0?'left':'right'}:{sourceHandle:dy>=0?'bottom':'top',targetHandle:dy>=0?'top':'bottom'};}
 const edges=original.map(e=>({...e,source:destination(e.source),target:destination(e.target),...ports(destination(e.source),destination(e.target)),type:'default',
   data:{original:e},animated:e.source===selected||e.target===selected,
   markerEnd:e.organization?undefined:{type:'arrowclosed',width:16,height:16},style:{stroke:e.source===selected||e.target===selected?'#7060b5':e.kind==='membership'?'#c4bdde':'#9daabd',strokeWidth:e.kind==='membership'?1.4:1.8,strokeDasharray:e.kind==='ai-content'?'5 5':undefined},
   labelStyle:{fill:'#6b7183',fontSize:11},labelBgStyle:{fill:'#fcfbff',fillOpacity:.95},labelBgPadding:[7,4],labelBgBorderRadius:7
  })).filter(e=>{if(e.source===e.target||!live.has(e.source)||!live.has(e.target))return false;const key=[...([e.source,e.target].sort()),e.label].join('|');if(seen.has(key))return false;seen.add(key);return true;});
 return {nodes,edges};
}

export function absolutePositions(nodes){
 const map=new Map(nodes.map(n=>[n.id,n])),result={};
 for(const node of nodes){
  if(node.type==='researchDirection')continue;
  if(node.type==='researchGroup'){
   if(node.data.collapsed)for(const member of node.data.members){result[member.id]={
    x:member.position.x+node.position.x-node.data.origin.x,y:member.position.y+node.position.y-node.data.origin.y};}
   continue;
  }
  const parent=map.get(node.parentId),p=node.position;
  result[node.id]={x:p.x+(parent?.position.x||0),y:p.y+(parent?.position.y||0)};
 }
 return result;
}

export async function arrange(elk,data,compact=false,direction='RIGHT'){
 const size=nodeSize(compact);
 if(data.directions?.length){
  // ELK's stress layout gives an unconstrained network, rather than a step flow.
  const children=[...data.directions.map(d=>({id:'direction:'+d.id,width:200,height:160})),...data.nodes.map(n=>({id:n.id,...size}))];
  const edges=[...data.nodes.map(n=>({id:'member:'+n.id,source:'direction:'+n.direction,target:n.id})),...(data.auto_edges||[]),...data.edges];
  const graph={id:'root',layoutOptions:{'elk.algorithm':'stress','elk.stress.desiredEdgeLength':'230','elk.spacing.nodeNode':'85','elk.aspectRatio':'1.6','elk.randomSeed':'42'},children,
   edges:edges.map(e=>({id:e.id,sources:[e.source],targets:[e.target]}))};
  const laid=await elk.layout(graph);
  if(laid.height>laid.width)for(const n of laid.children){const x=n.x+n.width/2,y=n.y+n.height/2;n.x=y-n.width/2;n.y=x-n.height/2;}
  const spaced=await elk.layout({...laid,layoutOptions:{'elk.algorithm':'sporeOverlap','elk.spacing.nodeNode':'70'}});
  return Object.fromEntries(spaced.children.map(n=>[n.id,{x:n.x,y:n.y}]));
 }
 // ELK performs the layout; the adapter only translates source IDs and dimensions.
 const algorithm=data.edges.length?'layered':'box';
 const graph={id:'root',layoutOptions:{'elk.algorithm':algorithm,'elk.direction':direction,'elk.aspectRatio':'1.5',
  'elk.hierarchyHandling':'INCLUDE_CHILDREN','elk.spacing.nodeNode':'55','elk.layered.spacing.nodeNodeBetweenLayers':'95',
  'elk.padding':'[top=40,left=40,bottom=40,right=40]'},children:[],edges:[]};
 const grouped=new Set();
 for(const group of data.groups){
  const members=data.nodes.filter(n=>n.group===group.id);if(!members.length)continue;
  members.forEach(n=>grouped.add(n.id));
  graph.children.push({id:'group:'+group.id,layoutOptions:{'elk.algorithm':algorithm,'elk.aspectRatio':'1.5','elk.padding':'[top=72,left=28,bottom=28,right=28]'},
   children:members.map(n=>({id:n.id,...size}))});
 }
 graph.children.push(...data.nodes.filter(n=>!grouped.has(n.id)).map(n=>({id:n.id,...size})));
 graph.edges=data.edges.map(e=>({id:e.id,sources:[e.source],targets:[e.target]}));
 const laid=await elk.layout(graph),positions={};
 function visit(parent,offset={x:0,y:0}){for(const n of parent.children||[]){const pos={x:(n.x||0)+offset.x,y:(n.y||0)+offset.y};if(n.children)visit(n,pos);else positions[n.id]=pos;}}
 visit(laid);return positions;
}
