'use strict';
const ScholarlyResults={
 names:{wos:'Web of Science',openalex:'OpenAlex',crossref:'Crossref',semantic_scholar:'Semantic Scholar',arxiv:'arXiv'},
 planRequest(draft){const {query,...fields}=draft;return {message:query,...fields};},
 criteriaLines(plan){const criteria=plan.criteria||{required:plan.include_groups||[],optional:plan.optional_groups||[]};return Object.entries({required:'必须',priority:'优先',optional:'方法参考',exclusion:'排除'}).map(([key,label])=>label+'：'+((criteria[key]||[]).map(g=>g.join(' / ')).join('；')||'未设置'));},
 rankAccept(ranks,system,quartile){if(!quartile)return true;const value=ranks?.[system]||{},entries=(value.entries||[]).filter(e=>system!=='CAS'||e.scope==='major'),known=value.status==='matched'&&entries.length>0;if(quartile==='unknown')return !known;return Boolean(known&&entries.some(e=>e.quartile===(system==='JCR'?'Q'+quartile:quartile)));},
 filter(papers,{text='',source='',scope='',sort='relevance',rankSystem='CAS',quartile='',screening={},decision='',concept='focus'}={}){
  const query=text.trim().toLocaleLowerCase();
  const rows=papers.filter(p=>(concept==='all'||(concept==='matched'?p.concept_match?.status==='matched':!['partial','excluded'].includes(p.concept_match?.status)))&&this.rankAccept(p.journal_ranks,rankSystem,quartile)&&(!decision||(screening[p.paper_id]?.decision||'undecided')===decision)&&(!source||(p.sources||[]).includes(source))&&(!scope||(scope==='saved'?(p.workspace_matches||[]).length:!(p.workspace_matches||[]).length))&&(!query||[p.title,p.abstract,p.doi,p.venue,...(p.authors||[])].join(' ').toLocaleLowerCase().includes(query)));
  if(sort==='newest')rows.sort((a,b)=>(b.year||0)-(a.year||0));
  if(sort==='oldest')rows.sort((a,b)=>(a.year||9999)-(b.year||9999));
  return rows;
 },
 summary(data){
  const state={completed:'检索完成',partial:'部分来源完成',failed:'检索失败',needs_configuration:'来源待配置'}[data.status]||'结果待核对';
  return state+' · 去重后 '+(data.papers||[]).length+' 条题录';
 }
};
if(typeof module!=='undefined')module.exports=ScholarlyResults;

function drawScholarlyRuleDraft(box,plan,onEdit){
 box.replaceChildren();box.hidden=!plan.original_intent;if(box.hidden)return;
 plan.criteria||={required:plan.include_groups||[],priority:[],optional:plan.optional_groups||[],exclusion:[]};
 box.append(el('strong','待核对的规则草稿'));
 for(const [key,label]of Object.entries({required:'必须',priority:'优先',optional:'方法参考',exclusion:'排除'})){
  const control=input('未设置；组内 /，组间 ;',(plan.criteria[key]||[]).map(g=>g.join(' / ')).join('; '));
  control.setAttribute('aria-label','规则草稿 · '+label);control.onchange=()=>{const values=control.value.split(/[;；]/).map(g=>g.split(/[\/／]/).map(t=>t.trim()).filter(Boolean)).filter(g=>g.length);plan.criteria[key]=values;onEdit(key,values);};
  box.append(field(label,control));control.setAttribute('aria-label','规则草稿 · '+label);
 }
 box.append(el('p','英文查询：'+plan.query,'code-text'));
}

async function showScholarlySearch(options={}){
 const watchMode=options.watch===true,body=modal(watchMode?'从研究想法建立关注':'文献检索');body.classList.add('scholarly-search');
 const fresh=!S.scholarlySearch,session=S.scholarlySearch||={draft:{query:'',sources:['crossref'],wos_query:'',from_year:null,to_year:null,max_results:20,provider_queries:{},include_groups:[]},result:null,busy:false,message:''};
 const draft=session.draft,query=el('textarea'),wosQuery=input('例如 TS=(terahertz AND starch)',draft.wos_query),fromYear=input('不限',draft.from_year??''),toYear=input('不限',draft.to_year??''),limit=input('每来源 1–100 条',draft.max_results);limit.type='number';limit.min='1';limit.max='100';limit.step='1';
 query.value=draft.original_intent||draft.query;query.rows=2;query.maxLength=2000;query.placeholder='例如：关注电池阻抗测量，优先无损检测，也可参考温度补偿，排除燃烧研究';query.setAttribute('aria-label','检索词或研究问题');limit.value=String(watchMode?Math.min(draft.max_results,20):draft.max_results);
 for(const node of [fromYear,toYear]){node.type='number';node.min='1900';node.max='2100';node.step='1';}
 const years=el('div',null,'form-grid');years.append(field('起始年份',fromYear),field('结束年份',toYear));
 const sourceBox=el('fieldset',null,'scholarly-sources'),legend=el('legend','文献来源'),sourceChecks={};sourceBox.append(legend);
 for(const [id,name]of Object.entries(ScholarlyResults.names)){
  const check=el('input'),label=el('label',null,'check-field');check.type='checkbox';check.checked=draft.sources.includes(id);check.setAttribute('aria-label',name);sourceChecks[id]=check;label.append(check,el('span',name));sourceBox.append(label);
 }
 const advanced=el('details'),providerDetails=el('details'),wosField=field('WoS 字段检索式',wosQuery),groups=input('组内用 /，组间用 ;',(draft.include_groups||[]).map(g=>g.join(' / ')).join('; ')),providerQueries={},queryDetails=el('details'),status=el('p',null,'notice'),providerBox=el('div',null,'scholarly-providers'),results=el('div',null,'list scholarly-results'),resultHeader=el('div'),exports=el('div',null,'toolbar'),filters=el('div',null,'toolbar scholarly-filters');status.setAttribute('role','status');
 advanced.append(el('summary','来源、年份与高级检索'));queryDetails.append(el('summary','调整各来源检索词'));
 for(const id of ['openalex','crossref','semantic_scholar','arxiv']){const control=input('留空沿用主检索词',draft.provider_queries?.[id]||'');providerQueries[id]=control;queryDetails.append(field(ScholarlyResults.names[id],control));}
 const rulePreview=el('div',null,'soft-card'),text=input('筛选题名、作者、摘要、DOI'),source=select([['','所有已返回来源'],...Object.entries(ScholarlyResults.names)],'结果来源筛选'),scope=select([['','全部题录'],['new','尚未入库'],['saved','文献库已有']],'入库状态筛选'),sort=select([['relevance','检索词匹配优先'],['newest','本次结果 · 年份从新到旧'],['oldest','本次结果 · 年份从旧到新']],'结果排序'),pages=el('div',null,'pagination');let offset=0;
 const rankSystem=select([['CAS','中科院 · 大类'],['JCR','JCR · JIF学科']],'分区体系'),quartile=select([['','全部分区'],['1','1区 / Q1'],['2','2区 / Q2'],['3','3区 / Q3'],['4','4区 / Q4'],['unknown','分区未匹配']],'分区筛选'),decision=select([['','全部筛选状态'],['undecided','尚未判断'],['include','已保留'],['exclude','已排除']],'论文筛选状态');
 const concept=select([['focus','概念相关与题录待核'],['matched','仅概念交集已命中'],['all','全部取回题录 · 含部分命中']],'核心概念匹配');filters.append(concept,rankSystem,quartile,sort,text);const moreFilters=el('details');moreFilters.append(el('summary','更多筛选'),source,scope,decision);filters.append(moreFilters);
 function saveDraft(){const previous=session.draft,intentChanged=Boolean(previous.original_intent&&query.value.trim()!==previous.original_intent.trim());if(intentChanged){groups.value='';wosQuery.value='';for(const control of Object.values(providerQueries))control.value='';rulePreview.hidden=true;for(const control of exports.querySelectorAll('button'))control.disabled=true;session.message='想法已变化，请重新生成并抽样；下方保留上一次结果。';status.textContent=session.message;}session.draft={query:intentChanged?query.value:previous.original_intent?previous.query:query.value,...(!intentChanged&&previous.original_intent?{original_intent:previous.original_intent,criteria:previous.criteria}:{}),sources:Object.keys(sourceChecks).filter(id=>sourceChecks[id].checked),wos_query:wosQuery.value,from_year:fromYear.value?Number(fromYear.value):null,to_year:toYear.value?Number(toYear.value):null,max_results:Number(limit.value),optional_groups:intentChanged?[]:previous.optional_groups||[],include_groups:groups.value.trim()?groups.value.split(/[;；]/).map(g=>g.split(/[／/]/).map(t=>t.trim()).filter(Boolean)).filter(g=>g.length):[],provider_queries:Object.fromEntries(Object.entries(providerQueries).filter(([,control])=>control.value.trim()).map(([id,control])=>[id,control.value.trim()]))};if(session.draft.criteria)session.draft.criteria.required=session.draft.include_groups;wosField.hidden=!sourceChecks.wos.checked;}
 const controls=[query,wosQuery,fromYear,toYear,limit,groups,...Object.values(providerQueries),...Object.values(sourceChecks)];
 for(const node of controls){node.addEventListener('input',saveDraft);node.addEventListener('change',saveDraft);}saveDraft();
 function resultRow(paper){
  const row=el('div',null,'list-row radar-row'),copy=el('div',null,'row-copy'),actions=el('div',null,'radar-actions');
  copy.append(paper.url?extLink(paper.title||'题名待补',paper.url,'text-link'):el('strong',paper.title||'题名待补'));
  const meta=[paper.year||'年份待补',paper.venue,(paper.sources||[]).map(id=>ScholarlyResults.names[id]||id).join(' / ')];copy.append(el('p',meta.filter(Boolean).join(' · '),'muted'));
  if(paper.concept_match?.label)copy.append(badge(paper.concept_match.label,paper.concept_match.status==='matched'?'green':'orange'));
  if(paper.arxiv_id)copy.append(badge('含预印本来源 · 版本关系待核对','orange'));
  copy.append(compactJournalRanks(paper.journal_ranks||{}));
  if(paper.abstract)copy.append(el('p',paper.abstract.slice(0,160)+(paper.abstract.length>160?'…':''),'scholarly-abstract-preview'));
  const metadata=el('details');metadata.append(el('summary',paper.abstract?'摘要与题录详情':'来源未提供摘要 · 查看题录'));
  if(paper.authors?.length)metadata.append(el('p',paper.authors.join('；'),'muted'));
  if(paper.doi)metadata.append(el('p','DOI: '+paper.doi,'muted'));
  if(paper.concept_match?.label)metadata.append(el('small',paper.concept_match.label+' · '+paper.concept_match.matched_groups+'/'+paper.concept_match.total_groups+' 组','muted'));
  if(paper.query_matches?.length)metadata.append(el('small','匹配词：'+paper.query_matches.join('、'),'muted'));
  if(paper.context_matches?.length)metadata.append(el('p','补充概念命中：'+paper.context_matches.join('、'),'muted'));
  if(paper.abstract)metadata.append(el('p',paper.abstract,'section-subtitle'));copy.append(metadata);
  const state=session.result.screening?.[paper.paper_id]?.decision;
  const setDecision=async value=>{if(session.screeningBusy)return;session.screeningBusy=true;try{const saved=await api('/api/scholarly-screen',{run_id:session.result.run_id,paper_id:paper.paper_id,decision:value,revision:session.result.screening_revision});Object.assign(session.result,saved);}finally{session.screeningBusy=false;drawResults();}};
  actions.append(btn(state==='include'?'已保留 · 撤回':'保留',()=>setDecision(state==='include'?'reset':'include'),state==='include'?'primary':'quiet-button','check'),btn(state==='exclude'?'已排除 · 恢复':'排除',()=>setDecision(state==='exclude'?'reset':'exclude'),'quiet-button','x'));
  if(paper.workspace_matches?.length){actions.append(badge('文献库已有','green'),btn('打开文献',()=>{dismiss();navigate('paper',paper.workspace_matches[0].id);},'quiet-button','book'));}
  else if(paper.doi){if(paper.acquisition?.message)copy.append(el('p',paper.acquisition.message,'muted'));const acquire=btn(paper.acquisition?'重试获取':'获取全文',async()=>{acquire.disabled=true;try{const result=await job('/api/acquire',{doi:paper.doi,project:S.project});paper.acquisition=result;if(result.id&&['downloaded','already_saved','pdf_unavailable'].includes(result.status))paper.workspace_matches=[{id:result.id}];notify(result.message||'获取流程已处理，可在文献库核对全文状态');drawResults();}catch(error){acquire.disabled=false;throw error;}},'quiet-button','download');actions.append(acquire);}
  else actions.append(badge('无 DOI · 可打开来源核对','orange'));
  row.append(copy,actions);return row;
 }
 function drawResults(){
  if(!results.isConnected)return;
  const data=session.result;results.replaceChildren();pages.replaceChildren();resultHeader.replaceChildren();exports.replaceChildren();providerBox.replaceChildren();filters.hidden=!data;
  if(!data)return;
  const included=Object.values(data.screening||{}).filter(item=>item.decision==='include').length;
  resultHeader.append(el('h3',ScholarlyResults.summary(data)+' · 已保留 '+included),el('p','本次检索词：'+data.plan.query+' · '+date(data.generated_at),'section-subtitle'),el('p','仅题录和摘要，未核查全文。分区按最新已登记年度；JCR按任一学科匹配。','muted'));
  const labels={completed:'已取完',bounded:'达到取回上限',partial:'部分取回',failed:'失败',needs_configuration:'待配置'};
  for(const [id,info]of Object.entries(data.providers||{})){
   const card=el('div',null,'soft-card');card.append(el('strong',ScholarlyResults.names[id]||id),badge(labels[info.status]||info.status,['completed','bounded'].includes(info.status)?'green':'orange'),el('p','本次取回 '+(info.retrieved||0)+' 条'+(Number.isFinite(info.upstream_total)?' / 来源命中 '+info.upstream_total+' 条':'')+' · '+(info.message||''),'muted'));providerBox.append(card);
  }
  if(data.warnings?.length){const warnings=el('details');warnings.append(el('summary','来源诊断 · '+data.warnings.length+' 项'));for(const value of data.warnings)warnings.append(el('p',value,'code-text'));providerBox.append(warnings);}
  if(data.run_id)for(const [kind,label]of [['bibtex','导出 '+(included?'保留项':'全部')+' BibTeX'],['json','导出 '+(included?'保留项':'全部')+' JSON']]){const link=el('a',label,'quiet-button');link.href='/api/scholarly-export?run_id='+encodeURIComponent(data.run_id)+'&format='+kind+(included?'&selected=true':'');link.download='literature-'+data.run_id+(kind==='bibtex'?'.bib':'.json');exports.append(link);}
  const subscribe=btn('转为论文提醒',()=>showScholarlySubscription(data),'quiet-button','radar');subscribe.disabled=watchMode&&session.draft.original_intent!==data.plan.original_intent;exports.append(subscribe);
  const rows=ScholarlyResults.filter(data.papers||[],{text:text.value,source:source.value,scope:scope.value,sort:sort.value,rankSystem:rankSystem.value,quartile:quartile.value,screening:data.screening||{},decision:decision.value,concept:concept.value});
  const broad=(data.papers||[]).filter(p=>p.concept_match?.status==='partial').length;if(broad&&concept.value!=='all')resultHeader.append(el('p',broad+' 条只命中部分概念，已收进“全部取回题录”；原始回执及全部题录导出继续保留。','muted'));
  if(offset>=rows.length)offset=0;
  for(const paper of rows.slice(offset,offset+20))results.append(resultRow(paper));
  if(!rows.length)results.append(empty(data.papers?.length?'没有符合筛选的题录':data.status==='failed'?'所选来源均未成功':data.status==='needs_configuration'?'所选来源尚未配置':'成功来源未返回题录',data.papers?.length?'清除筛选或更换条件。':'请先查看上方来源状态，再调整检索词、年份或来源。'));
  const prev=btn('上一页',()=>{offset=Math.max(0,offset-20);drawResults();},'quiet-button'),next=btn('下一页',()=>{offset+=20;drawResults();},'quiet-button');prev.disabled=!offset;next.disabled=offset+20>=rows.length;pages.append(prev,el('span',rows.length?(offset+1)+'–'+Math.min(offset+20,rows.length)+' / '+rows.length:'0 条'),next);
 }
 const filterControls={text,source,scope,sort,rankSystem,quartile,decision,concept};
 for(const [key,node]of Object.entries(filterControls)){if(session.filters?.[key]!==undefined)node.value=session.filters[key];node.addEventListener(node===text?'input':'change',()=>{session.filters=Object.fromEntries(Object.entries(filterControls).map(([id,control])=>[id,control.value]));offset=0;drawResults();});}
 function update(){if(!results.isConnected)return;if(!session.busy){const current=session.draft;query.value=current.original_intent||current.query;wosQuery.value=current.wos_query||'';fromYear.value=current.from_year??'';toYear.value=current.to_year??'';limit.value=String(current.max_results);groups.value=(current.include_groups||[]).map(g=>g.join(' / ')).join('; ');for(const [id,control]of Object.entries(providerQueries))control.value=current.provider_queries?.[id]||'';for(const [id,check]of Object.entries(sourceChecks))check.checked=current.sources.includes(id);wosField.hidden=!sourceChecks.wos.checked;}status.textContent=session.message||'先写研究想法，生成可读规则；核对后抽样检索，查看命中理由，再启用持续关注。';drawScholarlyRuleDraft(rulePreview,session.draft,(key,values)=>{if(key==='required'){groups.value=values.map(g=>g.join(' / ')).join('; ');wosQuery.value='';for(const control of Object.values(providerQueries))control.value='';}saveDraft();});for(const control of [...controls,prepare,submit])control.disabled=session.busy;drawResults();}
 session.update=update;
 const prepare=btn('生成规则草稿',async()=>{
  saveDraft();if(!session.draft.query.trim())throw Error('请先填写检索需求');if(!session.draft.sources.length)throw Error('请至少选择一个文献来源');
  session.busy=true;session.message='正在准备英文检索式，不会开始外部检索…';update();
  try{const plan=await job('/api/scholarly-plan',ScholarlyResults.planRequest(session.draft));session.draft=plan;session.message='检索式已准备，请核对术语和范围，再点“开始检索”。';}
  catch(error){session.message='检索式未准备：'+error.message;}
  finally{session.busy=false;session.update?.();}
 },'quiet-button','sparkles');
 const submit=btn(watchMode?'按草稿抽样检索':'搜索论文',async()=>{
  saveDraft();let plan=structuredClone(session.draft);if(!plan.query.trim())throw Error('请填写检索词');if(!plan.sources.length)throw Error('请至少选择一个来源');
  if([plan.from_year,plan.to_year].some(y=>y!==null&&(!Number.isInteger(y)||y<1900||y>2100)))throw Error('年份须为 1900–2100 的整数');if(plan.from_year&&plan.to_year&&plan.from_year>plan.to_year)throw Error('起始年份不能晚于结束年份');
  if(watchMode&&!plan.original_intent){session.message='请先生成并核对上方规则草稿。';update();return;}if(watchMode)plan.max_results=Math.min(plan.max_results,20);
  session.busy=true;session.message='正在检索所选来源，可关闭窗口；重新打开会接着显示本次状态。';update();
  try{if(watchMode||/[\u4e00-\u9fff]/.test(plan.query)||(plan.sources.includes('wos')&&!plan.wos_query.trim())){session.message='正在把研究问题转换为英文检索式…';session.update?.();plan=await job('/api/scholarly-plan',ScholarlyResults.planRequest(plan));session.draft=plan;}session.message='正在查询 '+plan.sources.map(id=>ScholarlyResults.names[id]).join('、')+'…';session.update?.();session.result=await job('/api/scholarly-search',plan);session.message=ScholarlyResults.summary(session.result)+'。';offset=0;}
  catch(error){session.message='检索未完成：'+error.message+(session.result?'；下方保留的是上一次结果。':'');}
  finally{session.busy=false;session.update?.();}
 },'primary','search');
 const actions=el('div',null,'form-actions');actions.append(prepare,submit,btn('关闭',dismiss,'quiet-button'));advanced.append(sourceBox,wosField,years,field('取回上限',limit),field('必须概念 · 用于转为提醒',groups),queryDetails,el('p','中文需求转换使用现有 DeepSeek；相同需求复用已有草稿。抽样后按可见题录解释命中与缺口。','muted'));providerDetails.append(el('summary','查看各来源状态与诊断'),providerBox);
 const previous=select([['','打开最近检索…']],'最近检索');controls.push(previous);previous.addEventListener('change',async()=>{if(!previous.value||session.busy)return;try{const result=await api('/api/scholarly-result?run_id='+encodeURIComponent(previous.value));session.result=result;session.draft={provider_queries:{},include_groups:[],wos_query:'',from_year:null,to_year:null,...result.plan};session.message='已打开保存结果，可继续筛选，或修改条件重新检索。';update();}catch(error){notify(error.message,true);}});
 body.append(el('p',watchMode?'研究想法 → 规则草稿 → 小样本结果与理由 → 本人启用。现有关注保持原样。':'找论文、核对题录、保留与获取全文；查询可转为持续关注。','section-subtitle'),previous,field('检索词或研究问题',query),actions,rulePreview,advanced,status,resultHeader,exports,filters,results,pages,providerDetails);update();
 try{const [config,history]=await Promise.all([api('/api/scholarly-settings'),api('/api/scholarly-history')]);if(!results.isConnected)return;for(const record of history.records||[]){const option=el('option',(record.generated_at?date(record.generated_at)+' · ':'')+record.query);option.value=record.run_id;previous.append(option);}if(fresh&&!session.busy&&!query.value.trim()){session.draft.sources=['wos','openalex','crossref'].filter(id=>config.configured?.[id]);if(!session.draft.sources.length)session.draft.sources=['crossref'];update();}for(const id of ['wos','openalex','semantic_scholar'])sourceChecks[id].parentElement.append(el('small',config.configured?.[id]?' · 已配置':id==='semantic_scholar'?' · 匿名可能限流':' · 未配置密钥','muted'));}catch(error){if(results.isConnected)providerBox.append(el('p','配置状态暂未读取：'+error.message,'notice'));}
}

async function showScholarlySubscription(data){
 const rules=await api('/api/watch-rules'),body=modal('转为论文提醒'),name=input('给这条关注起个名字',data.plan.query.slice(0,100));
 const projects=S.workspace?.projects||Array.from($('projectContext').options,option=>option.value);
 const project=select([['共享','全局关注'],...[...new Set([S.project,...projects])].filter(p=>p&&p!=='共享').map(p=>[p,p])],'提醒所属项目');project.value=S.project||'共享';
 body.append(el('p','请结合刚才的样本与命中理由核对。启用后按这份规则检查近期题录；已有关注继续保留。','section-subtitle'),field('关注名称',name),field('所属项目',project),el('p','原始想法：'+(data.plan.original_intent||data.plan.query),'section-subtitle'),el('p',data.plan.query,'code-text'),el('p','来源：'+data.plan.sources.map(id=>ScholarlyResults.names[id]).join(' / '),'muted'));
 for(const line of ScholarlyResults.criteriaLines(data.plan))body.append(el('p',line,'muted'));
 body.append(btn('返回检索',showScholarlySearch,'quiet-button'),btn('核对样本后启用关注',async()=>{await api('/api/scholarly-subscribe',{name:name.value,project:project.value,plan:data.plan,revision:rules.revision,run_id:data.run_id});await showScholarlySearch();notify('持续关注已保存，可在“关注规则”调整');},'primary','radar'));
}
