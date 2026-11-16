import { build } from 'esbuild';
import { writeFile } from 'node:fs/promises';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { BookOpen,NotebookPen,FileText,Layers,GitBranch,Compass,ChartNoAxesCombined } from 'lucide-react';
const icons={};
for(const [name,Icon] of Object.entries({paper:BookOpen,note:NotebookPen,report:FileText,topic:Layers,project:GitBranch,background:Compass,result:ChartNoAxesCombined})){
  icons[name]='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(renderToStaticMarkup(React.createElement(Icon,{size:24,color:'#ffffff',strokeWidth:1.5})));
}
await writeFile('src/generated-icons.json',JSON.stringify(icons));
await build({entryPoints:['src/project-canvas.jsx'],bundle:true,minify:true,format:'iife',target:['chrome120'],
  outfile:'dist/project-canvas.js',define:{'process.env.NODE_ENV':'"production"'},legalComments:'linked',sourcemap:false});
