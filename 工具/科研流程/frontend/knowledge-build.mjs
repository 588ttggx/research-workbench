import { build } from 'esbuild';
import { mkdir, copyFile, readFile, writeFile, access } from 'node:fs/promises';
import { resolve, dirname, join } from 'node:path';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { BookOpen, NotebookPen, Lightbulb, Flag, Layers, CircleHelp } from 'lucide-react';

const outdir = resolve('dist/knowledge-graph');
await mkdir(join(outdir, 'fonts'), { recursive: true });
// The same upstream node glyphs are available without loading the project canvas.
const nodeIcons={};
nodeIcons.pending='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(renderToStaticMarkup(React.createElement(CircleHelp,{size:12,color:'#b4945d',fill:'#fffdf7',strokeWidth:1.7})));
for(const [key,Icon] of Object.entries({paper:BookOpen,note:NotebookPen,concept:Lightbulb,claim:Flag,topic:Layers})){
 for(const [suffix,color] of [['','#ffffff'],['Dark','#52635f']])nodeIcons[key+suffix]='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(renderToStaticMarkup(React.createElement(Icon,{size:24,color,strokeWidth:1.6})));
}
await writeFile(join(outdir,'icons.json'),JSON.stringify(nodeIcons));
await writeFile(join(outdir,'icons.js'),'window.ResearchKnowledgeIcons='+JSON.stringify(nodeIcons)+';');
const result = await build({
  entryPoints: ['src/knowledge-3d.mjs', 'src/knowledge-3d-worker.mjs', 'src/knowledge-icons.tsx', 'src/knowledge-cache.mjs', 'src/knowledge-density.mjs'],
  jsx:'automatic', bundle: true, minify: true, format: 'iife', target: ['chrome120'],
  outdir, metafile: true, legalComments: 'linked', sourcemap: false,
  plugins: [{
    name: 'offline-graph-fonts',
    setup(builder) {
      builder.onResolve({ filter: /^troika-three-text$/ }, () => ({ path: resolve('node_modules/troika-three-text/src/index.js') }));
      builder.onResolve({ filter: /unicode-font-resolver-client\.factory\.js$/ }, () => ({ path: resolve('src/knowledge-offline-font-resolver.mjs') }));
    },
  }],
});
const semanticResult=await build({entryPoints:['src/knowledge-semantic-worker.mjs'],bundle:true,minify:true,format:'esm',target:['chrome120'],outdir,metafile:true,legalComments:'linked'});
Object.assign(result.metafile.inputs,semanticResult.metafile.inputs);
for (const file of ['NotoSansSC-Regular.otf', 'OFL.txt', 'SOURCE.txt']) await copyFile(resolve('assets/fonts', file), join(outdir, 'fonts', file));

const licenses = new Map();
for (const input of Object.keys(result.metafile.inputs).filter(path => path.includes('node_modules'))) {
  let folder = dirname(resolve(input));
  while (folder.includes('node_modules')) {
    try {
      const pkg = JSON.parse(await readFile(join(folder, 'package.json'), 'utf8'));
      if (!licenses.has(pkg.name)) {
        let license = '';
        for (const name of ['LICENSE', 'LICENSE.txt', 'LICENSE.md', 'LICENCE', 'LICENSE-MIT', 'license']) {
          try { license = await readFile(join(folder, name), 'utf8'); break; } catch { /* alternate upstream license name */ }
        }
        if (!license && pkg.name==='embedding-atlas') license=await readFile(resolve('assets/licenses/embedding-atlas-LICENSE.txt'),'utf8');
        if (!license) throw new Error(`Bundled package has no license file: ${pkg.name}`);
        licenses.set(pkg.name, `${pkg.name}@${pkg.version} (${pkg.license})\n${license}`);
      }
      break;
    } catch (error) {
      if (error.message.startsWith('Bundled package')) throw error;
      folder = dirname(folder);
    }
  }
}
await writeFile(join(outdir, 'THIRD_PARTY_LICENSES.txt'), [...licenses.entries()].sort().map(([, body]) => body).join('\n\n--------------------\n\n'));
await copyFile(resolve('src/vendor/lucide-animated/LICENSE.txt'),join(outdir,'LUCIDE_ANIMATED_LICENSE.txt'));
await copyFile(resolve('src/vendor/lucide-animated/SOURCE.txt'),join(outdir,'LUCIDE_ANIMATED_SOURCE.txt'));
await access(join(outdir, 'knowledge-3d.js'));
console.log(`Knowledge graph built: ${licenses.size} licensed packages, local worker and OFL font.`);

await copyFile(resolve('assets/licenses/embedding-atlas-SOURCE.txt'),join(outdir,'EMBEDDING_ATLAS_SOURCE.txt'));
