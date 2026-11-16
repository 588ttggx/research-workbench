import React from 'react';
import { createRoot } from 'react-dom/client';
import { MotionConfig } from 'motion/react';
import { ZoomIn, ZoomOut, PanelRightClose, BookOpen, Network, Ellipsis } from 'lucide-react';
import { SearchIcon } from './vendor/lucide-animated/search';
import { SettingsIcon } from './vendor/lucide-animated/settings';
import { DownloadIcon } from './vendor/lucide-animated/download';
import { ExpandIcon } from './vendor/lucide-animated/expand';
import { LayoutGridIcon } from './vendor/lucide-animated/layout-grid';
import { PlayIcon } from './vendor/lucide-animated/play';
import { PauseIcon } from './vendor/lucide-animated/pause';
import { RotateCWIcon } from './vendor/lucide-animated/rotate-cw';
import { LayersIcon } from './vendor/lucide-animated/layers';
import { BoxesIcon } from './vendor/lucide-animated/boxes';

// Original Lucide Animated components retain their upstream geometry and motion.
const icons={search:SearchIcon,settings:SettingsIcon,download:DownloadIcon,expand:ExpandIcon,
 overview:LayoutGridIcon,play:PlayIcon,pause:PauseIcon,refresh:RotateCWIcon,layers:LayersIcon,
 boxes:BoxesIcon,zoomIn:ZoomIn,zoomOut:ZoomOut,panel:PanelRightClose,book:BookOpen,network:Network,more:Ellipsis};
let activeRoots=0;
function create(){
 const entries=new Map(),reduced=matchMedia('(prefers-reduced-motion: reduce)');
 function decorate(button,name){
  let entry=entries.get(button);
  if(!entry){
   const label=document.createElement('span');label.className='kg-action-label';
   for(const child of [...button.childNodes]){if(child.nodeType===1&&(child as Element).classList.contains('icon'))child.remove();else label.append(child);}
   button.append(label);button.setAttribute('aria-label',label.textContent||'');button.title=label.textContent||'';
   const slot=document.createElement('span');slot.className='kg-action-icon';slot.setAttribute('aria-hidden','true');button.prepend(slot);
   entry={root:createRoot(slot),name:'',handle:null,stop:null,start:null};activeRoots++;
   entry.start=()=>{if(!reduced.matches)entry.handle?.startAnimation?.();};
   entry.stop=()=>entry.handle?.stopAnimation?.();
   button.addEventListener('mouseenter',entry.start);button.addEventListener('focus',entry.start);
   button.addEventListener('mouseleave',entry.stop);button.addEventListener('blur',entry.stop);
   entries.set(button,entry);
  }
  if(entry.name===name)return;entry.name=name;const Icon=icons[name]||LayersIcon;
  entry.root.render(<MotionConfig reducedMotion="user"><Icon size={18} ref={handle=>{entry.handle=handle;}} /></MotionConfig>);
 }
 function stop(){for(const entry of entries.values())entry.stop();}
 reduced.addEventListener('change',stop);
 return {decorate,destroy(){reduced.removeEventListener('change',stop);for(const [button,entry] of entries){button.removeEventListener('mouseenter',entry.start);button.removeEventListener('focus',entry.start);button.removeEventListener('mouseleave',entry.stop);button.removeEventListener('blur',entry.stop);entry.root.unmount();activeRoots--;}entries.clear();}};
}
window.ResearchGraphIcons={create,stats:()=>({activeRoots})};
