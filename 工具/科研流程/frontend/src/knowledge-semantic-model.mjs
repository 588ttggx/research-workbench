// The projection algorithm is upstream Apple Embedding Atlas, pinned locally.
import { createUMAPFromKNN } from '../node_modules/embedding-atlas/dist/umap.js';

export async function semanticPositions(index, dimensions = 2) {
  const { ids, k, indices, distances } = index;
  if (![2, 3].includes(dimensions) || !Array.isArray(ids) || indices.length !== ids.length * k || distances.length !== indices.length
      || indices.some(i => !Number.isInteger(i) || i < 0 || i >= ids.length)
      || distances.some(d => !Number.isFinite(d) || d < 0)) throw new Error('语义布局输入无效');
  if (ids.length < 3) return Object.fromEntries(ids.map((id, i) => [id, { x: i * 160, y: 0, z: 0 }]));
  const instance = await createUMAPFromKNN(ids.length, dimensions, Int32Array.from(indices), Float32Array.from(distances),
    { seed: 42, minDist: .25, spread: 1, nEpochs: ids.length > 1000 ? 200 : 300, gpu: false });
  try {
    await instance.run();
    const embedding = instance.embedding;
    if (![...embedding].every(Number.isFinite)) throw new Error('语义布局未完成');
    const axes = Array.from({ length: dimensions }, (_, axis) => ids.map((_, i) => embedding[i * dimensions + axis]));
    const bounds = axes.map(values => [Math.min(...values), Math.max(...values)]);
    const scale = Math.max(900, 36 * Math.sqrt(ids.length)) / Math.max(1, ...bounds.map(([a, b]) => b - a));
    return Object.fromEntries(ids.map((id, i) => [id, Object.fromEntries(['x', 'y', 'z'].map((axis, j) =>
      [axis, j < dimensions ? (embedding[i * dimensions + j] - (bounds[j][0] + bounds[j][1]) / 2) * scale : 0]))]));
  } finally { instance.destroy(); }
}
