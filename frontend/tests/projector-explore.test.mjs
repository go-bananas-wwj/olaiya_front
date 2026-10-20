import test from 'node:test'
import assert from 'node:assert/strict'
import {similarityRadius,withinSimilarity,radialUniverse,needStatus,needPlane} from '../src/showcase/projector/projectorExplore.mjs'
const source={points:[{product:{id:1},position:[0,0,0]},{product:{id:2},position:[0,0,0]},{product:{id:3},position:[1,2,3]}],missingIds:[],byId:new Map()}
test('sphere membership and native threshold agree at bounds, ties and missing values',()=>{
 const rows=[1,.9999998,.9,.899,.1,0,-.5,null]
 for(const t of [0,.5,.9,1])for(const score of rows){
  const inside=withinSimilarity(score,t)
  if(Number.isFinite(score))assert.equal(inside,Math.sqrt(2*(1-Math.max(-1,Math.min(1,score))))<=similarityRadius(t)+1e-12)
  else assert.equal(inside,false)
 }
})
test('radial positions use native distance, keep zero vectors, and never depend on threshold',()=>{
 const rows=[{id:2,score:.9},{id:3,score:1}],radial=radialUniverse(source,1,rows)
 assert.equal(radial.points.length,3)
 assert.ok(Math.abs(Math.hypot(...radial.byId.get(2).position)-Math.sqrt(.2))<1e-9)
 assert.equal(Math.hypot(...radial.byId.get(3).position),0)
 assert.equal(Math.hypot(...radial.byId.get(1).position),0)
 assert.deepEqual(source.points[2].position,[1,2,3])
})
test('need view preserves identities, and lack of price never excludes',()=>{
 const plane=needPlane(source)
 assert.equal(plane.points[2].position[2],0);assert.equal(plane.points.length,source.points.length)
 assert.equal(needStatus({scores:[0],declared_directions:[]},0,'保湿'),'evidence')
 assert.equal(needStatus({scores:[null],declared_directions:['保湿']},0,'保湿'),'declared')
 assert.equal(needStatus({scores:[null],declared_directions:[]},0,'保湿'),'unknown')
})
test('a source with an index vector but no UMAP coordinate still has honest local distance',()=>{
 const empty={points:[],byId:new Map(),missingIds:[1,2],catalogProducts:[{id:1},{id:2}]}
 const local=radialUniverse(empty,1,[{id:2,score:.5}])
 assert.equal(local.points.length,2);assert.ok(Math.abs(Math.hypot(...local.byId.get(2).position)-1)<1e-12)
 assert.deepEqual(local.missingIds,[]);assert.equal(empty.points.length,0)
})
