# Open Notebook frontend source

Upstream: [Open Notebook v1.15.0](https://github.com/lfnovo/open-notebook/tree/v1.15.0/frontend), MIT. The adjacent frontend/LICENSE retains the upstream copyright and license.

This source corresponds to the standalone frontend bundled in runtime-open-notebook.zip. Only package.json and package-lock.json were changed for the reviewed Next.js, Zod and follow-redirects pins. The source manifest records their exact versions, all source file hashes and the matching binary ZIP hash.

Build inside frontend with npm ci --ignore-scripts, then npm run build. The release uses the generated .next/standalone server and copies .next/static and public beside it.
