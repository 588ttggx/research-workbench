// Troika's default resolver retries a public CDN when a local lookup fails.
// For this offline application a missing glyph uses the local font's .notdef.
// The worker serializes this factory, so it deliberately has no outer closures.
export default function offlineFontResolverFactory() {
  return {
    getFontsForString(text, options) {
      return Promise.resolve({ fontUrls: [options.dataUrl], chars: new Uint8Array(text.length) });
    },
  };
}
