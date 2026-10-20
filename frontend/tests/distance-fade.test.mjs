import test from 'node:test'
import assert from 'node:assert/strict'
import {distanceOpacity} from '../src/showcase/projector/projectorExplore.mjs'
test('distance fading is continuous, bounded and becomes weaker farther from selection',()=>{
 const values=[0,.1,.5,1,2,5].map(d=>distanceOpacity(d,1))
 assert.equal(values[0],1);assert.ok(values.every(v=>v>=.12&&v<=1))
 for(let i=1;i<values.length;i++)assert.ok(values[i]<values[i-1])
 assert.ok(Math.abs(distanceOpacity(.5,1)-distanceOpacity(.500001,1))<.00001)
})
