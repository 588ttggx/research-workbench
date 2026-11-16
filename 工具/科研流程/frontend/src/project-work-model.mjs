export const statuses=['待定','进行中','等待','暂停','完成'];

export function workForm(row,noun='工作'){
 return {title:row.title||'',item_type:row.item_type||(noun==='计划'?'plan':'work'),status:row.status||'待定',
  kind:row.kind||'',next_step:row.next_step||'',execution_notes:row.execution_notes||'',due_on:row.due_on||'',due_date_rule:row.due_date_rule||null,
  question_id:row.question_id||'',depends_on:row.depends_on||[],references:row.references||[],stage_ids:row.stage_ids||[]};
}

function normalizedValue(value){
 if(Array.isArray(value))return value.map(normalizedValue);
 if(value&&typeof value==='object')return Object.fromEntries(Object.keys(value).sort().map(key=>[key,normalizedValue(value[key])]));
 return value;
}
const sameValue=(left,right)=>JSON.stringify(normalizedValue(left))===JSON.stringify(normalizedValue(right));
const nullableFields=new Set(['kind','next_step','due_on','question_id']);

export function workFields(values,base=null){
 return Object.fromEntries(Object.entries(values)
  .filter(([field,value])=>!base||!sameValue(value,base[field]))
  .map(([field,value])=>[field,nullableFields.has(field)&&value===''?null:value]));
}

export function rebaseWorkForm(base,draft,current){
 const changes=Object.entries(draft).filter(([field,value])=>!sameValue(value,base[field]));
 const conflicts=changes.filter(([field,value])=>!sameValue(current[field],base[field])&&!sameValue(current[field],value));
 return {values:{...current,...Object.fromEntries(changes)},conflicts:conflicts.map(([field])=>field)};
}

export function itemsOfType(rows,type='work',stageId=''){
 return (rows||[]).filter(row=>(row.item_type||'work')===type&&(!stageId||(row.stage_ids||[]).includes(stageId)));
}

const normalized=text=>String(text??'').trim().toLowerCase();

/**
 * 单一工作视图投影：显示范围、筛选、稳定排序、摘要截取与统计都来自这里。
 * 纯函数，不修改原数组、不写任务稿。
 * - 默认包含普通完成项，排除移除/被替代项；history=true 才把后者纳入。
 * - compact 只取未完成项的前 5 条，并返回真实未完成总数。
 */
export function workView(rows,{compact=false,history=false,kind='',question='',query=''}={}){
 const source=Array.isArray(rows)?rows:[];
 const needle=normalized(query);
 const filtered=source
  .map((row,index)=>({...row,_order:index}))
  .filter(row=>{
   if(!history&&(row.removed||row.replacement))return false;
   if(kind&&row.kind!==kind)return false;
   if(question&&(row.question_id||'independent')!==question)return false;
   if(needle&&!normalized([row.title,row.next_step,row.kind].filter(Boolean).join(' ')).includes(needle))return false;
   return true;
  })
  .sort((a,b)=>(a.pin_rank??Infinity)-(b.pin_rank??Infinity)
   ||(a.status==='进行中'?0:1)-(b.status==='进行中'?0:1)
   ||(a._order)-(b._order));
 const pool=compact?filtered.filter(row=>row.status!=='完成'):filtered;
 const shown=compact?pool.slice(0,5):pool;
 const stats=Object.fromEntries(statuses.map(status=>[status,filtered.filter(row=>row.status===status).length]));
 return {
  filtered,
  shown,
  stats,
  total:filtered.length,
  scope:compact?pool.length:filtered.length,
  hidden:pool.length-shown.length,
  completed:filtered.filter(row=>row.status==='完成').length,
  historyShown:history?filtered.filter(row=>row.removed||row.replacement).length:0,
 };
}

export function visibleWork(rows,options={}){
 return workView(rows,options).shown;
}

export function counts(rows){
 const list=Array.isArray(rows)?rows:[];
 return Object.fromEntries(statuses.map(status=>[status,list.filter(row=>!row.removed&&!row.replacement&&row.status===status).length]));
}

export function blockedBy(row,rows){
 return (row.depends_on||[]).map(id=>rows.find(r=>r.id===id)||{id,title:'关联工作已失效',done:false}).filter(r=>!r.done);
}

/** 行内 Markdown 只用于展示：去掉强调/代码标记，保留原文，不做 HTML 注入。 */
export function plainInline(text){
 return String(text??'')
  .replace(/!\[([^\]]*)\]\([^)]*\)/g,'$1')
  .replace(/\[([^\]]+)\]\([^)]*\)/g,'$1')
  .replace(/(\*\*|__|~~|`)/g,'')
  .replace(/\s+/g,' ')
  .trim();
}
