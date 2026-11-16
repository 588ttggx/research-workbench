import { buildLayout } from './knowledge-3d-model.mjs';

self.onmessage = ({ data }) => {
  try {
    self.postMessage({ revision: data.revision, positions: buildLayout(data, data.iterations) });
  } catch (error) {
    self.postMessage({ revision: data.revision, error: String(error.message || error) });
  }
};
