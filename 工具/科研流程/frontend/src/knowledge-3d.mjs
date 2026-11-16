import * as THREE from 'three';
import CameraControls from 'camera-controls';
import { normalizeGraph, finitePoint } from './knowledge-3d-model.mjs';
import { createGraphObjects } from './knowledge-3d-objects.mjs';
import { createLabels,labelStats } from './knowledge-3d-labels.mjs';

CameraControls.install({ THREE });
const assetBase = new URL('./', document.currentScript?.src || new URL('/vendor/knowledge-graph/knowledge-3d.js', location.href));

export function mount(container, initial = {}) {
  let options = { ...initial }, data = { nodes: [], edges: [] }, positions = Object.create(null);
  let transientPins=new Set();let graph, worker, revision = 0, topology = '', inputPositionSignature = '', raf = 0, lastFrame = 0;
  let frames=0;let destroyed = false, paused = false, inViewport = true, width = 1, height = 1, motion, dragging, hover = null, firstLayout = true, previewTimer;
  const iconTextures = {}, iconRequest = new AbortController();
  const cleanup = [];
  const scene = new THREE.Scene(); scene.background = new THREE.Color('#ffffff');
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 20000); camera.position.set(260, 170, 320);
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2)); renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.domElement.style.cssText = 'display:block;width:100%;height:100%;touch-action:none;outline:none';
  renderer.domElement.setAttribute('aria-label', '三维知识关系图，拖拽旋转，滚轮缩放，单击查看关系，双击打开知识，右键或长按查看关系，Enter 打开当前对象');
  renderer.domElement.tabIndex = 0;
  container.append(renderer.domElement);
  const controls = new CameraControls(camera, renderer.domElement);
  controls.smoothTime = 0.32; controls.draggingSmoothTime = 0.12; controls.minDistance = 12; controls.maxDistance = 8000;
  controls.dollyToCursor = true;
  scene.add(new THREE.HemisphereLight('#ffffff', '#dbe2d2', 2.0));
  const light = new THREE.DirectionalLight('#fff8ec', 1.9); light.position.set(100, 200, 300); scene.add(light);
  const labels = createLabels(scene, new URL('fonts/NotoSansSC-Regular.otf', assetBase).href, invalidate);
  const raycaster = new THREE.Raycaster(), pointer = new THREE.Vector2(), dragPlane = new THREE.Plane(), hit = new THREE.Vector3();
  const tooltip = document.createElement('div');
  tooltip.className = 'knowledge-3d-tooltip'; tooltip.hidden = true;
  tooltip.style.cssText = 'position:absolute;z-index:8;max-width:300px;padding:8px 11px;background:#fffffff5;color:#3f594c;border:1px solid #c9d7c8;border-radius:8px;box-shadow:0 5px 20px #27364b15;font:12px/1.5 system-ui;pointer-events:auto;white-space:normal';
  const tooltipTitle = document.createElement('div'), previewButton = document.createElement('button');
  previewButton.type = 'button'; previewButton.textContent = '查看关系'; previewButton.style.cssText = 'font:inherit;border:1px solid #d6dfd4;border-radius:5px;background:#f5f8f2;color:#42634f;padding:3px 9px;margin-top:6px;cursor:pointer';
  previewButton.addEventListener('click', () => { if (hover) { options.selected = hover; options.onSelect?.(hover); invalidate(); } });
  tooltip.append(tooltipTitle, previewButton);
  if (getComputedStyle(container).position === 'static') { const old = container.style.position; container.style.position = 'relative'; cleanup.push(() => { container.style.position = old; }); }
  container.append(tooltip);

  function fail(error) { if (!destroyed) options.onError?.(error instanceof Error ? error : new Error(String(error))); }
  function active() { return !destroyed && !paused && inViewport && !document.hidden; }
  function invalidate() { if (active() && !raf) raf = requestAnimationFrame(frame); }
  function emitPositions() { options.onPositions?.(Object.fromEntries(data.nodes.map(n => [n.id, { ...positions[n.id] }]))); }
  function duration(value, fallback = 450) { return options.reducedMotion || matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : Number.isFinite(value) ? value : fallback; }

  function frame(now) {
    raf = 0;
    if (!active()) return;
    const delta = lastFrame ? Math.min((now - lastFrame) / 1000, 0.08) : 1 / 60; lastFrame = now;
    const cameraMoving = controls.update(delta);
    if (motion) {
      const progress = Math.min(1, Math.max(0, (now - motion.started) / motion.duration));
      const eased = 1 - (1 - progress) ** 3;
      for (const node of data.nodes) {
        const from = motion.from[node.id], to = motion.to[node.id];
        positions[node.id] = { x: from.x + (to.x - from.x) * eased, y: from.y + (to.y - from.y) * eased, z: from.z + (to.z - from.z) * eased, ...(to.fixed ? { fixed: true } : {}) };
      }
      if (progress === 1) { const emit = motion.emit; motion = null; if (emit) emitPositions(); }
    }
    if (graph) {
      const adjacent = graph.update(positions, options.selected, hover, camera, height);
      labels.update(data.nodes, positions, camera, width, height, { ...options, hover, metrics: graph.metrics }, adjacent);
    }
    renderer.render(scene, camera);frames++;
    if (cameraMoving || motion) invalidate();
  }

  function movePositions(target, shouldEmit) {
    const ms = duration(undefined, 450);
    if (ms && active()) {
      motion = { from: Object.fromEntries(data.nodes.map(n => [n.id, { ...positions[n.id] }])), to: target, duration: ms, started: performance.now(), emit: shouldEmit };
    } else { positions = target; motion = null; if (shouldEmit) emitPositions(); }
    invalidate();
  }

  function layout(held=new Set()) {
    transientPins=new Set([...held].filter(id=>positions[id]&&!positions[id].fixed));
    revision += 1;
    const layoutRevision = revision;
    if (!worker) {
      worker = new Worker(new URL('knowledge-3d-worker.js', assetBase));
      worker.onmessage = ({ data: result }) => {
        if (destroyed || result.revision !== revision) return;
        if (result.error) { fail(result.error); return; }
        // A drag after the layout request is authoritative over the worker result.
        for (const node of data.nodes) if (positions[node.id]?.fixed) result.positions[node.id] = { ...positions[node.id] };
        for(const node of data.nodes){if(transientPins.has(node.id)&&!positions[node.id]?.fixed)delete result.positions[node.id].fixed;result.positions[node.id].settled=true;result.positions[node.id].cardSpacing=true;}
        movePositions(result.positions, true);
        if (firstLayout) { firstLayout = false; fit({ positions: result.positions, duration: duration(undefined, 450) }); }
      };
      worker.onerror = event => fail(event.message || '三维布局计算失败');
    }
    const seeded=Object.fromEntries(Object.entries(positions).map(([id,p])=>[id,transientPins.has(id)?{...p,fixed:true}:p]));
    worker.postMessage({ ...data, appearance: options.appearance, positions:seeded, revision: layoutRevision, iterations: data.nodes.length > 1000 ? 170 : 240 });
  }

  function update(next = {}) {
    if (destroyed) return;
    const merged = { ...options, ...next };
    let normalized;
    try { normalized = normalizeGraph(merged); } catch (error) { fail(error); return; }
    options = merged;
    const nextTopology = JSON.stringify([normalized.nodes.map(n => [n.id, n.community, n.kind, n.color, n.label,n.status,n.suggested]), normalized.edges.map(e => [e.id, e.from, e.to, e.suggested, e.status])]);
    const changed = nextTopology !== topology;
    const previousIds=new Set(data.nodes.map(n=>n.id));
    const added=normalized.nodes.filter(n=>!previousIds.has(n.id));
    if(changed&&normalized.nodes.length&&added.length===normalized.nodes.length)firstLayout=true;
    data = normalized;
    if (changed) {
      revision += 1;
      topology = nextTopology;
      if (graph) { scene.remove(graph.group); graph.dispose(); }
      graph = createGraphObjects(data.nodes, data.edges, { appearance: options.appearance, iconTextures }); scene.add(graph.group);
    }
    graph?.setAppearance(options.appearance);
    const incoming = options.positions || {};
    const signature = JSON.stringify(data.nodes.map(n => [n.id, incoming[n.id]?.x, incoming[n.id]?.y, incoming[n.id]?.z, incoming[n.id]?.fixed]));
    const newPositions = signature !== inputPositionSignature;
    inputPositionSignature = signature;
    let needsLayout = false;
    const nextPositions = Object.create(null);
    data.nodes.forEach((node, index) => {
      const value = newPositions && finitePoint(incoming[node.id]) ? incoming[node.id] : positions[node.id];
      nextPositions[node.id] = finitePoint(value) ? { ...value } : { x: Math.cos(index * 2.39996) * Math.sqrt(index + 1) * 12, y: Math.sin(index * 2.39996) * Math.sqrt(index + 1) * 12, z: 0 };
      if (!finitePoint(value)) needsLayout = true;
    });
    // A pure appearance/selection update must not interrupt a running layout.
    if (changed || newPositions) {
      const interruptedLayout = !!motion;if(newPositions&&!changed&&options.layoutStrategy==='semantic'&&!firstLayout)movePositions(nextPositions,false);else{positions=nextPositions;motion=null;}
      if (interruptedLayout) emitPositions();
    }
    if (changed || newPositions) {
      const zValues = Object.values(positions).map(p => p.z);
      const planar = data.nodes.length > 2 && Math.max(...zValues) - Math.min(...zValues) < 0.001 && !Object.values(positions).every(p => p.fixed);
      if (options.layoutStrategy==='semantic') { if(firstLayout){firstLayout=false;fit({duration:0});} }
      else if (!firstLayout&&added.length)layout(previousIds);
      else if (needsLayout || planar || firstLayout && data.nodes.some(n=>!positions[n.id]?.fixed&&(!positions[n.id]?.settled||!positions[n.id]?.cardSpacing))) layout();
      else if (firstLayout && data.nodes.length) { firstLayout = false; fit({ duration: 0 }); }
    }
    invalidate();
  }

  function bounds(map = positions, ids) {
    const points = data.nodes.filter(n => !ids || ids.includes(n.id)).map(n => map[n.id]).filter(finitePoint);
    const box = new THREE.Box3(); for (const point of points) box.expandByPoint(new THREE.Vector3(point.x, point.y, point.z));
    if (!points.length) box.set(new THREE.Vector3(-50, -50, -50), new THREE.Vector3(50, 50, 50));
    const sphere = box.getBoundingSphere(new THREE.Sphere()); sphere.radius = Math.max(sphere.radius + 16, 30); return sphere;
  }
  function stopCamera() {
    // CameraControls.stop() snaps to its end pose; capture the actual pose first.
    const point = controls.getPosition(new THREE.Vector3(), false), target = controls.getTarget(new THREE.Vector3(), false);
    controls.setLookAt(point.x, point.y, point.z, target.x, target.y, target.z, false);
    controls.update(0); lastFrame = 0;
  }
  function fit(settings = {}) {
    if (destroyed) return;
    if (Array.isArray(settings)) settings = { ids: settings };
    stopCamera();
    controls.fitToSphere(bounds(settings.positions || positions, settings.ids), duration(settings.duration) > 0);
    invalidate();
  }
  function focus(id, settings = {}) {
    const point = positions[id]; if (destroyed || !point) return;
    stopCamera();
    const neighbors = new Set([id]); for (const edge of data.edges) if (edge.from === id || edge.to === id) { neighbors.add(edge.from); neighbors.add(edge.to); }
    const radius = Math.min(180, Math.max(36, bounds(positions, [...neighbors]).radius * 0.6));
    const target = new THREE.Vector3(point.x, point.y, point.z);
    const offset = camera.position.clone().sub(controls.getTarget(new THREE.Vector3(), false)).normalize().multiplyScalar(radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)));
    const destination = target.clone().add(offset);
    controls.setLookAt(destination.x, destination.y, destination.z, target.x, target.y, target.z, duration(settings.duration) > 0);
    invalidate();
  }
  function getView() { return { version: 1, position: controls.getPosition(new THREE.Vector3(), false).toArray(), target: controls.getTarget(new THREE.Vector3(), false).toArray(), zoom: camera.zoom }; }
  function setView(view, settings = {}) {
    if (destroyed || !view || !Array.isArray(view.position) || !Array.isArray(view.target) || ![...view.position, ...view.target].every(Number.isFinite)) return;
    stopCamera(); controls.setLookAt(...view.position, ...view.target, duration(settings.duration, 0) > 0); invalidate();
  }

  function pointerCoordinates(event) {
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }
  function pick(event) {
    pointerCoordinates(event);
    const intersection = graph && raycaster.intersectObjects(graph.meshes, false).find(hit=>graph.metrics.get(hit.object.userData.nodes[hit.instanceId].id)?.detailVisible!==false);
    return intersection ? intersection.object.userData.nodes[intersection.instanceId] : null;
  }
  let emptyPointer, lastDrag = 0;
  raycaster.params.Line.threshold=2.2;
  function pickEdge(event){
    pointerCoordinates(event);
    const hit=graph&&raycaster.intersectObjects(graph.edgeObjects,false)[0];
    return hit ? hit.object.userData.segmentRows[Math.floor(hit.index / 2)] : null;
  }
  function pointerDown(event) {
    options.onInteract?.();
    stopCamera();
    if (event.button !== 0) { invalidate(); return; }
    const node = pick(event);
    if (!node) { emptyPointer={x:event.clientX,y:event.clientY};invalidate(); return; }
    controls.enabled = false;
    const p = positions[node.id];
    dragPlane.setFromNormalAndCoplanarPoint(camera.getWorldDirection(new THREE.Vector3()), new THREE.Vector3(p.x, p.y, p.z));
    raycaster.ray.intersectPlane(dragPlane, hit);
    dragging = { id: node.id, x: event.clientX, y: event.clientY, offset: new THREE.Vector3(p.x, p.y, p.z).sub(hit), moved: false, previewed: false };
    if (event.pointerType === 'touch') previewTimer = setTimeout(() => { if (dragging && !dragging.moved) { dragging.previewed = true; options.selected = dragging.id; options.onSelect?.(dragging.id); invalidate(); } }, 500);
    motion = null; renderer.domElement.setPointerCapture(event.pointerId); event.stopPropagation();
  }
  function pointerMove(event) {
    const xy = pointerCoordinates(event);
    if (dragging) {
      if (Math.hypot(event.clientX - dragging.x, event.clientY - dragging.y) > 4) { dragging.moved = true; clearTimeout(previewTimer); }
      if (dragging.moved && raycaster.ray.intersectPlane(dragPlane, hit)) {
        hit.add(dragging.offset); positions[dragging.id] = { x: hit.x, y: hit.y, z: hit.z, fixed: true }; invalidate();
      }
      return;
    }
    const node = pick(event), id = node?.id || null;
    if (hover !== id) { hover = id; options.onHover?.(id); invalidate(); }
    tooltip.hidden = !node;
    if (node) { tooltipTitle.textContent = String(node.label || node.title || node.id); tooltip.style.left = `${Math.min(xy.x + 14, Math.max(4, width - 310))}px`; tooltip.style.top = `${Math.min(xy.y + 16, Math.max(4, height - 90))}px`; }
    renderer.domElement.style.cursor = node ? 'grab' : 'default';
  }
  function pointerUp(event) {
    clearTimeout(previewTimer);
    if (!dragging) {if(emptyPointer&&Math.hypot(event.clientX-emptyPointer.x,event.clientY-emptyPointer.y)<5){const edge=pickEdge(event);if(edge)options.onEdgeSelect?.(edge.id);}emptyPointer=null;return;}
    const was = dragging; dragging = null; controls.enabled = true;
    if (renderer.domElement.hasPointerCapture(event.pointerId)) renderer.domElement.releasePointerCapture(event.pointerId);
    if (was.moved) { lastDrag = performance.now(); emitPositions(); } else if (!was.previewed && event.type !== 'pointercancel') { options.selected = was.id; tooltip.hidden = true; options.onSelect?.(was.id); }
    invalidate();
  }
  function listen(target, name, listener, configuration) { target.addEventListener(name, listener, configuration); cleanup.push(() => target.removeEventListener(name, listener, configuration)); }
  listen(renderer.domElement, 'pointerdown', pointerDown, true);
  listen(renderer.domElement, 'pointermove', pointerMove);
  listen(renderer.domElement, 'pointerup', pointerUp);
  listen(renderer.domElement, 'pointercancel', pointerUp);
  listen(renderer.domElement, 'dblclick', event => { if (performance.now() - lastDrag < 300) return; const node = pick(event); if (node) { event.preventDefault(); options.onOpen?.(node.id); } });
  listen(renderer.domElement, 'pointerleave', event => { if (!dragging && !tooltip.contains(event.relatedTarget)) { hover = null; tooltip.hidden = true; invalidate(); } });
  listen(tooltip, 'pointerleave', event => { if (event.relatedTarget !== renderer.domElement) { hover = null; tooltip.hidden = true; invalidate(); } });
  listen(renderer.domElement, 'contextmenu', event => { const node = pick(event); if (node) { event.preventDefault(); options.selected = node.id; options.onSelect?.(node.id); invalidate(); } });
  listen(renderer.domElement, 'wheel', () => { options.onInteract?.();stopCamera(); invalidate(); }, { capture: true, passive: true });
  listen(renderer.domElement, 'keydown', event => { options.onInteract?.();if (event.key === 'Escape') { options.selected = null; options.onSelect?.(null); invalidate(); } else if (event.key === 'Home') fit(); else if (event.key === 'Enter' && (hover || options.selected)) { event.preventDefault(); options.onOpen?.(hover || options.selected); } });
  listen(renderer.domElement, 'webglcontextlost', event => { event.preventDefault(); pause(); fail('图形上下文已中断，请重新打开三维视图'); });
  controls.addEventListener('control', invalidate); cleanup.push(() => controls.removeEventListener('control', invalidate));
  listen(document, 'visibilitychange', () => { if (document.hidden && raf) { cancelAnimationFrame(raf); raf = 0; } else { lastFrame = 0; invalidate(); } });
  const resize = new ResizeObserver(() => {
    width = Math.max(1, container.clientWidth); height = Math.max(1, container.clientHeight);
    renderer.setSize(width, height, false); camera.aspect = width / height; camera.updateProjectionMatrix(); invalidate();
  }); resize.observe(container); cleanup.push(() => resize.disconnect());
  const visible = new IntersectionObserver(entries => { inViewport = entries[0]?.isIntersecting !== false; if (!inViewport && raf) { cancelAnimationFrame(raf); raf = 0; } else { lastFrame = 0; invalidate(); } });
  visible.observe(container); cleanup.push(() => visible.disconnect());

  function pause() { paused = true; if (raf) cancelAnimationFrame(raf); raf = 0; tooltip.hidden = true; }
  function resume() { if (!destroyed) { paused = false; lastFrame = 0; invalidate(); } }
  function destroy() {
    if (destroyed) return; destroyed = true; revision += 1;
    if (raf) cancelAnimationFrame(raf); raf = 0; clearTimeout(previewTimer); iconRequest.abort(); worker?.terminate(); worker = null;
    for (const fn of cleanup.reverse()) fn();
    controls.dispose(); labels.dispose(); graph?.dispose(); for (const texture of Object.values(iconTextures)) texture.dispose(); scene.clear();
    renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove(); tooltip.remove();
  }
  function exportImage() { if (destroyed) return null; controls.update(0); renderer.render(scene, camera); return renderer.domElement.toDataURL('image/png'); }
  async function loadIcons() {
    try {
      const definitions = options.icons || window.ResearchKnowledgeIcons || await fetch(new URL('icons.json', assetBase), { signal: iconRequest.signal }).then(response => { if (!response.ok) throw new Error('本地图标暂时不可用'); return response.json(); });
      if (destroyed) return;
      const loader = new THREE.TextureLoader();
      for (const kind of ['paper', 'note', 'concept', 'claim', 'topic']) if (definitions[kind]) {
        let source = definitions[kind];
        if (source.startsWith('data:image/svg+xml') && !source.includes(';base64,')) {
          const svg = decodeURIComponent(source.slice(source.indexOf(',') + 1)).replace(/stroke=(["'])(?!none\1)[^"']*\1/g, 'stroke="#ffffff"');
          source = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
        }
        const texture = loader.load(source, () => { if (!destroyed) invalidate(); }); texture.colorSpace = THREE.SRGBColorSpace; iconTextures[kind] = texture;
      }
      graph?.setIcons(iconTextures); invalidate();
    } catch (error) { if (!destroyed && error.name !== 'AbortError') options.onIconError?.(error); }
  }
  update(initial);
  loadIcons();
  return {rearrange:()=>layout(),stats:()=>({frames,worker:!!worker,pendingFrame:!!raf,resources:renderer.info.memory,calls:renderer.info.render.calls,appearance:options.appearance==='cards'?'cards':'orbs',visibleCards:[...(graph?.metrics?.values()||[])].filter(m=>m.cardVisible).length,labels:labels.stats().visible,iconTextures:Object.keys(iconTextures).length}),update, focus, fit, getView, setView, exportImage, destroy, pause, resume, stop:stopCamera, zoom(factor){stopCamera();const distance=controls.getPosition(new THREE.Vector3(),false).distanceTo(controls.getTarget(new THREE.Vector3(),false));controls.dollyTo(distance/factor,duration(undefined)>0);invalidate();} };
}

window.ResearchGraph3D = { mount, labelStats, version: 1 };
