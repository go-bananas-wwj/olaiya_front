import test from 'node:test'
import assert from 'node:assert/strict'
import {distanceFromCosine,pairForReference,projectionAvailable,projectionVariance} from '../src/showcase/projector/projectorLogic.mjs'
test('distances use the original normalized vector score and never invent missing values',()=>{
 assert.equal(distanceFromCosine(.8,'cosine'),.19999999999999996)
 assert.ok(Math.abs(distanceFromCosine(.8,'euclidean')-Math.sqrt(.4))<1e-12)
 assert.equal(distanceFromCosine(1.0000001,'cosine'),0)
 assert.equal(distanceFromCosine(null,'cosine'),null)
 assert.equal(distanceFromCosine(NaN,'cosine'),null)
})
test('reference pair always keeps actual IDs and supports a same-product comparison',()=>{
 assert.deepEqual(pairForReference(414,{a:9,b:73}),{a:414,b:73})
 assert.deepEqual(pairForReference(73,{a:9,b:73}),{a:73,b:9})
 assert.deepEqual(pairForReference(9,{a:9,b:9}),{a:9,b:9})
})
test('3D cannot be inferred from an old 2D layout or a non-ready mode',()=>{
 const data={projection:{status:'ready',umap_3d:{status:'unavailable'},pca:{status:'ready',explained_variance_ratio:[.07,.04,.03]}}}
 assert.equal(projectionAvailable(data,'umap',2),true)
 assert.equal(projectionAvailable(data,'umap',3),false)
 assert.equal(projectionAvailable(data,'pca',3),true)
 assert.equal(projectionVariance(data,[2,0,1],2),10)
})

test('a 3D PCA quality measure is never attributed to a 2D projection',async()=>{
 const {projectionQuality}=await import('../src/showcase/projector/projectorLogic.mjs')
 const data={projection:{quality:{neighbor_recall_10:.44},umap_3d:{quality:{neighbor_recall_10:.49}},pca:{quality:{neighbor_recall_10:.11}}}}
 assert.equal(projectionQuality(data,'pca',2),null)
 assert.equal(projectionQuality(data,'pca',3).neighbor_recall_10,.11)
 assert.equal(projectionQuality(data,'umap',2).neighbor_recall_10,.44)
 assert.equal(projectionQuality(data,'umap',3).neighbor_recall_10,.49)
})
