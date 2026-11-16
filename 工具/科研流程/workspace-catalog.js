(function(root){
 'use strict';
 function visible(doc,scope='current'){
  return scope==='archived'?!!doc.archived:!doc.archived&&(scope==='system'?doc.visibility==='system':scope==='all'||doc.visibility!=='system');
 }
 function filter(documents,{scope='current',kind='',query=''}={}){
  const q=query.trim().toLocaleLowerCase();
  return documents.filter(d=>visible(d,scope)&&(!kind||d.kind===kind)&&(!q||[d.title,d.display_title,d.kind,d.path,d.project,d.record_id,...(d.paper_ids||[])].filter(Boolean).join(' ').toLocaleLowerCase().includes(q))).sort((a,b)=>(b.file_modified||0)-(a.file_modified||0));
 }
 const api={visible,filter};root.ResearchCatalog=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
