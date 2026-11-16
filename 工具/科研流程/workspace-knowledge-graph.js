/* The knowledge graph owns view state only. Documents and relations stay in their existing stores. */
(function(root){
 'use strict';
 const Model=root.KnowledgeScene,storageKey='research:knowledge-scene:v1',palette=['#7d9f9b','#a493b8','#b49b7b','#8b9eb4','#99a781','#b68f9b'],caches=new WeakMap();
 function element(tag,text,cls){const node=document.createElement(tag);if(text!==undefined&&text!==null)node.textContent=text;if(cls)node.className=cls;return node;}
 function button(text,action,cls=''){const node=element('button',text,cls);node.type='button';node.onclick=action;return node;}
 function readStorage(){try{const raw=localStorage.getItem(storageKey);if(raw)return JSON.parse(raw);const entries=[];for(let i=0;i<localStorage.length;i++){const key=localStorage.key(i);if(/^research:layout:v[0-9]+:knowledge:/.test(key)){try{entries.push([key,JSON.parse(localStorage.getItem(key))]);}catch{}}}return {positions:Model.migratePositions(entries)};}catch{return {};}}
 function load3D(){if(root.ResearchGraph3D)return Promise.resolve();if(root.__knowledge3DLoad)return root.__knowledge3DLoad;
  root.__knowledge3DLoad=new Promise((resolve,reject)=>{const script=element('script');script.src='/vendor/knowledge-graph/knowledge-3d.js';script.onload=()=>root.ResearchGraph3D?resolve():reject(new Error('三维视图未完成加载'));script.onerror=()=>{script.remove();root.__knowledge3DLoad=null;reject(new Error('三维视图暂时无法加载，可继续使用二维视图'));};document.head.append(script);});return root.__knowledge3DLoad;
 }
 function loadIcons(){if(root.ResearchGraphIcons)return Promise.resolve();return root.__knowledgeIconsLoad||=(new Promise((resolve,reject)=>{const script=element('script');script.src='/vendor/knowledge-graph/knowledge-icons.js';script.onload=resolve;script.onerror=()=>{root.__knowledgeIconsLoad=null;script.remove();reject(new Error('动态图标暂不可用'));};document.head.append(script);}));}
 function mount(parent,bridge){
  if(!caches.has(bridge.api))caches.set(bridge.api,Model.createSnapshotCache());const cache=caches.get(bridge.api);let activeScope='',cacheRestored=false,iconController=null;
   const focusedEntry=Boolean(bridge.graphFocus);
   const saved=readStorage(),initialOrganization=!focusedEntry&&saved.version>=3&&['free','topics','communities'].includes(saved.state?.organization)?saved.state.organization:'free',state=Model.normalizeState({...saved.state,...(focusedEntry?{selected:bridge.graphFocus||'',showCandidates:true,query:'',focusRoot:bridge.graphFocus||''}:{}),view:'knowledge',readingMode:initialOrganization==='free'?'all':'topics',organization:initialOrganization}),views=saved.views||{},positionViews=saved.positionViews||{'2d':saved.positions||{},'3d':{}},navigationViews=saved.navigationViews||{},layouts={},filters={include_history:'0',source_project:'',topic:'',purpose:'',kind:'',...(focusedEntry?{}:saved.scope)};
  let snapshot={nodes:[],edges:[]},nodeIndex=new Map(),scene={nodes:[],edges:[],matches:[]},layout={nodes:{},communities:[]},points=positionViews['2d']||{},currentMode='2d',requestedMode='2d',renderer3D=null,cy=null,destroyed=false,requestId=0,modeId=0,hover='',selectedEdge='',labelFrame=null,extraction=null,refreshTimer=null,playing=false,presentation=null,semanticWorker=null,semanticRequest=0,semanticKey='',searchRequest=0,searchTimer=null,interactionVersion=0,gatheredFor='';
  const labelNodes=new Map(),labelBoxes=new Map();let drawingZoom=0,densityKey='';
  const densitySvg=document.createElementNS('http://www.w3.org/2000/svg','svg'),densityGroup=document.createElementNS('http://www.w3.org/2000/svg','g');densitySvg.classList.add('kg-density');densitySvg.setAttribute('aria-hidden','true');densitySvg.append(densityGroup);
  const requests=new Set();function request(path,body){const controller=new AbortController();requests.add(controller);return bridge.api(path,body,{signal:controller.signal}).finally(()=>requests.delete(controller));}
  const feedbackAnimations=new Set();function feedback(node,frames,duration){if(reducedQuery.matches)return;const animation=node.animate(frames,{duration,easing:'cubic-bezier(.22,1,.36,1)'});feedbackAnimations.add(animation);animation.onfinish=animation.oncancel=()=>feedbackAnimations.delete(animation);}
  const motion=Model.createMotion(),reducedQuery=matchMedia('(prefers-reduced-motion: reduce)'),shell=element('section',null,'kg-workspace'),tools=element('div',null,'kg-toolbar'),scope=element('div',null,'kg-scope'),status=element('div','正在读取知识与来源…','kg-status'),body=element('div',null,'kg-body'),stage=element('div',null,'kg-stage'),layer=element('div',null,'kg-layer'),canvas=element('div',null,'kg-canvas'),halos=element('canvas',null,'kg-halos'),labels=element('div',null,'kg-labels'),empty=element('div',null,'kg-empty'),panel=element('aside',null,'kg-inspector'),splitter=element('div',null,'kg-splitter'),legend=element('div',null,'kg-communities'),footer=element('div',null,'kg-footer');
  shell.setAttribute('aria-label','知识关系图');canvas.setAttribute('aria-label','可交互知识关系图');canvas.setAttribute('role','img');panel.setAttribute('aria-label','选中知识及来源');splitter.setAttribute('role','separator');splitter.setAttribute('aria-orientation','vertical');splitter.setAttribute('aria-label','调整详情栏宽度');splitter.tabIndex=0;
  shell.style.setProperty('--kg-detail-width',Math.max(300,Math.min(620,saved.detailWidth||340))+'px');
  const search=element('input');search.type='search';search.placeholder='搜索概念、结论或资料…';search.setAttribute('aria-label','搜索知识关系图');search.value=state.query;
  const twoD=button('二维',()=>switchMode('2d')),threeD=button('三维',()=>switchMode('3d')),orbs=button('圆点',()=>setAppearance('orbs')),cards=button('卡片',()=>setAppearance('cards')),organization=element('select'),candidate=element('label',null,'kg-check'),candidateInput=element('input');candidateInput.type='checkbox';candidateInput.checked=state.showCandidates;candidate.append(candidateInput,document.createTextNode('显示 AI 索引'));organization.setAttribute('aria-label','知识图组织方式');organization.append(new Option('自由探索','free'),new Option('主题分层','topics'),new Option('自动群落','communities'));organization.value=state.organization;
  const exitPlay=button('退出演示',()=>finishPresentation()),play=button('演示',startPresentation),detailToggle=button('收起详情',()=>togglePanel()),progressToggle=button('抽取进度',()=>showCoverage());
  tools.append(element('strong','知识地图','kg-title'),element('span','', 'kg-divider'),twoD,threeD,search,candidate,detailToggle);
  const controls=element('div',null,'kg-controls');controls.append(button('＋',()=>zoom(1.25)),button('−',()=>zoom(.8)),button('适应',()=>fit()),button('主题总览',()=>showOverview()),button('重新排布',()=>arrange()),play,exitPlay,button('全屏',()=>document.fullscreenElement?document.exitFullscreen():shell.requestFullscreen().catch(showError)),button('导出图片',exportImage),progressToggle);
  const more=element('details',null,'kg-more'),moreTitle=element('summary','更多'),moreItems=element('div',null,'kg-more-items');more.append(moreTitle,moreItems);for(const child of [...controls.children].slice(4)){if(child!==play&&child!==exitPlay)moreItems.append(child);}controls.append(more);
  const preview=element('div',null,'kg-node-preview');preview.hidden=true;stage.append(preview);layer.append(densitySvg,halos,canvas,labels);stage.append(layer,empty,controls);body.append(stage,splitter,panel);footer.append(element('span','单击查看关系 · 双击打开知识 · 拖动保存位置 · 琥珀标记为未核查索引'),button('新增关系',()=>bridge.showRelationEditor?.(snapshot.nodes)),button('专业精修',()=>bridge.showProfessionalGraph?.({project:bridge.project,mode:state.view,layout:'community',root:state.selected,elements:{nodes:scene.nodes.map(n=>({data:{...n,full_label:n.label},position:points[n.id]})),edges:scene.edges.map(e=>({data:{id:e.id,source:e.from,target:e.to,label:e.label}}))},source_relations:scene.edges})),button('刷新',()=>refresh()));shell.append(tools,scope,status,legend,body,footer);parent.append(shell);for(const child of [...footer.querySelectorAll('button')])moreItems.append(child);const viewsGroup=element('div',null,'kg-segmented'),appearanceGroup=element('div',null,'kg-segmented');viewsGroup.append(twoD,threeD);appearanceGroup.append(orbs,cards);tools.insertBefore(organization,search);tools.insertBefore(appearanceGroup,search);tools.insertBefore(viewsGroup,search);const filterToggle=button('筛选',()=>{scope.hidden=!scope.hidden;filterToggle.classList.toggle('active',!scope.hidden);filterToggle.setAttribute('aria-expanded',String(!scope.hidden));});filterToggle.setAttribute('aria-expanded',String(Object.values(filters).some(v=>v&&v!=='0')));tools.insertBefore(filterToggle,detailToggle);const searchWrap=element('div',null,'kg-search'),searchTrigger=button('搜索',()=>search.focus(),'kg-search-icon');tools.replaceChild(searchWrap,search);searchWrap.append(searchTrigger,search);scope.append(candidate);scope.hidden=!Object.values(filters).some(v=>v&&v!=='0');if(bridge.icon){filterToggle.prepend(bridge.icon('settings'));detailToggle.prepend(bridge.icon('file'));}moreItems.addEventListener('click',event=>{if(event.target.closest('button'))more.open=false;});
   exitPlay.hidden=true;if(!focusedEntry&&saved.collapsed!==false)shell.classList.add('kg-detail-collapsed');updateButtons();
  function setLabel(node,text){const label=node.querySelector('.kg-action-label');if(label)label.textContent=text;else node.textContent=text;node.setAttribute('aria-label',text);node.title=text;if(node===play)iconController?.decorate(play,playing?'pause':'play');}
  function showError(error){if(destroyed||error?.name==='AbortError')return;const text=error?.message||String(error);status.textContent=text;status.classList.add('kg-error');bridge.notify?.(text,true);}
  function navigationKey(){return [currentMode,state.readingMode,state.organization,state.organization==='topics'?state.topicPath.join('/'):state.community||'',state.focusRoot||'',state.query?'search:'+state.query:'',scopeQuery()].join(':');}
  function rememberNavigation(){
   if(currentMode==='2d'&&cy)views['2d']={zoom:cy.zoom(),pan:{...cy.pan()}};else if(currentMode==='3d'&&renderer3D)views['3d']=renderer3D.getView?.();
   navigationViews[navigationKey()]={view:views[currentMode],...(state.focusRoot?{positions:Object.fromEntries(scene.nodes.filter(n=>points[n.id]).map(n=>[n.id,points[n.id]]))}:{})};
   if(!state.focusRoot)positionViews[currentMode]=points;
   const keys=Object.keys(navigationViews);for(const key of keys.slice(0,Math.max(0,keys.length-20)))delete navigationViews[key];
  }

  function save(){if(destroyed||focusedEntry)return;rememberNavigation();try{localStorage.setItem(storageKey,JSON.stringify({version:3,state,scope:filters,positions:positionViews['2d'],positionViews,views,navigationViews,mode:currentMode,detailWidth:parseFloat(shell.style.getPropertyValue('--kg-detail-width')),collapsed:shell.classList.contains('kg-detail-collapsed')}));}catch{}}
  let sceneIndex=new Map(),expansionOrigin=null;function nodeFor(id){return sceneIndex.get(id)||nodeIndex.get(id);}
  function cancelMotion(){interactionVersion++;const current=currentMode==='2d'&&cy?Object.fromEntries(cy.nodes().map(n=>[n.id(),{...points[n.id()],...n.position()}])):null;layer.layerVersion=(layer.layerVersion||0)+1;for(const a of layer.getAnimations())a.cancel();layer.inert=false;for(const animation of feedbackAnimations)animation.cancel();feedbackAnimations.clear();playing=false;motion.cancel();cy?.stop(true,false);cy?.elements().stop(true,false);if(current)Object.assign(points,current);renderer3D?.stop?.();setLabel(play,presentation?'继续演示':'演示');}
  function finishPresentation(){cancelMotion();const prior=presentation;presentation=null;exitPlay.hidden=true;setLabel(play,'演示');if(!prior)return;if(currentMode==='2d'&&prior.mode==='2d'&&cy){cy.zoom(prior.view.zoom);cy.pan(prior.view.pan);}else if(currentMode==='3d'&&prior.mode==='3d')renderer3D?.setView(prior.view);save();}
  function updateButtons(){organization.hidden=false;organization.value=state.organization;orbs.classList.toggle('active',state.appearance==='orbs');cards.classList.toggle('active',state.appearance==='cards');twoD.classList.toggle('active',currentMode==='2d');threeD.classList.toggle('active',currentMode==='3d');candidateInput.checked=state.showCandidates;setLabel(detailToggle,shell.classList.contains('kg-detail-collapsed')?'展开详情':'收起详情');}
  function navigateView(change){cancelMotion();rememberNavigation();change();const prior=navigationViews[navigationKey()];points=prior?.positions||{...positionViews[currentMode]};if(state.focusRoot&&!prior){points=Object.fromEntries(Object.entries(positionViews[currentMode]||{}).filter(([id,p])=>p.fixed||id===state.focusRoot));}if(prior?.view)views[currentMode]=prior.view;else delete views[currentMode];selectedEdge='';preview.hidden=true;updateButtons();rebuild();if(currentMode==='3d'&&prior?.view)renderer3D?.setView?.(prior.view);else if(currentMode==='3d'&&!prior?.view)fit(true,false);save();}
  
  function setAppearance(value){cancelMotion();state.appearance=value;updateButtons();rebuild();save();}
  organization.onchange=()=>navigateView(()=>{state.organization=organization.value;state.readingMode=state.organization==='free'?'all':'topics';state.view='knowledge';state.focusRoot='';state.expanded=[];});
  function scopeQuery(extra={}){return new URLSearchParams({...filters,view:'knowledge',include_candidates:state.showCandidates?'1':'0',...extra}).toString();}
  function cacheSnapshot(){if(activeScope){cache.set(activeScope,{snapshot,layouts});root.KnowledgeGraphDiskCache?.put(activeScope,cache.get(activeScope)).catch(()=>{});}}
  function restoreCached(found=cache.get(scopeQuery())){if(!found||!Model.validSnapshot(found.snapshot)||!found.layouts['2d'])return false;snapshot=found.snapshot;Object.assign(layouts,found.layouts);layout=layouts[currentMode]||layouts['2d'];activeScope=scopeQuery();nodeIndex=new Map(snapshot.nodes.map(n=>[n.id,n]));cacheRestored=true;rebuild();status.textContent=countText()+' · 正在核对更新';return true;}
  async function ensureLayout(mode,retry=true){
   const fingerprint=snapshot.graph_fingerprint||snapshot.fingerprint||'',cached=layouts[mode];
   if(cached?.graph_fingerprint===fingerprint)return cached;
   const key=activeScope;let value;try{value=await request('/api/knowledge/layout?'+scopeQuery({fingerprint,dimensions:mode==='3d'?'3':'2'}));}catch(error){if(retry&&!destroyed&&/409|变化|fingerprint/i.test(error.message||'')){await refresh();return ensureLayout(mode,false);}throw error;}
   if(destroyed||key!==activeScope||fingerprint!==(snapshot.graph_fingerprint||snapshot.fingerprint))throw new Error('资料范围已变化，请重试');
   if(value.graph_fingerprint!==fingerprint)throw new Error('资料版本已变化，请重试');layouts[mode]=value;cacheSnapshot();return value;
  }
  async function refresh(){
   const id=++requestId,key=scopeQuery();if(refreshTimer){clearTimeout(refreshTimer);refreshTimer=null;}status.classList.remove('kg-error');if(!scene.nodes.length)status.textContent='正在读取知识与来源…';
   else status.textContent=countText()+' · 正在核对更新';
   try{
    const value=await request('/api/knowledge/graph?'+key);if(destroyed||id!==requestId)return;
    const fingerprint=value.graph_fingerprint||value.fingerprint||'';
    if(activeScope===key&&fingerprint===(snapshot.graph_fingerprint||snapshot.fingerprint)&&layouts[currentMode]){status.textContent=countText();semanticLayout();refreshExtraction();return;}
   if(focusedEntry){
    snapshot=value;nodeIndex=new Map((value.nodes||[]).map(n=>[n.id,n]));renderInspector();
   }
    const found=cache.get(key),known=found?.snapshot.graph_fingerprint===fingerprint?found.layouts:{};
    const nextLayout=known[currentMode]||await request('/api/knowledge/layout?'+scopeQuery({fingerprint,dimensions:currentMode==='3d'?'3':'2'}));
    if(destroyed||id!==requestId)return;if(nextLayout.graph_fingerprint!==fingerprint)throw new Error('fingerprint changed');
    snapshot=value;activeScope=key;for(const name of Object.keys(layouts))delete layouts[name];Object.assign(layouts,known,{[currentMode]:nextLayout});layout=nextLayout;
    for(const node of value.nodes||[])if(!points[node.id]&&points[node.record_id])points[node.id]={...points[node.record_id]};
    nodeIndex=new Map((value.nodes||[]).map(n=>[n.id,n]));cacheSnapshot();rebuild();save();semanticLayout();refreshExtraction();
   }catch(error){if(destroyed||id!==requestId)return;if(/409|fingerprint/i.test(error.message||'')){status.textContent='资料已有更新，正在重新核对…';if(!refreshTimer)refreshTimer=setTimeout(()=>{refreshTimer=null;refresh();},1200);}else{if(!scene.nodes.length){const found=cache.get(key)||await root.KnowledgeGraphDiskCache?.get(key).catch(()=>null);if(destroyed||id!==requestId)return;if(found){cache.set(key,found);restoreCached(found);}}if(scene.nodes.length)status.textContent=countText()+' · 暂时无法核对更新，保留上次画面';else showError(error);}}
  }
  async function semanticLayout(){
   if(destroyed||state.organization!=='free'||state.focusRoot||!snapshot.nodes.length)return;
   const fingerprint=snapshot.graph_fingerprint,mode=currentMode,startedInteraction=interactionVersion;let token=semanticRequest;
   try{
    let index=layouts[mode]?.semanticIndex;if(!index||index.fingerprint!==fingerprint)index=await request('/api/knowledge/explore?'+scopeQuery({fingerprint}));
    if(destroyed||token!==semanticRequest||currentMode!==mode||snapshot.graph_fingerprint!==fingerprint||!Array.isArray(index.ids))return;
    layouts[mode].semanticIndex=index;
    const nextKey=[mode,fingerprint,index.model,index.vector_count].join('|');if(semanticKey===nextKey)return;semanticKey=nextKey;token=++semanticRequest;
    const existing=index.ids.filter(id=>points[id]?.semantic);
    if(existing.length){
     for(const [row,id] of index.ids.entries()){
      if(points[id]?.semantic||points[id]?.fixed)continue;
      const nearby=index.indices.slice(row*index.k,(row+1)*index.k).map(i=>points[index.ids[i]]).filter(p=>p?.semantic);
      if(nearby.length){const p=nearby.reduce((v,p)=>({x:v.x+p.x,y:v.y+p.y,z:v.z+(p.z||0)}),{x:0,y:0,z:0}),angle=Model.hash(id)/4294967296*Math.PI*2;points[id]={...points[id],x:p.x/nearby.length+Math.cos(angle)*44,y:p.y/nearby.length+Math.sin(angle)*44,z:p.z/nearby.length,semantic:true};}
     }
     rebuild();cacheSnapshot();return;
    }
    semanticWorker?.terminate();const worker=new Worker('/vendor/knowledge-graph/knowledge-semantic-worker.js',{type:'module'});semanticWorker=worker;
    worker.onmessage=({data})=>{
     worker.terminate();if(semanticWorker===worker)semanticWorker=null;
     if(destroyed||token!==semanticRequest||currentMode!==mode||data.fingerprint!==snapshot.graph_fingerprint)return;
     if(data.error){status.textContent=countText()+' · 语义布局暂不可用，保留当前位置';return;}
     if(startedInteraction!==interactionVersion){layouts[mode].semanticPositions=data.positions;cacheSnapshot();return;}
     for(const [id,p] of Object.entries(data.positions))if(!points[id]?.fixed)points[id]={...points[id],...p,semantic:true};
     delete views[mode];rebuild();if(mode==='3d')renderer3D?.fit({positions:points,duration:450});cacheSnapshot();save();
    };
    worker.onerror=()=>{worker.terminate();if(semanticWorker===worker)semanticWorker=null;if(!destroyed)status.textContent=countText()+' · 保留当前布局';};
    worker.postMessage({index,fingerprint,dimensions:mode==='3d'?3:2});
   }catch(error){if(!destroyed&&token===semanticRequest&&error?.name!=='AbortError')status.textContent=countText();}
  }
  function countText(){const shown=currentMode==='2d'?(scene.renderedCount??scene.nodes.length):scene.nodes.length,total=scene.totalCount??scene.nodes.length;return `${shown} / ${total} 个知识对象 · ${scene.level==='local'?'当前对象的局部关系':scene.level==='search'?(scene.retrieval==='hybrid'?'语义与文字检索':'文字匹配'):'缩放查看细节'} · ${scene.nodes.reduce((n,row)=>n+Number(!!row.suggested),0)} 项未核查索引`;}

  function rebuild(){
   scene=Model.project({...snapshot,communities:layout.communities||[],community_links:layout.community_links||[]},state);scene.appearance=state.appearance;scene.readingMode=state.readingMode;scene.organization=state.organization;scene.freshIds=scene.nodes.filter(n=>!points[n.id]).map(n=>n.id);const proposed={...layout.nodes,...Object.fromEntries(scene.nodes.filter(n=>n.group&&Model.positions&&n.position&&Number.isFinite(n.position.x)).map(n=>[n.id,{...n.position,community:n.group_id,color:n.color}]))};if(expansionOrigin){for(const [index,node] of scene.nodes.filter(n=>!points[n.id]).entries()){const angle=index*2.399963,radius=(state.appearance==='cards'?170:105)*Math.sqrt(index+1);proposed[node.id]={x:expansionOrigin.x+Math.cos(angle)*radius,y:expansionOrigin.y+Math.sin(angle)*radius,z:expansionOrigin.z||0};}expansionOrigin=null;}if(state.expanded.length)for(const node of scene.nodes)if(!Model.semantic(node)&&!node.group&&!points[node.id])delete proposed[node.id];points={...points,...Model.positions(scene.nodes,scene.edges,points,proposed)};scene.nodes=scene.nodes.map(n=>({...n,importance:layouts[currentMode]?.semanticIndex?.importance?.[n.id]||0,community:n.group_id||layout.nodes?.[n.id]?.community,color:colorFor(n)}));sceneIndex=new Map(scene.nodes.map(n=>[n.id,n]));scene.positions=points;scene.communities=layout.communities||[];scene.selected=state.selected;scene.layoutStrategy=state.organization==='free'&&scene.level!=='local'?'semantic':'relations';scene.expanded=[...state.expanded];scene.hover=hover;scene.searchMatches=scene.matches;
   empty.hidden=!!scene.nodes.length;empty.replaceChildren();if(!scene.nodes.length){empty.append(element('strong',state.view==='knowledge'?'这里还没有已抽取的概念或结论':'当前范围没有资料'),element('p',state.view==='knowledge'?'来源资料会沿既有后台逐段抽取；AI索引可在图中预览，不计入必须逐条处理的待办。':'调整来源、主题或历史范围后重试。'));if(state.view==='knowledge')empty.append(button('查看抽取进度',showCoverage));}
   status.textContent=countText();renderLegend();if(currentMode==='2d')render2D();else renderer3D?.update(scene);renderInspector();save();
  }
  function colorFor(n){if(n.group)return '#a094c5';if(n.paper_id||n.kind==='论文')return '#89a8ad';if(!Model.semantic(n))return '#ad9acb';return /Claim|claim|结论/.test(n.record_kind||n.semantic_kind||n.kind||'')?'#c4ac86':'#89a99d';}
  function renderLegend(){
   legend.replaceChildren();if(state.focusRoot){legend.append(button('返回知识图',()=>navigateView(()=>{state.focusRoot='';state.expanded=[];}),'kg-trail-home'),element('span',nodeFor(state.focusRoot)?.label||'局部关系'));if(scene.hiddenCount){if(state.localPage>0)legend.append(button('上一组',()=>navigateView(()=>{state.localPage--;})));if((state.localPage+1)*60<scene.totalCount-1)legend.append(button('下一组关系',()=>navigateView(()=>{state.localPage=(state.localPage||0)+1;})));}return;}if(state.readingMode!=='topics'){legend.append(element('span','内容相近用于发现，科研关系沿原文核查'));return;}
   legend.append(button(state.organization==='topics'?'全部主题':'全部群落',()=>showOverview(),'kg-trail-home'));
   if(state.organization==='topics')for(const [index,t] of (scene.path||[]).entries())legend.append(element('span','›','kg-trail-divider'),button(t.label,()=>navigateView(()=>{state.topicPath=state.topicPath.slice(0,index+1);state.expanded=[];state.selected='';}),'kg-trail-home'));
   else{const group=(layout.communities||[]).find(c=>c.id===state.community);if(group)legend.append(element('span','›','kg-trail-divider'),element('span',group.label));}
   const groups=scene.nodes.filter(n=>n.group);if(groups.length){const chooser=element('select');chooser.setAttribute('aria-label','快速进入主题');chooser.append(new Option('进入主题 · '+groups.length,''));for(const c of groups)chooser.append(new Option(c.label+' · '+c.members.length,c.id));chooser.onchange=()=>{if(chooser.value)openNode(chooser.value);};legend.append(chooser);}
   legend.append(element('span','图标区分类型 · 琥珀标记未核查索引','kg-type-key'));
  }
  function glyphFor(node){const source=root.ResearchKnowledgeIcons||root.ResearchCanvas?.knowledgeIcons||{},icons=(state.appearance==='cards'?source.dark:source.light)||source;const type=node.group?'topic':node.paper_id||node.kind==='论文'?'paper':!Model.semantic(node)?'note':/Claim|claim|结论/.test(node.record_kind||node.semantic_kind||node.kind||'')?'claim':'concept';return (state.appearance==='cards'?icons[type+'Dark']:null)||icons[type]||icons[type==='claim'?'report':type==='concept'?'background':type]||'';}
  function short(text,length){text=String(text||'').replace(/\s+/g,' ').trim();return text.length>length?text.slice(0,length-1)+'…':text;}
  const cardFont=13,cardLeading=cardFont*1.5;
  function compactLabel(node){return (node.kind||'知识')+'\n'+short(node.label||node.id,32)+'\n'+(node.source_ids?.length||1)+' 处来源'+(node.suggested?' · AI 提取':'');}
  let measureContext=null;
  // Cytoscape centres a wrapped label by its longest line, so short cards would drift right.
  // Measure the card font locally and shift the block so every card starts on the same column.
  function cardTextShift(label,textLimit,cardWidth,padding){measureContext||=(measureContext=document.createElement('canvas').getContext('2d'));measureContext.font='500 '+cardFont+'px "Segoe UI", "Microsoft YaHei", sans-serif';let width=0;for(const line of String(label).split('\n'))width=Math.max(width,measureContext.measureText(line).width);return Math.round(padding-(cardWidth-Math.min(textLimit,width))/2);}
  // A 26px left gutter holds the type icon; the label text starts after it on every line.
  function displayLabel(node){if(state.appearance!=='cards')return node.group?short(node.label,28)+'\n'+node.members.length+' 项':short(node.label||node.id,36);const title=short(node.label||node.id,28),titleLines=title.length>14?[title.slice(0,14),title.slice(14)]:[title],summary=short(node.summary||node.reason||'',13),lines=[node.group?'主题':node.kind||node.semantic_kind||'知识',...titleLines];if(summary)lines.push(summary);lines.push((node.group?node.members.length+' 个对象':sourceNodes(node).length+' 个来源')+(node.suggested||node.status==='CANDIDATE'?' · AI 提取':''));return lines.join('\n');}
  function graphStyles(){const cards=state.appearance==='cards';return [
   {selector:'node',style:{shape:cards?'round-rectangle':'ellipse',width:'data(drawWidth)',height:'data(drawHeight)','background-color':cards?'#ffffff':'data(color)','border-color':cards?'#e5dfec':'#f0edf4','border-width':cards?1.4:4,label:'data(display_label)','font-family':'Segoe UI, Microsoft YaHei,sans-serif','font-size':'data(drawFont)','font-weight':500,color:'#66616f','text-wrap':'wrap','text-overflow-wrap':'anywhere','text-max-width':'data(drawTextWidth)','text-valign':cards?'center':'bottom','text-margin-y':cards?0:10,'text-margin-x':'data(drawTextX)','line-height':1.5,'text-justification':cards?'left':'center','background-image':n=>n.data('glyph')?(n.data('pending')&&root.ResearchKnowledgeIcons?.pending?[n.data('glyph'),root.ResearchKnowledgeIcons.pending]:[n.data('glyph')]):'none','background-fit':'none','background-width':n=>[n.data('drawIcon'),n.data('drawAudit')],'background-height':n=>[n.data('drawIcon'),n.data('drawAudit')],'background-clip':['node','none'],'background-position-x':n=>[cards?n.data('drawIconX'):'50%','100%'],'background-position-y':n=>[cards?n.data('drawIconY'):'50%','0%'],'overlay-opacity':0,'transition-property':'opacity,border-color,background-color,border-width','transition-duration':200}},
   {selector:'node[?material]',style:{shape:'round-rectangle',}},
   {selector:'node[?claim]',style:{shape:cards?'round-rectangle':'round-diamond',}},
   {selector:'node[?group]',style:{'font-weight':600,shape:cards?'round-rectangle':'ellipse','border-color':cards?'#ded5ea':'#eee8f7'}},
   {selector:'node[?pending]',style:{'border-style':'solid'}},
   {selector:'node[?stale]',style:{opacity:.5,'border-color':'#b77368'}},
   {selector:'edge',style:{width:1.15,'line-color':'#d3c9e1',opacity:.72,'curve-style':'unbundled-bezier','control-point-distances':'data(curveDistance)','control-point-weights':.5,'line-cap':'round','target-arrow-shape':'triangle','target-arrow-color':'#c4b8d4','arrow-scale':.6,'overlay-opacity':0,'transition-property':'opacity,line-color,width','transition-duration':200}},
   {selector:'edge[?selfLoop]',style:{'curve-style':'bezier','loop-direction':'-45deg','loop-sweep':'65deg'}},
   {selector:'edge[?dense]',style:{width:.7,opacity:.38,'target-arrow-shape':'none'}},
   {selector:'edge[?pending]',style:{'line-style':'dashed','line-color':'#c8b39b'}},
   {selector:'node.kg-muted',style:{opacity:.78}},
   {selector:'edge.kg-muted',style:{opacity:.08}},
   {selector:'edge.kg-near',style:{opacity:1,width:1.9,'line-color':'#ab95cc','target-arrow-color':'#ab95cc'}},
   {selector:'node.kg-selected, node.kg-hover',style:{'border-width':cards?2.5:6,'border-color':'#b69dd1','z-index':30}},
   {selector:'node.kg-match',style:{'border-width':cards?2.5:6,'border-color':'#b88753','text-opacity':1}},
   {selector:'node.kg-label-low',style:{'text-opacity':.0}},
   {selector:'node.kg-hover, node.kg-selected, node.kg-match',style:{'text-opacity':1}}
   ,{selector:'node.kg-card-compact',style:{label:'data(compact_label)','font-size':'data(drawFont)','line-height':1.3,'text-max-width':'data(drawTextWidth)'}}
   ,{selector:'node.kg-layout-footprint',style:{width:state.appearance==='cards'?246:126,height:state.appearance==='cards'?150:100,label:''}},
   {selector:'node.kg-native-label-hidden',style:{'text-opacity':0}}
  ];}
  let labelTier='',previewTimer=null,previewHideTimer=null,draggedUntil=0;
  function showPreview(id,pinned=false){const row=nodeFor(id);if(!row)return;clearTimeout(previewHideTimer);clearTimeout(previewTimer);previewTimer=setTimeout(()=>{if(destroyed||currentMode!=='2d')return;const node=cy.getElementById(id);if(!node.length)return;preview.replaceChildren(element('strong',row.label||row.id),element('small',short(row.summary,90)));const actions=element('div',null,'kg-preview-actions');actions.append(button(row.group?'进入主题':'打开页面',()=>openNode(id)),button('查看关系',()=>{preview.hidden=true;selectNode(id);}));if(!row.group)actions.append(button(state.expanded.includes(id)?'收起来源':'展开来源',()=>{preview.hidden=true;expand(id);}));preview.append(actions);const p=node.renderedPosition();preview.style.left=Math.min(Math.max(8,p.x+22),Math.max(8,stage.clientWidth-284))+'px';preview.style.top=Math.min(Math.max(8,p.y+24),Math.max(8,stage.clientHeight-164))+'px';preview.hidden=false;},pinned?0:120);}
  preview.onpointerenter=()=>{clearTimeout(previewHideTimer);clearTimeout(previewTimer);};preview.onpointerleave=()=>{previewHideTimer=setTimeout(()=>{preview.hidden=true;},180);};
  function render2D(redrawOnly=false){
   const newCanvas=!cy;
   if(!cy){cy=root.cytoscape({container:canvas,elements:[],layout:{name:'preset'},minZoom:.06,maxZoom:4,boxSelectionEnabled:false,wheelSensitivity:.7,style:graphStyles()});
    cy.on('tap','node',event=>{if(Date.now()<draggedUntil)return;const id=event.target.id();if(nodeFor(id)?.group)openNode(id);else selectNode(id);});
    cy.on('dbltap','node',event=>{if(Date.now()>=draggedUntil&&!nodeFor(event.target.id())?.group)openNode(event.target.id());});
    cy.on('cxttap taphold','node',event=>showPreview(event.target.id(),true));
    cy.on('tap','edge',event=>{cancelMotion();selectedEdge=event.target.id();if(shell.classList.contains('kg-detail-collapsed'))togglePanel(false);renderInspector();});
    cy.on('tap',event=>{if(event.target===cy){cancelMotion();preview.hidden=true;state.selected='';selectedEdge='';highlight();renderInspector();save();}});
    cy.on('mouseover','node',event=>{hover=event.target.id();event.target.addClass('kg-hover');showPreview(hover);});
    cy.on('mouseout','node',event=>{hover='';event.target.removeClass('kg-hover');clearTimeout(previewTimer);previewHideTimer=setTimeout(()=>{preview.hidden=true;},200);});
    cy.on('drag','node',()=>{draggedUntil=Date.now()+220;preview.hidden=true;});
    cy.on('dragfree','node',event=>{draggedUntil=Date.now()+220;const n=event.target,p=n.position();points[n.id()]={...points[n.id()],x:p.x,y:p.y,fixed:true};save();});
    cy.on('position','node',()=>scheduleLabels());
    cy.on('pan zoom',()=>{if(destroyed)return;preview.hidden=true;clearTimeout(previewTimer);scheduleLabels();views['2d']={zoom:cy.zoom(),pan:{...cy.pan()}};});
    cy.on('grab mousedown',()=>cancelMotion());canvas.tabIndex=0;canvas.onkeydown=event=>{if(event.key==='Enter'&&state.selected)openNode(state.selected);};
   }else if(!redrawOnly)cy.style(graphStyles());
   if(newCanvas&&views['2d'])cy.viewport(views['2d']);
   const gathering=scene.level==='local'&&gatheredFor!==state.focusRoot+'|'+state.appearance+'|'+(state.localPage||0),needsFit=!views['2d']&&!gathering;if(needsFit){const viewport=readingViewport();if(viewport){cy.viewport(viewport);views['2d']=viewport;}}
   const screen=Object.fromEntries(scene.nodes.filter(n=>points[n.id]).map(n=>[n.id,{x:points[n.id].x*cy.zoom()+cy.pan().x,y:points[n.id].y*cy.zoom()+cy.pan().y}]));
   const displayNodes=Model.selectVisible(scene.nodes,screen,{width:canvas.clientWidth,height:canvas.clientHeight,appearance:state.appearance,selected:state.selected,hover,matches:scene.matches||[],importance:layouts[currentMode]?.semanticIndex?.importance||{}}),displayIds=new Set(displayNodes.map(n=>n.id)),displayEdges=Model.visibleEdges(scene.edges,displayIds,state.selected);
   scene.renderedCount=displayNodes.length;
   drawingZoom=0;
   const previousIds=new Set(cy.nodes().map(n=>n.id())),ids=displayIds,edgeIds=new Set(displayEdges.map(e=>e.id));cy.batch(()=>{
    cy.edges().filter(e=>!edgeIds.has(e.id())).remove();cy.nodes().filter(n=>!ids.has(n.id())).remove();
    for(const n of displayNodes){const cardLabel=displayLabel(n),labelLines=state.appearance==='cards'?cardLabel.split('\n').length:0,textShift=state.appearance==='cards'?[cardTextShift(cardLabel,188,230,39),cardTextShift(compactLabel(n),164,184,10)]:[0,0],data={...n,...screenNodeData(n,cy.zoom(),labelLines||3,textShift),id:n.id,labelLines,textShift,display_label:cardLabel,compact_label:compactLabel(n),glyph:glyphFor(n),color:colorFor(n),claim:/Claim|claim|结论/.test(n.record_kind||n.semantic_kind||n.kind||''),material:!Model.semantic(n)&&!n.group,pending:!!n.suggested||n.status==='CANDIDATE',stale:!!n.stale};const old=cy.getElementById(n.id);if(old.length){old.data(data);if(old.position().x!==points[n.id].x||old.position().y!==points[n.id].y){if(!redrawOnly&&!reducedQuery.matches&&points[n.id].semantic)old.animate({position:points[n.id]},{duration:450,easing:'ease-in-out-cubic'});else if(!redrawOnly)old.position(points[n.id]);}}else cy.add({group:'nodes',data,position:points[n.id]});}
    for(const e of Model.curveEdges(displayEdges)){const data={...e,id:e.id,source:e.from,target:e.to,pending:!!e.suggested,dense:scene.nodes.length>1000||scene.edges.length>2500};const old=cy.getElementById(e.id);if(old.length)old.data(data);else cy.add({group:'edges',data});}
   });
   if(!redrawOnly){labelTier='';highlight();cy.resize();}
   if(scene.level==='local'&&!redrawOnly)gatherLocal();
   scheduleLabels();status.textContent=countText();
  }
  function highlight(){if(!cy)return;cy.elements().removeClass('kg-muted kg-near kg-selected kg-match');if(state.selected){const n=cy.getElementById(state.selected);if(n.length){cy.elements().addClass('kg-muted');n.closedNeighborhood().removeClass('kg-muted');n.connectedEdges().addClass('kg-near');n.addClass('kg-selected');}}
   for(const id of scene.matches||[])cy.getElementById(id).addClass('kg-match').removeClass('kg-muted');scheduleLabels();
  }
  function scheduleLabels(){if(labelFrame!==null||destroyed||currentMode!=='2d')return;labelFrame=requestAnimationFrame(()=>{labelFrame=null;drawLabels();});}
  function screenNodeData(node,zoom,labelLines=3,textShift=[0,0]){
   const cards=state.appearance==='cards',compact=cards&&zoom<.65,scale=1/Math.max(.04,zoom),paper=!!node.paper_id||node.kind==='论文',lines=Math.max(3,Math.min(5,labelLines));
   // Cards centre their label block, so the type icon is placed on the first text line.
   const iconY=(cards&&!compact?(134-lines*cardLeading)/2+.75:9)*scale,textX=(cards?(compact?textShift[1]:textShift[0]):0)*scale;
   return {drawWidth:(cards?(compact?184:230):paper?44:node.group?56:50)*scale,drawHeight:(cards?(compact?90:134):paper?52:node.group?56:50)*scale,drawIcon:(cards?(compact?0:18):24)*scale,drawAudit:10*scale,drawIconX:13*scale,drawIconY:iconY,drawTextX:textX,drawFont:(cards?cardFont:12)*scale,drawTextWidth:(cards?(compact?164:188):150)*scale};
  }
  function drawDensity(){
   densitySvg.hidden=currentMode!=='2d'||state.organization!=='free'||scene.level==='local'||scene.level==='search';if(densitySvg.hidden||!cy)return;
   if(!root.ResearchKnowledgeDensity){if(!root.__densityLoad){const script=element('script');script.src='/vendor/knowledge-graph/knowledge-density.js';script.onload=()=>{if(!destroyed){densityKey='';drawDensity();}};script.onerror=()=>{root.__densityLoad=false;script.remove();};root.__densityLoad=true;document.head.append(script);}return;}
   const key=[snapshot.graph_fingerprint,scene.nodes.length,scene.nodes.filter(n=>points[n.id]?.semantic).length].join('|');
   if(key!==densityKey){densityKey=key;densityGroup.replaceChildren();for(const [i,d] of root.ResearchKnowledgeDensity.paths(scene.nodes,points).entries()){const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',d);path.setAttribute('fill','#b9cfc4');path.setAttribute('fill-opacity',String(.075+i*.012));path.setAttribute('stroke','#a7c5b5');path.setAttribute('stroke-opacity','.26');path.setAttribute('stroke-width','.6');path.setAttribute('vector-effect','non-scaling-stroke');densityGroup.append(path);}}
   densityGroup.setAttribute('transform',`translate(${cy.pan().x} ${cy.pan().y}) scale(${cy.zoom()})`);
  }
  function drawLabels(){
   if(!cy||destroyed||currentMode!=='2d')return;halos.hidden=true;
   const screen=Object.fromEntries(scene.nodes.filter(n=>points[n.id]).map(n=>[n.id,{x:points[n.id].x*cy.zoom()+cy.pan().x,y:points[n.id].y*cy.zoom()+cy.pan().y}]));
   const visible=Model.selectVisible(scene.nodes,screen,{width:canvas.clientWidth,height:canvas.clientHeight,appearance:state.appearance,selected:state.selected,hover,matches:scene.matches||[],importance:layouts[currentMode]?.semanticIndex?.importance||{}});
   const signature=visible.map(n=>n.id).sort().join('|');if(signature!==cy.nodes().map(n=>n.id()).sort().join('|'))render2D(true);
   if(Math.abs(drawingZoom-cy.zoom())>.0001){drawingZoom=cy.zoom();cy.batch(()=>{for(const n of cy.nodes())n.data(screenNodeData(nodeFor(n.id()),drawingZoom,n.data('labelLines'),n.data('textShift')));});}drawDensity();
   const overlay=state.appearance!=='cards';cy.nodes().toggleClass('kg-native-label-hidden',overlay);cy.nodes().toggleClass('kg-card-compact',state.appearance==='cards'&&cy.zoom()<.65);
   if(!overlay){for(const node of labelNodes.values())node.remove();labelNodes.clear();labelBoxes.clear();return;}
   const required=new Set([state.selected,hover].filter(Boolean)),rank=new Map((scene.matches||[]).map((id,i)=>[id,i])),importance=layouts[currentMode]?.semanticIndex?.importance||{};
   const items=cy.nodes().map(n=>{const p=n.renderedPosition();return {id:n.id(),x:p.x,y:p.y,width:n.data('group')?180:148,height:36,radius:n.renderedWidth()/2,priority:n.id()===state.selected?1e6:n.id()===hover?9e5:rank.has(n.id())?1e5-rank.get(n.id()):Number(importance[n.id()]||0)};}).sort((a,b)=>b.priority-a.priority).slice(0,28);
   const used=new Set();
   for(const box of Model.placeLabels(items,{width:canvas.clientWidth,height:canvas.clientHeight,required,previous:Object.fromEntries(labelBoxes)})){
    used.add(box.id);labelBoxes.set(box.id,box);
    const row=nodeFor(box.id);if(!row)continue;let label=labelNodes.get(box.id);if(!label){label=button('',()=>nodeFor(box.id)?.group?openNode(box.id):selectNode(box.id),'kg-node-label');labelNodes.set(box.id,label);}label.classList.toggle('kg-label-required',required.has(row.id));if(label.textContent!==short(row.label||row.id,36))label.textContent=short(row.label||row.id,36);
    label.ondblclick=()=>{if(!row.group)openNode(row.id);};label.onkeydown=e=>{if(e.key==='Enter')openNode(row.id);};label.dataset.nodeId=row.id;label.title=row.label||row.id;
    label.style.cssText=`left:0;top:0;transform:translate(${box.x}px,${box.y}px);width:${box.width}px;height:${box.height}px`;if(label.parentNode!==labels)labels.append(label);
   }
   for(const [id,node] of labelNodes)if(!used.has(id)){node.remove();labelNodes.delete(id);labelBoxes.delete(id);}
  }


  function render2DIfNeeded(){if(currentMode==='2d'&&cy)render2D(true);}
  function selectNode(id,move=false){cancelMotion();state.selected=id;selectedEdge='';if(shell.classList.contains('kg-detail-collapsed'))togglePanel(false);render2DIfNeeded();highlight();renderer3D?.update({...scene,selected:id});renderInspector();feedback(panel,[{opacity:.75,transform:'translateY(4px)'},{opacity:1,transform:'translateY(0)'}],200);save();if(move)focus(id);}
  function transitionTheme(apply,direction){
   navigateView(()=>{apply();shell.classList.add('kg-detail-collapsed');});
  }
  function showOverview(){return transitionTheme(()=>{state.topicPath=[];state.community='';state.overviewAll=false;state.focusRoot='';state.query='';search.value='';state.selected='';state.expanded=[];},-1);}
  function enterCommunity(id){return transitionTheme(()=>{if(id==='__more__'){state.overviewAll=true;state.community='';}else state.community=id;state.selected='';state.expanded=[];},1);}
  function expand(id){
   if(nodeFor(id)?.group){openNode(id);return;}
   const closing=state.focusRoot===id;navigateView(()=>{state.focusRoot=closing?'':id;state.expanded=closing?[]:[id];state.selected=id;state.localPage=0;});
   if(!closing&&currentMode==='3d')renderer3D?.fit({ids:scene.nodes.map(n=>n.id),duration:450});
  }

  function openNode(id){const node=nodeFor(id);if(!node)return;preview.hidden=true;clearTimeout(previewTimer);if(node.group){expansionOrigin=points[id];if(node.navigation==='topic')transitionTheme(()=>{state.topicPath=[...state.topicPath,node.group_id];state.expanded=[];state.selected='';},1);else enterCommunity(node.group_id);return;}state.selected=id;save();if(Model.semantic(node)){bridge.openKnowledgeNode?.(node.id);return;}bridge.openGraphMaterial?.(node);}
  function sourceNodes(node){const ids=new Set(node.source_ids||[]);for(const ref of node.source_refs||[])ids.add(typeof ref==='string'?ref:ref.source_id||ref.id);for(const e of snapshot.edges||[])if(e.from===node.id||e.to===node.id){const other=nodeFor(e.from===node.id?e.to:e.from);if(other&&!Model.semantic(other))ids.add(other.id);}return [...ids].map(id=>nodeFor(id)||snapshot.nodes.find(n=>n.doc_id===id||n.paper_id===id||n.record_id===id)).filter(Boolean);}
  function renderInspector(){
   if(destroyed)return;panel.replaceChildren();const n=nodeFor(state.selected),edge=selectedEdge&&([...scene.edges,...(snapshot.edges||[])]).find(e=>e.id===selectedEdge);
    if(edge){
    const from=nodeFor(edge.from),to=nodeFor(edge.to);
    const registered=edge.source==='关系账本'&&Number.isInteger(edge.revision);
    const scientific=edge.layer==='scientific'||['Supports','Contradicts','Inconclusive'].includes(edge.kind);
    panel.append(element('span',registered?'本人登记的关系':edge.suggested?'AI 关联建议':'已记录关联','kg-eyebrow'),
      element('h3',edge.label||edge.kind||'资料关系'),element('p',(from?.label||edge.from)+' → '+(to?.label||edge.to)),
      element('p',edge.explanation||edge.reason||edge.conditions||'沿来源核对这条关联。'));
    if(edge.stale)panel.append(element('p','出处版本已有变化，以下保留建立关系时的原文片段。','kg-warning'));
    appendEvidence(edge.evidence||[]);
    if(!edge.stale&&!edge.aggregate&&(scientific||registered)&&edge.status==='CANDIDATE'){
     const reason=element('textarea');reason.placeholder='填写核查依据';
     const review=async action=>{
      if(!reason.value.trim()){showError(new Error('请填写关系核查依据。'));return;}
      try{await request('/api/research/review',{id:edge.id,revision:edge.revision,action,reason:reason.value});await refresh();}
      catch(error){showError(error);}
     };
     panel.append(reason,button(scientific?'确认科研关系':'确认登记关系',()=>review('VERIFIED')),
                  button('不采用关系',()=>review('REJECTED')));
    }
    if(registered&&!edge.stale&&edge.status!=='REJECTED'&&from&&to){
     const id=n=>n.record_id||n.paper_id||n.doc_id;
     panel.append(button('编辑登记关系',()=>bridge.showRelationEditor?.([from,to],{
       source:id(from),target:id(to),kind:edge.kind,revision:edge.revision,evidence:edge.evidence,conditions:edge.explanation
     })));
    }
    for(const id of [edge.from,edge.to])panel.append(button(nodeFor(id)?.label||id,()=>selectNode(id,true),'kg-source'));
    return;
   }
   if(n?.group){panel.append(element('span','主题群落','kg-eyebrow'),element('h3',n.label),element('p',n.summary),element('p',n.pendingCount+' 项 AI 索引'),button('展开主题',()=>openNode(n.id)));return;}
   if(!n){panel.append(element('span','READ & CONNECT','kg-eyebrow'),element('h3','从一个概念开始'),element('p','选择节点查看结论、限定条件和原文依据；展开来源后，资料与知识仍保留同一身份。'));if(extraction)appendProgress();return;}
   panel.append(element('span',n.kind||n.semantic_kind||'知识','kg-eyebrow'),element('h3',n.label||n.id),element('span',n.stale?'来源有变化':n.suggested||n.status==='CANDIDATE'?'AI 提取':n.status==='VERIFIED'?'提取已核对':'已记录','kg-badge'),element('p',n.summary||n.reason||''));
   if(n.conditions)panel.append(element('p','适用条件：'+(typeof n.conditions==='string'?n.conditions:JSON.stringify(n.conditions))));
   const actions=element('div',null,'kg-panel-actions');actions.append(button('打开页面',()=>openNode(n.id)),button('聚焦',()=>focus(n.id)),button(state.expanded.includes(n.id)?'收起局部来源':'展开局部来源',()=>expand(n.id)));panel.append(actions);
   const sources=sourceNodes(n);if(sources.length){panel.append(element('h4','原稿来源'));for(const source of sources)panel.append(button((source.paper_id?'论文 · ':'知识稿 · ')+(source.label||source.id),()=>bridge.openGraphMaterial?.(source),'kg-source'));}
   appendEvidence([...(n.source_refs?.filter(r=>typeof r==='object')||[]),...(n.evidence||[])]);
   if(n.stale)panel.append(element('p','此节点保留旧证据；重新抽取核对前不视为当前结论。','kg-warning'));
    if(n.record_kind==='ExtractedClaim'&&n.source_kind==='original'&&!n.stale&&bridge.compareOriginal)panel.append(button('比对原文',()=>bridge.compareOriginal(n.id)));
    if(n.extracted)appendReviewTools(n);
   const adjacent=(snapshot.edges||[]).filter(e=>e.from===n.id||e.to===n.id);if(adjacent.length){panel.append(element('h4','直接关联 · '+adjacent.length));for(const e of adjacent){const other=nodeFor(e.from===n.id?e.to:e.from);if(other)panel.append(button((e.label||e.kind||'关联')+' · '+(other.label||other.id),()=>{if(!scene.nodes.some(row=>row.id===other.id)){state.expanded=[...new Set([...state.expanded,n.id])];rebuild();}selectNode(other.id,true);},'kg-source'));}}
  }
  function appendReviewTools(n){
   const tools=element('details',null,'kg-review'),reason=element('textarea'),review=element('div',null,'kg-panel-actions');
   tools.append(element('summary','核查与整理'));reason.placeholder='核查说明或不采用原因';reason.setAttribute('aria-label','核查说明');
   if(n.suggested||n.status==='CANDIDATE')review.append(button('确认提取准确',()=>extractionAction('verify',n,{reason:reason.value||'本人核对了本节点提取内容及原文出处。'})));
   review.append(button('不采用',()=>extractionAction('reject',n,{reason:reason.value||'本人选择不采用此提取结果。'})),button('提炼为知识稿',()=>extractionAction('promote',n)));
   tools.append(reason,review);
   const compatible=snapshot.nodes.filter(other=>other.id!==n.id&&other.record_kind===n.record_kind&&other.extracted&&!other.stale);
   if(compatible.length){
    const query=element('input'),target=element('select');query.type='search';query.placeholder='查找同义概念或相同论断';query.setAttribute('aria-label','查找合并目标');target.setAttribute('aria-label','合并到同类知识');
    const update=()=>{const value=query.value.trim().normalize('NFKC').toLocaleLowerCase();target.replaceChildren(new Option('选择合并目标',''));if(value.length<2)return;for(const row of compatible.filter(row=>String(row.label||'').normalize('NFKC').toLocaleLowerCase().includes(value)).slice(0,20))target.append(new Option((row.label||row.id)+' · '+row.id.slice(-6),row.id));};
    query.addEventListener('input',update);update();tools.append(query,target,button('合并到所选知识',()=>{if(!target.value||!reason.value.trim()){showError(new Error('请选择目标并填写明确的对应依据。'));return;}extractionAction('alias',n,{target:target.value,target_revision:nodeFor(target.value)?.revision,reason:reason.value});}));
   }
   panel.append(tools);
  }
  function appendEvidence(rows){const seen=new Set();for(const ref of rows){const text=ref.quote||ref.text||ref.excerpt||ref.location;if(!text||seen.has(text))continue;seen.add(text);if(text.length>420){const excerpt=element('details',null,'kg-evidence'),title=element('summary',text.slice(0,210)+'…');excerpt.append(title,element('blockquote',text));panel.append(excerpt);}else panel.append(element('blockquote',text));if(ref.location!==text)panel.append(element('small',ref.location||ref.page||ref.source_id||''));const source=nodeFor(ref.source_id||ref.id)||snapshot.nodes.find(n=>[n.paper_id,n.doc_id,n.record_id].includes(ref.source_id||ref.id));if(source)panel.append(button(ref.page?'打开原文第 '+ref.page+' 页':'打开这段依据的来源',()=>source.paper_id&&bridge.navigate?bridge.navigate('paper',source.paper_id,'original',ref.page?'page='+ref.page:String(ref.section||'')):bridge.openGraphMaterial?.(source),'kg-source'));}}
  async function extractionAction(action,node,extra={}){try{const result=await request('/api/knowledge/extraction',{action,id:node?.record_id||node?.id,revision:node?.revision,...extra});if(action==='promote')bridge.loadKnowledge?.(true);extraction=await request('/api/knowledge/extraction');await refresh();if(!node)showCoverage();else bridge.notify?.(action==='promote'?'已建立带来源的知识稿':'提取状态已保存');}catch(error){showError(error);}}
  async function refreshExtraction(){try{const value=await request('/api/knowledge/extraction');if(destroyed)return false;extraction=value;if(!state.selected&&!selectedEdge)renderInspector();if(!scene.semanticCount&&state.view==='knowledge')empty.append(element('p',progressText()));if(value.enabled&&!value.paused&&['queued','running','due','scheduled'].includes(value.runtime?.state)&&!refreshTimer)refreshTimer=setTimeout(()=>{refreshTimer=null;refresh();},12000);return true;}catch{return false;}}
  function progressText(){const c=extraction?.counts||{};return `${c.processed_chunks||0} / ${c.total_chunks||0} 段已处理 · ${c.concepts||0} 个概念 · ${c.claims||0} 条结论`;}
  function appendProgress(){if(extraction?.runtime){const r=extraction.runtime;panel.append(element('p','实际状态：'+({running:'任务执行中',queued:'任务已排队',scheduled:'等待计划检查',current:'资料已检查',due:'等待调度',paused:'已暂停',disabled:'自动提取关闭',blocked:'外部服务阻断'}[r.state]||r.state)+' · '+r.reason+(r.next_check?' · 下次检查 '+new Date(r.next_check).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'')));}if(extraction.counts?.rejected_candidates)panel.append(element('p',`${extraction.counts.partial_index_units} 段中有 ${extraction.counts.rejected_candidates} 条AI候选未通过证据校验，已保留拒收原因且未入图；已通过的索引不等于人工科研核查。`,'kg-warning'));panel.append(element('h4','知识抽取'),element('p',progressText()),element('p',extraction.paused?'当前已暂停':({needs_attention:'部分来源需要核查，可查看下方失败原因',pending:'等待调度或继续处理',complete:'文字覆盖处理完成；科研核查另行进行',partial:'可用文字已处理，部分来源不可用'}[extraction.status]||'等待开始')));const actions=element('div',null,'kg-panel-actions');actions.append(button(extraction.runtime?.state==='blocked'?'服务恢复后继续':extraction.paused?'继续抽取':extraction.enabled?'暂停抽取':'开始抽取',()=>extractionAction(extraction.runtime?.state==='blocked'||extraction.paused?'resume':extraction.enabled?'pause':'start')),button('重试失败项',()=>extractionAction('retry_failed')),button(extraction.enabled?'关闭自动更新':'启用自动更新',()=>extractionAction(extraction.enabled?'disable':'enable')));panel.append(actions);}
  function showCoverage(){cancelMotion();state.selected='';selectedEdge='';panel.replaceChildren(element('span','SOURCE COVERAGE','kg-eyebrow'),element('h3','抽取与来源覆盖'));if(shell.classList.contains('kg-detail-collapsed'))togglePanel(false);if(!extraction){panel.append(element('p','正在读取进度…'));refreshExtraction().then(ok=>{if(ok)showCoverage();else if(!destroyed)panel.replaceChildren(element('p','暂时无法读取抽取进度，可稍后刷新。'));});return;}appendProgress();for(const row of extraction.coverage||[]){const card=element('div',null,'kg-coverage-row');card.append(element('strong',row.title||row.source_id),element('small',`${({ready:row.rebuilding?'新版文字已发布，知识重建中':row.text_complete?'文字覆盖完成':'等待处理或接续',missing_original:'缺少原文',out_of_scope:'不在知识准入范围',unparsed:'原文尚未解析',stale_cache:'原文与缓存版本不符',partial_parse:'解析范围不完整',low_quality_text:'原文乱码或 OCR 质量不足，待修复'}[row.status]||'待处理')} · ${row.processed_chunks||0}/${row.total_chunks||0} 段${row.rejected_candidates?' · '+row.rejected_candidates+'条AI候选被校验拦截':''}`));const failure=extraction.failures?.find(f=>f.source_id===row.source_id);if(failure)card.append(element('p',failure.message,'kg-warning'));const source=nodeFor(row.source_id);if(source)card.append(button('打开来源',()=>bridge.openGraphMaterial?.(source)));panel.append(card);}if(extraction.failures?.length)panel.append(element('p',`${extraction.failures.length} 项处理失败，可重试；未获得的全文不会生成结论。`,'kg-warning'));}
  function togglePanel(force){const collapsed=force===undefined?!shell.classList.contains('kg-detail-collapsed'):force;shell.classList.toggle('kg-detail-collapsed',collapsed);updateButtons();resize();save();}
  function resize(){cy?.resize();scheduleLabels();renderer3D?.update({...scene});}
  function zoom(factor){cancelMotion();if(currentMode==='3d'){renderer3D?.zoom?.(factor);return;}if(!cy)return;const target={level:cy.zoom()*factor,renderedPosition:{x:canvas.clientWidth/2,y:canvas.clientHeight/2}};if(reducedQuery.matches)cy.zoom(target);else cy.animate({zoom:target},{duration:280,easing:'ease-out-cubic'});save();}
  function readingViewport(ids){
   const wanted=ids?new Set(ids):null,rows=scene.nodes.filter(n=>(!wanted||wanted.has(n.id))&&points[n.id]).map(n=>points[n.id]);if(!rows.length)return null;
   const xs=rows.map(p=>p.x),ys=rows.map(p=>p.y),left=Math.min(...xs),right=Math.max(...xs),top=Math.min(...ys),bottom=Math.max(...ys),pad=state.appearance==='cards'?180:90;
   const zoom=Math.min(state.appearance==='cards'?1:1.15,Math.max(.06,Math.min(canvas.clientWidth/Math.max(1,right-left+pad*2),canvas.clientHeight/Math.max(1,bottom-top+pad*2))));
   return {zoom,pan:{x:canvas.clientWidth/2-(left+right)/2*zoom,y:canvas.clientHeight/2-(top+bottom)/2*zoom}};
  }
  function fit(animate=true,interrupt=true){if(interrupt)cancelMotion();const pending=layouts[currentMode]?.semanticPositions;if(pending){for(const [id,p] of Object.entries(pending))if(!points[id]?.fixed)points[id]={...points[id],...p,semantic:true};delete layouts[currentMode].semanticPositions;delete views[currentMode];rebuild();cacheSnapshot();}if(currentMode==='3d'){renderer3D?.fit();return;}if(!cy)return;const viewport=readingViewport();if(viewport){if(!animate||reducedQuery.matches)cy.viewport(viewport);else cy.animate(viewport,{duration:450,easing:'ease-in-out-cubic'});}scheduleLabels();}

  function focus(id){cancelMotion();if(currentMode==='3d'){renderer3D?.focus(id);return;}if(!cy)return;const n=cy.getElementById(id);if(n.length){if(reducedQuery.matches){cy.zoom(Math.max(.8,Math.min(1.5,cy.zoom())));cy.center(n);}else cy.animate({center:{eles:n},zoom:Math.max(.8,Math.min(1.5,cy.zoom()))},{duration:450,easing:'ease-in-out-cubic'});}scheduleLabels();}
  function focusMany(ids){cancelMotion();if(currentMode==='3d'){renderer3D?.fit({ids,duration:450});return;}const wanted=new Set(ids),collection=cy?.nodes().filter(n=>wanted.has(n.id()));if(collection?.length){if(reducedQuery.matches)cy.fit(collection,70);else cy.animate({fit:{eles:collection,padding:70}},{duration:450,easing:'ease-in-out-cubic'});}}
  async function switchMode(mode){
   if(destroyed||currentMode===mode&&requestedMode===mode)return;requestedMode=mode;cancelMotion();positionViews[currentMode]=points;rememberNavigation();const token=++modeId;if(currentMode==='2d'&&cy)views['2d']={zoom:cy.zoom(),pan:{...cy.pan()}};if(currentMode==='3d'&&renderer3D)views['3d']=renderer3D.getView?.();
   if(mode==='3d'){status.textContent='正在准备三维视图…';try{await Promise.all([load3D(),ensureLayout('3d')]);if(destroyed||token!==modeId)return;cy?.destroy();cy=null;labels.replaceChildren();halos.hidden=true;currentMode='3d';points=navigationViews[navigationKey()]?.positions||positionViews['3d']||{};if(navigationViews[navigationKey()]?.view)views['3d']=navigationViews[navigationKey()].view;layout=layouts['3d']||layout;rebuild();
     const created=await root.ResearchGraph3D.mount(canvas,{...scene,positions:points,selected:state.selected,reducedMotion:reducedQuery.matches,onInteract:cancelMotion,onSelect:id=>selectNode(id),onOpen:id=>openNode(id),onEdgeSelect:id=>{selectedEdge=id;if(shell.classList.contains('kg-detail-collapsed'))togglePanel(false);renderInspector();},onPositions:next=>{if(destroyed)return;points={...points,...next};scene.positions=points;save();},onError:showError});if(destroyed||token!==modeId){created.destroy();return;}renderer3D=created;if(views['3d'])renderer3D.setView?.(views['3d']);status.textContent=countText();semanticLayout();
    }catch(error){if(destroyed||token!==modeId)return;renderer3D?.destroy();renderer3D=null;canvas.replaceChildren();currentMode=requestedMode='2d';points=navigationViews[navigationKey()]?.positions||positionViews['2d']||{};if(navigationViews[navigationKey()]?.view)views['2d']=navigationViews[navigationKey()].view;layout=layouts['2d']||layout;halos.hidden=false;rebuild();showError(new Error('三维暂不可用，已返回二维；可以继续检索、展开和打开原文。'));}
   }else{try{await ensureLayout('2d');}catch(error){if(!destroyed&&token===modeId)showError(error);return;}if(destroyed||token!==modeId)return;renderer3D?.destroy();renderer3D=null;cy?.destroy();cy=null;canvas.replaceChildren();currentMode='2d';points=navigationViews[navigationKey()]?.positions||positionViews['2d']||{};if(navigationViews[navigationKey()]?.view)views['2d']=navigationViews[navigationKey()].view;layout=layouts['2d']||layout;halos.hidden=false;rebuild();}
   feedback(canvas,[{opacity:.7},{opacity:1}],600);updateButtons();save();semanticLayout();
  }
  // Local expansion gathers the selected object, its direct relations and their sources into
  // a compact radial layout. It only moves the local view; the main graph keeps its coordinates.
  function gatherLocal(){
   const root=state.focusRoot;if(!root||currentMode!=='2d'||!cy)return;
   const key=root+'|'+state.appearance+'|'+(state.localPage||0);
   if(gatheredFor===key)return;const center=points[root];if(!center)return;
   gatheredFor=key;
   const nodes=scene.nodes.filter(n=>!n.group&&n.id!==root&&points[n.id]);if(!nodes.length){fit(true,false);return;}
   const adj=new Map();for(const e of scene.edges){if(e.from===e.to||!points[e.from]||!points[e.to])continue;const a=adj.get(e.from)||new Set();a.add(e.to);adj.set(e.from,a);const b=adj.get(e.to)||new Set();b.add(e.from);adj.set(e.to,b);}
   const ring=new Map([[root,0]]),queue=[root];
   while(queue.length){const id=queue.shift();for(const other of adj.get(id)||[]){if(ring.has(other)||other===root)continue;ring.set(other,ring.get(id)+1);queue.push(other);}}
   const groups=new Map();
   for(const n of nodes){if(points[n.id]?.fixed)continue;const d=Math.min(2,ring.get(n.id)??1),rows=groups.get(d)||[];rows.push(n);groups.set(d,rows);}
   const cards=state.appearance==='cards',base=cards?310:160,step=cards?270:140,spacing=cards?270:115;
   const targets={[root]:{x:center.x,y:center.y}};
   for(const [distance,rows] of [...groups].sort((a,b)=>a[0]-b[0])){
    const angle=n=>{const p=points[n.id];return Math.atan2(p.y-center.y,p.x-center.x);};
    rows.sort((a,b)=>angle(a)-angle(b));
    const radius=Math.max(base*distance,rows.length*spacing/(Math.PI*2)),start=angle(rows[0]);
    rows.forEach((n,i)=>{const a=start+i*Math.PI*2/rows.length;targets[n.id]={x:center.x+Math.cos(a)*radius,y:center.y+Math.sin(a)*radius};});
   }
   const xs=Object.values(targets).map(p=>p.x),ys=Object.values(targets).map(p=>p.y),pad=cards?150:110;
   const wide=Math.max(...xs)-Math.min(...xs),high=Math.max(...ys)-Math.min(...ys);
   const zoom=Math.min(cards?1.25:1.45,Math.max(.18,Math.min(cy.width()/(wide+pad*2),cy.height()/(high+pad*2))));
   const view={zoom,pan:{x:cy.width()/2-(Math.min(...xs)+Math.max(...xs))/2*zoom,y:cy.height()/2-(Math.min(...ys)+Math.max(...ys))/2*zoom}};
   for(const [id,target] of Object.entries(targets))points[id]={...points[id],...target,localSettled:true};
   if(reducedQuery.matches){for(const [id,target] of Object.entries(targets)){const n=cy.getElementById(id);if(n.length)n.position(target);}cy.viewport(view);}
   else{
    const version=interactionVersion;let order=0;
    for(const [id,target] of Object.entries(targets)){const n=cy.getElementById(id);if(!n.length)continue;if(id===root){n.animate({position:target},{duration:360,easing:'ease-out-cubic'});continue;}n.delay(Math.min(200,order*28)).animate({position:target},{duration:620,easing:'ease-in-out-cubic'});order++;}
    setTimeout(()=>{if(destroyed||!cy||version!==interactionVersion)return;cy.animate(view,{duration:720,easing:'ease-in-out-cubic'});views['2d']={zoom:view.zoom,pan:view.pan};save();},40);
   }
   if(reducedQuery.matches)views['2d']={zoom:view.zoom,pan:view.pan};
   scheduleLabels();save();
  }
  function arrange(incremental,fitLayout=false){
   if(!incremental)cancelMotion();if(currentMode==='3d'){renderer3D?.rearrange?.();return;}if(!cy?.nodes().length)return;
   const selected=incremental?cy.nodes().filter(n=>incremental.includes(n.id())).closedNeighborhood():cy.elements(),before=new Map(selected.nodes().map(n=>[n.id(),{...n.position()}]));
   const fixed=selected.nodes().filter(n=>points[n.id()]?.fixed||n.id()===state.focusRoot||incremental&&!incremental.includes(n.id())),locked=fixed.filter(n=>!n.locked());locked.lock();
   // Reserve the largest appearance with fCoSE's own node bounds. Appearance changes never relayout.
   selected.nodes().addClass('kg-layout-footprint');
   try{
    selected.layout({name:'fcose',quality:'proof',randomize:false,animate:false,fit:false,nodeDimensionsIncludeLabels:false,fixedNodeConstraint:fixed.length?fixed.map(n=>({nodeId:n.id(),position:{...n.position()}})):undefined,nodeSeparation:80,nodeRepulsion:()=>state.appearance==='cards'?17000:8500,idealEdgeLength:()=>state.appearance==='cards'?280:140,numIter:700,tilingPaddingHorizontal:80,tilingPaddingVertical:60}).run();
    const targets=new Map(selected.nodes().map(n=>[n.id(),{...n.position()}])),view=fitLayout?cy.getFitViewport(cy.elements(),65):null;
    selected.nodes().removeClass('kg-layout-footprint');locked.unlock();
    for(const n of selected.nodes()){
     const target=targets.get(n.id());points[n.id()]={...points[n.id()],...target,localSettled:true,cardSpacing:true};
     if(!reducedQuery.matches&&!n.locked()){n.position(before.get(n.id()));n.animate({position:target},{duration:450,easing:'ease-in-out-cubic'});}
    }
    if(view){const ratio=Math.min(view.zoom,1)/view.zoom;view.pan={x:cy.width()/2+(view.pan.x-cy.width()/2)*ratio,y:cy.height()/2+(view.pan.y-cy.height()/2)*ratio};view.zoom=Math.min(view.zoom,1);if(reducedQuery.matches)cy.viewport(view);else cy.animate(view,{duration:450,easing:'ease-in-out-cubic'});}
    scheduleLabels();save();
   }finally{selected.nodes().removeClass('kg-layout-footprint');locked.unlock();}
  }
  function startPresentation(){
   if(playing){cancelMotion();return;}if(!scene.nodes.length)return;
   if(!presentation)presentation={mode:currentMode,view:currentMode==='2d'?{zoom:cy.zoom(),pan:{...cy.pan()}}:renderer3D?.getView(),index:0};
   cancelMotion();playing=true;setLabel(play,'暂停演示');exitPlay.hidden=false;
   const token=motion.start(),groups=new Map();for(const n of scene.nodes){const key=n.group_id||layout.nodes?.[n.id]?.community||n.kind;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(n.id);}const stops=[...groups.values()];
   const advance=()=>{if(!motion.active(token)||destroyed||!presentation)return;if(presentation.index>=stops.length){finishPresentation();return;}const ids=stops[presentation.index++];if(currentMode==='3d')renderer3D?.focus(ids[0]);else{const wanted=new Set(ids),group=cy?.nodes().filter(n=>wanted.has(n.id()));if(group?.length){if(reducedQuery.matches)cy.fit(group,80);else cy.animate({fit:{eles:group,padding:80}},{duration:900,easing:'ease-in-out-cubic'});}}motion.delay(advance,3000);};advance();
  }
  async function exportImage(){try{let value;if(currentMode==='3d')value=await renderer3D?.exportImage();else if(cy){const image=new Image();image.src=cy.png({scale:2,bg:'#ffffff',full:false});await image.decode();const out=element('canvas');out.width=image.width;out.height=image.height;const ctx=out.getContext('2d');ctx.drawImage(image,0,0);ctx.scale(2,2);for(const label of labels.children){const x=parseFloat(label.style.left),y=parseFloat(label.style.top),w=parseFloat(label.style.width);ctx.fillStyle='#ffffff';ctx.fillRect(x,y,w,label.offsetHeight);ctx.fillStyle='#343e3a';ctx.font='12px Microsoft YaHei,sans-serif';ctx.save();ctx.beginPath();ctx.rect(x,y,w,label.offsetHeight);ctx.clip();let line='',row=0;for(const char of label.textContent){if(line&&ctx.measureText(line+char).width>w-12){ctx.fillText(line,x+6,y+14+16*row++);line='';}line+=char;}ctx.fillText(line,x+6,y+14+16*row);ctx.restore();}value=out.toDataURL('image/png');}if(value instanceof Blob)value=URL.createObjectURL(value);if(!value)return;const a=element('a');a.href=value;a.download='知识关系图-'+currentMode+'.png';a.click();if(value.startsWith('blob:'))setTimeout(()=>URL.revokeObjectURL(value),500);}catch(error){showError(error);}}
  search.oninput=()=>{
   cancelMotion();clearTimeout(searchTimer);const token=++searchRequest;rememberNavigation();state.query=search.value;state.searchResult=null;state.focusRoot='';
   if(!state.query.trim()){const prior=navigationViews[navigationKey()];if(prior?.view)views[currentMode]=prior.view;rebuild();return;}
   searchTimer=setTimeout(async()=>{
    if(destroyed||token!==searchRequest)return;const fingerprint=snapshot.graph_fingerprint;
    const local=Model.project({...snapshot,communities:layout.communities||[]},state);if(local.nodes.length){delete views[currentMode];rebuild();}
    status.textContent='正在查找相关知识…';
    try{const result=await request('/api/knowledge/explore?'+scopeQuery({fingerprint,q:state.query.trim()}));if(destroyed||token!==searchRequest||fingerprint!==snapshot.graph_fingerprint)return;state.searchResult=result;delete views[currentMode];rebuild();if(currentMode==='3d')renderer3D?.fit();}
    catch(error){if(!destroyed&&token===searchRequest){rebuild();status.textContent=countText()+' · 当前使用文字匹配';}}
   },220);
  };
  search.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();if(scene.level==='search'&&scene.nodes.length)selectNode(scene.nodes[0].id,true);}};
  candidateInput.onchange=()=>{state.showCandidates=candidateInput.checked;refresh();save();};
  let resizing=null;splitter.onpointerdown=event=>{cancelMotion();resizing={x:event.clientX,width:panel.getBoundingClientRect().width};splitter.setPointerCapture(event.pointerId);};splitter.onpointermove=event=>{if(!resizing)return;const width=Math.max(280,Math.min(620,shell.clientWidth*.55,resizing.width+resizing.x-event.clientX));shell.style.setProperty('--kg-detail-width',width+'px');resize();};splitter.onpointerup=()=>{resizing=null;save();};splitter.onpointercancel=()=>{resizing=null;};splitter.onkeydown=event=>{if(!['ArrowLeft','ArrowRight'].includes(event.key))return;event.preventDefault();const width=parseFloat(shell.style.getPropertyValue('--kg-detail-width'))+(event.key==='ArrowLeft'?20:-20);shell.style.setProperty('--kg-detail-width',Math.max(280,Math.min(620,width))+'px');resize();save();};
  stage.addEventListener('pointerdown',()=>{if(layer.inert)cancelMotion();},true);stage.addEventListener('wheel',()=>cancelMotion(),{capture:true,passive:true});
  const observer=new ResizeObserver(()=>resize());observer.observe(stage);const reducedChange=()=>{cancelMotion();renderer3D?.update({...scene,reducedMotion:reducedQuery.matches});};reducedQuery.addEventListener('change',reducedChange);
  if(bridge.loadKnowledge)bridge.loadKnowledge().then(catalog=>{if(destroyed)return;
   const add=(key,label,rows)=>{const select=element('select');select.setAttribute('aria-label',label);select.append(new Option(label,''));for(const row of rows)select.append(new Option(row.label,row.id));select.value=filters[key];select.onchange=()=>{filters[key]=select.value;state.expanded=[];refresh();};scope.append(select);};
   const projects=new Map();for(const row of [...(catalog.documents||[]),...(catalog.papers||[])]){const id=row.source_project||row.project;if(id&&id!=='共享')projects.set(id,row.source_project_title||id);}add('source_project','全部来源',[...projects].map(([id,label])=>({id,label})));
   add('topic','全部主题',(catalog.classification?.nodes||[]).filter(n=>n.dimension==='topic').map(n=>({id:n.id,label:n.title})));
   add('purpose','全部用途',(catalog.classification?.nodes||[]).filter(n=>n.dimension==='usage'||n.dimension==='purpose').map(n=>({id:n.id,label:n.title})));
   add('kind','全部类型',[...new Set([...(catalog.documents||[]).map(n=>n.kind),'概念','结论','论文'])].filter(Boolean).map(id=>({id,label:id})));
   const history=element('label',null,'kg-check'),input=element('input');input.type='checkbox';input.checked=filters.include_history==='1';input.onchange=()=>{filters.include_history=input.checked?'1':'0';refresh();};history.append(input,document.createTextNode('包含历史'));scope.append(history);
  }).catch(showError);
  if(!root.ResearchKnowledgeIcons){const script=element('script');script.src='/vendor/knowledge-graph/icons.js';script.onload=()=>{if(destroyed)return;if(cy)cy.batch(()=>{for(const n of cy.nodes())n.data('glyph',glyphFor(nodeFor(n.id())));});renderer3D?.update({...scene});};script.onerror=()=>script.remove();document.head.append(script);}
  loadIcons().then(()=>{if(destroyed)return;iconController=root.ResearchGraphIcons.create();const names={'＋':'zoomIn','−':'zoomOut','适应':'expand','主题总览':'overview','重新排布':'boxes','演示':'play','继续演示':'play','暂停演示':'pause','退出演示':'panel','全屏':'expand','导出图片':'download','抽取进度':'layers','新增关系':'network','专业精修':'boxes','刷新':'refresh'};for(const b of controls.querySelectorAll('button')){const name=names[b.textContent.trim()];if(name)iconController.decorate(b,name);}iconController.decorate(searchTrigger,'search');iconController.decorate(filterToggle,'settings');iconController.decorate(detailToggle,'panel');iconController.decorate(moreTitle,'more');}).catch(()=>{});
  if(!restoreCached()){const key=scopeQuery();root.KnowledgeGraphDiskCache?.get(key).then(found=>{if(!destroyed&&!activeScope&&key===scopeQuery()&&found){cache.set(key,found);restoreCached();}}).catch(()=>{});}refresh().then(()=>{if(saved.mode==='3d'&&!destroyed&&modeId===0)switchMode('3d');});
  return {refresh,getDiagnostics:()=>({mode:currentMode,appearance:state.appearance,readingMode:state.readingMode,organization:state.organization,path:state.topicPath,cacheRestored,playing,presentation:!!presentation,nodes:scene.nodes.length,two:cy?{zoom:cy.zoom(),nodes:cy.nodes().length,edges:cy.edges().length}:null,semantic:{pending:!!semanticWorker,vectors:layouts[currentMode]?.semanticIndex?.vector_count||0},local:!!state.focusRoot,three:renderer3D?.stats?.(),icons:root.ResearchGraphIcons?.stats?.(),canvases:canvas.querySelectorAll('canvas').length}),getScene:()=>({...scene,positions:points,selected:state.selected,expanded:[...state.expanded],mode:currentMode}),destroy(){if(destroyed)return;cancelMotion();save();destroyed=true;iconController?.destroy();iconController=null;for(const animation of feedbackAnimations)animation.cancel();feedbackAnimations.clear();for(const controller of requests)controller.abort();requests.clear();requestId++;modeId++;semanticRequest++;searchRequest++;clearTimeout(searchTimer);semanticWorker?.terminate();semanticWorker=null;labelNodes.clear();labelBoxes.clear();motion.destroy();if(labelFrame!==null)cancelAnimationFrame(labelFrame);clearTimeout(previewTimer);clearTimeout(previewHideTimer);if(refreshTimer)clearTimeout(refreshTimer);observer.disconnect();reducedQuery.removeEventListener('change',reducedChange);cy?.destroy();renderer3D?.destroy();shell.remove();}};
 }
 root.WorkspaceKnowledgeGraph={mount};
})(typeof globalThis!=='undefined'?globalThis:this);
