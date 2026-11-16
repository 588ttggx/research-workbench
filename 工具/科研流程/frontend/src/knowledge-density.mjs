// D3 supplies kernel density estimation and contour paths; the view only themes them.
import { contourDensity } from 'd3-contour';
import { geoPath, geoIdentity } from 'd3-geo';
function paths(nodes, positions) {
  const rows=nodes.filter(n=>positions[n.id]?.semantic).map(n=>positions[n.id]);
  if(rows.length<8)return [];
  const xs=rows.map(p=>p.x),ys=rows.map(p=>p.y),x=Math.min(...xs),y=Math.min(...ys);
  const scale=440/Math.max(1,Math.max(...xs)-x,Math.max(...ys)-y),padding=36;
  const contours=contourDensity().x(p=>(p.x-x)*scale+padding).y(p=>(p.y-y)*scale+padding).size([512,512]).bandwidth(14).thresholds(5)(rows);
  const path=geoPath(geoIdentity().scale(1/scale).translate([x-padding/scale,y-padding/scale]));
  return contours.map(c=>path(c)).filter(Boolean);
}
window.ResearchKnowledgeDensity={paths};
