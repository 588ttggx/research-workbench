'use strict';
async function renderDataRemote(host){
 const data=await api('/api/data-remote');host.replaceChildren(el('h3','数据远程备份'),el('p',data.message,'section-subtitle'),el('p',data.scope,'section-subtitle'));
 if(data.local_backup){const backup=data.local_backup,local=el('div',null,'soft-card');local.append(el('strong','最近的本机完整备份'),el('p',new Date(backup.time).toLocaleString('zh-CN')+' · '+(backup.bytes/1024/1024).toFixed(1)+' MB · '+(backup.restored?'已校验并完成隔离恢复':backup.verified?'已校验，隔离恢复待检查':'等待校验'),'section-subtitle'),el('p',backup.path,'code-text'),btn('复制备份路径',async()=>{await navigator.clipboard.writeText(backup.path);notify('备份路径已复制');},'quiet-button','link'),el('p','这是本机科研工作区备份；独立存储的连接单独维护。','muted'));if(backup.zotero_native){const native=backup.zotero_native;local.append(el('p','Zotero 原生恢复已核对：'+native.items+' 个条目、'+native.notes+' 份笔记、'+native.storage_files+' 个库内附件文件；原条目 ID 保留。'+(native.linked_paths_require_relink?'外链附件已保存，换机后需重新关联路径。':''),'section-subtitle'));}host.append(local);}
 const locations={same_volume:'与主工作区在同一卷，只能作为同盘副本',same_physical_disk:'与主工作区在同一块物理硬盘，不能作为独立容灾',different_physical_disk:'已识别为不同物理硬盘；完整系统恢复仍需单独核验',independence_unverified:'存储独立性尚未核实'};
 if(data.destination)host.append(el('p','位置：'+data.destination,'code-text'),el('p',locations[data.storage_scope]||'存储独立性尚未核实','section-subtitle'));
 if(data.last_success)host.append(el('p','最近成功备份：'+new Date(data.last_success).toLocaleString('zh-CN'),'section-subtitle'));
 if(data.last_error)host.append(el('p',data.last_error+'；旧版本保留，后台按退避时间重试。','notice'));
 if(data.last_verified)host.append(el('p','原生恢复检查：'+new Date(data.last_verified.checked).toLocaleString('zh-CN')+' · 从空缓存恢复并核对 SHA256','section-subtitle'));
 const details=el('details');details.append(el('summary',data.destination?'更换或重新连接备份目录':'连接外置硬盘或 NAS'));
 const destination=input('已连接的外置盘 / NAS 目录',data.destination||''),progress=el('p',null,'section-subtitle');details.append(field('备份目录',destination),el('p','选择已有目录。系统只建立自己的 DVC 副本目录，原始数据和其他连接保留。NAS 登录沿用系统连接。','section-subtitle'),btn('连接并开启自动备份',async()=>{await api('/api/data-remote/configure',{enabled:true,revision:data.revision,path:destination.value});await renderDataRemote(host);notify('连接已保存，后台会接续受版本管理的数据备份');},'primary','link'));host.append(details,progress);
 if(data.destination){const actions=el('div',null,'validation-actions');actions.append(btn(data.enabled?'暂停自动备份':'恢复自动备份',async()=>{await api('/api/data-remote/configure',{enabled:!data.enabled,revision:data.revision,path:data.destination});await renderDataRemote(host);},'quiet-button',data.enabled?'pause':'activity'));
  if(data.enabled&&data.status!=='conflict')actions.append(btn('立即备份',async()=>{await job('/api/data-remote/sync',{},row=>{progress.textContent=row.phase||'正在备份';});await renderDataRemote(host);},'quiet-button','upload'),btn('检查远程恢复',async()=>{await job('/api/data-remote/verify',{},row=>{progress.textContent=row.phase||'正在隔离恢复';});await renderDataRemote(host);notify('已从远程副本恢复并核对，没有使用原件或现用缓存');},'quiet-button','check'));host.append(actions);}
}
// One visible input control is reused by the page and its analysis settings.
function analysisFileControl(onSelect,initialFile=null){
 const area=el('div',null,'analysis-import'),file=el('input'),copy=el('div',null,'analysis-import-copy'),name=el('h3',initialFile?initialFile.name:'导入分析文件');
 file.type='file';file.accept='.csv,text/csv';file.hidden=true;file.setAttribute('aria-label','分析数据 CSV 文件');
 const choose=btn(initialFile?'更换文件':'选择分析文件',()=>file.click(),'primary','upload');
 copy.append(el('span','1 · 选择文件','overline'),name,el('p','选择电脑上的 UTF-8 CSV，或把文件拖到这里。最多 4 MB；无需手动放进指定文件夹，原文件不会改动。','section-subtitle'));
 area.append(ic('upload'),copy,choose,file);
 async function selectFile(selected){if(!selected)return;if(!/\.csv$/i.test(selected.name))throw Error('请选择 CSV 数据。原厂格式请先在对应专业软件中导出 CSV。');if(selected.size>4*1024*1024)throw Error('分析文件最多 4 MB');name.textContent=selected.name;choose.replaceChildren(document.createTextNode('更换文件'));await onSelect(selected);}
 file.onchange=()=>{const selected=file.files[0];file.value='';return selectFile(selected).catch(error=>notify(error.message));};
 for(const type of ['dragenter','dragover'])area.addEventListener(type,event=>{event.preventDefault();area.classList.add('dragover');});
 area.ondragleave=()=>area.classList.remove('dragover');area.ondrop=event=>{event.preventDefault();area.classList.remove('dragover');if(event.dataTransfer.files.length!==1){notify('每次选择一份 CSV，相关分析会集中保留版本。');return;}selectFile(event.dataTransfer.files[0]).catch(error=>notify(error.message));};
 return {element:area,file};
}
