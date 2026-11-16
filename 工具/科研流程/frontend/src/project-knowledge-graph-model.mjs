export function knowledgeGraph(raw,knowledge){
 const docs=new Set(knowledge.documents.map(d=>d.id)),papers=new Set(knowledge.papers.map(p=>p.id));
 const nodes=raw.nodes.filter(n=>n.source.kind==='paper'?papers.has(n.source.paper_id):docs.has(n.document_id));
 const ids=new Set(nodes.map(n=>n.id));
 const directions=(raw.directions||[]).map(d=>({...d,node_ids:d.node_ids.filter(id=>ids.has(id))})).filter(d=>d.node_ids.length);
 for(const d of directions)ids.add('direction:'+d.id);
 return {...raw,nodes,directions,groups:[],show_frames:false,papers:raw.papers.filter(p=>papers.has(p.id)),
  edges:raw.edges.filter(e=>ids.has(e.source)&&ids.has(e.target)),auto_edges:(raw.auto_edges||[]).filter(e=>ids.has(e.source)&&ids.has(e.target))};
}
