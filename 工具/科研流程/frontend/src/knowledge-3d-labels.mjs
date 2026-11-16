import * as THREE from 'three';
import { Text, configureTextBuilder } from 'troika-three-text';
import { terminateWorker } from 'troika-worker-utils';
import { chooseLabels } from './knowledge-3d-model.mjs';
import { nodeRadius, nodePresentation } from './knowledge-3d-objects.mjs';

let configuredFont;
let activeManagers = 0, pendingTextRequests = 0;
function releaseIdleWorkers() {
  if (activeManagers || pendingTextRequests) return;
  terminateWorker('#default');
  for (let index = 0; index < 4; index += 1) terminateWorker(`TroikaTextSDFGenerator_JS_${index}`);
}
export function createLabels(scene, fontURL, invalidate) {
  activeManagers += 1;
  if (configuredFont !== fontURL) {
    configureTextBuilder({ defaultFontURL: fontURL, unicodeFontsURL: fontURL, useWorker: true });
    configuredFont = fontURL;
  }
  const labels = new Map(), projected = new THREE.Vector3(), world = new THREE.Vector3();
  function retire(text) {
    scene.remove(text); text.userData.retired = true;
    if (!text.userData.requests) {
      text.dispose(); text.userData.graphMaterial.dispose();
      text.removeEventListener('syncstart', text.userData.onStart);
      text.removeEventListener('synccomplete', text.userData.onComplete);
    }
  }
  function update(nodes, positions, camera, width, height, state, adjacent) {
    const candidates = [];
    const matches = new Set((state.searchMatches || []).slice(0,20));
    camera.updateMatrixWorld();
    for (const node of nodes) {
      if(state.metrics?.get(node.id)?.detailVisible===false)continue;
      const p = positions[node.id];
      projected.set(p.x, p.y, p.z).project(camera);
      if (projected.z < -1 || projected.z > 1 || Math.abs(projected.x) > 0.95 || Math.abs(projected.y) > 0.95) continue;
      world.set(p.x,p.y,p.z).applyMatrix4(camera.matrixWorldInverse); const depth = Math.max(camera.near, -world.z);
      const scale = height / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * depth);
      const priority = node.id === state.selected ? 1000 : node.id === state.hover ? 950 : matches.has(node.id) ? 850 : adjacent.has(node.id) ? 100 : node.group || node.kind === 'topic' || node.kind === 'community' ? 70 : Number(node.importance||0)*10000 + 1;
      const title = String(node.label || node.title || node.id).replace(/\s+/g, ' '), metric = state.metrics?.get(node.id);
      const short = priority<800 && title.length > 22 ? `${title.slice(0, 21)}…` : title;
      const textWidth = Math.min(245, [...short].reduce((sum, ch) => sum + (ch.charCodeAt(0) > 255 ? 12 : 7), 0));
      const card = state.appearance === 'cards';
      if (card && !metric?.cardVisible) continue;
      const cardWidth = metric ? metric.cardWidth * scale : 184, cardHeight = metric ? metric.cardHeight * scale : 92;
      if (card && cardWidth < 74) continue;
      candidates.push({ id: node.id, node, text: short, x: (projected.x + 1) * width / 2, y: (-projected.y + 1) * height / 2 + (card ? -cardHeight / 2 + 8 : (state.appearance === 'cards' && metric ? metric.cardHeight / 2 : metric?.radius || nodeRadius(node)) * scale + 6), z: projected.z, depth, width: card ? cardWidth - 16 : textWidth, height: card ? cardHeight - 16 : 17, priority, card, cardWidth, cardHeight });
    }
    candidates.sort((a,b)=>b.priority-a.priority);candidates.splice(Math.max(100,candidates.filter(c=>c.priority>=800).length));
    // Hide labels whose anchor is covered by a closer node in this projection.
    for (const item of candidates) {
      if (item.priority >= 800) continue;
      item.hidden = candidates.some(other => other.id !== item.id && other.depth < item.depth - 10 && Math.abs(other.x - item.x) < 10 && Math.abs(other.y - item.y) < 11);
    }
    const selected = chooseLabels(candidates, { width, height, limit: nodes.length > 300 ? 28 : 42 });
    const used = new Set();
    function renderText(key, item, content, configuration = {}) {
      used.add(key);
      let text = labels.get(key);
      if (!text) {
        text = new Text(); text.font = fontURL; text.unicodeFontsURL = fontURL;
        text.material = new THREE.MeshBasicMaterial({ transparent: true, depthTest: false, depthWrite: false });
        text.userData.graphMaterial = text.material.baseMaterial;
        text.userData.requests = 0;
        text.userData.onStart = () => { pendingTextRequests += 1; text.userData.requests += 1; };
        text.userData.onComplete = () => {
          pendingTextRequests -= 1; text.userData.requests -= 1;
          if (text.userData.retired) retire(text); else invalidate();
          releaseIdleWorkers();
        };
        text.addEventListener('syncstart', text.userData.onStart);
        text.addEventListener('synccomplete', text.userData.onComplete);
        text.fontSize = 1; text.lineHeight = 1.3; text.overflowWrap = 'break-word';
        text.anchorX = 'center'; text.anchorY = 'top'; text.textAlign = 'center';
        text.color = '#536457'; text.outlineColor = '#ffffff'; text.outlineWidth = '6%';
        text.renderOrder = 5;
        labels.set(key, text); scene.add(text);
      }
      const pixels = configuration.fontSize || 12.5, maxWidth = Math.max(24, Math.floor(((configuration.width || 245) + 0.001) / 8) * 8);
      const anchor = configuration.align === 'left' ? 'left' : 'center';
      if (text.text !== content || text.maxWidth !== maxWidth / pixels || text.anchorX !== anchor) {
        text.text = content; text.maxWidth = maxWidth / pixels; text.anchorX = anchor; text.textAlign = configuration.align || 'center'; text.sync();
      }
      text.visible = true;
      text.color = configuration.color || (item.priority >= 800 ? '#2f5d48' : '#59665c');
      text.outlineWidth = item.card ? 0 : '6%';
      text.clipRect = item.card ? [anchor === 'left' ? 0 : -maxWidth / pixels / 2, -((configuration.maxHeight || 32) / pixels), anchor === 'left' ? maxWidth / pixels : maxWidth / pixels / 2, 0.2] : null;
      const worldPerPixel = 2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * item.depth / height;
      text.scale.setScalar(pixels * worldPerPixel);
      world.set((configuration.x ?? item.x) / width * 2 - 1, -((configuration.y ?? item.y) / height) * 2 + 1, item.z).unproject(camera);
      text.position.copy(world).addScaledVector(camera.getWorldDirection(projected), -0.1); text.quaternion.copy(camera.quaternion);
    }
    for (const item of selected) {
      if (!item.card) { renderText(item.id, item, item.text); continue; }
      const presentation = nodePresentation(item.node), left = item.x - item.cardWidth / 2 + 10, roomy = item.cardWidth >= 130;
      if (roomy) renderText(`${item.id}:meta`, item, presentation.meta.length > 15 ? `${presentation.meta.slice(0, 14)}…` : presentation.meta, { x: left + 23, y: item.y + 3, width: item.cardWidth - 49, fontSize: 9, align: 'left', color: '#7b8a7e' });
      const fontSize = roomy ? 12 : 10, titleLimit = Math.max(6, Math.floor((item.cardWidth - 24) / fontSize) * 2);
      renderText(item.id, item, presentation.title.length > titleLimit ? `${presentation.title.slice(0, titleLimit - 1)}…` : presentation.title, { x: left, y: item.y + (roomy ? 25 : 17), width: item.cardWidth - 24, fontSize, align: 'left', color: '#344c40' });
      if (presentation.summary && item.cardHeight > 106) renderText(`${item.id}:summary`, item, presentation.summary.length > 16 ? `${presentation.summary.slice(0, 15)}…` : presentation.summary, { x: left, y: item.y + item.cardHeight - 31, width: item.cardWidth - 24, fontSize: 10, align: 'left', color: '#839086' });
    }
    for (const [id, text] of labels) if (!used.has(id)) { retire(text); labels.delete(id); }
  }
  function dispose() { for (const text of labels.values()) retire(text); labels.clear(); activeManagers -= 1; releaseIdleWorkers(); }
  return { update, dispose, stats: () => ({ visible: labels.size }) };
}

export function labelStats(){return {activeManagers,pendingTextRequests};}
