import test from 'node:test'
import assert from 'node:assert/strict'
import { coincidentDisplayOffsets, paperAxes } from '../src/showcase/projector/projectorPresentation.mjs'
import { normalizeUniverse } from '../src/showcase/projector/projectorGeometry.mjs'

test('exact coincident products receive stable separate pixel offsets without changing scientific coordinates',()=>{
 const ps=[3,1,2].map(id=>({product:{id},position:[.1,.2,.3]}));ps.push({product:{id:4},position:[.1,.2,.300001]})
 const before=JSON.stringify(ps),offsets=coincidentDisplayOffsets(ps)
 assert.equal(JSON.stringify(ps),before)
 assert.deepEqual([...coincidentDisplayOffsets([...ps].reverse()).entries()].sort(),[...offsets.entries()].sort())
 assert.deepEqual(offsets.get(4),[0,0])
 for(const a of [1,2,3])for(const b of [1,2,3])if(a!==b)assert.ok(Math.hypot(...offsets.get(a).map((x,i)=>x-offsets.get(b)[i]))>=17.99)
 for(let axis=0;axis<2;axis++)assert.ok(Math.abs([1,2,3].reduce((s,id)=>s+offsets.get(id)[axis],0))<1e-9)
})
test('large identical-profile groups remain finite and individually addressable',()=>{
 const ps=Array.from({length:50},(_,id)=>({product:{id},position:[0,0,0]})),o=coincidentDisplayOffsets(ps)
 assert.equal(new Set([...o.values()].map(JSON.stringify)).size,50)
 assert.ok([...o.values()].every(v=>v.every(Number.isFinite)))
})
test('paper axes label actual projection coordinates, include the full data and never stretch input geometry',()=>{
 const products=[{id:1,coordinates_3d:[10,20,30],pca_coordinates:[.01,.02,.03]},{id:2,coordinates_3d:[20,40,60],pca_coordinates:[.04,.05,.06]}]
 const u=normalizeUniverse(products,'umap',3),before=JSON.stringify(u.points),a=paperAxes(u,{dimensions:3,algorithm:'umap'})
 assert.deepEqual(a.edges.map(x=>x.label),['UMAP 1','UMAP 2','UMAP 3'])
 assert.ok(a.segments.some(s=>s.kind==='grid'))
 assert.equal(a.corners.length,8)
 for(const edge of a.edges)for(const tick of edge.ticks)assert.ok(Math.abs(tick.position[edge.axis]/u.scale+u.center[edge.axis]-tick.value)<1e-9)
 assert.equal(JSON.stringify(u.points),before)
 const p=paperAxes(normalizeUniverse(products,'pca',2,[2,1,0]),{dimensions:2,algorithm:'pca',axisOrder:[2,1,0]})
 assert.deepEqual(p.edges.map(x=>x.label),['PC 3','PC 2'])
 assert.equal(p.corners.length,4)
})
test('empty and flat plots produce safe frames without fake product coordinates',()=>{
 assert.deepEqual(paperAxes(normalizeUniverse([]),{dimensions:2}).edges,[])
 const u=normalizeUniverse([{id:1,coordinates_3d:[1,1,1]}],'umap',3),a=paperAxes(u,{dimensions:3})
 assert.ok(a.corners.every(p=>p.every(Number.isFinite)))
 assert.ok(a.edges.every(e=>e.ticks.length>0))
 assert.equal(u.points.length,1)
})

test('dense plots pick the closest visible point directly, with stable depth and ID ties',async()=>{
 const {nearestVisiblePoint}=await import('../src/showcase/projector/projectorPresentation.mjs')
 const points=Array.from({length:64},(_,i)=>({product:{id:i+1},x:100+i*.05,y:100,visible:true,depth:.5}))
 assert.equal(nearestVisiblePoint(points,100,100).id,1)
 assert.equal(nearestVisiblePoint(points,102,100).id,41)
 const ties=[{product:{id:7},x:10,y:20,visible:true,depth:.7},{product:{id:9},x:10,y:20,visible:true,depth:.2}]
 assert.equal(nearestVisiblePoint(ties,10,20).id,9)
 assert.equal(nearestVisiblePoint(ties,100,200),null)
 assert.equal(nearestVisiblePoint([{...ties[0],visible:false}],10,20),null)
})

test('very small real axis values use scientific notation rather than a fake zero',async()=>{
 const {axisNumber}=await import('../src/showcase/projector/projectorPresentation.mjs')
 assert.equal(axisNumber(2e-12),'2.0e-12')
 assert.equal(axisNumber(-0),'0')
})
