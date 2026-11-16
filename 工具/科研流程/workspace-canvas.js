/* The project workspace uses React Flow; sources and editors retain their identities. */
function projectQuestionRoute(project,id='',history=false,step=''){
 const params=new URLSearchParams({project,view:history?'question-history':'overview'});
 if(id)params.set('question',id);
 if(history&&step)params.set('step',step);
 return '#projects?'+params;
}
async function renderProjects(){
 const token=S.renderToken,project=S.project,host=el('div',null,'project-canvas-host');$('view').append(host);
 host.append(el('p','正在打开项目进展…','loading-state'));
 const canvas=await WorkspaceLoading.loadProjectCanvas();
 if(token!==S.renderToken||project!==S.project)return;
 host.replaceChildren();
 const bridge={api,notify,markdown,projects:()=>{location.hash='#projects';},manageProject:showProjectProfile,
  openProjectArea:route=>{if(project===S.project&&token===S.renderToken)navigate(route);},
  openQuestionHistory:id=>{location.hash=projectQuestionRoute(S.project,id,true);},
  openProjectChanges:project=>{if(project===S.project&&token===S.renderToken)showAutomation('review',{area:'projects'}).catch(e=>notify(e.message,true));},
  openPaper:async id=>{await loadWorkspace();navigate('paper',id);},
  openDocument:async id=>{await loadWorkspace();navigate('document',id);},
  editDocument:async id=>{await loadWorkspace();S.pendingDraft={id};navigate('document',id);}};
 const projectParams=new URLSearchParams(location.hash.split('?')[1]);
 const initialView=projectParams.get('view')||'progress';
 const initialQuestion=projectParams.get('question')||(initialView==='records'?localStorage.getItem('research:question:'+S.project):'')||'';
 const mounted=canvas.mount(host,{project,bridge,initialView,initialQuestion,initialStage:projectParams.get('stage')||'',initialDocument:projectParams.get('document')||''});
 S.canvasCleanup=()=>{mounted.unmount();S.canvasCleanup=null;S.projectReferencesRefresh=null;S.openProjectRecord=null;};
 S.projectReferencesRefresh=()=>mounted.refresh();
 S.openProjectRecord=()=>mounted.newRecord();
}
