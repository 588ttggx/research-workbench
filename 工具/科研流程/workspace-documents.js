// One original, one editor, and a version-bound update review.
function documentState(doc){if(doc.ai_review_pending&&!doc.needs_review)return 'AI 生成正文';if(doc.kind==='项目记录'&&!doc.needs_action&&['CANDIDATE','DRAFT'].includes(doc.review_status))return '已保存';return doc.update_state?.label||doc.status;}
function documentSection(doc){return TopicNavigation.isKnowledge(doc)?'knowledge':'projects';}
function sourceVersions(doc){return Object.fromEntries(doc.references.map(r=>[r.id,r.sha]));}

function documentMarkdown(body,base){
 const renderer=new marked.Renderer(),renderLink=renderer.link.bind(renderer);
 renderer.link=token=>renderLink({...token,href:/^https?:/i.test(token.href)||token.href.startsWith('/api/')?token.href:'/?linked='+encodeURIComponent(token.href)});
 const prepared=String(body||'').replace(/\[\[([^\]\n]+)\]\]/g,(_,target)=>{const [path,label]=target.split('|');return '['+(label||path.split('/').pop())+'](/?linked='+encodeURIComponent(path)+')';})
  .replace(/(<a\b[^>]*\bhref\s*=\s*)(["'])(file:|zotero:)([^"']*)\2/gi,(_,prefix,quote,scheme,path)=>prefix+quote+'/?linked='+encodeURIComponent(scheme+path)+quote);
 const node=el('div');node.innerHTML=DOMPurify.sanitize(marked.parse(prepared,{renderer}));
 const used=new Map();node.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach(h=>{const stem=h.textContent.trim().toLowerCase().replace(/\s+/g,'-'),n=used.get(stem)||0;used.set(stem,n+1);h.id=stem+(n?'-'+(n+1):'');});
 // Short stable identifiers in old notes should open their registered source too.
 const known=new Set([...(S.workspace?.papers||[]).map(p=>p.id),...(S.workspace?.documents||[]).map(d=>d.record_id).filter(Boolean)]);
 if(known.size){const escaped=[...known].sort((a,b)=>b.length-a.length).map(s=>s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'));
  const pattern=new RegExp('(?<![\\w.-])('+escaped.join('|')+')(?![\\w.-])','g'),walker=document.createTreeWalker(node,NodeFilter.SHOW_TEXT),texts=[];
  while(walker.nextNode())if(!walker.currentNode.parentElement.closest('a,pre,script,style,button'))texts.push(walker.currentNode);
  for(const text of texts){const value=text.textContent;pattern.lastIndex=0;let match,offset=0;const fragment=document.createDocumentFragment();while((match=pattern.exec(value))){fragment.append(document.createTextNode(value.slice(offset,match.index)));const a=el('a',match[0]);a.href='/?linked='+encodeURIComponent(match[0]);fragment.append(a);offset=match.index+match[0].length;}if(offset){fragment.append(document.createTextNode(value.slice(offset)));text.replaceWith(fragment);}}
 }
 node.querySelectorAll('a').forEach(a=>{
  const href=a.getAttribute('href')||'';
  if(/^(https?:|zotero:)/i.test(href)){
   const url=new URL(href,location.origin);
   if(url.origin===location.origin&&/^#(?:document|paper|run|analyze|discover|knowledge|projects|lab|outputs)\b/.test(url.hash)){a.onclick=e=>{e.preventDefault();openWorkspaceHash(url.hash);};return;}
   a.target='_blank';a.rel='noopener noreferrer';return;
  }
  if(href.startsWith('/api/')){a.target='_blank';a.rel='noopener noreferrer';return;}
  a.onclick=async event=>{event.preventDefault();try{
   let target=href;
   // Wiki links pass through the same renderer as normal Markdown links.
   for(let i=0;i<2&&target.startsWith('/?linked=');i++)target=new URL(target,location.origin).searchParams.get('linked')||'';
   if(/^zotero:\/\/(?:select|open-pdf|note)\//i.test(target)){location.href=target;return;}
   if(/^\/?#(?:document|paper|run|analyze|discover|knowledge|projects|lab|outputs)(?:\?|$)/.test(target)){dismiss();openWorkspaceHash(target.replace(/^\//,''));return;}
   if(target.startsWith('#')){scrollDocumentAnchor(node,target.slice(1));return;}
   const result=await api('/api/workspace/resolve',{base,target});
   if(result.id){dismiss();navigate('document',result.id,'',result.anchor||'');}
   else if(result.paper_id){dismiss();navigate('paper',result.paper_id,result.tab||'',result.anchor||'');}
  }catch(error){notify(error.message,true);}};
 });return node;
}
function openWorkspaceHash(hash){dismiss();const [route,query='']=hash.slice(1).split('?'),p=new URLSearchParams(query);if(['document','paper','run'].includes(route))navigate(route,p.get('id')||'',p.get('tab')||'',p.get('anchor')||'');else location.hash=hash;}
function scrollDocumentAnchor(root,anchor){
 let name=anchor;try{name=decodeURIComponent(name);}catch(_){}
 const normalized=name.toLowerCase().replace(/\s+/g,'-');
 const heading=[...root.querySelectorAll('h1,h2,h3,h4,h5,h6')].find(h=>h.id===name||h.id===normalized||h.textContent.trim()===name);
 if(!heading){notify('这份资料没有对应章节，请在正文中查找。',true);return;}
 heading.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});
 heading.classList.add('linked-heading');setTimeout(()=>heading.classList.remove('linked-heading'),2200);
}

async function renderDocument(id){
 const token=S.renderToken,[original,knowledge]=await Promise.all([api('/api/workspace/document?id='+encodeURIComponent(id)),loadKnowledge(true)]);
 const indexed=knowledge.documents.find(d=>d.id===id),doc={...indexed,...original,used_by:indexed?.used_by||[],source_project_title:indexed?.source_project_title||projectLabel(original.source_project)};
 if(token!==S.renderToken||S.route!=='document'||new URLSearchParams(location.hash.split('?')[1]).get('id')!==id)return;
 S.doc=doc;const section=documentSection(doc);document.querySelectorAll('#primaryNav button').forEach(b=>{const active=b.dataset.route===section;b.classList.toggle('active',active);b.setAttribute('aria-current',active?'page':'false');});const view=$('view');view.replaceChildren();
 const back=materialBackButton(()=>navigate(section),section==='knowledge'?'返回知识':'返回项目');back.style.marginBottom='22px';view.append(back);const reviewBack=reviewReturnButton();if(reviewBack)view.append(reviewBack);
 const h=el('div',null,'object-heading'),meta=el('div',null,'object-meta');h.append(el('h1',docLabel(doc)));
 meta.append(badge(doc.kind),badge(documentState(doc)),el('span',doc.project),el('span','修改于 '+date(doc.file_modified)));
 if(doc.created)meta.append(el('span','生成于 '+docTime(doc)));if(doc.archived)meta.append(badge('已归档'));h.append(meta);view.append(h);
 const actions=el('div',null,'object-toolbar');
 if(doc.editable)actions.append(btn('编辑正文',()=>editDocument(doc),'primary','edit'),btn('AI 协助修改',()=>showDraftPrompt(doc),'','sparkles'),btn('关联论文',()=>showDocumentPapers(doc),'quiet-button','link'));
 else if(doc.proposal_id)actions.append(btn('核对修改预览',()=>showProposal(doc.proposal_id),'primary','check'));
 if(doc.ai_review_pending&&!doc.needs_review)actions.append(btn('核对 AI 正文',()=>showDocumentUpdate(doc),'quiet-button','check'));
 if(doc.visibility!=='system')actions.append(btn('仅讨论此资料',()=>{S.discussion={id:doc.id,title:docLabel(doc)};S.chat=null;return openAssistant();},'quiet-button','sparkles'));
 if(!doc.used_by.some(p=>p.project===S.project)&&(!doc.archived||/报告/.test(doc.kind))&&doc.visibility!=='system')actions.append(btn('选入当前项目',async()=>{await selectKnowledgeMaterial(doc);await loadWorkspace();await renderDocument(doc.id);},'quiet-button','plus'));
 actions.append(btn('归档'+(doc.archived?'恢复':'这份资料'),async()=>{await api('/api/workspace/archive',{id:doc.id,fingerprint:doc.fingerprint,archived:!doc.archived});await loadWorkspace();await renderDocument(doc.id);notify(doc.archived?'资料已恢复到原列表':'已退出日常列表；原稿与引用保留');},'quiet-button push-right','archive'));view.append(actions);
 if(doc.project!==S.project&&doc.project!=='共享')view.append(el('p','来源：'+doc.source_project_title+'。编辑正文会更新这份原稿，使用它的项目会收到变化提示。','notice info'));
 if(doc.archived){const archive=el('div',null,'notice info');archive.append(el('strong','这份资料已退出日常列表'),el('p',doc.archive_reason||'正文与原引用保留，可通过归档恢复重新显示。'));if(doc.archive_replacement)archive.append(btn('打开当前资料 · '+doc.archive_replacement.title,()=>navigate('document',doc.archive_replacement.id),'text-link'));view.append(archive);}
 const previews=S.workspace.pending.filter(p=>p.automatic!==true&&[doc.path,doc.kb_path].includes(p.target?.path));
 if(doc.needs_review||previews.length){const notice=el('section',null,previews.length?'document-update':'notice info');
  notice.append(el('strong',doc.needs_review?doc.update_state.source_count+' 份引用资料有更新':'这份资料有正文修改建议'));
  if(doc.needs_review)notice.append(btn('查看引用变化',()=>showDocumentUpdate(doc),'quiet-button','check'));
  for(const preview of previews)notice.append(btn('核对正文修改预览',()=>showProposal(preview.id),'quiet-button','edit'));view.append(notice);
 }else if(doc.upstream_changed)view.append(el('div','更远的关联资料有变化；本稿直接引用的正文未改变，可在来源中按需查看。','notice info'));
 const bodyTabs=tabs([['body','正文'],['sources','来源与引用'],['history','修改历史']],'body',draw),content=el('div');view.append(bodyTabs,content);
 function draw(tab){
  bodyTabs.querySelectorAll('button').forEach((b,i)=>b.classList.toggle('active',i===['body','sources','history'].indexOf(tab)));content.replaceChildren();
  if(tab==='history'){renderDocumentHistory(doc,content);return;}if(tab==='sources'){content.append(sourceSidebar(doc));return;}
  const layout=el('div',null,'document-layout'),body=el('article',null,'document-body'),rendered=markdown(doc.body,doc.id),firstTitle=rendered.querySelector('h1');
  if(firstTitle?.textContent===doc.title)firstTitle.remove();const contentTitle=rendered.querySelector('h1');if(doc.display_title!==doc.title&&contentTitle?.textContent===docLabel(doc))contentTitle.remove();
  body.append(rendered);layout.append(body,sourceSidebar(doc));content.append(layout);
 }draw('body');
 if(S.pendingDraft?.id===doc.id){const draft=S.pendingDraft;S.pendingDraft=null;editDocument(doc,draft);return;}
 const anchor=new URLSearchParams(location.hash.split('?')[1]).get('anchor');if(anchor)scrollDocumentAnchor(content,anchor);
}

async function showDocumentUpdate(old){
 const body=modal('处理资料更新'),generation=S.overlayGeneration;body.append(el('p','正在读取正文与来源版本…','loading-state'));
 let changes;try{changes=await api('/api/workspace/source-changes?id='+old.id);}catch(error){if(generation===S.overlayGeneration)body.replaceChildren(empty('资料暂未读取',error.message,btn('重新读取',()=>showDocumentUpdate(old))));return;}
 if(generation!==S.overlayGeneration||!$('overlay').open)return;
 const doc=changes.document;if(!doc)throw Error('审核服务版本尚未更新，请重载科研看板后重新读取。');
 $('overlayTitle').textContent='处理资料更新 · '+docLabel(doc);body.replaceChildren();
 body.append(el('p','核对只针对这份正文和当前来源版本，不改变论文阅读范围，也不替代正式科研判断审核。','section-subtitle'));
 if(!doc.needs_action){body.append(empty('这份资料已处理','当前没有新的引用变化或 AI 内容需要核对。'));return;}
 if(doc.needs_review){
  if(changes.fingerprint!==doc.fingerprint||JSON.stringify(changes.sources)!==JSON.stringify(sourceVersions(doc)))throw Error('资料又有变化，请重新打开核对。');
  body.append(el('h3','引用变化 · '+changes.changes.length),el('p','绿色为新增，橙色为删除；比较的是本稿曾引用的版本与当前来源。','muted'));
  for(const source of changes.changes){const item=el('details',null,'source-change');item.open=true;item.append(el('summary',source.title));
   const content=el('div',null,'source-change-body');
   if(source.before_available){for(const row of source.diff)content.append(el('div',row.text,'diff-row '+row.kind));if(source.truncated)content.append(el('p','变化较多，打开来源查看完整正文。','muted'));}
   else{content.append(el('p','这次变更早于版本对照启用，未保存当时正文；请核对当前来源。不会编造旧版本。','muted'),markdown(source.current_body,source.id));}
   item.append(content,btn('打开这份来源',()=>{dismiss();navigate('document',source.id);},'quiet-button','external'));body.append(item);
  }
 }
 if(doc.ai_review_pending){body.append(el('h3','AI 内容核对'),el('p','请核对文字是否符合实际来源；“完成核对”不会把 AI 建议升级为已验证结论。','muted'));const article=el('div',null,'note-comparison-pane');article.append(markdown(doc.body,doc.id));body.append(article);}
 const actions=el('div',null,'form-actions');
 if(doc.editable)actions.append(btn('编辑并完成核对',()=>{dismiss();S.pendingDraft={id:doc.id,completeReview:true};navigate('document',doc.id);},'primary','edit'),btn('AI 协助修订',()=>showDraftPrompt(doc),'quiet-button','sparkles'));
 actions.append(btn(doc.ai_review_pending?'确认内容已核对，无需修改':'确认无需修改正文',async()=>{
  await api('/api/workspace/acknowledge',{id:doc.id,fingerprint:doc.fingerprint,sources:sourceVersions(doc),review_ai:doc.ai_review_pending,reason:doc.ai_review_pending?'用户核对当前 AI 内容及来源，确认无需修改':'用户核对当前引用变化，确认无需修改正文'});
  if(await finishReview('document',doc.id))return;dismiss();await loadWorkspace();navigate('document',doc.id);notify('这份资料已处理；来源再次变化时会重新提示');
 },'quiet-button','check'));body.append(actions);
}

function editDocument(doc,initial=null){
 S.doc=doc;const view=$('view');view.replaceChildren(heading('EDIT DOCUMENT','编辑正文','修改原稿，保存前版本保留。处理更新时可一并完成核对。'));
 const review=el('input');review.type='checkbox';review.checked=initial?.completeReview===true;
 let saved=null;try{saved=JSON.parse(localStorage.getItem('research:draft:'+doc.id));}catch(_){}
 const draft=initial?.body!==undefined?initial:{...saved,...initial},title=input('',draft?.title||doc.title);title.id='editorTitle';title.className='editor-title';title.setAttribute('aria-label','资料标题');view.append(title);
 const controls=el('div',null,'object-toolbar'),save=btn(review.checked?'保存并完成核对':'保存正文',async()=>{
  save.disabled=true;try{
   const result=await api('/api/workspace/save',{id:doc.id,fingerprint:doc.fingerprint,body:S.editor.getMarkdown(),title:title.value,
    ...(review.checked?{reviewed_sources:true,reviewed_ai:doc.ai_review_pending,sources:sourceVersions(doc)}:{})});
   localStorage.removeItem('research:draft:'+doc.id);S.dirty=false;S.editor.destroy();S.editor=null;if(review.checked&&await finishReview('document',doc.id))return;await loadWorkspace();await renderDocument(result.id);
   notify(review.checked?'正文已保存，本次更新已处理':'正文已保存');
  }finally{save.disabled=false;}
 },'primary','check');
 const reviewBack=reviewReturnButton();if(reviewBack)controls.append(reviewBack);
 controls.append(save,btn('插入资料引用',()=>showReferencePicker(doc),'','link'),btn('返回阅读',()=>{preserveEditor();renderDocument(doc.id);},'','back'),el('span','未保存的编辑在本机保留','editor-warning'));view.append(controls);
 if(doc.needs_action){const lab=el('label',null,'check-field');lab.append(review,el('span','本次已核对正文及引用变化，保存时一并完成处理'));review.onchange=()=>{save.textContent=review.checked?'保存并完成核对':'保存正文';};view.append(lab);}
 if(saved&&saved.fingerprint!==doc.fingerprint&&initial?.body===undefined)view.append(el('div','发现未保存草稿，但正式正文也有更新，请核对后合并。','notice'));
 const host=el('div',null,'editor-host');view.append(host);
 S.editor=new toastui.Editor({el:host,height:'650px',initialEditType:'wysiwyg',previewStyle:'vertical',language:'zh-CN',usageStatistics:false,initialValue:draft?.body||doc.body,toolbarItems:[['heading','bold','italic','strike'],['hr','quote'],['ul','ol','task'],['table','link'],['code','codeblock'],['scrollSync']]});S.editor.moveCursorToEnd(false);
 let timer;const stash=()=>{S.dirty=true;clearTimeout(timer);timer=setTimeout(()=>{if(S.editor)localStorage.setItem('research:draft:'+doc.id,JSON.stringify({body:S.editor.getMarkdown(),title:title.value,fingerprint:doc.fingerprint}));},400);};S.editor.on('change',stash);title.oninput=stash;
}
