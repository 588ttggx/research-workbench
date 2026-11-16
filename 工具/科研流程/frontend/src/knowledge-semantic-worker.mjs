import { semanticPositions } from './knowledge-semantic-model.mjs';
self.onmessage = async ({ data }) => {
  try { self.postMessage({ fingerprint: data.fingerprint, dimensions: data.dimensions, positions: await semanticPositions(data.index, data.dimensions) }); }
  catch (error) { self.postMessage({ fingerprint: data.fingerprint, error: String(error.message || error) }); }
};
