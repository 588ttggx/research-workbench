import React,{useEffect,useRef,useState} from 'react';
import {Button,Modal} from './canvas-components.jsx';

export function AttachItems({project,stage,bridge,onClose,onSaved,itemType}){
 const noun=itemType==='plan'?'计划':'工作';
 const [work,setWork]=useState(null),[chosen,setChosen]=useState(new Set()),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const request=useRef(crypto.randomUUID());
 useEffect(()=>{bridge.api('/api/project-work?project='+encodeURIComponent(project)).then(setWork).catch(e=>setError(e.message));},[]);
 async function save(){setBusy(true);try{await bridge.api('/api/project-work/change',{project,op:'associate_stages',task_ids:[...chosen],stage_id:stage.id,fingerprint:work.fingerprint,request_id:request.current,lifecycle_revision:stage.lifecycle_revision});await onSaved();onClose();}catch(e){setError(e.message);}finally{setBusy(false);}}
 return <Modal title={'关联已有'+noun} onClose={onClose}><p>关联后使用同一{noun}，状态保持同步。</p>{work?.items.filter(t=>(t.item_type||'work')===itemType&&!t.removed&&!t.replacement).map(t=><label className="ps-task-select" key={t.id}><input type="checkbox" checked={chosen.has(t.id)||t.stage_ids?.includes(stage.id)||false} disabled={t.stage_ids?.includes(stage.id)} onChange={e=>setChosen(old=>{const n=new Set(old);e.target.checked?n.add(t.id):n.delete(t.id);return n;})}/>{t.title}{t.done?' · 已完成':''}</label>)}{error&&<p role="alert">{error}</p>}<div className="cv-dialog-actions"><Button onClick={onClose}>取消</Button><Button disabled={busy||!chosen.size} onClick={save}>关联所选{noun}</Button></div></Modal>;
}
