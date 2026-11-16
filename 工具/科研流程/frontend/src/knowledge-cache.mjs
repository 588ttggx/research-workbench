import { createStore, get, update } from 'idb-keyval';
const store=createStore('research-knowledge-view-cache','snapshots');
// Three read-only scope snapshots, never documents or live graphics resources.
window.KnowledgeGraphDiskCache={
 async get(key){const rows=await get('scopes-v1',store);return rows?.find(row=>row.key===key)?.value;},
 put(key,value){return update('scopes-v1',rows=>[{key,value},...(rows||[]).filter(row=>row.key!==key)].slice(0,3),store);}
};
