import test from 'node:test'
import assert from 'node:assert/strict'
import { modeDistance, distanceLabel, modeNeighbors, visibleCount } from '../src/showcase/projector/projectorModes.mjs'

test('the two modes never reinterpret one metric as another', () => {
  assert.ok(Math.abs(modeDistance({score:.992},'composition','cosine')-.008)<1e-12)
  assert.equal(modeDistance({score:.992},'evidence','cosine'),null)
  assert.equal(modeDistance({distance:.008},'evidence','euclidean'),.008)
  assert.equal(modeDistance({distance:null},'evidence'),null)
  assert.equal(distanceLabel('composition','cosine'),'余弦距离')
  assert.equal(distanceLabel('composition','euclidean'),'归一化欧氏距离')
  assert.equal(distanceLabel('evidence','cosine'),'八方向证据距离')
})
test('neighbor rows are unique identities, exclude self, and belong to current reference', () => {
  const lookup=new Map([[1,{id:1}],[2,{id:2}],[3,{id:3}]])
  const semantic={product_id:1,similar:[{id:1,score:1},{id:2,score:.9},{id:2,score:.8}]}
  assert.deepEqual(modeNeighbors(semantic,lookup,1,'composition').map(p=>p.id),[2])
  assert.deepEqual(modeNeighbors(semantic,lookup,3,'composition'),[])
  assert.deepEqual(modeNeighbors({product_id:1,available:true,items:[{id:3,distance:0}]},lookup,1,'evidence').map(p=>p.id),[3])
})
test('missing coordinates never inflate count or create a fake reference point',()=>{
 const rows=[{id:1,pca_coordinates:null},{id:2,pca_coordinates:[0,0,0]},{id:3,pca_coordinates:[1,2,3]}]
 assert.equal(visibleCount(rows,'pca',3,false,1,[]),2)
 assert.equal(visibleCount(rows,'pca',3,true,1,[{id:2}]),1)
})
