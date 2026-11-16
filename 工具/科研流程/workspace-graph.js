/* Canonical graph identities and visible relations; no dependency on categories. */
(function (root) {
 'use strict';
 const labels={RelatedTo:'内容相关',MethodSimilar:'方法相近',Supports:'支持',Contradicts:'反驳',Inconclusive:'证据未定',Uses:'方法参考',DerivedFrom:'来源于',ProducedBy:'生成于',Addresses:'回应问题',Tests:'检验',Documents:'记录',Resolves:'解决',LearnsFrom:'从中总结',Reuses:'复用',BelongsTo:'属于'};
 const groups=new Set(['主题草稿','积累类型','主线','项目']);
 function build(workspace,legacy,research){
  for(const definition of research.relation_types||workspace.relation_types||[])labels[definition.id]=definition.label;
  const allDocs=workspace.documents,docs=allDocs.filter(d=>!d.archived&&d.visibility!=='system'),byPath=new Map(allDocs.flatMap(d=>[d.kb_path,d.path].filter(Boolean).map(p=>[p,d])));
  const activePapers=new Set(workspace.papers.filter(p=>!p.hidden&&p.has_original!==false&&[undefined,null,'','共享','待归类',workspace.project].includes(p.project)).map(p=>p.id));
  const hidden=d=>d&&(d.archived||d.visibility==='system');
  const nodes=new Map(),aliases=new Map(),edges=[],seen=new Set();
  for(const d of docs){nodes.set(d.id,{id:d.id,label:d.display_title||d.title,kind:d.kind,status:d.status,doc_id:d.id,path:d.kb_path,summary:d.excerpt});aliases.set(d.id,d.id);}
  for(const n of legacy.nodes){
   if(n.status==='不采用')continue;
   if(n.paper_id&&!activePapers.has(n.paper_id))continue;
   const doc=byPath.get(n.path);if(!n.paper_id&&n.kind!=='主线'&&hidden(doc))continue;
   // An old path without an indexed original is not a second document source.
   if(n.path&&!n.paper_id&&!doc&&!groups.has(n.kind))continue;
   const id=!n.paper_id&&n.kind!=='主线'&&n.kind!=='项目'&&doc?doc.id:n.id;
   const current=doc&&!n.paper_id&&!groups.has(n.kind)?{label:doc.display_title||doc.title,kind:doc.kind,status:doc.status,summary:doc.excerpt,path:doc.kb_path||doc.path}:{};
   aliases.set(n.id,id);nodes.set(id,{...nodes.get(id),...n,id,kind:n.paper_id?'论文':n.kind,...current,doc_id:doc&&!hidden(doc)?doc.id:undefined});
   if(n.kind==='项目'&&doc){aliases.set(doc.id,id);nodes.delete(doc.id);}
  }
  for(const p of workspace.papers){
   if(!activePapers.has(p.id))continue;
   const id='paper:'+p.id;aliases.set(p.id,id);
   if(!nodes.has(id))nodes.set(id,{id,paper_id:p.id,label:p.display_title||p.title,kind:'论文',status:p.reading_status||'阅读范围待核查',summary:p.title});
  }
  for(const n of research.nodes){
   if(n.kind==='Paper'&&(!activePapers.has(n.id)||['RETIRED','REJECTED','DELETED_AT_SOURCE'].includes(n.status)))continue;
   if(n.owner==='RSpace'&&n.status==='DELETED_AT_SOURCE')continue;
   const doc=allDocs.find(d=>d.record_id===n.id||d.id===n.data?.doc_id||d.id===n.id||[d.kb_path,d.path].filter(Boolean).includes(n.uri));
   if(n.kind!=='Paper'&&hidden(doc))continue;
   if(n.owner==='Markdown'&&n.uri?.endsWith('.md')&&!doc)continue;
   if(n.kind==='Document'&&!doc)continue;
   const id=n.kind==='Paper'?'paper:'+n.id:n.kind==='Project'&&n.project===workspace.project?'project':doc?(aliases.get(doc.id)||doc.id):'record:'+n.id;
   aliases.set(n.id,id);
   if(n.kind==='Project'&&n.project!==workspace.project)continue;
   if(nodes.has(id)){Object.assign(nodes.get(id),{record_id:n.id,uri:n.uri,owner:n.owner});continue;}
   nodes.set(id,{id,record_id:n.id,paper_id:n.kind==='Paper'?n.id:undefined,uri:n.uri,owner:n.owner,label:n.data?.title||n.id,kind:labels[n.kind]||({'RUN':'分析运行',Dataset:'数据集',Environment:'环境',Code:'代码',Figure:'图',Result:'结果'}[n.kind]||n.kind),status:n.status,doc_id:doc?.id,summary:n.data?.scope||'来源：'+n.owner});
  }
  const canonical=id=>aliases.get(id)||id;
  function add(edge){const from=canonical(edge.from),to=canonical(edge.to),key=[from,to,edge.label,!!edge.suggested].join('|');if(from===to||!nodes.has(from)||!nodes.has(to)||seen.has(key))return;seen.add(key);edges.push({...edge,from,to,label:edge.label||'关系待补'});}
  for(const e of legacy.edges){
   const from=canonical(e.from),to=canonical(e.to),paper=nodes.get(from)?.paper_id||nodes.get(to)?.paper_id;
   const doc=docs.find(d=>canonical(d.id)===(nodes.get(from)?.paper_id?to:from));
   if(paper&&doc?.paper_ids?.includes(paper))continue;
   add({...e,id:'legacy:'+edges.length,group:groups.has(nodes.get(from)?.kind)});
  }
  for(const e of research.relations){
   if(e.status==='REJECTED'||e.stale||e.evidence.some(v=>v.stale))continue;
   add({id:e.id,from:e.source,to:e.target,label:labels[e.kind]||e.kind,source:e.evidence.some(v=>v.generator)?'AI 内容分析':'关系账本',
        evidence:e.evidence,scope:e.evidence.map(v=>v.location||'').filter(Boolean).join('；'),explanation:e.conditions,
        suggested:e.status!=='VERIFIED'||e.stale,stale:!!e.stale,revision:e.revision});
  }
  for(const d of docs){
   for(const ref of d.references||[])add({id:'reference:'+d.id+':'+ref.id,from:d.id,to:ref.id,label:'正文引用',source:'原稿中的明确链接',explanation:'资料导航关系；科研支持关系需要单独核查。',changed:ref.changed});
   for(const paper of d.paper_ids||[])add({id:'paper-doc:'+d.id+':'+paper,from:d.id,to:'paper:'+paper,label:['阅读笔记','文献理解','论文批注','笔记','项目经验','方法记录'].includes(d.kind)?'对应论文':'关联论文',source:'已登记文献 ID',explanation:'来自资料中的明确文献标识，不要求预先分类。'});
  }
  return {nodes,edges,aliases};
 }
 function fromCatalog(workspace,snapshot,options={}){
  const hideDerived=options.hideDerived!==false,mergePapers=options.mergePapers!==false;
  const docs=new Map(workspace.documents.map(d=>[d.id,d])),papers=new Set(workspace.papers.filter(p=>!p.hidden&&p.has_original!==false).map(p=>p.id)),nodes=new Map(),aliases=new Map();
  for(const row of snapshot.nodes||[]){
   if(hideDerived&&/^文献\/AI阅读记录\//.test(row.path||''))continue;
   if(row.paper_id&&!papers.has(row.paper_id)||row.doc_id&&!docs.has(row.doc_id))continue;
   const id=row.doc_id||row.id;aliases.set(row.id,id);if(row.record_id)aliases.set(row.record_id,id);
   nodes.set(id,{...row,id});
  }
  let edges=(snapshot.edges||[]).map(e=>({...e,from:aliases.get(e.from)||e.from,to:aliases.get(e.to)||e.to})).filter(e=>nodes.has(e.from)&&nodes.has(e.to)&&e.from!==e.to);
  if(mergePapers){
   // 一份阅读卡片与它的论文条目合并成一个对象，避免同一篇论文出现两次。
   const merged=new Map(),cardPapers=new Map();
   for(const edge of edges){
    if(edge.label!=='引用论文')continue;
    const a=nodes.get(edge.from),b=nodes.get(edge.to),paper=a&&a.kind==='论文'?a:b&&b.kind==='论文'?b:null,card=a&&a.kind!=='论文'?a:b&&b.kind!=='论文'?b:null;
    if(paper&&card&&/^文献\/阅读卡片\//.test(card.path||'')){
     if(!cardPapers.has(card.id))cardPapers.set(card.id,new Set());
     cardPapers.get(card.id).add(paper.id);
    }
   }
   for(const [id,paperIds] of cardPapers){
    const doc=docs.get(nodes.get(id)?.doc_id||id),declared=new Set(doc?.paper_ids||[]);
    const paperId=[...paperIds][0];
    if(paperIds.size===1&&declared.size<=1&&(!declared.size||declared.has(paperId)||declared.has(paperId.replace(/^paper:/,''))))merged.set(id,paperId);
   }
   if(merged.size){
    for(const [from,to] of merged){nodes.delete(from);aliases.set(from,to);}
    for(const [alias,id] of aliases)if(merged.has(id))aliases.set(alias,merged.get(id));
    edges=edges.map(e=>({...e,from:aliases.get(e.from)||e.from,to:aliases.get(e.to)||e.to})).filter(e=>e.from!==e.to);
   }
  }
  const seen=new Set();edges=edges.filter(e=>{const key=[e.from,e.to,e.label].join('|');if(seen.has(key))return false;seen.add(key);return true;});
  return {nodes,edges,aliases};
 }
 function destination(node,workspace){
  if(!node)return null;
  if(node.owner==='Data Storage'&&node.record_id)return {action:'rawdata',id:node.record_id};
  if(node.paper_id)return {route:'paper',id:node.paper_id};
  const doc=workspace.documents.find(d=>node.doc_id&&d.id===node.doc_id||node.record_id&&d.record_id===node.record_id||[d.kb_path,d.path].filter(Boolean).includes(node.uri||node.path));
  if(doc&&(workspace.include_history||!doc.archived&&doc.visibility!=='system'))return {route:'document',id:doc.id};
  if(node.kind==='主线')return {action:'mainlines'};
  if(node.kind==='项目')return {route:'projects'};
  if(node.record_id)return {action:'record',id:node.record_id};
  return null;
 }
 function select(graph,{mode='references',root='project',showCandidates=true,search=''}={}){
  const {nodes}=graph;let pool=graph.edges.filter(e=>showCandidates||!e.suggested);
  if(mode==='focus'&&!groups.has(nodes.get(root)?.kind))pool=pool.filter(e=>!e.group);
  let ids;
  if(mode==='references'){ids=new Set([...nodes].filter(([,n])=>!groups.has(n.kind)).map(([id])=>id));pool=pool.filter(e=>!e.group);}
  else if(mode==='all')ids=new Set(nodes.keys());
  else{ids=new Set([root]);for(let depth=0;depth<(mode==='focus'?1:2);depth++){const next=new Set(ids);for(const e of pool){if(ids.has(e.from))next.add(e.to);if(ids.has(e.to))next.add(e.from);}ids=next;}if(root!=='project')ids.delete('project');}
  const query=search.trim().toLocaleLowerCase();
  if(query){const hits=new Set([...ids].filter(id=>{const n=nodes.get(id);return n&&[n.label,n.kind,n.paper_id,n.doc_id,n.summary].join(' ').toLocaleLowerCase().includes(query);}));const neighbors=new Set(hits);for(const e of pool){if(hits.has(e.from))neighbors.add(e.to);if(hits.has(e.to))neighbors.add(e.from);}ids=new Set([...ids].filter(id=>neighbors.has(id)));}
  const visible=[...ids].map(id=>nodes.get(id)).filter(Boolean);const selected=new Set(visible.map(n=>n.id));pool=pool.filter(e=>selected.has(e.from)&&selected.has(e.to));
  const linked=new Set(pool.flatMap(e=>[e.from,e.to]));return {nodes:visible,edges:pool,isolated:visible.filter(n=>!linked.has(n.id)).length};
 }
 function edgeLabels(mode){return mode==='all'?'data(label)':'';}
 function styles(labelMode,appearance='orbs'){
  const compact=appearance==='orbs',icons=root.ResearchCanvas?.knowledgeIcons||root.ResearchKnowledgeIcons||{};
  const icon=name=>compact&&icons[name]?{'background-image':icons[name],'background-width':22,'background-height':22,'background-fit':'none'}:{};
  const tint=(color,border,name)=>({'background-color':compact?color:'#ffffff','border-color':compact?border:'#e4dfed',...icon(name)});
  return [
   {selector:'node',style:{shape:compact?'ellipse':'round-rectangle',width:compact?52:190,height:compact?52:100,
    ...tint('#ad9acb','#f1ebf8','note'),'border-width':compact?5:1,label:'data(label)','font-family':'Segoe UI, Microsoft YaHei',
    'font-size':compact?11:14,'font-weight':500,'text-wrap':'wrap','text-max-width':compact?136:158,'text-valign':compact?'bottom':'center',
    'text-margin-y':compact?12:0,color:'#7c6e90','line-height':1.65,'overlay-opacity':0,
    'transition-property':'opacity,border-color,background-color,border-width','transition-duration':220}},
   {selector:'node[kind = "论文"]',style:{...tint('#89a8ad','#edf4f3','paper'),shape:'round-rectangle',...(compact?{width:43,height:51}:{})}},
   {selector:'node[kind = "背景"]',style:{...tint('#ab99cb','#f2edf9','background'),shape:compact?'diamond':'round-rectangle',...(compact?{width:60,height:60}:{})}},
   {selector:'node[kind = "报告"], node[kind = "分析报告"]',style:{...tint('#c4ac86','#f8f2e9','report'),shape:'round-rectangle',...(compact?{width:49,height:43}:{})}},
   {selector:'node[kind = "主线"], node[kind = "项目"], node[kind = "主题"], node[kind = "主题草稿"]',style:{...tint('#a094c5','#f0ebf8','topic'),width:compact?67:200,height:compact?67:106,shape:compact?'ellipse':'round-rectangle','font-weight':600}},
   {selector:'node[?root]',style:{...tint('#8b79b1','#eae3f5','project'),'border-width':compact?7:2,'font-size':compact?12:15}},
   {selector:'node[color]',style:compact?{'background-color':'data(color)','border-color':'data(color)'}:{'border-color':'data(color)','border-width':3}},
   {selector:'node[?pending]',style:{'border-style':'dashed','border-color':'#d5c39e'}},
   {selector:'edge',style:{width:1.1,'line-color':'#d8d1e3','target-arrow-color':'#c9bfd9','target-arrow-shape':'triangle','arrow-scale':.65,'curve-style':'bezier','control-point-step-size':90,label:ResearchGraph.edgeLabels(labelMode),'font-size':10,color:'#a291b5','text-background-color':'#fefcff','text-background-opacity':.95,'text-background-padding':'5px','text-rotation':'none','text-margin-y':-7,'overlay-opacity':0,'transition-property':'opacity,line-color,width','transition-duration':200}},
   {selector:'edge[?pending]',style:{'line-style':'dashed','line-color':'#d8c9ac','target-arrow-color':'#d8c9ac'}},
   {selector:'.far',style:{'text-opacity':0,'arrow-scale':.45,'font-size':0}},{selector:'.hover-edge',style:{width:2.2,'line-color':'#ab95cc','target-arrow-color':'#ab95cc'}},
   {selector:'node.depth-near',style:{width:64,height:64,'shadow-blur':22,'shadow-opacity':.20,'shadow-offset-y':7,'shadow-color':'#4b3f63','z-index':30}},
   {selector:'node.depth-mid',style:{width:52,height:52,'shadow-blur':12,'shadow-opacity':.10,'shadow-offset-y':4,'shadow-color':'#4b3f63','z-index':20}},
   {selector:'node.depth-far',style:{width:40,height:40,opacity:.55,'shadow-blur':4,'shadow-opacity':.05,'z-index':10}},
   {selector:'.dim',style:{opacity:.12}},{selector:'node:selected',style:{'border-color':'#c5b4e0','border-width':compact?8:3,'overlay-opacity':0}},
   {selector:'edge:selected',style:{label:labelMode==='none'?'':'data(label)','font-size':11,width:2.4,'line-color':'#ac92ce','target-arrow-color':'#ac92ce'}},
   {selector:'.connected',style:{label:labelMode==='none'?'':'data(label)',width:1.9,'line-color':'#b5a2ce','target-arrow-color':'#b5a2ce'}}
  ];
 }
 function layout(layoutName,root,reduced){return layoutName==='breadthfirst'?{name:'breadthfirst',directed:true,roots:[root],spacingFactor:1.12,avoidOverlap:true,padding:32,animate:!reduced,animationDuration:450}:{name:'fcose',quality:'proof',randomize:true,animate:!reduced,animationDuration:500,nodeDimensionsIncludeLabels:true,nodeSeparation:100,nodeRepulsion:()=>9000,idealEdgeLength:()=>90,edgeElasticity:()=>.45,gravity:.1,gravityRange:3.8,numIter:2500,padding:28};}
 const api={build,fromCatalog,select,edgeLabels,labels,destination,styles,layout};root.ResearchGraph=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
