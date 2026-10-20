import test from 'node:test'
import assert from 'node:assert/strict'
import {needPlane} from '../src/showcase/projector/projectorExplore.mjs'
const product=(id,score,price)=>({id,ingredient_count:20,need_score:score,scores:[score],price_current:price})
const source={points:[product(1,2,null),product(2,0,0),product(3,null,100)].map(product=>({product,position:[1,2,3]})),missingIds:[]}
test('2D need plane keeps missing-price products, plots real zero on baseline and excludes missing scores',()=>{
 const view=needPlane(source,'保湿',2)
 assert.equal(view.points.length,2);assert.ok(view.points.every(p=>p.position[2]===0))
 assert.equal(view.byId.get(2).position[1],view.needAxes.y0)
 assert.equal(view.excluded[0].product.id,3)
})
test('3D price plot excludes unknown prices rather than placing them on negative axes',()=>{
 const view=needPlane(source,'保湿',3)
 assert.deepEqual(view.points.map(p=>p.product.id),[2]);assert.equal(view.byId.get(2).position[2],view.needAxes.z0)
 assert.equal(view.excluded.length,2)
})
