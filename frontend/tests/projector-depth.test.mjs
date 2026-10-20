import test from 'node:test'
import assert from 'node:assert/strict'
import { displayUniverse, depthCue } from '../src/showcase/projector/projectorDepth.mjs'
import {normalizeUniverse} from '../src/showcase/projector/projectorGeometry.mjs'
test('visual depth expands all three axes without changing source coordinates or normalized geometry',()=>{
 const products=[{id:1,coordinates_3d:[0,0,0]},{id:2,coordinates_3d:[1,2,3]}], saved=JSON.stringify(products)
 const raw=normalizeUniverse(products,'umap',3), geometry=displayUniverse(raw,3)
 assert.deepEqual(geometry.points[1].position,raw.points[1].position.map((v,i)=>v*[1.12,1.1,2.1][i]))
 assert.equal(geometry.byId.get(1),geometry.points[0]);assert.equal(JSON.stringify(products),saved)
 assert.deepEqual(raw.points[1].position,[1/3,2/3,1])
 assert.equal(displayUniverse(raw,2),raw)
})
test('depth cues are bounded, truthful to camera depth, and disabled in 2D',()=>{
 const near=depthCue(2,4,3),far=depthCue(7,4,3)
 assert.ok(near.scale>far.scale);assert.ok(near.opacity>far.opacity)
 assert.ok(near.scale<=1.55&&far.scale>=.65)
 assert.deepEqual(depthCue(2,4,2),{scale:1,opacity:1})
 assert.deepEqual(depthCue(NaN,4,3),{scale:1,opacity:1})
})
