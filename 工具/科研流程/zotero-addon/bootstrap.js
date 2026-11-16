/* Native Zotero endpoint authentication is inherited, never reimplemented. */
var registeredEndpoint;
var endpointPath='/api/users/:userID/workspace/better-notes';
function install(){}
function uninstall(){}
function noteSHA256(text){
 const hash=Components.classes['@mozilla.org/security/hash;1'].createInstance(Components.interfaces.nsICryptoHash),data=new TextEncoder().encode(text);
 hash.init(hash.SHA256);hash.update(data,data.length);
 return Array.from(hash.finish(false),c=>c.charCodeAt(0).toString(16).padStart(2,'0')).join('');
}
async function startup(data){
 await Zotero.initializationPromise;
 const version=data?.version||'1.0.2';
 const NativeEndpoint=Object.getPrototypeOf(Zotero.Server.LocalAPI.Items.prototype).constructor;
 registeredEndpoint=class extends NativeEndpoint{
  supportedMethods=['POST'];
  supportedDataTypes=['application/json'];
  async run(request){
   const body=request.data;
   if(!body||!['inspect','detach','backup'].includes(body.operation))return [400,'text/plain','Invalid operation'];
   if(body.operation==='backup'){
    const ok=await Zotero.DB.backUpDatabase({force:true,suffix:'research-workspace',online:true});
    if(!ok)return [503,'application/json',JSON.stringify({error:'Native database backup is busy or unavailable'})];
    const linked=[];
    for(const library of Zotero.Libraries.getAll()){
     const items=await Zotero.Items.getAll(library.libraryID,false,true);
     for(const item of items){
      if(!item.isAttachment()||item.attachmentLinkMode!==Zotero.Attachments.LINK_MODE_LINKED_FILE)continue;
      const path=await item.getFilePathAsync();
      if(!path)return [409,'application/json',JSON.stringify({error:'A registered linked attachment is unavailable; backup is incomplete'})];
      linked.push({key:item.key,path,raw_path:item.attachmentPath});
     }
    }
    return [200,'application/json',JSON.stringify({version,app_version:Zotero.version,created:new Date().toISOString(),database:Zotero.DB.path+'.research-workspace.bak',storage:Zotero.getStorageDirectory().path,linked,engine:'Zotero.DB.backUpDatabase online snapshot'})];
   }
   const api=Zotero.BetterNotes?.api?.sync;
   if(!api)return [503,'application/json',JSON.stringify({error:'Better Notes 尚未就绪'})];
   const ids=await api.getSyncNoteIds(),items=await Zotero.Items.getAsync(ids),records=items.filter(item=>item.libraryID===request.libraryID).map(item=>{
    const state=api.getSyncStatus(item.id);
    return {key:item.key,version:item.version,title:item.getNoteTitle(),path:state.path,filename:state.filename,note_sha256:noteSHA256(item.getNote())};
   });
   if(body.operation==='inspect')return [200,'application/json',JSON.stringify({records,changes:0,version})];
   if(!Array.isArray(body.records)||!body.records.length||body.records.length>50)return [400,'text/plain','Explicit note versions required'];
   const selected=[];
   for(const expected of body.records){
    if(!/^[A-Z0-9]{8}$/.test(expected.key||''))return [400,'text/plain','Invalid note key'];
    const item=await Zotero.Items.getByLibraryAndKeyAsync(request.libraryID,expected.key);
    if(!item||!item.isNote()||item.version!==expected.version||noteSHA256(item.getNote())!==expected.note_sha256)return [409,'text/plain','Note changed; compare current originals first'];
    const state=api.getSyncStatus(item.id);
    if(api.isSyncNote(item.id)&&(state.path!==expected.path||state.filename!==expected.filename))return [409,'text/plain','Sync target changed'];
    selected.push(item);
   }
   // Native plugin removal only; neither Zotero note nor Markdown is modified.
   for(const item of selected)if(api.isSyncNote(item.id))await api.removeSyncNote(item.id);
   return [200,'application/json',JSON.stringify({detached:selected.map(item=>item.key),changes:selected.length})];
  }
 };
 if(Zotero.Server.Endpoints[endpointPath])throw new Error('Workspace endpoint already registered');
 Zotero.Server.Endpoints[endpointPath]=registeredEndpoint;
}
function shutdown(){if(Zotero.Server.Endpoints[endpointPath]===registeredEndpoint)delete Zotero.Server.Endpoints[endpointPath];registeredEndpoint=null;}
