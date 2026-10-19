import test from 'node:test'
import assert from 'node:assert/strict'
import { coordinatesFor, normalizeUniverse, visibleProducts, screenHits, pointColor, shortProductLabel, layoutLabels, fitPerspective } from '../src/showcase/projector/projectorGeometry.mjs'

const products = [
  { id: 9, name: 'A', coordinates: [0, 20], coordinates_3d: [0, 20, 5], pca_coordinates: [1, 2, 3], scores: [999] },
  { id: 73, name: 'B', coordinates: [10, 40], coordinates_3d: [10, 40, 15], pca_coordinates: [4, 6, 8], scores: [0] },
  { id: 414, name: 'C', coordinates: null, coordinates_3d: null, pca_coordinates: null, scores: [1, 2, 3] },
]

test('only the requested, finite projection is geometry; efficacy scores cannot replace missing coordinates', () => {
  assert.deepEqual(coordinatesFor(products[0], 'umap', 2), [0, 20, 0])
  assert.deepEqual(coordinatesFor(products[0], 'umap', 3), [0, 20, 5])
  assert.deepEqual(coordinatesFor(products[0], 'pca', 2), [1, 2, 0])
  assert.deepEqual(coordinatesFor(products[0], 'pca', 3), [1, 2, 3])
  assert.equal(coordinatesFor(products[2], 'umap', 3), null)
  assert.equal(coordinatesFor({ coordinates_3d: [0, 2, NaN] }, 'umap', 3), null)
  assert.equal(coordinatesFor(products[0], 'unknown', 3), null)
})

test('PCA component selection permutes real coordinates before taking two axes; UMAP is not permuted', () => {
  assert.deepEqual(coordinatesFor(products[0], 'pca', 2, [2, 0, 1]), [3, 1, 0])
  assert.deepEqual(coordinatesFor(products[0], 'pca', 3, [2, 0, 1]), [3, 1, 2])
  assert.deepEqual(coordinatesFor(products[0], 'umap', 2, [2, 0, 1]), [0, 20, 0])
  assert.equal(coordinatesFor(products[0], 'pca', 3, [0, 0, 1]), null)
})

test('normalization uses one full-universe scale and preserves all axis proportions', () => {
  const geometry = normalizeUniverse(products, 'umap', 3)
  assert.equal(geometry.points.length, 2)
  assert.deepEqual(geometry.missingIds, [414])
  assert.deepEqual(geometry.points[0].position, [-.5, -1, -.5])
  assert.deepEqual(geometry.points[1].position, [.5, 1, .5])
  assert.equal(geometry.scale, .1)
  assert.equal(geometry.byId.get(9), geometry.points[0])
})

test('isolation filters drawn records without recomputing universe coordinates or changing projection scale', () => {
  const geometry = normalizeUniverse(products, 'umap', 2)
  const subset = visibleProducts(geometry.points, 9, [{ id: 414 }], true)
  assert.deepEqual(subset.map(p => p.product.id), [9])
  assert.equal(subset[0], geometry.byId.get(9))
  assert.equal(visibleProducts(geometry.points, 9, [], false).length, 2)
  assert.equal(visibleProducts(geometry.points, null, [], true).length, 0)
})

test('same-position products are all reachable, while clipped and hidden points cannot be hit', () => {
  const points = [
    { product: products[0], x: 40, y: 50, depth: .2, visible: true },
    { product: products[1], x: 40, y: 50, depth: .8, visible: true },
    { product: products[2], x: 40, y: 50, depth: .1, visible: false },
  ]
  assert.deepEqual(screenHits(points, 40, 50, 8).map(p => p.id), [9, 73])
  assert.deepEqual(screenHits(points, 65, 50, 8), [])
})

test('empty or degenerate universes do not invent coordinates, jitter duplicates or divide by zero', () => {
  assert.deepEqual(normalizeUniverse([], 'umap', 3).points, [])
  const same = normalizeUniverse([{ id: 1, coordinates: [4, 4] }, { id: 2, coordinates: [4, 4] }], 'umap', 2)
  assert.deepEqual(same.points.map(p => p.position), [[0, 0, 0], [0, 0, 0]])
  assert.ok(Number.isFinite(same.scale))
})

test('selection context uses source-style rose and orange; unknown evidence has a distinct tone', () => {
  assert.equal(pointColor(products[0], { selected: 9, neighborIds: new Set([73]), colorBy: 'none' }), '#96004f')
  assert.equal(pointColor(products[1], { selected: 9, neighborIds: new Set([73]), colorBy: 'none' }), '#e9a023')
  assert.equal(pointColor(products[2], { selected: 9, neighborIds: new Set([73]), colorBy: 'none' }), '#c8c8cc')
  assert.notEqual(pointColor({ scores: [null] }, { colorBy: 0 }), pointColor({ scores: [0] }, { colorBy: 0 }))
})

test('short labels use existing product identities and keep full metadata untouched', () => {
  const a = { name: '黑绷带面霜（Re-Plasty Age Recovery Night）', brand: '赫莲娜' }
  assert.equal(shortProductLabel(a), '黑绷带面霜（Re-Plasty Age Recovery Night）')
  assert.equal(shortProductLabel({ name: 'SkinCeuticals Prevent C E Ferulic® With 15% L-Ascorbic Acid' }), 'Prevent C E Ferulic® With 15% L-Ascorbic Acid')
  assert.equal(shortProductLabel({ name: 'SkinCeuticals Serum 10' }), 'Serum 10')
  assert.equal(shortProductLabel(a, 'brand'), '赫莲娜')
  assert.equal(a.name, '黑绷带面霜（Re-Plasty Age Recovery Night）')
})

const intersects = (a, b) => a.left < b.left + b.width && a.left + a.width > b.left && a.top < b.top + b.height && a.top + a.height > b.top
test('selected labels are placed first, at readable sizes, without covering any selected/neighbor node or other label', () => {
  const points = Array.from({ length: 20 }, (_, i) => ({ product: { id:i, name:`产品名称 ${i}` }, x:200, y:150, visible:true }))
  const labels = layoutLabels(points, { width:400, height:300, selected:19, pointSize:6, measure:(text,fontSize)=>text.length*fontSize*.7 })
  assert.equal(labels[0].product.id, 19)
  assert.equal(labels[0].fontSize, 14)
  assert.ok(labels.length > 0 && labels.length < points.length)
  for (const [index, label] of labels.entries()) {
    assert.ok(label.fontSize >= 12)
    assert.ok(label.left >= 4 && label.top >= 4 && label.left+label.width<=396 && label.top+label.height<=296)
    assert.ok(!intersects(label, {left:192,top:142,width:16,height:16}))
    for (const prior of labels.slice(0,index)) assert.equal(intersects(label, prior), false)
    if (label.leader) { assert.equal(label.leader.x1, 200); assert.equal(label.leader.y1,150) }
  }
  assert.ok(labels.some(label=>label.leader), 'offset labels retain a line to the real point')
  assert.ok(points.every(p=>p.x===200&&p.y===150), 'no node is displaced to make room for text')
})

test('label placement stays inside a phone viewport, skips unplaceable or clipped labels and is deterministic', () => {
  const points = [
    {product:{id:1,name:'边缘产品（完整来源名称）'},x:8,y:8,visible:true},
    {product:{id:2,name:'裁掉的点'},x:-1,y:20,visible:false},
  ]
  const options={width:160,height:100,selected:1,pointSize:6}
  const first=layoutLabels(points,options)
  assert.equal(first.length,1)
  assert.ok(first[0].left>=4&&first[0].top>=4)
  assert.deepEqual(layoutLabels(points,options),first)
  assert.deepEqual(layoutLabels(points,{...options,width:5,height:5}),[])
})

const dot=(a,b)=>a.reduce((sum,v,i)=>sum+v*b[i],0)
function ndcFor(point,fit,aspect) {
  const offset=point.map((v,i)=>v-fit.target[i]),depth=fit.distance-dot(offset,fit.direction),tan=Math.tan(42*Math.PI/360)
  return [dot(offset,fit.right)/(depth*tan*aspect),dot(offset,fit.up)/(depth*tan)]
}
test('perspective framing fits actual point bounds to 80% of a limiting viewport dimension without axis stretch',()=>{
  const positions=[[-1,-.1,-.4],[.8,.1,.7],[.3,.9,.2],[-.4,-.8,.1]]
  for(const aspect of [.48,1,1.8]) {
    const fit=fitPerspective(positions,{aspect})
    const ndc=positions.map(point=>ndcFor(point,fit,aspect))
    assert.ok(ndc.every(xy=>xy.every(v=>Math.abs(v)<=.800001)))
    const spans=[0,1].map(i=>Math.max(...ndc.map(p=>p[i]))-Math.min(...ndc.map(p=>p[i])))
    assert.ok(Math.max(...spans)>1.599, `framing should use 80% of one dimension: ${spans}`)
  }
})
test('tight real neighbor subsets receive the same framing margin, with no minimum-radius zoom cap',()=>{
  const tight=[[.8,.2,.3],[.800001,.200002,.300001],[.800004,.200001,.299998]]
  const fit=fitPerspective(tight,{aspect:.48})
  assert.ok(fit.distance<.001)
  const ndc=tight.map(point=>ndcFor(point,fit,.48))
  const spans=[0,1].map(i=>Math.max(...ndc.map(p=>p[i]))-Math.min(...ndc.map(p=>p[i])))
  assert.ok(Math.max(...spans)>1.599)
  const coincident=fitPerspective([[.8,.2,.3],[.8,.2,.3]],{aspect:.48})
  assert.ok(Number.isFinite(coincident.distance)&&coincident.distance>0)
  assert.ok(ndcFor([.8,.2,.3],coincident,.48).every(v=>Math.abs(v)<1e-7))
})

test('identity labels retain variants, source suffixes and formulation descriptors', () => {
  assert.equal(shortProductLabel({ name: '科瑞肤多维智效修护面霜（莹润型）' }), '科瑞肤多维智效修护面霜（莹润型）')
  assert.notEqual(shortProductLabel({ name: '面霜（莹润型）' }), shortProductLabel({ name: '面霜（轻盈型）' }))
  assert.equal(shortProductLabel({ name: 'CeraVe 面霜（美国官网）' }), 'CeraVe 面霜（美国官网）')
  assert.equal(shortProductLabel({ name: 'SkinCeuticals C E Ferulic® With 15% L-Ascorbic Acid' }), 'C E Ferulic® With 15% L-Ascorbic Acid')
})

test('coincidence groups exact projection coordinates, never screen proximity or product identity', async () => {
  const { groupCoincidentPoints } = await import('../src/showcase/projector/projectorGeometry.mjs')
  const points = [
    {product:{id:1,name:'同名'},position:[.2,.3,.4],x:100,y:80,visible:true},
    {product:{id:2,name:'同名'},position:[.2,.3,.4],x:100,y:80,visible:true},
    {product:{id:3,name:'另一款'},position:[.2,.3,.400001],x:100,y:80,visible:true},
  ]
  const groups = groupCoincidentPoints(points)
  assert.equal(groups.length,2)
  assert.deepEqual(groups[0].members.map(p=>p.product.id),[1,2])
  assert.equal(groups[1].members.length,1)
  assert.deepEqual(points.map(p=>p.position),[[.2,.3,.4],[.2,.3,.4],[.2,.3,.400001]])
})

test('one label represents an exact coordinate group and prefers the selected identity', () => {
  const points = [1,2,3].map(id=>({product:{id,name:`产品 ${id}（不同版本）`},position:[1,2,3],x:200,y:150,visible:true}))
  const labels=layoutLabels(points,{width:500,height:300,selected:2})
  assert.equal(labels.length,1)
  assert.equal(labels[0].product.id,2)
  assert.equal(labels[0].coincidentCount,3)
  assert.deepEqual(labels[0].members.map(p=>p.product.id),[1,2,3])
})

test('coincident badges remain available without labels and do not confuse screen overlap with shared projection', async () => {
  const {groupCoincidentPoints,layoutCoincidentBadges}=await import('../src/showcase/projector/projectorGeometry.mjs')
  const points=[1,2].map(id=>({product:{id},position:[1,2,3],x:80,y:60,visible:true}))
  points.push({product:{id:3},position:[1,2,4],x:80,y:60,visible:true})
  const badges=layoutCoincidentBadges(groupCoincidentPoints(points),{width:160,height:120})
  assert.equal(badges.length,1)
  assert.equal(badges[0].count,2)
  assert.deepEqual(badges[0].members.map(p=>p.product.id),[1,2])
  assert.ok(badges[0].left>=4&&badges[0].top>=4)
  assert.ok(badges[0].left+badges[0].width<=156&&badges[0].top+badges[0].height<=116)
})

test('long selected identity keeps a readable label beyond a dense neighborhood with reserved badges', () => {
  const selected={product:{id:9,name:'黑绷带面霜（Re-Plasty Age Recovery Night）'},position:[0,0,0],x:260,y:200,visible:true}
  const points=[selected,...Array.from({length:40},(_,i)=>({product:{id:100+i,name:`近邻产品 ${i}`},position:[i+1,1,0],x:130+(i%8)*36,y:100+Math.floor(i/8)*45,visible:true}))]
  const reserved=[{left:100,top:100,width:320,height:200}]
  const labels=layoutLabels(points,{width:520,height:400,selected:9,reserved})
  const primary=labels.find(label=>label.product.id===9)
  assert.ok(primary,'selected product must remain labeled in a dense PCA neighborhood')
  assert.equal(primary.text,selected.product.name)
  assert.ok(primary.left>=4&&primary.top>=4&&primary.left+primary.width<=516&&primary.top+primary.height<=396)
  assert.deepEqual(selected.position,[0,0,0])
})

test('coincident annotations prioritize selection and neighbors, limit clutter and yield to the main identity', async()=>{
  const {layoutCoincidentBadges}=await import('../src/showcase/projector/projectorGeometry.mjs')
  const groups=Array.from({length:15},(_,i)=>({key:String(i),members:[1,2].map(n=>({product:{id:i*10+n},position:[i,0,0],x:40+(i%5)*130,y:60+Math.floor(i/5)*140,visible:true}))}))
  const reserved=[{left:0,top:0,width:140,height:100}]
  const badges=layoutCoincidentBadges(groups,{width:700,height:500,selected:141,neighborIds:new Set([131]),reserved})
  assert.ok(badges.length<=8)
  assert.equal(badges[0].product.id,141)
  assert.equal(badges[1].product.id,131)
  assert.ok(badges.every(b=>!intersects(b,reserved[0])))
  assert.ok(badges.every(b=>b.width===44&&b.height===44))
})
