import test from 'node:test'
import assert from 'node:assert/strict'
import { modeSimilarity, similarityOrder } from '../src/showcase/projector/projectorModes.mjs'
import { familyAssignments, FAMILY_COLORS } from '../src/showcase/projector/compositionFamilies.mjs'
test('similarity retains native cosine scores, true zero and unknown',()=>{
 assert.equal(modeSimilarity({score:.992},'composition'),.992)
 assert.equal(modeSimilarity({score:0},'composition'),0)
 assert.equal(modeSimilarity({score:-.2},'composition'),-.2)
 assert.equal(modeSimilarity({score:null},'composition'),null)
 assert.equal(modeSimilarity({distance:.2},'evidence'),.8)
 assert.equal(modeSimilarity({distance:null},'evidence'),null)
 assert.deepEqual(similarityOrder([{id:1,score:.1},{id:2,score:.99},{id:3,score:.1},{id:4,score:null}],'composition').map(p=>p.id),[2,1,3,4])
})
test('families require the exact source index, and unknown records are unassigned',()=>{
 const artifact={source_index_sha256:'abc',assignments:[[7,0],[8,1]],k:8}
 assert.equal(familyAssignments(artifact,{source_index_sha256:'different'}).size,0)
 const assignments=familyAssignments(artifact,{source_index_sha256:'abc'})
 assert.equal(assignments.get(7),0);assert.equal(assignments.get(999),undefined)
 assert.equal(new Set(FAMILY_COLORS).size,8)
})
