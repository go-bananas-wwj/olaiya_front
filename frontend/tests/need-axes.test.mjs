import test from 'node:test'
import assert from 'node:assert/strict'
import {needPlane} from '../src/showcase/projector/projectorExplore.mjs'
const make=score=>({points:[{product:{id:1,ingredient_count:20,need_score:score,scores:[2,6.5]},position:[1,2,3]},{product:{id:2,ingredient_count:10,need_score:0,scores:[0,null]},position:[0,1,2]},{product:{id:3,ingredient_count:30,need_score:null,scores:[null,null]},position:[2,3,4]}],byId:new Map(),missingIds:[]})
test('need axes are actual count and raw evidence index, with shared zero-based scales',()=>{
 const input=make(2),plane=needPlane(input,'保湿'),axes=plane.needAxes
 assert.equal(axes.xLabel,'已收录成分数（项）');assert.equal(axes.yLabel,'保湿成分证据指数')
 assert.ok(axes.xMax>=30);assert.ok(axes.yMax>=6.5)
 const point=plane.byId.get(1)
 assert.equal(point.position[0],axes.x0+20/axes.xMax*(axes.x1-axes.x0))
 assert.equal(point.position[1],axes.y0+2/axes.yMax*(axes.y1-axes.y0))
 assert.deepEqual(input.points[0].position,[1,2,3]);assert.equal(plane.points.length,3)
})
test('switching need moves products by their actual index, never changes the shared scale',()=>{
 const a=needPlane(make(2),'保湿'),b=needPlane(make(4),'修护')
 assert.equal(a.needAxes.yMax,b.needAxes.yMax)
 assert.equal(a.byId.get(1).position[0],b.byId.get(1).position[0]);assert.notEqual(a.byId.get(1).position[1],b.byId.get(1).position[1])
 assert.equal(b.needAxes.need,'修护')
})
test('missing evidence gets separate rail while true zero remains on numerical baseline',()=>{
 const p=needPlane(make(2),'保湿'),a=p.needAxes
 assert.equal(p.byId.get(2).position[1],a.y0);assert.equal(p.byId.get(2).need_missing,false)
 assert.equal(p.byId.get(3).position[1],a.missingY);assert.equal(p.byId.get(3).need_missing,true)
 assert.notEqual(a.missingY,a.y0)
})
