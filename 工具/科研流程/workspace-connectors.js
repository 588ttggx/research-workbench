'use strict';
async function renderScholarlyConnection(host){
 const data=await api('/api/scholarly-settings');host.replaceChildren(el('h3','文献检索接口'),el('p',data.message,'section-subtitle'));
 const names={wos:'Web of Science',openalex:'OpenAlex',crossref:'Crossref',semantic_scholar:'Semantic Scholar',arxiv:'arXiv'},links={wos:'https://developer.clarivate.com/apis/wos-starter',openalex:'https://openalex.org/settings/api',semantic_scholar:'https://www.semanticscholar.org/product/api#api-key-form'};
 const summary=el('div',null,'form-actions');for(const [id,name]of Object.entries(names))summary.append(badge(name+' · '+(data.configured[id]?(id==='crossref'||id==='arxiv'?'无需密钥':'密钥已保存'):'待填写密钥'),data.configured[id]?'green':'orange'));host.append(summary);
 host.append(el('p','WoS 需单独申请 API 权限，学校网页登录权限不等于 API 权限。OpenAlex 申请免费 Key；Semantic Scholar 可匿名搜索，Key 可减少公共限流。Crossref 和 arXiv 可直接使用。','section-subtitle'));
 const details=el('details');details.open=!data.configured.wos||!data.configured.openalex;details.append(el('summary','填写或更新接口配置'));
 const mode=select([['starter','WoS Starter'],['expanded','WoS Expanded']],'已获准的 WoS 接口');mode.value=data.wos_api;
 const email=input('用于 Crossref 联系信息',data.contact_email||'');email.type='email';details.append(field('WoS 接口类型',mode),field('真实联系邮箱（建议）',email));
 const keys={},clear={};for(const id of ['wos','openalex','semantic_scholar']){const key=input(data.configured[id]?'已保存，留空沿用':'仅在本机填写 API Key');key.type='password';key.autocomplete='off';keys[id]=key;const remove=el('input');remove.type='checkbox';clear[id]=remove;const label=el('label',null,'check-field');label.append(remove,el('span','清除此密钥'));details.append(field(names[id]+' API Key',key),label,extLink('申请 '+names[id]+' API 权限',links[id],'text-link'));}
 const save=btn('保存文献接口配置',async()=>{const body={revision:data.revision,wos_api:mode.value,contact_email:email.value,clear:Object.entries(clear).filter(([,value])=>value.checked).map(([id])=>id+'_api_key')};for(const [id,key]of Object.entries(keys)){if(key.value)body[id+'_api_key']=key.value;key.value='';}await api('/api/scholarly-settings',body);await renderScholarlyConnection(host);notify('本机配置已保存，两边 AI 共用');},'primary','check');details.append(save,el('p','已保存的密钥不会显示或回传；留空保留，勾选后才清除。','muted'));host.append(details);
 const report=el('div'),choice=select([['all','全部来源'],...Object.entries(names)],'检查哪个来源');
 const check=btn('检查接口连接',async()=>{check.disabled=true;report.replaceChildren(el('p','正在对每个所选来源做一次最小查询…','muted'));try{const value=await job('/api/scholarly-check',{sources:choice.value==='all'?Object.keys(names):[choice.value]});report.replaceChildren();const result=value.result||value;const states={completed:'连接成功',bounded:'连接成功 · 达到本次上限',partial:'部分取回',needs_configuration:'需要填写密钥',failed:'连接失败或受限'};for(const [id,info]of Object.entries(result.providers||{}))report.append(el('p',names[id]+'：'+(states[info.status]||info.status)+'；取回 '+info.retrieved+' 条'));for(const warning of result.warnings||[])report.append(el('p',warning,'muted'));}finally{check.disabled=false;}},'quiet-button','activity');host.append(choice,check,report,el('p','以后在 AI 对话中说“帮我搜索近三年的……论文”即可。实际题录和检索记录会保留，失败来源会明确说明。','section-subtitle'));
}

// Connection settings live here; native facts keep one editor in their source.
const RSPACE_FIELD_LABELS={id:'统一 ID',project:'项目',status:'状态',sample:'样品',batch:'批次',instrument:'仪器',calibration:'校准',sop:'SOP',dataset:'数据集',raw_uri:'原始数据位置',checksum:'SHA256',start:'开始时间',end:'结束时间',valid_until:'校准有效期',independent_sample_id:'独立样品 ID',preparation_id:'制样重复 ID',scan_id:'扫描 ID',measurement_date:'测量日期',time_unit:'时间单位',signal_unit:'信号单位',thickness_mm:'厚度 / mm',temperature_celsius:'温度 / °C',humidity_percent:'湿度 / %',instrument_state:'仪器状态',method_id:'分析方法 ID',dynamic_range_db:'动态范围 / dB',water_vapor_metric:'水汽指标',reference_pairing_confirmed:'已确认样品参考配对',geometry_confirmed:'已确认方法适用条件'};
async function renderNoteBoundary(host){
 const data=await api('/api/note-sync/boundary');host.replaceChildren(el('h3','笔记的主稿与同步'),el('p','知识正文在工作区维护，Zotero 保留原生批注和历史笔记。','section-subtitle'),el('p',data.message,'notice info'));
 if(data.status==='ready'){if(data.last?.status==='completed')host.append(badge('旧同步迁移已完成','green'),el('p','最近原生核验：'+new Date(data.last.checked).toLocaleString('zh-CN')+'；两端正文与快照均保留。','muted'));else host.append(el('p',data.records.length+' 项 Better Notes 原生同步注册；只处理对应本工作区的笔记，其余不变。','muted'),btn('核对原稿并取消旧双向同步',async()=>{const result=await api('/api/note-sync/boundary',{});notify('已核验 '+result.detached.length+' 项，主稿与 Zotero 历史都保留');await renderNoteBoundary(host);await loadWorkspace();},'quiet-button','check'));}
 if(data.history?.some(r=>r.status==='retired_history')){const history=el('details');history.append(el('summary','查看已保留的旧同步稿'),el('p','历史对照可查看，不再进入日常自动化审核。','muted'));for(const row of data.history.filter(r=>r.status==='retired_history'))history.append(btn(row.title,()=>showNoteSync(row.id),'list-row','file'));host.append(history);}
 if(['restart_required','ready'].includes(data.status)){const link=extLink('下载本机笔记连接','/api/note-sync/plugin','quiet-button');link.download='研序笔记连接.xpi';host.append(el('p','此连接包随工作区本地维护；原生自动软件更新关闭，文献和笔记状态同步继续自动运行。','section-subtitle'),link);}
 host.append(btn('重新检查原生连接',()=>renderNoteBoundary(host),'text-link','activity'));
}

async function renderRSpaceConnection(host){
 const data=await api('/api/rspace');host.replaceChildren(el('h3','RSpace 正式实验平台'),el('p',data.message,'section-subtitle'));
 const names={not_connected:'尚未连接',paused:'自动同步已暂停',configured:'自动同步已启用'};
 host.append(badge(names[data.status]||data.status,data.enabled?'green':'orange'));
 if(data.deployment?.installed){const actions=el('div',null,'form-actions');actions.append(extLink('打开正式实验平台',data.deployment.url,'quiet-button'),btn('查看本机日常账号',async()=>{const value=await api('/api/rspace/account',{}),body=modal('RSpace 本机日常账号'),name=input('',value.username),password=input('',value.initial_password);name.readOnly=password.readOnly=true;password.type='password';body.append(el('p',value.scope,'section-subtitle'),field('用户名',name),field('初始化密码',password),btn('显示 / 隐藏密码',()=>{password.type=password.type==='password'?'text':'password';},'quiet-button'),extLink('前往登录',value.url,'primary'));},'quiet-button','user'),btn('启动或恢复本机服务',async()=>{const value=await api('/api/rspace/start',{});notify(value.message);},'text-link','activity'));host.append(actions);}
 if(data.progress.last_success)host.append(el('p','最近完整同步：'+new Date(data.progress.last_success).toLocaleString('zh-CN'),'muted'));
 if(data.progress.last_error)host.append(el('p','最近未完成：'+data.progress.last_error+'。保留已同步结果，后台按退避规则接续。','notice'));
 const details=el('details');details.open=!data.base;details.append(el('summary',data.base?'修改连接与字段映射':'连接实验平台'));
 const base=input('例如 https://lab.example.edu',data.base||''),key=input('留空沿用本机密钥');key.type='password';key.autocomplete='off';
 const inventory=el('input');inventory.type='checkbox';inventory.checked=data.inventory;const il=el('label',null,'check-field');il.append(inventory,el('span','同时同步 Inventory 样品与容器'));
 details.append(field('实例地址',base),field('RSpace API Key',key),il);
 const mapping=el('div'),rows=[],kindLabels={ExperimentIndex:'实验记录',InstrumentIndex:'仪器',CalibrationIndex:'校准记录',BatchIndex:'材料批次',SOP:'正式 SOP'};
 function add(formId='',type='ExperimentIndex'){
  const row=el('div',null,'form-actions'),id=input('原生表单 ID',formId),kind=select(Object.entries(kindLabels),'科研索引类型');kind.value=type;
  const value={id,kind};rows.push(value);row.append(field('RSpace 表单 ID',id),field('记录类型',kind),btn('移除映射',()=>{rows.splice(rows.indexOf(value),1);row.remove();},'text-link'));mapping.append(row);
 }
 Object.entries(data.forms).forEach(([id,kind])=>add(id,kind));if(!rows.length)add();
 details.append(el('h4','哪些原生表单进入实验区'),el('p','只同步明确选择的表单；普通文档不会被猜成实验。原生表单列表可在保存连接后读取。','section-subtitle'),mapping,btn('再映射一个表单',()=>add(),'quiet-button','plus'));
 const fields=el('details'),inputs={},labels=RSPACE_FIELD_LABELS;
 fields.append(el('summary','对应原生记录中的字段名称'));
 for(const [id,label]of Object.entries(labels)){const value=input('RSpace 字段名称',data.fields[id]);inputs[id]=value;fields.append(field(label,value));}details.append(fields);
 const report=el('div');
 async function save(enabled){const value=key.value;key.value='';return api('/api/rspace/configure',{revision:data.revision,enabled,base:base.value,inventory:inventory.checked,forms:Object.fromEntries(rows.filter(r=>r.id.value.trim()).map(r=>[r.id.value.trim(),r.kind.value])),fields:Object.fromEntries(Object.entries(inputs).map(([k,i])=>[k,i.value])),...(value?{api_key:value}:{})});}
 details.append(btn('保存并启用自动同步',async()=>{await save(true);await renderRSpaceConnection(host);notify('连接与映射已保存，后台沿现有流程同步');},'primary','check'),btn('保存连接并读取表单',async()=>{await save(false);await renderRSpaceConnection(host);const result=await api('/api/rspace/forms');const list=el('div');list.append(el('p',result.message,'section-subtitle'));for(const form of result.forms)list.append(el('p',form.id+' · '+form.name));host.append(list);},'quiet-button','link'),report);host.append(details);
 if(data.base){const actions=el('div',null,'form-actions');actions.append(btn(data.enabled?'暂停自动同步':'恢复自动同步',async()=>{await api('/api/rspace/configure',{revision:data.revision,enabled:!data.enabled});await renderRSpaceConnection(host);},'quiet-button',data.enabled?'pause':'activity'));
  if(data.enabled)actions.append(btn('立即同步',async()=>{await job('/api/rspace/sync',{},row=>{report.textContent=row.phase||'正在同步';});await renderRSpaceConnection(host);notify('原生索引已更新，正式正文继续在 RSpace 编辑');},'quiet-button','activity'));host.append(actions);}
 if(data.progress.unresolved?.length)host.append(el('p',data.progress.unresolved.length+' 项原生引用尚未找到对应 ID，保留字段与来源，等待后续登记。','notice'));
}

function showNativeRecord(node){
 const body=modal(node.data.title||node.id);body.append(badge(node.status),el('p','正式内容在 RSpace 维护，工作区显示其索引与来源。','section-subtitle'),extLink('打开并编辑正式记录',node.uri,'primary'),el('p',node.id+' · '+node.data.global_id,'code-text'));
 const fields=el('dl',null,'raw-version');for(const [key,value]of Object.entries(node.data.metadata||{})){if(!value)continue;const cell=el('dd');cell.append(document.createTextNode(value));if(['sample','batch','instrument','calibration','sop'].includes(key))cell.append(btn('查看关联'+RSPACE_FIELD_LABELS[key],async()=>{const data=await api('/api/rspace/records'),targets=data.records.filter(n=>n.id===value||(n.data.global_id===value&&n.external_id?.split('#')[0]===node.external_id?.split('#')[0]));if(targets.length!==1)throw Error('对应原生记录尚未接入或存在歧义，请在正式实验平台核对');showNativeRecord(targets[0]);},'text-link','link'));if(key==='raw_uri'){if(safeUrl(value)&&/^https?:/i.test(value))cell.append(extLink('打开数据位置',value));else cell.append(btn('复制数据位置',async()=>{await navigator.clipboard.writeText(value);notify('数据位置已复制，可在文件管理器打开');},'text-link','copy'));}if(key==='method_id')cell.append(btn('维护所属方法',()=>showMethods(value),'text-link','settings'));fields.append(el('dt',RSPACE_FIELD_LABELS[key]||key),cell);}body.append(fields,el('p','原生修改时间：'+(node.data.source_modified||'未返回'),'muted'));
 body.append(btn('查看来源关系',async()=>{const trace=await api('/api/research/trace?id='+encodeURIComponent(node.id));const host=el('div');body.append(host);drawProvenanceTrace(host,trace);},'quiet-button','link'));
}

async function renderLabWorkspace(){
 const token=S.renderToken,view=$('view');view.append(heading('LAB','实验记录','在正式平台填写一次，样品、仪器、校准和实验状态自动关联到这里。'));
 const [data,connection]=await Promise.all([api('/api/research?section=lab&project='+encodeURIComponent(S.project)),api('/api/rspace')]);if(token!==S.renderToken)return;
 if(connection.base)view.append(extLink('在 RSpace 创建与编辑正式记录',connection.base+'/workspace','primary'));
 view.append(el('p',connection.enabled?'RSpace 原生记录单向同步；正式正文通过记录详情打开编辑。':'正式实验平台尚未启用。连接在“连接与设置 → 软件连接”集中维护，现有索引继续保留。','notice info'));
 const scope=select([['current','当前项目与共享'],['all','全部已接入实验记录']],'实验记录范围'),top=el('div',null,'toolbar');top.append(scope,el('span',connection.records+' 项原生索引','note-count'));view.append(top);
 let active='experiments';const bar=tabs([['experiments','实验'],['samples','样品与批次'],['instruments','仪器与校准'],['qc','质量控制']],'experiments',key=>{active=key;draw();}),box=el('div',null,'list');view.append(bar,box);
 const native=await api('/api/rspace/records');if(token!==S.renderToken)return;
 function draw(){box.replaceChildren();bar.querySelectorAll('button').forEach((button,i)=>button.classList.toggle('active',i===['experiments','samples','instruments','qc'].indexOf(active)));
  const types={experiments:['ExperimentIndex'],samples:['SampleIndex','BatchIndex','Container'],instruments:['InstrumentIndex','CalibrationIndex','SOP'],qc:['QC']}[active];
  const records=[...data.nodes.filter(n=>n.owner!=='RSpace'),...native.records].filter(n=>types.includes(n.kind)&&n.status!=='DELETED_AT_SOURCE'&&(scope.value==='all'||[S.project,'共享',''].includes(n.project)));
  for(const n of records){if(n.owner==='RSpace'){const row=btn('',()=>showNativeRecord(n),'list-row'),copy=el('div',null,'row-copy');copy.append(el('strong',n.data.title||n.id),el('p',n.id+' · '+n.project));row.append(ic('flask'),copy,badge(n.status),ic('arrow'));box.append(row);}else if(n.kind==='QC'&&n.owner==='Pipeline'){const row=btn('',()=>showQCRecord(n),'list-row');row.append(ic('check'),el('strong',n.data.title||n.id),badge(n.status),ic('arrow'));box.append(row);}else{const d=S.workspace&&objectForPath(n.uri);if(d)box.append(docRow(d));else{const row=btn('',async()=>{await ensureWorkspace();const current=objectForPath(n.uri);if(!current)throw Error('原稿索引尚未读取，请重新打开实验区');navigate('document',current.id);},'list-row');row.append(ic('file'),el('strong',n.data.title||n.id),badge(n.status),ic('arrow'));box.append(row);}}}
  if(!records.length)box.append(empty('当前没有这类记录','原生平台接入后自动显示；未知事实保持未知，不用重复抄录。'));
 }scope.onchange=draw;draw();
}
