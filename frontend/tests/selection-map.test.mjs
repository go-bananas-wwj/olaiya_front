import test from 'node:test'
import assert from 'node:assert/strict'
import { addSelectionCandidate, selectionPoint, groupSelectionPoints, selectedRectangleIds, readSelectionState, writeSelectionState } from '../src/showcase/selection/selectionLogic.mjs'

test('four unique candidates preserve user order without replacing prior choices',()=>{
 let ids=[];for(const id of [9,73,9,65,69,1594])ids=addSelectionCandidate(ids,id)
 assert.deepEqual(ids,[9,73,65,69])
})
test('true zero has a coordinate; unknown or excluded data never becomes a zero-price point',()=>{
 const axes={x:{min:0,max:10},y:{min:0,max:5}},box={left:0,top:0,width:100,height:50}
 assert.deepEqual(selectionPoint({id:1,plottable:true,unit_price:0,evidence_score:0},axes,box),{x:0,y:50})
 assert.equal(selectionPoint({plottable:false,unit_price:null,evidence_score:null},axes,box),null)
 assert.equal(selectionPoint({plottable:true,unit_price:2,evidence_score:null},axes,box),null)
})
test('coincident records are grouped by exact values, never jittered to appear unique',()=>{
 const rows=[{id:1,plottable:true,unit_price:2,evidence_score:1},{id:2,plottable:true,unit_price:2,evidence_score:1},{id:3,plottable:true,unit_price:2.000001,evidence_score:1}]
 assert.deepEqual(groupSelectionPoints(rows).map(g=>g.items.map(p=>p.id)),[[1,2],[3]])
})
test('rectangle selection adds only visible matching products, while keeping faded context',()=>{
 const ps=[{id:1,x:20,y:20,matches_filters:true},{id:2,x:30,y:20,matches_filters:false},{id:3,x:90,y:20,matches_filters:true}]
 assert.deepEqual(selectedRectangleIds(ps,{x1:40,y1:30,x2:10,y2:10}),[1])
})
test('URL roundtrips need, units, package budget and brand without destroying compare links',()=>{
 const start='https://example.com/?compare=9,73'
 const url=writeSelectionState(start,{view:'selection',efficacy:'修护',unit:'ml',brand:'理肤泉',budget:300})
 assert.equal(new URL(url).searchParams.get('compare'),'9,73')
 assert.deepEqual(readSelectionState(url),{view:'selection',efficacy:'修护',unit:'ml',brand:'理肤泉',budget:300})
 assert.deepEqual(readSelectionState('https://example.com/?view=selection&budget=NaN&efficacy=乱填&unit=kg'),{view:'selection',efficacy:'保湿',unit:null,brand:'',budget:null})
})
