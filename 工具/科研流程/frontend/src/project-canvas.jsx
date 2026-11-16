import React from 'react';
import {createRoot} from 'react-dom/client';
import {ReactFlowProvider} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import './project-canvas.css';
import knowledgeIcons from './generated-icons.json';
import {ProjectWorkspace} from './project-workspace.jsx';

window.ResearchCanvas={knowledgeIcons,mount(host,options){const root=createRoot(host);let handle=null;root.render(<ReactFlowProvider><ProjectWorkspace {...options} setHandle={value=>{handle=value;}}/></ReactFlowProvider>);return {refresh:()=>handle?.refresh(),newRecord:()=>handle?.newRecord(),unmount:()=>root.unmount()};}};
