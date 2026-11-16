(function(root){
 'use strict';
 const clone=value=>JSON.parse(JSON.stringify(value));
 function create(items,{kind='review',context={},currentId}={}){
  const rows=clone(items),found=rows.findIndex(item=>item.id===currentId);
  return {items:rows,index:found<0?0:found,kind,context:clone(context),completed:[],skipped:[],suspended:null};
 }
 function current(state){return state.items[state.index]||null;}
 function complete(state,{ok,id,error}={}){
  const item=current(state);
  if(ok!==true||!item||(id!==undefined&&id!==item.id))return {...state,...(error?{error}:{})};
  return {...state,index:state.index+1,completed:[...state.completed,item.id],suspended:null,error:null};
 }
 function skip(state){const item=current(state);return item?{...state,index:state.index+1,skipped:[...state.skipped,item.id],suspended:null}:state;}
 function suspend(state,target){return {...state,suspended:clone(target)};}
 function resume(state){return {...state,suspended:null};}
 function isCurrentImpact(target){
  return Boolean(target&&!target.optional&&target.kind!=='work_add'&&
   ['pending','writing','needs_choice'].includes(target.status||'pending')&&
   (target.review_level?target.review_level==='decision':target.proposal_id||target.kind==='native_review')&&
   (target.proposal_id||target.kind==='native_review'));
 }
 function isHistoryImpact(target){
  return Boolean(target&&!target.optional&&target.kind!=='work_add'&&target.proposal_id&&
   ['deferred','rejected'].includes(target.status));
 }
 function materials({documents=[],pending=[],targets=[],sync=[],judgments=[]}={}){
  const groups=new Map(),byPath=new Map(documents.flatMap(d=>[d.path,d.kb_path].filter(Boolean).map(p=>[p,d]))),byId=new Map(documents.flatMap(d=>[d.id,d.record_id].filter(Boolean).map(id=>[id,d])));
  function group(key,doc,label,area){
   area=area||(doc?.content_role==='knowledge'?'knowledge':'projects');
   if(!groups.has(key))groups.set(key,{key,doc,label:doc?.display_title||doc?.title||label||key,area,reasons:[],sync:[],drafts:[],judgments:[],optional:false});
   return groups.get(key);
  }
  for(const row of sync){const doc=byPath.get(row.local_path),g=group(doc?.id||'sync:'+row.id,doc,row.title||row.local_path);g.sync.push(row);g.reasons.push('同步稿存在差异');}
  for(const p of pending){if(p.automatic)continue;const doc=byPath.get(p.target?.path),g=group(doc?.id||'draft:'+p.id,doc,p.target_label||p.summary);g.drafts.push(p);g.reasons.push('有正文修改预览');}
  for(const n of judgments){const doc=byId.get(n.id),g=group(doc?.id||n.id,doc,n.data?.title||n.title);g.judgments.push(n);g.reasons.push('科研判断待核查');}
  for(const target of targets){if(!isCurrentImpact(target))continue;const doc=target.kind==='document'?byId.get(target.id):null,g=group(doc?.id||target.kind+':'+target.id,doc,target.label,target.area);
   g.area=target.area||g.area;
   if(g.impact){const found=new Map([...(g.impact.sources||[]),...(target.sources||[])].map(s=>[s.id,s]));g.impact.sources=[...found.values()];}
   else g.impact=clone(target);
   g.reasons.push(target.reason||'关联内容需要核对');
  }
  return [...groups.values()];
 }
 const api={create,current,complete,skip,suspend,resume,isCurrentImpact,isHistoryImpact,materials};root.ReviewQueue=api;
 if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
