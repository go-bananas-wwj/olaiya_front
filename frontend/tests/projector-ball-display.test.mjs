import test from 'node:test'
import assert from 'node:assert/strict'
import { boundedBallOffset } from '../src/showcase/projector/projectorBallDisplay.mjs'

test('display separation preserves sphere ray membership while native points stay fixed',()=>{
 const viewport=[800,600],ball=[0,0,-3,.45],projection=[1.35,1.8]
 const hit=([x,y])=>{const a=(x/800*2-1)/1.35,b=(1-y/600*2)/1.8,n=Math.hypot(a,b,1),along=3/n;return 9-along*along<=.45**2}
 for(let x=280;x<=520;x+=3)for(let y=180;y<=420;y+=7){
  const raw=[x,y],copy=[...raw],offset=boundedBallOffset(raw,[18,-11],viewport,ball,projection,16)
  assert.deepEqual(raw,copy)
  assert.ok(Math.hypot(...offset)<=16+1e-8)
  assert.equal(hit(raw),hit([x+offset[0],y+offset[1]]))
 }
})

test('zero-size and high-threshold envelopes do not get a false minimum visual distance',()=>{
 assert.deepEqual(boundedBallOffset([400,300],[18,-11],[800,600],[0,0,-3,0],[1.35,1.8],0),[0,0])
 const offset=boundedBallOffset([400,300],[18,-11],[800,600],[0,0,-3,2e-6],[1.35,1.8],.00005)
 assert.ok(Math.hypot(...offset)<=.00005)
})

test('flat view separation preserves the displayed circle boundary, not the larger sphere silhouette',()=>{
 const viewport=[800,600],ball=[-.35,.15,-3,.45],projection=[1.35,1.8]
 const hit=([x,y])=>{const worldX=(x/800*2-1)/1.35*3,worldY=(1-y/600*2)/1.8*3;return (worldX-ball[0])**2+(worldY-ball[1])**2<=ball[3]**2}
 for(let x=240;x<=440;x+=.75)for(let y=190;y<=360;y+=2.5){
  const raw=[x,y],offset=boundedBallOffset(raw,[18,-11],viewport,ball,projection,16,true)
  assert.ok(Math.hypot(...offset)<=16+1e-8)
  assert.equal(hit(raw),hit([x+offset[0],y+offset[1]]),`flat boundary changed at ${raw}`)
 }
})
