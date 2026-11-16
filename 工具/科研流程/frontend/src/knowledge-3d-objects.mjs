import * as THREE from 'three';
import { chooseLabels } from './knowledge-3d-model.mjs';

export const DEFAULT_COLORS = { paper: '#7faaa8', note: '#aa97bf', knowledge: '#aa97bf', concept: '#8ba5bd', claim: '#bd9d6d', topic: '#a48eb7' };
export function nodeKind(node) {
  if (node.group || /^(topic|community|主题)$/i.test(node.kind || '')) return 'topic';
  const kind = String(node.record_kind || node.kind || '');
  if (/concept|概念/i.test(kind)) return 'concept';
  if (/claim|结论/i.test(kind)) return 'claim';
  if (/^(paper|论文)$/i.test(kind)) return 'paper';
  return 'note';
}
export const nodeRadius = node => node.group ? Math.min(16, 8 + Math.sqrt(node.members?.length || 1)) : Math.min(7.2, Math.max(3.8, Number(node.radius) || 4.3));
export function nodePresentation(node) {
  const kind = nodeKind(node), type = { paper: '论文', note: '知识稿', concept: '概念', claim: '结论', topic: '主题' }[kind];
  const sources = node.sources || node.source_refs || node.provenance || [];
  const count = Number(node.source_count ?? (Array.isArray(sources) ? sources.length : 0));
  const pending = node.suggested || /candidate|pending/i.test(node.status || '');
  return { kind, title: String(node.label || node.title || node.id), summary: String(node.summary || node.description || node.excerpt || '').replace(/\s+/g, ' '), meta: [type, count ? `${count} 个来源` : '', pending ? 'AI 提取' : ''].filter(Boolean).join(' · ') };
}

function rectanglePath(shape, width, height, radius) {
  const x = -width / 2, y = -height / 2;
  shape.moveTo(x + radius, y); shape.lineTo(x + width - radius, y); shape.quadraticCurveTo(x + width, y, x + width, y + radius);
  shape.lineTo(x + width, y + height - radius); shape.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
  shape.lineTo(x + radius, y + height); shape.quadraticCurveTo(x, y + height, x, y + height - radius);
  shape.lineTo(x, y + radius); shape.quadraticCurveTo(x, y, x + radius, y);
  return shape;
}
function roundedRectangle(width, height, radius, outline = false) {
  const shape = rectanglePath(new THREE.Shape(), width, height, radius);
  if (outline) shape.holes.push(rectanglePath(new THREE.Path(), width - 0.025, height - 0.025, radius - 0.01));
  return new THREE.ShapeGeometry(shape, 4);
}
function edgeCurves(edges) {
  const pairs = new Map(), specs = new Map();
  for (const edge of edges) { const key = JSON.stringify([edge.from, edge.to].sort()); if (!pairs.has(key)) pairs.set(key, []); pairs.get(key).push(edge); }
  for (const rows of pairs.values()) {
    rows.sort((a, b) => a.id.localeCompare(b.id));
    rows.forEach((edge, index) => specs.set(edge.id, { offset: rows.length === 1 ? 0.16 : (index - (rows.length - 1) / 2) * 0.24, direction: edge.from <= edge.to ? 1 : -1 }));
  }
  return specs;
}

export function createGraphObjects(nodes, edges, initial = {}) {
  let appearance = initial.appearance === 'cards' ? 'cards' : 'orbs', lastPositionSignature = '', lastFocus;
  const group = new THREE.Group(), metrics = new Map(), batches = new Map();
  const orbMeshes = [], cardMeshes = [], borders = [], iconMeshes = [];
  const transform = new THREE.Object3D(), color = new THREE.Color(), faded = new THREE.Color('#f5f6f1');
  for (const node of nodes) { const kind = nodeKind(node); if (!batches.has(kind)) batches.set(kind, []); batches.get(kind).push(node); }
  function instances(geometry, material, items, target) {
    const mesh = new THREE.InstancedMesh(geometry, material, items.length); mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    mesh.userData.nodes = items; mesh.frustumCulled = false; target.push(mesh); group.add(mesh); return mesh;
  }
  for (const [kind, items] of batches) {
    const geometry = kind === 'paper' ? new THREE.BoxGeometry(1.6, 1.8, 0.6) : kind === 'claim' ? new THREE.OctahedronGeometry(1.15, 0) : new THREE.SphereGeometry(1, 16, 12);
    instances(geometry, new THREE.MeshStandardMaterial({ roughness: 0.65, metalness: 0.02 }), items, orbMeshes);
    const card = instances(roundedRectangle(1, 1, 0.08), new THREE.MeshBasicMaterial({ color: '#ffffff', side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1 }), items, cardMeshes);
    card.renderOrder = 1;
    const border = instances(roundedRectangle(1, 1, 0.08, true), new THREE.MeshBasicMaterial({ color: DEFAULT_COLORS[kind], side: THREE.DoubleSide, transparent: true, opacity: 0.65, depthWrite: false }), items, borders); border.renderOrder = 2;
  }
  function setIcons(textures = {}) {
    for (const mesh of iconMeshes) { group.remove(mesh); mesh.geometry.dispose(); mesh.material.dispose(); }
    iconMeshes.length = 0;
    for (const [kind, items] of batches) if (textures[kind]) {
      const mesh = instances(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ map: textures[kind], color: '#ffffff', transparent: true, depthWrite: false, side: THREE.DoubleSide }), items, iconMeshes);
      mesh.userData.kind = kind; mesh.renderOrder = 3;
    }
  }
  setIcons(initial.iconTextures);
  const pendingNodes = nodes.filter(n => n.suggested || /candidate|pending/i.test(n.status || ''));
  const auditMarkers = instances(new THREE.SphereGeometry(1, 6, 4), new THREE.MeshBasicMaterial({ color: '#d5a957' }), pendingNodes, []);
  auditMarkers.userData.auditMarker = true;
  const screenRight = new THREE.Vector3(), screenUp = new THREE.Vector3(), forward = new THREE.Vector3();
  const curveSpecs = edgeCurves(edges), segments = edges.length > 2500 ? 8 : 12;
  const edgeObjects = [false, true].map(suggested => {
    const rows = edges.filter(edge => Boolean(edge.suggested || /pending|candidate/i.test(edge.status || '')) === suggested);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(rows.length * segments * 6), 3).setUsage(THREE.DynamicDrawUsage));
    const material = suggested ? new THREE.LineDashedMaterial({ color: '#b7a9c9', transparent: true, opacity: 0.38, dashSize: 2, gapSize: 1.5, depthWrite: false }) : new THREE.LineBasicMaterial({ color: '#b9b4cb', transparent: true, opacity: 0.48, depthWrite: false });
    const lines = new THREE.LineSegments(geometry, material); lines.userData.rows = rows; lines.userData.segmentRows = rows.flatMap(edge => Array(segments).fill(edge)); lines.frustumCulled = false; group.add(lines); return lines;
  });
  const activeGeometry = new THREE.BufferGeometry(); activeGeometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(edges.length * segments * 6), 3).setUsage(THREE.DynamicDrawUsage));
  const activeEdges = new THREE.LineSegments(activeGeometry, new THREE.LineBasicMaterial({ color: '#6b9481', transparent: true, opacity: 0.94, depthWrite: false })); activeEdges.frustumCulled = false; group.add(activeEdges);
  const halo = new THREE.Mesh(new THREE.TorusGeometry(1, 0.03, 6, 48), new THREE.MeshBasicMaterial({ color: '#6c907b', transparent: true, opacity: 0.9, depthTest: false, depthWrite: false })); halo.visible = false; halo.renderOrder = 4; group.add(halo);
  const a = new THREE.Vector3(), b = new THREE.Vector3(), control = new THREE.Vector3(), side = new THREE.Vector3(), axis = new THREE.Vector3(), point = new THREE.Vector3(), previous = new THREE.Vector3(), projection = new THREE.Vector3();
  function refreshEdges(positions, focus) {
    let signature = '';
    for (const node of nodes) { const p = positions[node.id]; signature += `${p.x},${p.y},${p.z};`; }
    const moved = signature !== lastPositionSignature;
    if (moved) {
      lastPositionSignature = signature;
      for (const lines of edgeObjects) {
        const array = lines.geometry.attributes.position.array;
        lines.userData.rows.forEach((edge, index) => {
          const from = positions[edge.from], to = positions[edge.to], spec = curveSpecs.get(edge.id); a.set(from.x, from.y, from.z); b.set(to.x, to.y, to.z);
          let curve;
          if (edge.from === edge.to) curve = new THREE.CubicBezierCurve3(a.clone(), a.clone().add(new THREE.Vector3(18, 22, 6)), a.clone().add(new THREE.Vector3(-18, 22, 6)), a.clone());
          else {
            axis.subVectors(b, a).normalize().multiplyScalar(spec.direction); side.set(0, 0, 1).cross(axis);
            if (side.lengthSq() < 0.01) side.set(0, 1, 0).cross(axis); side.normalize();
            control.addVectors(a, b).multiplyScalar(0.5).addScaledVector(side, Math.max(a.distanceTo(b), 16) * spec.offset);
            curve = new THREE.QuadraticBezierCurve3(a.clone(), control.clone(), b.clone());
          }
          curve.getPoint(0, previous);
          for (let step = 0; step < segments; step += 1) { curve.getPoint((step + 1) / segments, point); array.set([previous.x, previous.y, previous.z, point.x, point.y, point.z], (index * segments + step) * 6); previous.copy(point); }
        });
        lines.geometry.attributes.position.needsUpdate = true;
        lines.geometry.boundingSphere = null;
        if (lines.material.isLineDashedMaterial) lines.computeLineDistances();
      }
    }
    if (moved || focus !== lastFocus) {
      const active = activeGeometry.attributes.position.array; let offset = 0;
      for (const lines of edgeObjects) {
        const array = lines.geometry.attributes.position.array;
        lines.userData.rows.forEach((edge, index) => { if (edge.from === focus || edge.to === focus) { const start = index * segments * 6; active.set(array.subarray(start, start + segments * 6), offset); offset += segments * 6; } });
      }
      activeGeometry.attributes.position.needsUpdate = true; activeGeometry.setDrawRange(0, offset / 3); lastFocus = focus;
    }
    for (const lines of edgeObjects) lines.material.opacity = focus ? 0.14 : lines.material.isLineDashedMaterial ? 0.38 : 0.48;
  }
  function update(positions, selected, hover, camera, viewportHeight = 700) {
    const focus = selected || hover, adjacent = new Set(focus ? [focus] : []), cards = appearance === 'cards';
    for (const edge of edges) if (edge.from === focus || edge.to === focus) { adjacent.add(edge.from); adjacent.add(edge.to); }
    camera.updateMatrixWorld(); screenRight.setFromMatrixColumn(camera.matrixWorld, 0); screenUp.setFromMatrixColumn(camera.matrixWorld, 1); forward.setFromMatrixColumn(camera.matrixWorld, 2);
    for (const node of nodes) {
      const p = positions[node.id]; projection.set(p.x,p.y,p.z).applyMatrix4(camera.matrixWorldInverse); const depth = Math.max(camera.near, -projection.z);
      const worldPerPixel = 2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * depth / Math.max(1, viewportHeight);
      const radius = Math.max(nodeRadius(node), Math.min(nodeRadius(node) * 8, (node.group ? 26 : 21) * worldPerPixel));
      const cardWidth = Math.max(112 * worldPerPixel, Math.min(node.group ? 210 : 185, 196 * worldPerPixel));
      const summary = cardWidth / worldPerPixel >= 170;
      const cardHeight = cardWidth * (summary ? 0.65 : 0.6);
      metrics.set(node.id, { radius, worldPerPixel, cardWidth, cardHeight, summary });
    }
    const screen=Object.create(null),viewportWidth=viewportHeight*camera.aspect;
    for(const node of nodes){const p=positions[node.id];projection.set(p.x,p.y,p.z).project(camera);if(projection.z>=-1&&projection.z<=1)screen[node.id]={x:(projection.x+1)*viewportWidth/2,y:(1-projection.y)*viewportHeight/2};}
    const representative=globalThis.KnowledgeScene?.selectVisible(nodes,screen,{width:viewportWidth,height:viewportHeight,appearance,selected,hover,importance:Object.fromEntries(nodes.map(n=>[n.id,n.importance||0]))});
    const shown=representative?new Set(representative.map(n=>n.id)):null;
    for(const node of nodes){const m=metrics.get(node.id);m.detailVisible=!shown||shown.has(node.id);if(!m.detailVisible)m.radius=1.5*m.worldPerPixel;}
    // Projected cards share the same collision policy as their text. Covered cards keep compact icon tiles until there is room for their title.
    if (cards) {
      const viewportWidth = viewportHeight * camera.aspect, candidates = [];
      for (const node of nodes) {
        const p = positions[node.id], m = metrics.get(node.id); projection.set(p.x,p.y,p.z).project(camera);
        const w = m.cardWidth / m.worldPerPixel, h = m.cardHeight / m.worldPerPixel;
        m.cardVisible = false;
        if (projection.z < -1 || projection.z > 1||!m.detailVisible) continue;
        candidates.push({id:node.id,card:true,x:(projection.x+1)*viewportWidth/2,y:(1-projection.y)*viewportHeight/2-h/2,width:w,height:h,priority:node.id===selected?1000:node.id===hover?950:100+Number(node.degree||0)-projection.z});
      }
      for (const item of chooseLabels(candidates,{width:viewportWidth,height:viewportHeight,limit:nodes.length>300?28:42,padding:12})) metrics.get(item.id).cardVisible=true;
    }
    for (const mesh of orbMeshes) { mesh.visible = !cards; if (cards) continue;
      mesh.userData.nodes.forEach((node, index) => { const p = positions[node.id], m = metrics.get(node.id); transform.position.set(p.x, p.y, p.z); transform.quaternion.identity(); transform.scale.setScalar(cards && m.cardVisible ? 0 : m.radius * (node.id === hover || node.id === selected ? 1.06 : 1)); transform.updateMatrix(); mesh.setMatrixAt(index, transform.matrix); color.set(node.color || DEFAULT_COLORS[nodeKind(node)]); if (focus && !adjacent.has(node.id)) color.lerp(faded, 0.2); mesh.setColorAt(index, color); });
      mesh.instanceMatrix.needsUpdate = true; mesh.instanceColor.needsUpdate = true; mesh.boundingSphere = null;
    }
    for (const [index, mesh] of cardMeshes.entries()) {
      mesh.visible = cards; borders[index].visible = cards; if (!cards) continue;
      mesh.userData.nodes.forEach((node, i) => { const p = positions[node.id], m = metrics.get(node.id); transform.position.set(p.x, p.y, p.z); transform.quaternion.copy(camera.quaternion); transform.scale.set(m.cardVisible ? m.cardWidth : 0, m.cardVisible ? m.cardHeight : 0, 1); transform.updateMatrix(); mesh.setMatrixAt(i, transform.matrix); transform.position.addScaledVector(forward, 0.1); transform.scale.set(m.cardVisible ? m.cardWidth : 0, m.cardVisible ? m.cardHeight : 0, 1); transform.updateMatrix(); borders[index].setMatrixAt(i, transform.matrix); color.set(focus && !adjacent.has(node.id) ? '#f8f9f6' : '#ffffff'); mesh.setColorAt(i, color); });
      mesh.instanceMatrix.needsUpdate = true; mesh.instanceColor.needsUpdate = true; mesh.boundingSphere = null; borders[index].instanceMatrix.needsUpdate = true;
    }
    for (const mesh of iconMeshes) {
      mesh.userData.nodes.forEach((node, index) => { const p = positions[node.id], m = metrics.get(node.id), card = cards && m.cardVisible, size = !m.detailVisible?0:card ? m.cardWidth * 0.13 : m.radius * 1.0;
        transform.position.set(p.x, p.y, p.z).addScaledVector(forward, card ? 0.05 : m.radius * 1.1);
        if (card) transform.position.addScaledVector(screenRight, -m.cardWidth * 0.37).addScaledVector(screenUp, m.cardHeight * 0.29);
        transform.quaternion.copy(camera.quaternion); transform.scale.set(size, size, 1); transform.updateMatrix(); mesh.setMatrixAt(index, transform.matrix);
        color.set(cards ? DEFAULT_COLORS[nodeKind(node)] : '#ffffff'); if (focus && !adjacent.has(node.id)) color.lerp(faded, 0.2); mesh.setColorAt(index, color);
      }); mesh.instanceMatrix.needsUpdate = true; mesh.instanceColor.needsUpdate = true;
    }
    pendingNodes.forEach((node, index) => { const p = positions[node.id], m = metrics.get(node.id), card = cards && m.cardVisible; transform.position.set(p.x, p.y, p.z).addScaledVector(screenRight, card ? m.cardWidth * 0.43 : m.radius * 0.85).addScaledVector(screenUp, card ? m.cardHeight * 0.36 : m.radius * 0.85).addScaledVector(forward, card ? 0.08 : m.radius * 0.4); transform.scale.setScalar(m.detailVisible?Math.max(0.7, 2.5 * m.worldPerPixel):0); transform.quaternion.identity(); transform.updateMatrix(); auditMarkers.setMatrixAt(index, transform.matrix); }); auditMarkers.instanceMatrix.needsUpdate = true;
    refreshEdges(positions, focus);
    const p = selected && positions[selected]; halo.visible = Boolean(p) && !cards;
    if (p) { halo.position.set(p.x, p.y, p.z); halo.scale.setScalar(metrics.get(selected).radius * 1.3); halo.quaternion.copy(camera.quaternion); }
    return adjacent;
  }
  function dispose() { group.traverse(object => { object.geometry?.dispose(); object.material?.dispose(); }); group.clear(); }
  return { group, get meshes() { return appearance === 'cards' ? cardMeshes : orbMeshes; }, edgeObjects, auditMarkers, metrics, setIcons, setAppearance(value) { appearance = value === 'cards' ? 'cards' : 'orbs'; }, update, dispose };
}
