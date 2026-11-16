import test from 'node:test';
import assert from 'node:assert/strict';
import { semanticPositions } from './knowledge-semantic-model.mjs';
test('upstream UMAP supplies finite real 2D and 3D coordinates for the same IDs', async () => {
  const n = 40, k = 4, input = { ids: Array.from({ length: n }, (_, i) => 'K' + i), k,
    indices: Array.from({ length: n * k }, (_, i) => (Math.floor(i / k) + i % k) % n),
    distances: Array.from({ length: n * k }, (_, i) => i % k / 4) };
  for (const dimensions of [2, 3]) {
    const positions = await semanticPositions(input, dimensions);
    assert.deepEqual(Object.keys(positions), input.ids);
    assert.ok(Object.values(positions).every(p => Object.values(p).every(Number.isFinite)));
    assert.ok(dimensions === 2 ? Object.values(positions).every(p => p.z === 0) : Object.values(positions).some(p => p.z !== 0));
  }
});
test('invalid neighborhood indices fail before WASM runs', async () => {
  await assert.rejects(semanticPositions({ ids: ['a'], k: 1, indices: [2], distances: [0] }), /输入无效/);
});
