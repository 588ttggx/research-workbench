/* Route readiness and in-flight project reads; no second workspace cache. */
(function(root){
 'use strict';
 function requiresWorkspace(hash){
  const [route]=String(hash||'#projects').replace(/^#/,'').split('?');
  return !['discover','knowledge','knowledge-node','lab','analyze','projects'].includes(route);
 }
 function createLoader(read,currentProject,apply){
  const pending=new Map();
  return function load(project,{refresh=false}={}){
   if(pending.has(project))return refresh?pending.get(project).catch(()=>{}).then(()=>load(project)):pending.get(project);
   let request;
   try{request=Promise.resolve(read(project));}catch(error){request=Promise.reject(error);}
   const result=request.then(value=>{if(currentProject()===project)apply(value,project);return value;}).finally(()=>{if(pending.get(project)===result)pending.delete(project);});
   pending.set(project,result);return result;
  };
 }
 function createAssetLoader(attach){
  const requests=new Map();
  return function load(url,type,ready){
   if(requests.has(url))return requests.get(url);
   const pending=attach(url,type).then(()=>{
    const value=ready?.();
    if(ready&&!value)throw Error('资源已读取，但未能初始化：'+url);
    return value;
   }).catch(error=>{requests.delete(url);throw error;});
   requests.set(url,pending);
   return pending;
  };
 }
 const loadAsset=createAssetLoader((url,type)=>new Promise((resolve,reject)=>{
  const node=root.document.createElement(type==='style'?'link':'script');
  if(type==='style'){node.rel='stylesheet';node.href=url;}else node.src=url;
  node.onload=resolve;
  node.onerror=()=>{node.remove();reject(Error('暂时无法加载资源：'+url));};
  root.document.head.append(node);
 }));
 const loadPlotly=()=>loadAsset('/vendor/plotly.js','script',()=>root.Plotly);
 const loadProjectCanvas=async()=>{
  const [canvas]=await Promise.all([
   loadAsset('/project-canvas.js','script',()=>root.ResearchCanvas),
   loadAsset('/project-canvas.css','style'),
  ]);
  return canvas;
 };
 const api={requiresWorkspace,createLoader,createAssetLoader,loadPlotly,loadProjectCanvas};
 root.WorkspaceLoading=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
