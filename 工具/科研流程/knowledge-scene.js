/* Read-only view model shared by the 2D and 3D knowledge renderers. */
(function(root){
 'use strict';
 function semantic(node){return !!node.extracted||/ExtractedConcept|ExtractedClaim/i.test(node.record_kind||'')||/^(Concept|Claim|concept|claim|概念|结论)$/.test(node.semantic_kind||node.kind||'');}
 function available(row){return row.active!==false&&!['REJECTED','DELETED','RETIRED'].includes(row.status);}
 function normalizeState(state={}){return {view:'knowledge',showCandidates:true,selected:'',expanded:[],query:'',...state,readingMode:['topics','materials','all'].includes(state.readingMode)?state.readingMode:state.view==='materials'?'materials':'topics',organization:['free','communities'].includes(state.organization)?state.organization:'topics',appearance:state.appearance==='cards'?'cards':'orbs',topicPath:Array.isArray(state.topicPath)?state.topicPath:[]};}
 function validSnapshot(value){return value?.admission_version==='knowledge-admission-v6';}
 function curveEdges(edges){const groups=new Map();for(const edge of edges){const key=[edge.from,edge.to].sort().join('\u0000');if(!groups.has(key))groups.set(key,[]);groups.get(key).push(edge);}const offsets=new Map();for(const rows of groups.values()){rows.sort((a,b)=>String(a.id).localeCompare(String(b.id)));rows.forEach((edge,i)=>{const offset=rows.length===1?24:(i-(rows.length-1)/2)*36;offsets.set(edge.id,(offset||12)*(String(edge.from)<=String(edge.to)?1:-1));});}return edges.map(edge=>({...edge,curveDistance:offsets.get(edge.id),selfLoop:edge.from===edge.to}));}
 function project(snapshot,state={}){
  // Old callers keep their previous automatic-community behaviour; persisted UI
  // state is normalized explicitly before using the new organization controls.
  if(!state.readingMode)return projectLegacy(snapshot,state);
  const normalized=normalizeState(state),mode=normalized.readingMode;
  if(mode==='topics'&&normalized.organization==='communities')return {...projectLegacy(snapshot,{...state,view:'knowledge'}),readingMode:mode,organization:'communities',appearance:normalized.appearance,path:[]};
  const all=(snapshot.nodes||[]).filter(n=>available(n)&&(state.showCandidates!==false||!n.suggested)),byId=new Map(all.map(n=>[n.id,n])),edges=(snapshot.edges||[]).filter(e=>available(e)&&(state.showCandidates!==false||!e.suggested)&&byId.has(e.from)&&byId.has(e.to)),topics=(snapshot.topics||[]).filter(t=>!t.dimension||t.dimension==='topic'),topicById=new Map(topics.map(t=>[t.id,t]));
  const fingerprint=snapshot.graph_fingerprint||snapshot.fingerprint||'',common={readingMode:mode,organization:normalized.organization,appearance:normalized.appearance,semanticCount:all.filter(semantic).length,materialCount:all.filter(n=>!semantic(n)).length,fingerprint,scope:snapshot.scope||{}};
  const match=nodes=>{const q=(state.query||'').trim().toLocaleLowerCase();return q?nodes.filter(n=>[n.label,n.summary,n.id,...(n.members||[]).map(id=>[byId.get(id)?.label,byId.get(id)?.summary].join(' '))].join(' ').toLocaleLowerCase().includes(q)).map(n=>n.id):[];};
  const finish=(nodes,pool,extra={})=>({...common,nodes,edges:curveEdges(pool),matches:match(nodes),level:'detail',path:[],...extra});
  if(state.focusRoot&&byId.has(state.focusRoot)){
   const root=state.focusRoot,neighbors=new Set([root]);for(const e of edges){if(e.from===root)neighbors.add(e.to);if(e.to===root)neighbors.add(e.from);}
   const ranked=[root,...[...neighbors].filter(id=>id!==root).sort((a,b)=>Number(!!byId.get(a).suggested)-Number(!!byId.get(b).suggested)||String(byId.get(a).label||a).localeCompare(String(byId.get(b).label||b),'zh-CN'))];
   const page=Math.max(0,Number(state.localPage)||0),shown=new Set([root,...ranked.slice(1+page*60,1+(page+1)*60)]);
   return finish(all.filter(n=>shown.has(n.id)),edges.filter(e=>shown.has(e.from)&&shown.has(e.to)),{level:'local',totalCount:neighbors.size,hiddenCount:neighbors.size-shown.size,root});
  }
  if(normalized.organization==='free'&&(state.query||'').trim()){
   const result=state.searchResult,q=state.query.trim(),current=result?.query===q&&result?.fingerprint===fingerprint;
   const ids=current?result.ids:match(all),rank=new Map(ids.map((id,i)=>[id,i])),selected=new Set(ids.slice(0,100));
   return finish(all.filter(n=>selected.has(n.id)).sort((a,b)=>rank.get(a.id)-rank.get(b.id)),edges.filter(e=>selected.has(e.from)&&selected.has(e.to)),{level:'search',totalCount:ids.length,retrieval:current?result.backend:'text',matches:ids.slice(0,100)});
  }
  let ids;
  if(mode==='all')ids=new Set(all.map(n=>n.id));
  else if(mode==='materials')ids=new Set(all.filter(n=>!semantic(n)).map(n=>n.id));
  else if(!topics.length)ids=new Set(all.filter(semantic).map(n=>n.id));
  else{
   const ancestry=id=>{const result=new Set();while(id&&topicById.has(id)&&!result.has(id)){result.add(id);id=topicById.get(id).parent||topicById.get(id).parent_id;}return result;};
   const path=[];for(const id of normalized.topicPath){if(id==='__unclassified__'){path.push({id,title:'未分类知识'});break;}if(!topicById.has(id))break;const t=topicById.get(id),parent=t.parent||t.parent_id||'';if(parent!==(path.at(-1)?.id||''))break;path.push(t);}
   const current=path.at(-1)?.id||'',members=all.filter(semantic),basis=members.length?members:all,topicMembers=new Map(topics.map(t=>[t.id,[]])),unclassified=[];
   for(const n of basis){const parents=new Set((n.topics||[]).flatMap(id=>[...ancestry(typeof id==='string'?id:id.id)]));if(!parents.size)unclassified.push(n.id);for(const id of parents)topicMembers.get(id)?.push(n.id);}
   const children=current==='__unclassified__'?[]:topics.filter(t=>(t.parent||t.parent_id||'')===current&&topicMembers.get(t.id)?.length),groups=children.map(t=>({id:'topic:'+t.id,group_id:t.id,navigation:'topic',group:true,kind:'主题',label:t.title||t.label||t.id,members:topicMembers.get(t.id),pendingCount:topicMembers.get(t.id).filter(id=>byId.get(id).suggested).length,summary:topicMembers.get(t.id).length+' 个知识对象 · 已有主题分类',suggested:topicMembers.get(t.id).some(id=>byId.get(id).suggested)}));
   if(!current&&unclassified.length)groups.push({id:'topic:__unclassified__',group_id:'__unclassified__',navigation:'topic',group:true,kind:'主题',label:'未分类知识',members:unclassified,pendingCount:unclassified.filter(id=>byId.get(id).suggested).length,summary:unclassified.length+' 个尚未归入已有主题的知识对象'});
   const covered=new Set(groups.flatMap(g=>g.members));ids=new Set(current==='__unclassified__'?unclassified:current?(topicMembers.get(current)||[]).filter(id=>!covered.has(id)):[]);
   for(const id of state.expanded||[])if(byId.has(id)){ids.add(id);for(const e of edges){if(e.from===id)ids.add(e.to);if(e.to===id)ids.add(e.from);}}
   const nodes=[...groups,...all.filter(n=>ids.has(n.id))],owners=new Map(groups.flatMap(g=>g.members.map(id=>[id,g.id]))),bundles=new Map();
   for(const e of edges){const a=ids.has(e.from)?e.from:owners.get(e.from),b=ids.has(e.to)?e.to:owners.get(e.to);if(!a||!b||a===b)continue;if(a===e.from&&b===e.to){bundles.set(e.id,e);continue;}const key=[a,b,e.layer||'',e.kind||e.label||'',!!e.suggested].join('|');if(!bundles.has(key))bundles.set(key,{...e,id:'topic-bundle:'+key,from:a,to:b,aggregate:true,original_ids:[],count:0});const row=bundles.get(key);row.count++;row.original_ids.push(e.id);}
   return finish(nodes,[...bundles.values()],{level:groups.length?'overview':current?'topic':'detail',path:path.map(t=>({id:t.id,label:t.title||t.label||t.id})),communityCount:groups.length});
  }
  for(const id of state.expanded||[])if(byId.has(id)){ids.add(id);for(const e of edges){if(e.from===id)ids.add(e.to);if(e.to===id)ids.add(e.from);}}
  const nodes=all.filter(n=>ids.has(n.id));return finish(nodes,edges.filter(e=>ids.has(e.from)&&ids.has(e.to)),{totalCount:nodes.length});
 }
 // Screen-space detail selection. Actual knowledge IDs remain in the logical
 // scene; panning/zooming changes only which native nodes can be read at once.
 function selectVisible(nodes,screen,{width=1000,height=700,appearance='orbs',selected='',hover='',matches=[],importance={},limit=appearance==='cards'?36:90}={}){
  const required=new Set([selected,hover,...matches.slice(0,12)].filter(Boolean)),ranking=new Map(matches.map((id,i)=>[id,i]));
  const inView=n=>{const p=screen[n.id];return !!p&&p.x>=0&&p.y>=0&&p.x<=width&&p.y<=height;};
  const nearView=n=>{const p=screen[n.id];return !!p&&p.x>=-30&&p.y>=-30&&p.x<=width+30&&p.y<=height+30;};
  const baseCount=nodes.filter(n=>required.has(n.id)||nearView(n)).length;
  // A sparse zoomed view keeps a context ring outside the viewport so edges and neighbours
  // do not disappear the moment they leave the screen; dense overviews stay at 30px.
  const margin=baseCount<30?Math.max(width,height)*.35:30;
  const score=n=>(n.id===selected?1e6:n.id===hover?9e5:ranking.has(n.id)?1e5-ranking.get(n.id):Number(importance[n.id]||0))+(inView(n)?1e4:0);
  const pool=nodes.filter(n=>required.has(n.id)||screen[n.id]&&screen[n.id].x>=-margin&&screen[n.id].y>=-margin&&screen[n.id].x<=width+margin&&screen[n.id].y<=height+margin).sort((a,b)=>score(b)-score(a)||String(a.id).localeCompare(String(b.id)));
  const picked=[],occupied=new Set(),boxes=[],sources=new Map(),namePoints=new Map(),spacing=appearance==='cards'?240:102;
  // A zoomed-in viewport only holds a few objects; show all of them instead of thinning
  // overlaps, so zooming in never hides a node that is already in view.
  const sparse=baseCount<=12;
  const bounds=p=>({x:p.x-(appearance==='cards'?120:29),y:p.y-(appearance==='cards'?72:29),width:appearance==='cards'?240:58,height:appearance==='cards'?144:58});
  const conceptName=n=>/Concept|概念/.test(n.record_kind||n.kind||'')?String(n.label||'').normalize('NFKC').toLocaleLowerCase():'';
  // Only a duplicate that sits next to an already shown concept looks repeated; the same
  // name in another region is a different instance and must stay visible when zooming.
  const duplicateNear=(n,p)=>{const name=conceptName(n);if(!name)return false;const rows=namePoints.get(name);return !!rows&&rows.some(q=>Math.abs(q.x-p.x)<=spacing&&Math.abs(q.y-p.y)<=spacing*.7);};
  const add=n=>{picked.push(n);const name=conceptName(n),p=screen[n.id];if(name&&p){const rows=namePoints.get(name)||[];rows.push(p);namePoints.set(name,rows);}if(p){occupied.add(Math.floor(p.x/spacing)+':'+Math.floor(p.y/(spacing*.7)));boxes.push(bounds(p));}const source=(n.source_ids||[]).join('|')||n.id;sources.set(source,(sources.get(source)||0)+1);};
  for(const n of pool)if(required.has(n.id))add(n);
  for(const cap of [2,8,Infinity])for(const n of pool){if(picked.length>=limit)break;const p=screen[n.id];if(!p||picked.includes(n)||duplicateNear(n,p))continue;const source=(n.source_ids||[]).join('|')||n.id,key=Math.floor(p.x/spacing)+':'+Math.floor(p.y/(spacing*.7));if(!sparse&&((sources.get(source)||0)>=cap||occupied.has(key)||boxes.some(box=>overlap(box,bounds(p),6))))continue;add(n);}
  return picked;
 }
 function visibleEdges(edges,ids,selected=''){
  const pool=edges.filter(e=>ids.has(e.from)&&ids.has(e.to));
  return pool.sort((a,b)=>Number(b.from===selected||b.to===selected)-Number(a.from===selected||a.to===selected)||String(a.id).localeCompare(String(b.id))).slice(0,Math.max(80,ids.size*2));
 }
 function projectLegacy(snapshot,state={}){
  const all=(snapshot.nodes||[]).filter(n=>available(n)&&(state.showCandidates!==false||!n.suggested)),byId=new Map(all.map(n=>[n.id,n]));
  const edges=(snapshot.edges||[]).filter(e=>available(e)&&(state.showCandidates!==false||!e.suggested)&&byId.has(e.from)&&byId.has(e.to));
  const groups=(snapshot.communities||[]).map(c=>({...c,members:(c.members||[]).filter(id=>byId.has(id)&&semantic(byId.get(id)))})).filter(c=>c.members.length);
  if(state.view!=='materials'&&groups.length&&!state.community){
   const displayGroups=!state.overviewAll&&groups.length>18?[...groups.slice(0,17),{id:'__more__',label:'更多主题 · '+(groups.length-17),members:groups.slice(17).flatMap(c=>c.members),children:groups.slice(17).map(c=>c.id),center:{x:0,y:Math.max(...groups.slice(0,17).map(c=>c.center?.y||0))+300,z:0},color:'#91a3c2'}]:groups;
   const owners=new Map(),groupOwners=new Map();for(const c of displayGroups)for(const id of c.children||[c.id])groupOwners.set(id,c.id);
   const nodes=displayGroups.map(c=>{for(const id of c.members)owners.set(id,c.id);return {id:'view:'+c.id,group_id:c.id,group:true,kind:'主题',label:c.label,color:c.color,members:c.members,
    summary:(c.children?c.children.length+' 个其他主题；':'')+c.members.length+' 个概念和结论；内容分群用于导航，不能代替科研判断。',suggested:c.members.some(id=>byId.get(id).suggested),position:c.center||{},pendingCount:c.members.filter(id=>byId.get(id).suggested).length};}),bundles=new Map();
   for(const e of edges){const a=owners.get(e.from),b=owners.get(e.to);if(!a||!b||a===b)continue;const key=[a,b,e.kind||e.label,!!e.suggested].join('|');if(!bundles.has(key))bundles.set(key,{id:'bundle:'+key,from:'view:'+a,to:'view:'+b,kind:e.kind,label:e.label,suggested:e.suggested,aggregate:true,original_ids:[],count:0});const row=bundles.get(key);row.count++;row.original_ids.push(e.id);}
   for(const edge of snapshot.community_links||[]){const a=groupOwners.get(edge.from),b=groupOwners.get(edge.to);if(a&&b&&a!==b)bundles.set(edge.id,{...edge,from:'view:'+a,to:'view:'+b,aggregate:true});}
   const query=(state.query||'').trim().toLocaleLowerCase(),matches=query?nodes.filter(n=>n.members.some(id=>[byId.get(id).label,byId.get(id).summary,id].join(' ').toLocaleLowerCase().includes(query))).map(n=>n.id):[];
   return {nodes,edges:[...bundles.values()],matches,level:'overview',communityCount:groups.length,semanticCount:all.filter(semantic).length,materialCount:all.filter(n=>!semantic(n)).length,fingerprint:snapshot.graph_fingerprint||snapshot.fingerprint||'',scope:snapshot.scope||{}};
  }
  const selectedGroup=groups.find(c=>c.id===state.community),ids=new Set(all.filter(n=>state.view==='materials'?!semantic(n):semantic(n)&&(!selectedGroup||selectedGroup.members.includes(n.id))).map(n=>n.id));
  for(const id of state.expanded||[])if(byId.has(id)){ids.add(id);for(const e of edges){if(e.from===id)ids.add(e.to);if(e.to===id)ids.add(e.from);}}
  const nodes=all.filter(n=>ids.has(n.id)),query=(state.query||'').trim().toLocaleLowerCase();
  const matches=query?nodes.filter(n=>[n.label,n.summary,n.id].join(' ').toLocaleLowerCase().includes(query)).map(n=>n.id):[];
  return {nodes,edges:edges.filter(e=>ids.has(e.from)&&ids.has(e.to)),matches,level:state.community?'community':'detail',semanticCount:all.filter(semantic).length,
   materialCount:all.filter(n=>!semantic(n)).length,fingerprint:snapshot.graph_fingerprint||snapshot.fingerprint||'',scope:snapshot.scope||{}};
 }
 function migratePositions(entries){const positions=Object.create(null);for(const [key,rows] of [...entries].filter(([key])=>/^research:layout:v[0-9]+:knowledge:/.test(key)).sort((a,b)=>Number(a[0].match(/:v([0-9]+):/)[1])-Number(b[0].match(/:v([0-9]+):/)[1]))){if(!rows||typeof rows!=='object')continue;for(const [id,point] of Object.entries(rows))if(valid(point)){positions[id]={...point,fixed:true};if(!id.startsWith('doc:')&&!id.startsWith('paper:'))positions['doc:'+id]={...point,fixed:true};}}return positions;}
 function hash(text){let value=2166136261;for(const c of String(text))value=Math.imul(value^c.charCodeAt(0),16777619);return value>>>0;}
 function valid(point){return point&&Number.isFinite(point.x)&&Number.isFinite(point.y);}
 function positions(nodes,edges,previous={},proposed={}){
  const result={},taken=[],attached=new Set();
  for(const edge of edges){if(valid(previous[edge.from]))attached.add(edge.to);if(valid(previous[edge.to]))attached.add(edge.from);}
  for(const n of nodes){const p=previous[n.id];if(valid(p)){result[n.id]={...p};taken.push(p);}}
  for(const n of [...nodes].sort((a,b)=>String(a.id).localeCompare(String(b.id)))){
   if(result[n.id])continue;const supplied=proposed[n.id];
   if(valid(supplied)&&(supplied.fixed||!attached.has(n.id))){result[n.id]={...supplied,z:Number.isFinite(supplied.z)?supplied.z:0};taken.push(result[n.id]);continue;}
   const neighbors=edges.filter(e=>e.from===n.id||e.to===n.id).map(e=>result[e.from===n.id?e.to:e.from]).filter(valid),seed=hash(n.id),angle=seed/4294967296*Math.PI*2;
   const centre=neighbors.length?{x:neighbors.reduce((v,p)=>v+p.x,0)/neighbors.length,y:neighbors.reduce((v,p)=>v+p.y,0)/neighbors.length,z:neighbors.reduce((v,p)=>v+(p.z||0),0)/neighbors.length}:{x:0,y:0,z:0};
   let point;for(let i=0;i<150;i++){const radius=neighbors.length?85+i*13:90+Math.sqrt(taken.length+i)*76,a=angle+i*2.399963;
    point={x:centre.x+Math.cos(a)*radius,y:centre.y+Math.sin(a)*radius,z:centre.z};if(!taken.some(p=>Math.hypot(point.x-p.x,point.y-p.y)<70))break;}
   result[n.id]=point;taken.push(point);
  }return result;
 }
 function overlap(a,b,padding=4){return !(a.x+a.width+padding<=b.x||b.x+b.width+padding<=a.x||a.y+a.height+padding<=b.y||b.y+b.height+padding<=a.y);}
 function placeLabels(items,{width,height,required=new Set(),previous={}}={}){
  const boxes=[],ordered=[...items].filter(n=>n.x>=-20&&n.y>=-20&&n.x<=width+20&&n.y<=height+20).sort((a,b)=>Number(required.has(b.id))-Number(required.has(a.id))||(b.priority||0)-(a.priority||0)||String(a.id).localeCompare(String(b.id)));
  for(const item of ordered){const w=Math.min(width-12,item.width||130),h=item.height||20,candidates=[];
   const prior=previous[item.id];if(prior)candidates.push({x:item.x+prior.x-prior.nodeX,y:item.y+prior.y-prior.nodeY});
   for(const distance of [20,44,70,102].map(d=>d+(item.radius||0)))for(const [dx,dy] of [[-w/2,distance],[18,-h/2],[-w-18,-h/2],[-w/2,-h-distance]])candidates.push({x:item.x+dx,y:item.y+dy});
   if(required.has(item.id))for(let y=8;y<height-h;y+=h+6)for(let x=8;x<width-w;x+=w+8)candidates.push({x,y});
   for(const p of candidates){const box={id:item.id,x:Math.max(6,Math.min(width-w-6,p.x)),y:Math.max(6,Math.min(height-h-6,p.y)),width:w,height:h,nodeX:item.x,nodeY:item.y};
    if(!boxes.some(other=>overlap(box,other))){boxes.push(box);break;}}
  }return boxes;
 }
 // Cache only read-only snapshots; live canvases, workers and listeners are never retained.
 function createSnapshotCache(limit=3){
  const entries=new Map();
  return {get(key){const value=entries.get(key);if(!value)return;entries.delete(key);entries.set(key,value);return value;},
   set(key,value){const fingerprint=value.snapshot.graph_fingerprint||value.snapshot.fingerprint;
    const layouts=Object.fromEntries(Object.entries(value.layouts||{}).filter(([,layout])=>fingerprint&&(layout.graph_fingerprint||layout.fingerprint)===fingerprint));
    entries.delete(key);entries.set(key,{snapshot:value.snapshot,layouts});while(entries.size>limit)entries.delete(entries.keys().next().value);
   }};
 }
 function createMotion(){let generation=0,destroyed=false,frame=null,timer=null;
  function cancel(){generation++;if(frame!==null&&typeof cancelAnimationFrame==='function')cancelAnimationFrame(frame);if(timer!==null)clearTimeout(timer);frame=timer=null;}
  return {start(){cancel();return generation;},active(token){return !destroyed&&token===generation;},cancel,destroy(){cancel();destroyed=true;},
   frame(callback){frame=requestAnimationFrame(callback);},delay(callback,ms){timer=setTimeout(callback,ms);}};
 }
 const api={normalizeState,validSnapshot,selectVisible,visibleEdges,curveEdges,createSnapshotCache,migratePositions,semantic,project,positions,placeLabels,overlap,createMotion,hash};root.KnowledgeScene=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
