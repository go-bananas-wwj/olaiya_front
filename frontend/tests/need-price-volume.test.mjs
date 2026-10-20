import test from 'node:test'
import assert from 'node:assert/strict'
import {needPlane} from '../src/showcase/projector/projectorExplore.mjs'
const source={points:[{product:{id:1,ingredient_count:20,need_score:2,scores:[2],price_current:100},position:[1,2,3]},{product:{id:2,ingredient_count:20,need_score:2,scores:[2],price_current:null},position:[0,1,2]},{product:{id:3,ingredient_count:30,need_score:0,scores:[0],price_current:0},position:[2,3,4]}],byId:new Map(),missingIds:[]}
test('third axis maps actual whole-item reference price while unknown price stays separate',()=>{
 const p=needPlane(source,'保湿'),a=p.needAxes
 assert.equal(a.zLabel,'整件参考价（元）');assert.ok(a.zMax>=100)
 assert.equal(p.byId.get(1).position[2],a.z0+100/a.zMax*(a.z1-a.z0))
 assert.equal(p.byId.get(2).position[2],a.missingZ);assert.equal(p.byId.get(2).price_missing,true)
 assert.equal(p.byId.get(3).position[2],a.z0);assert.equal(p.byId.get(3).price_missing,false)
 assert.deepEqual(source.points[0].position,[1,2,3]);assert.equal(p.points.length,3)
})
