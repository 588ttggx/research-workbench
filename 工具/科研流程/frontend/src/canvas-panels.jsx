import React,{useState} from 'react';
import {Check} from 'lucide-react';
import {Button,Modal} from './canvas-components.jsx';

export function DirectionDialog({direction,onSave,onClose}){
 const [title,setTitle]=useState(direction?.title||''),[summary,setSummary]=useState(direction?.summary||''),[error,setError]=useState('');
 return <Modal title={direction?'调整研究方向':'建立研究方向'} subtitle="按内容组织；可以自由改名，也可在笔记详情调整归属。" onClose={onClose}><label className="cv-field">方向名称<input autoFocus value={title} maxLength={48} onChange={e=>setTitle(e.target.value)}/></label><label className="cv-field">方向说明<textarea value={summary} maxLength={250} onChange={e=>setSummary(e.target.value)} rows={3}/></label>{error&&<p className="cv-error">{error}</p>}<div className="cv-dialog-actions"><Button icon={Check} variant="primary" onClick={async()=>{try{await onSave({title,summary,...(direction?{direction_id:direction.id}:{})});onClose();}catch(e){setError(e.message);}}}>保存方向</Button></div></Modal>;
}
