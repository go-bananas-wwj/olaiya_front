// Presentation only: source positions, embeddings and nearest-neighbor metrics stay untouched.
export function coincidentDisplayOffsets(points, spacing=18) {
 const groups=new Map(),result=new Map()
 for(const p of points){const key=JSON.stringify(p.position);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(p)}
 for(const [key,members] of groups){
  members.sort((a,b)=>a.product.id-b.product.id)
  if(members.length===1){result.set(members[0].product.id,[0,0]);continue}
  const slots=[[0,0]]
  for(let ring=1;slots.length<members.length;ring++){
   let q=-ring,r=ring
   for(const [dq,dr] of [[1,0],[1,-1],[0,-1],[-1,0],[-1,1],[0,1]])for(let step=0;step<ring;step++){
    if(slots.length<members.length)slots.push([spacing*(q+r/2),spacing*Math.sqrt(3)*r/2])
    q+=dq;r+=dr
   }
  }
  const center=[0,1].map(axis=>slots.reduce((sum,p)=>sum+p[axis],0)/slots.length)
  let hash=0;for(const c of key)hash=(Math.imul(hash,31)+c.charCodeAt(0))|0
  const angle=((hash>>>0)%360)*Math.PI/180,c=Math.cos(angle),s=Math.sin(angle)
  members.forEach((p,i)=>{const x=slots[i][0]-center[0],y=slots[i][1]-center[1];result.set(p.product.id,[x*c-y*s,x*s+y*c])})
 }
 return result
}

function ticks(lo,hi){
 const rough=(hi-lo)/4,magnitude=10**Math.floor(Math.log10(rough))
 const step=([1,2,2.5,5,10].find(n=>n*magnitude>=rough)||10)*magnitude
 const first=Math.ceil(lo/step)*step,values=[]
 for(let i=0;i<12;i++){const value=first+i*step;if(value>hi+step*1e-8)break;values.push(Math.abs(value)<step*1e-8?0:Number(value.toPrecision(10)))}
 return values
}
export function paperAxes(universe,{dimensions=3,algorithm='umap',axisOrder=[0,1,2]}={}) {
 if(!universe.points.length)return {segments:[],edges:[],corners:[],bounds:[]}
 const bounds=[],values=[]
 for(let axis=0;axis<dimensions;axis++){
  let lo=Infinity,hi=-Infinity
  for(const point of universe.points){lo=Math.min(lo,point.position[axis]);hi=Math.max(hi,point.position[axis])}
  const padding=hi>lo?(hi-lo)*.045:.45
  bounds.push([lo-padding,hi+padding])
  values.push(ticks((lo-padding)/universe.scale+universe.center[axis],(hi+padding)/universe.scale+universe.center[axis]))
 }
 if(dimensions===2)bounds.push([0,0])
 const [x,y,z]=bounds,corners=[]
 for(const xx of x)for(const yy of y)for(const zz of dimensions===3?z:[0])corners.push([xx,yy,zz])
 const segments=[],edge=(a,b,kind='frame')=>segments.push({a,b,kind})
 if(dimensions===3){
  for(const xx of x)for(const yy of y)edge([xx,yy,z[0]],[xx,yy,z[1]])
  for(const xx of x)for(const zz of z)edge([xx,y[0],zz],[xx,y[1],zz])
  for(const yy of y)for(const zz of z)edge([x[0],yy,zz],[x[1],yy,zz])
 }else{for(const xx of x)edge([xx,y[0],0],[xx,y[1],0]);for(const yy of y)edge([x[0],yy,0],[x[1],yy,0])}
 const world=(value,axis)=>(value-universe.center[axis])*universe.scale
 // Subtle grids on the floor/back panes; no colored origin tripod.
 for(const value of values[0]){const xx=world(value,0);edge([xx,y[0],z[0]],[xx,y[1],z[0]],'grid');if(dimensions===3)edge([xx,y[0],z[0]],[xx,y[0],z[1]],'grid')}
 for(const value of values[1]){const yy=world(value,1);edge([x[0],yy,z[0]],[x[1],yy,z[0]],'grid');if(dimensions===3)edge([x[0],yy,z[0]],[x[0],yy,z[1]],'grid')}
 if(dimensions===3)for(const value of values[2]){const zz=world(value,2);edge([x[0],y[0],zz],[x[1],y[0],zz],'grid');edge([x[0],y[0],zz],[x[0],y[1],zz],'grid')}
 const starts=[[x[0],y[0],z[1]],[x[0],y[0],z[1]],[x[0],y[0],z[0]]]
 const ends=[[x[1],y[0],z[1]],[x[0],y[1],z[1]],[x[0],y[0],z[1]]]
 const edges=Array.from({length:dimensions},(_,axis)=>({axis,start:starts[axis],end:ends[axis],label:algorithm==='pca'?`PC ${axisOrder[axis]+1}`:`UMAP ${axis+1}`,
  ticks:values[axis].map(value=>{const position=[...starts[axis]];position[axis]=world(value,axis);return {value,position}})}))
 return {segments,edges,corners,bounds}
}
export function axisNumber(value){
 if(value===0)return '0'
 if(Math.abs(value)>=10000||Math.abs(value)<.001)return value.toExponential(1)
 return Number(value.toPrecision(4)).toString()
}

// Dense neighborhoods use ordinary nearest-pixel picking, not a mandatory list.
export function nearestVisiblePoint(points,x,y,radius=7) {
 return points.filter(p=>p.visible&&Number.isFinite(p.x)&&Number.isFinite(p.y))
  .map(p=>({...p,distance:(p.x-x)**2+(p.y-y)**2})).filter(p=>p.distance<=radius**2)
  .sort((a,b)=>a.distance-b.distance||(a.depth??0)-(b.depth??0)||a.product.id-b.product.id)[0]?.product||null
}
