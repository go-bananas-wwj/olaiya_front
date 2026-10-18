import { forwardRef,useEffect,useImperativeHandle,useMemo,useRef,useState } from 'react'
import { Minus,Plus,ArrowsOutSimple } from '@phosphor-icons/react'
import { boundsFor,coordinatesFor,hitsAt,pointTone,groupScreenPoints,placeMapLabel } from './space.mjs'

export default forwardRef(function MapCanvas({products,visible,mode,axes,color,directions,selected,neighbors=[],comparison,focus,onChoose,onCluster,onViewportChange},ref){
 const frame=useRef(null),canvas=useRef(null),drag=useRef(null)
 const [size,setSize]=useState({width:760,height:500}),[camera,setCamera]=useState({zoom:1,x:0,y:0}),[hover,setHover]=useState(null)
 const locations=useMemo(()=>new Map(products.map(p=>[p.id,coordinatesFor(p,mode,axes)])),[products,mode,axes])
 const bounds=useMemo(()=>boundsFor([...locations.values()].filter(Boolean),mode),[locations,mode])
 const colorMax=useMemo(()=>Math.max(1,...products.map(p=>Number.isFinite(p.scores[color])?p.scores[color]:0)),[products,color])
 const padding={left:mode==='axes'?54:25,right:25,top:50,bottom:mode==='axes'?52:44}
 const plot={width:Math.max(1,size.width-padding.left-padding.right),height:Math.max(1,size.height-padding.top-padding.bottom)}
 const neighborKey=neighbors.map(p=>p.id).join(',')
 const featured=useMemo(()=>new Set([selected,...neighbors.map(p=>p.id)].filter(Boolean)),[selected,neighborKey])
 function screen(xy,cameraValue=camera){
  const uniform=Math.min((plot.width-36)/(bounds.x[1]-bounds.x[0]),(plot.height-36)/(bounds.y[1]-bounds.y[0]))
  const x=mode==='semantic'?padding.left+plot.width/2+(xy[0]-(bounds.x[0]+bounds.x[1])/2)*uniform:padding.left+18+(xy[0]-bounds.x[0])/(bounds.x[1]-bounds.x[0])*(plot.width-36)
  const y=mode==='semantic'?padding.top+plot.height/2-(xy[1]-(bounds.y[0]+bounds.y[1])/2)*uniform:padding.top+18+(1-(xy[1]-bounds.y[0])/(bounds.y[1]-bounds.y[0]))*(plot.height-36)
  return {x:(x-size.width/2)*cameraValue.zoom+size.width/2+cameraValue.x*size.width,y:(y-size.height/2)*cameraValue.zoom+size.height/2+cameraValue.y*size.height}
 }
 const points=useMemo(()=>visible.flatMap(product=>{const xy=locations.get(product.id);return xy?[{product,...screen(xy)}]:[]}),[visible,locations,bounds,size,camera,mode])
 const inFrame=p=>p.x>=padding.left&&p.x<=size.width-padding.right&&p.y>=padding.top&&p.y<=size.height-padding.bottom
 const groups=useMemo(()=>groupScreenPoints(points.filter(inFrame),size.width<500?48:48,featured),[points,size,featured,mode])
 const foreground=useMemo(()=>points.filter(p=>featured.has(p.product.id)),[points,featured])
 const unplaced=visible.filter(p=>!locations.get(p.id)).length
 function reset(){setCamera({zoom:1,x:0,y:0})}
 useImperativeHandle(ref,()=>({reset}),[])
 useEffect(()=>{const observer=new ResizeObserver(entries=>{const r=entries[0].contentRect;if(r.width>0&&r.height>0)setSize({width:r.width,height:r.height})});observer.observe(frame.current);return()=>observer.disconnect()},[])
 useEffect(()=>{reset();setHover(null)},[mode,axes[0],axes[1]])
 useEffect(()=>{
  const ids=[selected,...neighbors.map(p=>p.id)],xy=ids.map(id=>locations.get(id)).filter(Boolean)
  if(!xy.length)return
  const targets=xy.map(p=>screen(p,{zoom:1,x:0,y:0})),xs=targets.map(p=>p.x),ys=targets.map(p=>p.y)
  const minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys)
  const zoom=Math.max(1,Math.min(12,(plot.width-100)/Math.max(1,maxX-minX),(plot.height-100)/Math.max(1,maxY-minY)))
  setCamera({zoom,x:(size.width/2-(minX+maxX)/2)*zoom/size.width,y:(size.height/2-(minY+maxY)/2)*zoom/size.height})
 },[selected,neighborKey,locations,size.width,size.height,focus])
 useEffect(()=>{
  const el=canvas.current,dpr=window.devicePixelRatio||1;el.width=Math.round(size.width*dpr);el.height=Math.round(size.height*dpr)
  const ctx=el.getContext('2d');ctx.scale(dpr,dpr);ctx.clearRect(0,0,size.width,size.height);ctx.fillStyle='#fbfdfb';ctx.fillRect(0,0,size.width,size.height)
  ctx.strokeStyle='#edf3ee';ctx.lineWidth=1
  if(mode==='axes'){
   ctx.font='12px Arial';ctx.fillStyle='#647d6c'
   for(let i=0;i<=4;i++){const vx=bounds.x[1]*i/4,vy=bounds.y[1]*i/4,px=screen([vx,0]).x,py=screen([0,vy]).y
    if(px>=padding.left&&px<=size.width-padding.right){ctx.beginPath();ctx.moveTo(px,padding.top);ctx.lineTo(px,size.height-padding.bottom);ctx.stroke();ctx.textAlign='center';ctx.fillText(vx.toFixed(1),px,size.height-padding.bottom+20)}
    if(py>=padding.top&&py<=size.height-padding.bottom){ctx.beginPath();ctx.moveTo(padding.left,py);ctx.lineTo(size.width-padding.right,py);ctx.stroke();ctx.textAlign='right';ctx.fillText(vy.toFixed(1),padding.left-9,py+4)}
   }
   ctx.textAlign='center';ctx.fillText(`${directions[axes[0]]}证据指数`,padding.left+plot.width/2,size.height-9);ctx.save();ctx.translate(14,padding.top+plot.height/2);ctx.rotate(-Math.PI/2);ctx.fillText(`${directions[axes[1]]}证据指数`,0,0);ctx.restore()
  }else{
   for(let i=1;i<5;i++){const x=padding.left+plot.width*i/5,y=padding.top+plot.height*i/5;ctx.beginPath();ctx.moveTo(x,padding.top);ctx.lineTo(x,size.height-padding.bottom);ctx.stroke();ctx.beginPath();ctx.moveTo(padding.left,y);ctx.lineTo(size.width-padding.right,y);ctx.stroke()}
  }
  ctx.save();ctx.beginPath();ctx.rect(padding.left-16,padding.top-16,plot.width+32,plot.height+32);ctx.clip()
  for(const g of groups){ctx.beginPath();ctx.arc(g.x,g.y,g.radius,0,Math.PI*2);ctx.fillStyle=g.count>1?'#e0f0e5':pointTone(g.items[0].scores[color],colorMax);ctx.fill();ctx.strokeStyle=g.count>1?'#a7cdb7':'#65947b';ctx.lineWidth=1;ctx.stroke();if(g.count>1){ctx.fillStyle='#3b7254';ctx.font='600 11px Arial';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(g.count,g.x,g.y+.5)}}
  const target=foreground.find(p=>p.product.id===selected)
  if(target){ctx.setLineDash([4,5]);ctx.strokeStyle='#84bca9';ctx.lineWidth=1.2;for(const p of foreground.filter(p=>neighbors.some(n=>n.id===p.product.id))){ctx.beginPath();ctx.moveTo(target.x,target.y);ctx.lineTo(p.x,p.y);ctx.stroke()}ctx.setLineDash([])}
  const labels=[],nodeObstacles=foreground.filter(inFrame).map(p=>{const r=p.product.id===selected?19:16;return {x:p.x-r,y:p.y-r,w:r*2,h:r*2}})
  for(const p of [...foreground].sort((a,b)=>(a.product.id===selected?1:0)-(b.product.id===selected?1:0))){
   if(!inFrame(p))continue
   const isTarget=p.product.id===selected,rank=neighbors.findIndex(n=>n.id===p.product.id),slot=comparison.indexOf(p.product.id)
   const ink=isTarget?'#207c61':slot===1?'#a96d37':'#386e85',r=isTarget?12:9
   ctx.beginPath();ctx.arc(p.x,p.y,r+7,0,Math.PI*2);ctx.fillStyle='#ffffff';ctx.fill()
   if(isTarget){ctx.beginPath();ctx.arc(p.x,p.y,17,0,Math.PI*2);ctx.fillStyle='#d4ebe0';ctx.fill()}
   ctx.beginPath();ctx.arc(p.x,p.y,r,0,Math.PI*2);ctx.fillStyle=ink;ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.stroke();ctx.fillStyle='white';ctx.font='600 11px Arial';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(isTarget?'参':rank>=0?rank+1:slot===0?'A':'B',p.x,p.y+.5)
   if(size.width<500)continue
   let name=p.product.name.split('（')[0].replace(/^SkinCeuticals (?:Prevent )?/,'').replace(/® With.*$/,'')
   ctx.font=isTarget?'600 12px Arial':'12px Arial';const max=size.width<500?115:155
   while(ctx.measureText(name).width>max&&name.length>3)name=name.slice(0,-2)+'…'
   const w=ctx.measureText(name).width+18,h=27
   const label=placeMapLabel(p,w,h,size,nodeObstacles,labels)
   if(!label)continue
   labels.push(label)
   ctx.fillStyle='#ffffff';ctx.strokeStyle=isTarget?'#92bfaa':'#cee0d9';ctx.lineWidth=1;ctx.beginPath();ctx.roundRect(label.x,label.y,w,h,6);ctx.fill();ctx.stroke();ctx.fillStyle=ink;ctx.textAlign='left';ctx.textBaseline='middle';ctx.fillText(name,label.x+9,label.y+h/2)
  }
  ctx.restore()
 },[groups,foreground,points,size,bounds,camera,color,colorMax,selected,comparison,mode,neighborKey,directions])
 function pointer(e){const r=canvas.current.getBoundingClientRect();return {x:e.clientX-r.left,y:e.clientY-r.top}}
 function zoom(factor){setCamera(c=>({...c,zoom:Math.max(1,Math.min(16,c.zoom*factor))}))}
 function nodeHits(p){const focusHits=hitsAt(foreground,p.x,p.y,19);if(focusHits.length)return focusHits;const matches=groups.filter(g=>Math.hypot(g.x-p.x,g.y-p.y)<=g.radius+7);return [...new Map(matches.flatMap(g=>g.items).map(p=>[p.id,p])).values()]}
 const renderedCount=new Set([...groups.flatMap(g=>g.items.map(p=>p.id)),...foreground.filter(inFrame).map(p=>p.product.id)]).size
 useEffect(()=>{onViewportChange?.(renderedCount)},[renderedCount,onViewportChange])
 return <div className="space-map" ref={frame} data-testid="space-map" data-ready="true" data-total={products.length} data-plotted={points.length} data-rendered-product-count={renderedCount} data-unplaced={unplaced} data-min-marker-radius="5.5" data-clusters={groups.length}>
  <canvas ref={canvas} role="img" tabIndex={0} aria-label={`${mode==='semantic'?'成分表语义地图':'证据坐标'}，产品集合显示真实数量，参照与真实检索候选独立标记。全部${products.length}款均可通过搜索或列表查看。`} style={{touchAction:camera.zoom>1?'none':'pan-y'}}
   onKeyDown={e=>{if(['+','=','-','Home'].includes(e.key)){e.preventDefault();e.key==='Home'?reset():zoom(e.key==='-'?1/1.4:1.4)}}}
   onPointerDown={e=>{if(e.button!==0)return;drag.current={...pointer(e),camera,moved:false};e.currentTarget.setPointerCapture(e.pointerId)}}
   onPointerMove={e=>{const p=pointer(e),d=drag.current;if(d){if(Math.hypot(p.x-d.x,p.y-d.y)>4)d.moved=true;if(d.moved){setHover(null);setCamera({...d.camera,x:d.camera.x+(p.x-d.x)/size.width,y:d.camera.y+(p.y-d.y)/size.height})}return}const hits=nodeHits(p);setHover(hits.length?{...p,product:hits[0],count:hits.length}:null)}}
   onPointerUp={e=>{const d=drag.current;drag.current=null;if(!d||d.moved)return;const hits=nodeHits(pointer(e));setHover(null);if(hits.length===1)onChoose(hits[0]);else if(hits.length>1)onCluster(hits)}} onPointerCancel={()=>{drag.current=null}} onPointerLeave={()=>setHover(null)}/>
  <span className="space-map-caption">{mode==='semantic'?'全库语义投影 · 数字为集合数量':'原始证据坐标 · 未知不补零'}</span>
  {hover&&<div className="space-tooltip" style={{left:Math.max(10,Math.min(hover.x+15,size.width-240)),top:Math.max(40,hover.y-66)}}>{hover.count>1?<><strong>{hover.count} 款产品在这一处</strong><span>点击展开，选择其中一款</span></>:<><small>{hover.product.brand}</small><strong>{hover.product.name}</strong></>}</div>}
  <div className="space-zoom" role="group" aria-label="地图视图"><button type="button" aria-label="放大地图" onClick={()=>zoom(1.4)}><Plus size={18}/></button><button type="button" aria-label="缩小地图" onClick={()=>zoom(1/1.4)}><Minus size={18}/></button><button type="button" aria-label="重置地图" onClick={reset}><ArrowsOutSimple size={18}/></button></div>
  <div className="space-map-instructions"><span className="map-reference-key"/>参照产品<span className="map-neighbor-key"/>检索候选<span>拖动与缩放探索</span></div>
 </div>
})
