import test from 'node:test'
import assert from 'node:assert/strict'
import { matchingProducts, coordinatesFor, boundsFor, hitsAt, addComparison, pointTone } from '../src/showcase/space/space.mjs'

const products=[
 {id:9,name:'黑绷带面霜',brand:'赫莲娜',scores:[0,null],statuses:['scored','no_evidence'],coordinates:[1,2]},
 {id:73,name:'A.G.E. 面霜',brand:'修丽可',scores:[1,2],statuses:['scored','scored'],coordinates:[1,2]},
 {id:414,name:'Serum 10',brand:'修丽可',scores:[null,1],statuses:['unrated','scored'],coordinates:[4,5]},
]
test('search covers the complete catalogue with punctuation and brand matching',()=>{
 assert.deepEqual(matchingProducts(products,'A G E').map(p=>p.id),[73])
 assert.deepEqual(matchingProducts(products,'修丽可').map(p=>p.id),[73,414])
 assert.deepEqual(matchingProducts(products,'不存在'),[])
})
test('raw axes keep true zero while missing and unrated stay outside the plot',()=>{
 assert.equal(coordinatesFor(products[0],'axes',[0,1]),null)
 assert.equal(coordinatesFor(products[2],'axes',[0,1]),null)
 assert.deepEqual(coordinatesFor({...products[0],scores:[0,2]},'axes',[0,1]),[0,2])
 assert.deepEqual(coordinatesFor(products[0],'semantic',[0,1]),[1,2])
})
test('bounds use the full universe and raw axes start at zero',()=>{
 assert.deepEqual(boundsFor([[0,2],[1,4]],'axes'),{x:[0,1],y:[0,4]})
 assert.equal(boundsFor([],'axes').x[1],1)
 assert.ok(boundsFor([[3,3]],'semantic').x[1]>3)
})
test('every coincident product remains selectable, not just the last rendered dot',()=>{
 const points=products.map(p=>({product:p,x:p.id===414?100:10,y:10}))
 assert.deepEqual(hitsAt(points,10,10,9).map(p=>p.id),[9,73])
 assert.deepEqual(hitsAt(points,50,50,9),[])
})
test('comparison selection is unique, explicit and limited to two products',()=>{
 assert.deepEqual(addComparison([9],9),[9])
 assert.deepEqual(addComparison([9],73),[9,73])
 assert.deepEqual(addComparison([9,73],414),[9,73])
})
test('missing evidence has its own tone and cannot become a numerical zero',()=>{
 assert.notEqual(pointTone(null,2),pointTone(0,2))
 assert.notEqual(pointTone(0,2),pointTone(2,2))
})

test('screen aggregation keeps exact membership and excludes highlighted products',async()=>{
 const {groupScreenPoints}=await import('../src/showcase/space/space.mjs')
 const points=[{product:{id:1},x:10,y:10},{product:{id:2},x:13,y:12},{product:{id:3},x:90,y:90}]
 const groups=groupScreenPoints(points,32,new Set([3]))
 assert.equal(groups.length,1)
 assert.deepEqual(groups[0].items.map(p=>p.id),[1,2])
 assert.equal(groups[0].count,2)
 assert.equal(groups[0].x,11.5)
 assert.ok(groups[0].radius>=11)
})

test('neighboring screen cells merge colliding markers without moving source coordinates',async()=>{
 const {groupScreenPoints}=await import('../src/showcase/space/space.mjs')
 const points=[{product:{id:1},x:31,y:10},{product:{id:2},x:33,y:10},{product:{id:3},x:120,y:90}]
 const groups=groupScreenPoints(points,32)
 assert.equal(groups.length,2)
 assert.deepEqual(groups.flatMap(g=>g.items.map(p=>p.id)).sort(),[1,2,3])
 assert.equal(groups.find(g=>g.count===2).x,32)
 assert.equal(points[0].x,31)
})
