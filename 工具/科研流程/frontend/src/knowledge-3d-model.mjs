import { forceSimulation, forceManyBody, forceLink, forceCollide, forceX, forceY, forceZ } from 'd3-force-3d';

export function normalizeGraph({ nodes = [], edges = [] } = {}) {
  const ids = new Set();
  const copy = nodes.map(node => {
    const id = String(node.id ?? '');
    if (!id || ids.has(id)) throw new Error(`Invalid or duplicate graph node: ${id}`);
    ids.add(id);
    return { ...node, id };
  });
  const links = edges.map((edge, index) => {
    const from = String(edge.from ?? edge.source ?? ''), to = String(edge.to ?? edge.target ?? '');
    if (!ids.has(from) || !ids.has(to)) throw new Error(`Unknown graph edge endpoint: ${from} → ${to}`);
    return { ...edge, id: String(edge.id ?? `edge-${index}`), from, to };
  });
  return { nodes: copy, edges: links };
}

export function finitePoint(point) {
  return point && [point.x, point.y, point.z].every(Number.isFinite);
}

function hash(value) {
  let result = 2166136261;
  for (const char of String(value)) result = Math.imul(result ^ char.charCodeAt(0), 16777619);
  return result >>> 0;
}

export function buildLayout(input, iterations = 240) {
  const { nodes, edges } = normalizeGraph(input);
  nodes.sort((a, b) => a.id.localeCompare(b.id, 'en'));
  const groups = [...new Set(nodes.map(n => String(n.community ?? 'ungrouped')))].sort();
  const centers = new Map(groups.map((group, index) => {
    const z = 1 - 2 * (index + 0.5) / Math.max(1, groups.length);
    const theta = index * Math.PI * (3 - Math.sqrt(5));
    const radius = groups.length > 1 ? 260 + 48 * Math.sqrt(groups.length) : 0;
    return [group, { x: radius * Math.sqrt(1 - z * z) * Math.cos(theta), y: radius * Math.sqrt(1 - z * z) * Math.sin(theta), z: radius * z }];
  }));
  for (const node of nodes) {
    const saved = input.positions?.[node.id];
    const center = centers.get(String(node.community ?? 'ungrouped'));
    const seed = hash(node.id), theta = seed * 0.00031, z = (seed % 2001) / 1000 - 1;
    Object.assign(node, finitePoint(saved) ? saved : {
      x: center.x + Math.cos(theta) * Math.sqrt(1 - z * z) * 35,
      y: center.y + Math.sin(theta) * Math.sqrt(1 - z * z) * 35,
      z: center.z + z * 35,
    });
    if (saved?.fixed && finitePoint(saved)) Object.assign(node, { fx: saved.x, fy: saved.y, fz: saved.z });
  }
  const center = axis => node => centers.get(String(node.community ?? 'ungrouped'))[axis];
  const simulation = forceSimulation(nodes, 3).stop()
    .randomSource(() => 0.371)
    .force('charge', forceManyBody().strength(-650).distanceMax(1600))
    .force('link', forceLink(edges.map(e => ({ source: e.from, target: e.to }))).id(n => n.id).distance(240).strength(0.12))
    .force('collision', forceCollide(100).iterations(3))
    .force('x', forceX(center('x')).strength(0.045))
    .force('y', forceY(center('y')).strength(0.045))
    .force('z', forceZ(center('z')).strength(0.045));
  simulation.tick(Math.max(1, Math.min(600, iterations)));
  return Object.fromEntries(nodes.map(node => [node.id, { x: node.x, y: node.y, z: node.z, ...(input.positions?.[node.id]?.fixed ? { fixed: true } : {}) }]));
}

export function chooseLabels(candidates, { width, height, limit = 36, padding = 5 } = {}) {
  const chosen = [];
  for (const candidate of [...candidates].sort((a, b) => b.priority - a.priority || String(a.id).localeCompare(String(b.id)))) {
    if (chosen.length >= limit && candidate.priority < 800) continue;
    if (candidate.hidden) continue;
    const offsets = !candidate.card && candidate.priority >= 800 ? [0, -25, 25, -50, 50] : [0];
    for (const offset of offsets) {
      const item = { ...candidate, y: candidate.y + offset };
      if (!item.card && item.priority >= 800) {
        item.x = Math.min(width - item.width / 2 - 3, Math.max(item.width / 2 + 3, item.x));
        item.y = Math.min(height - item.height - 3, Math.max(3, item.y));
      }
      if (item.x - item.width / 2 < 2 || item.x + item.width / 2 > width - 2 || item.y < 2 || item.y + item.height > height - 2) continue;
      const overlaps = chosen.some(other => Math.abs(item.x - other.x) < (item.width + other.width) / 2 + padding && item.y < other.y + other.height + padding && item.y + item.height + padding > other.y);
      if (!overlaps) { chosen.push(item); break; }
    }
  }
  return chosen;
}
