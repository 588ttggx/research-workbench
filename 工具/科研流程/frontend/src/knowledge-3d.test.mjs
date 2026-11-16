import test from 'node:test';
import assert from 'node:assert/strict';
import { buildLayout, chooseLabels, normalizeGraph } from './knowledge-3d-model.mjs';

const nodes = Array.from({ length: 18 }, (_, i) => ({ id: `n${i}`, label: `太赫兹资料${i}`, community: Math.floor(i / 6) }));
const edges = nodes.slice(1).map((node, i) => ({ id: `e${i}`, from: nodes[i].id, to: node.id }));

test('a planar input becomes a reproducible spatial layout without changing fixed positions', () => {
  const input = { nodes, edges, positions: { n0: { x: 12, y: 25, z: 9, fixed: true } } };
  const a = buildLayout(input, 180), b = buildLayout(input, 180);
  assert.deepEqual(a, b);
  assert.deepEqual(a.n0, input.positions.n0);
  assert.equal(Object.keys(a).length, nodes.length);
  assert.ok(Object.values(a).every(p => [p.x, p.y, p.z].every(Number.isFinite)));
  assert.ok(Math.max(...Object.values(a).map(p => p.z)) - Math.min(...Object.values(a).map(p => p.z)) > 15);
});

test('saved spatial coordinates and isolated nodes survive graph updates', () => {
  const positions = { a: { x: 1, y: 2, z: 3, fixed: true }, isolated: { x: -8, y: 6, z: -4, fixed: true } };
  const result = buildLayout({ nodes: [{ id: 'a' }, { id: 'isolated' }], edges: [], positions }, 30);
  assert.deepEqual(result, positions);
});

test('labels avoid screen overlap while selected and hovered objects retain priority', () => {
  const labels = chooseLabels([
    { id: 'ordinary', x: 50, y: 50, width: 80, height: 20, priority: 1 },
    { id: 'selected', x: 55, y: 50, width: 80, height: 20, priority: 100 },
    { id: 'other', x: 180, y: 50, width: 80, height: 20, priority: 1 },
  ], { width: 300, height: 160 });
  assert.deepEqual(labels.map(x => x.id), ['selected', 'other']);
});

test('normalization reports duplicate identities and invalid edges without mutating source objects', () => {
  assert.throws(() => normalizeGraph({ nodes: [{ id: 'a' }, { id: 'a' }], edges: [] }), /duplicate/i);
  assert.throws(() => normalizeGraph({ nodes: [{ id: 'a' }], edges: [{ from: 'a', to: 'missing' }] }), /endpoint/i);
  const input = { nodes: [{ id: 'a', status: 'candidate' }], edges: [] };
  const output = normalizeGraph(input);
  assert.equal(input.nodes[0].x, undefined);
  assert.equal(output.nodes[0].status, 'candidate');
});

test('pending review uses a separate marker rather than replacing theme color', async()=>{
 const THREE=await import('three');const {createGraphObjects}=await import('./knowledge-3d-objects.mjs');
 const nodes=[{id:'AI',suggested:true,color:'#60c8ff'},{id:'REVIEWED',status:'VERIFIED',color:'#60c8ff'}];
 const objects=createGraphObjects(nodes,[]),camera=new THREE.PerspectiveCamera();camera.position.set(0,0,100);
 objects.update({AI:{x:0,y:0,z:0},REVIEWED:{x:20,y:0,z:0}},null,null,camera);
 assert.equal(objects.auditMarkers.count,1);assert.equal(nodes[0].color,nodes[1].color);objects.dispose();
});

test('semantic node types preserve distinct local icons and source-aware card descriptions',async()=>{
 const {nodeKind,nodePresentation}=await import('./knowledge-3d-objects.mjs');
 assert.equal(nodeKind({record_kind:'ExtractedConcept'}),'concept');
 assert.equal(nodeKind({kind:'ExtractedClaim'}),'claim');
 assert.equal(nodeKind({kind:'论文'}),'paper');
 const item=nodePresentation({id:'c',kind:'ExtractedClaim',label:'条件下的结论',summary:'原文限定的完整摘要',sources:[{id:'a'},{id:'b'}],suggested:true});
  assert.equal(item.title,'条件下的结论');assert.match(item.meta,/2.*来源/);assert.match(item.meta,/AI 提取/);assert.equal(item.summary,'原文限定的完整摘要');
});

test('curved edge buffers remain stable during camera movement and map every segment to its relation',async()=>{
 const THREE=await import('three');const {createGraphObjects}=await import('./knowledge-3d-objects.mjs');
 const nodes=[{id:'a'},{id:'b'}],edges=[{id:'ab',from:'a',to:'b'},{id:'ba',from:'b',to:'a'},{id:'self',from:'a',to:'a'}];
 const objects=createGraphObjects(nodes,edges),camera=new THREE.PerspectiveCamera();camera.position.set(0,0,100);
 const positions={a:{x:0,y:0,z:0},b:{x:40,y:0,z:0}};objects.update(positions,null,null,camera);
 const line=objects.edgeObjects[0],attribute=line.geometry.attributes.position,buffer=Array.from(attribute.array),version=attribute.version;
 assert.ok(buffer.some((n,i)=>i%3===1&&Math.abs(n)>0.1),'curves have genuine lateral displacement');
 assert.ok(line.userData.segmentRows.length>edges.length,'each curved segment retains its original relation');
 assert.ok(line.userData.segmentRows.every(e=>edges.includes(e)));
 camera.position.set(80,25,100);objects.update(positions,null,null,camera);
 assert.equal(attribute.version,version,'camera movement must not rebuild edge positions');assert.deepEqual(Array.from(attribute.array),buffer);
 positions.b.x=45;objects.update(positions,null,null,camera);assert.ok(attribute.version>version);objects.dispose();
});

test('orb and card switching keeps the coordinate table and camera-facing card instances',async()=>{
 const THREE=await import('three');const {createGraphObjects}=await import('./knowledge-3d-objects.mjs');
 const nodes=[{id:'a',kind:'paper'}],objects=createGraphObjects(nodes,[]),camera=new THREE.PerspectiveCamera();camera.position.set(35,25,100);camera.lookAt(0,0,0);camera.updateMatrixWorld();
 const positions={a:{x:3,y:7,z:11}},original=structuredClone(positions);objects.update(positions,'a',null,camera);
 const orb=objects.meshes[0];objects.setAppearance('cards');objects.update(positions,'a',null,camera);
 const card=objects.meshes[0],matrix=new THREE.Matrix4(),position=new THREE.Vector3(),quaternion=new THREE.Quaternion(),scale=new THREE.Vector3();card.getMatrixAt(0,matrix);matrix.decompose(position,quaternion,scale);
 assert.ok(!objects.meshes.includes(orb),'card appearance retains card hit targets at every detail level');assert.notEqual(card,orb);assert.ok(position.distanceTo(new THREE.Vector3(3,7,11))<1e-6);assert.ok(quaternion.normalize().angleTo(camera.quaternion)<1e-5);assert.deepEqual(positions,original);
 objects.setAppearance('orbs');objects.update(positions,null,null,camera);assert.equal(objects.meshes[0],orb);objects.dispose();
});

test('one generous spatial layout reserves card space in either appearance',()=>{
 const a=buildLayout({nodes,edges,appearance:'orbs'},240),b=buildLayout({nodes,edges,appearance:'cards'},240);
 assert.deepEqual(a,b,'appearance is not a different layout');
 const points=Object.values(a);
 const minimum=Math.min(...points.flatMap((p,i)=>points.slice(i+1).map(q=>Math.hypot(p.x-q.x,p.y-q.y,p.z-q.z))));
 assert.ok(minimum>145,`minimum automatic spacing ${minimum}`);
});

test('card text retains its card anchor even when selected near a screen boundary',()=>{
 const card={id:'a',card:true,x:30,y:40,width:100,height:60,priority:1000};
 const result=chooseLabels([card],{width:300,height:160});
 assert.ok(result.length===0||result[0].x===card.x&&result[0].y===card.y);
});

test('overview card planes retain a readable width before close-up',async()=>{
 const THREE=await import('three');const {createGraphObjects}=await import('./knowledge-3d-objects.mjs');
 const objects=createGraphObjects([{id:'a',kind:'paper'}],[],{appearance:'cards'}),camera=new THREE.PerspectiveCamera(42);camera.position.set(0,0,1000);
 objects.update({a:{x:0,y:0,z:0}},null,null,camera,700);
 const metric=objects.metrics.get('a');assert.ok(metric.cardWidth/metric.worldPerPixel>=130);objects.dispose();
});
