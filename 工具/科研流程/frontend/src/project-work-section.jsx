import React,{useState} from 'react';
import {Button} from './canvas-components.jsx';
import {ProjectWork} from './project-work.jsx';
import {AttachItems} from './attach-project-items.jsx';

// Current and all work share IDs and status; switching views never changes membership.
export function WorkSection({stageId='',data,project,bridge,onRefresh,locked=false}){
 const [all,setAll]=useState(false),[attach,setAttach]=useState(false),[question,setQuestion]=useState('');
 const scoped={...data,project_profile:{...data.project_profile,archived:locked||data.project_profile.archived}};
 return <div className="ps-work-section" aria-label={stageId?'节点工作':'项目工作'}>
  <div className="ps-inline"><span>{stageId?'本节点工作':'整个项目的工作'}</span><Button onClick={()=>setAll(!all)}>{all?'查看当前工作':'查看全部工作'}</Button>{stageId&&<Button disabled={scoped.project_profile.archived} onClick={()=>setAttach(true)}>关联已有工作</Button>}</div>
  <ProjectWork key={String(all)} stageId={stageId} data={scoped} project={project} bridge={bridge} onRefresh={onRefresh} compact={!all} question={question} onQuestion={setQuestion}/>
  {attach&&<AttachItems project={project} stage={{id:stageId,lifecycle_revision:data.project_profile.lifecycle_revision}} itemType="work" bridge={bridge} onClose={()=>setAttach(false)} onSaved={onRefresh}/>}
 </div>;
}
