import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import { Minus, Plus, ArrowsOutSimple } from '@phosphor-icons/react'
import { boundsFor, coordinatesFor, hitsAt, pointTone } from './space.mjs'

export default forwardRef(function MapCanvas({ products, visible, mode, axes, color, directions, selected, comparison, focus, onChoose, onCluster }, ref) {
  const frame=useRef(null),canvas=useRef(null),drag=useRef(null)
  const [size,setSize]=useState({width:700,height:500})
  const [camera,setCamera]=useState({zoom:1,x:0,y:0})
  const [hover,setHover]=useState(null)
  const locations=useMemo(()=>new Map(products.map(p=>[p.id,coordinatesFor(p,mode,axes)])),[products,mode,axes])
  const bounds=useMemo(()=>boundsFor([...locations.values()].filter(Boolean),mode),[locations,mode])
  const colorMax=useMemo(()=>Math.max(1,...products.map(p=>Number.isFinite(p.scores[color])?p.scores[color]:0)),[products,color])
  const padding={left:mode==='axes'?58:28,right:26,top:32,bottom:mode==='axes'?52:28}
  const plot={width:Math.max(1,size.width-padding.left-padding.right),height:Math.max(1,size.height-padding.top-padding.bottom)}
  function screen(xy,cameraValue=camera){
    const uniform=Math.min(plot.width/(bounds.x[1]-bounds.x[0]),plot.height/(bounds.y[1]-bounds.y[0]))
    const x=mode==='semantic'?padding.left+plot.width/2+(xy[0]-(bounds.x[0]+bounds.x[1])/2)*uniform
      :padding.left+(xy[0]-bounds.x[0])/(bounds.x[1]-bounds.x[0])*plot.width
    const y=mode==='semantic'?padding.top+plot.height/2-(xy[1]-(bounds.y[0]+bounds.y[1])/2)*uniform
      :padding.top+(1-(xy[1]-bounds.y[0])/(bounds.y[1]-bounds.y[0]))*plot.height
    return {x:(x-size.width/2)*cameraValue.zoom+size.width/2+cameraValue.x*size.width,y:(y-size.height/2)*cameraValue.zoom+size.height/2+cameraValue.y*size.height}
  }
  const points=useMemo(()=>visible.flatMap(product=>{
    const xy=locations.get(product.id)
    return xy?[{product,...screen(xy)}]:[]
  }),[visible,locations,bounds,size,camera,mode])
  const unplaced=visible.filter(p=>!locations.get(p.id)).length
  useImperativeHandle(ref,()=>({reset:()=>setCamera({zoom:1,x:0,y:0})}),[])
  useEffect(()=>{
    const observer=new ResizeObserver(entries=>{const r=entries[0].contentRect;if(r.width>0&&r.height>0)setSize({width:r.width,height:r.height})})
    observer.observe(frame.current);return()=>observer.disconnect()
  },[])
  useEffect(()=>{setCamera({zoom:1,x:0,y:0});setHover(null)},[mode,axes[0],axes[1]])
  useEffect(()=>{
    if(!focus)return
    const xy=locations.get(focus.id)
    if(!xy)return
    const p=screen(xy,{zoom:1,x:0,y:0})
    setCamera({zoom:1,x:.5-p.x/size.width,y:.5-p.y/size.height})
  },[focus,locations])
  useEffect(()=>{
    const el=canvas.current,dpr=window.devicePixelRatio||1
    el.width=Math.round(size.width*dpr);el.height=Math.round(size.height*dpr)
    const ctx=el.getContext('2d');ctx.scale(dpr,dpr);ctx.clearRect(0,0,size.width,size.height)
    ctx.fillStyle='#fcfcfd';ctx.fillRect(0,0,size.width,size.height)
    if(mode==='axes'){
      ctx.font='11px Arial';ctx.textAlign='right';ctx.fillStyle='#8c8b94';ctx.strokeStyle='#ededf1';ctx.lineWidth=1
      for(let i=0;i<=4;i++){
        const valueX=bounds.x[1]*i/4,valueY=bounds.y[1]*i/4
        const px=screen([valueX,0]).x,py=screen([0,valueY]).y
        if(px>=padding.left&&px<=size.width-padding.right){ctx.beginPath();ctx.moveTo(px,padding.top);ctx.lineTo(px,size.height-padding.bottom);ctx.stroke();ctx.textAlign='center';ctx.fillText(valueX.toFixed(1),px,size.height-padding.bottom+19)}
        if(py>=padding.top&&py<=size.height-padding.bottom){ctx.beginPath();ctx.moveTo(padding.left,py);ctx.lineTo(size.width-padding.right,py);ctx.stroke();ctx.textAlign='right';ctx.fillText(valueY.toFixed(1),padding.left-10,py+4)}
      }
      ctx.fillStyle='#65616f';ctx.textAlign='center';ctx.font='12px Arial';ctx.fillText(`${directions[axes[0]]}证据指数`,padding.left+plot.width/2,size.height-10)
      ctx.save();ctx.translate(15,padding.top+plot.height/2);ctx.rotate(-Math.PI/2);ctx.fillText(`${directions[axes[1]]}证据指数`,0,0);ctx.restore()
    }
    ctx.save();ctx.beginPath();ctx.rect(padding.left-8,padding.top-8,plot.width+16,plot.height+16);ctx.clip()
    for(const p of points){
      ctx.beginPath();ctx.arc(p.x,p.y,Math.min(3.2,2.4+camera.zoom*.12),0,Math.PI*2)
      ctx.fillStyle=pointTone(p.product.scores[color],colorMax);ctx.globalAlpha=.9;ctx.fill()
    }
    ctx.globalAlpha=1
    for(const p of points.filter(p=>comparison.includes(p.product.id)||p.product.id===selected)){
      const slot=comparison.indexOf(p.product.id)
      ctx.beginPath();ctx.arc(p.x,p.y,7,0,Math.PI*2);ctx.fillStyle=slot===1?'#c17740':'#6744b5';ctx.fill();ctx.lineWidth=2;ctx.strokeStyle='white';ctx.stroke()
      if(p.product.id===selected){ctx.beginPath();ctx.arc(p.x,p.y,11,0,Math.PI*2);ctx.lineWidth=1.4;ctx.strokeStyle='#352445';ctx.stroke()}
    }
    ctx.restore()
  },[points,size,bounds,camera,color,colorMax,selected,comparison,mode,directions])
  function pointer(e){const r=canvas.current.getBoundingClientRect();return{x:e.clientX-r.left,y:e.clientY-r.top}}
  function zoom(factor){setCamera(c=>({...c,zoom:Math.max(1,Math.min(12,c.zoom*factor))}))}
  return <div className="space-map" ref={frame} data-testid="space-map" data-ready="true" data-total={products.length} data-plotted={points.length} data-unplaced={unplaced}>
    <canvas ref={canvas} role="img" aria-label={`${mode==='semantic'?'成分表语义投影':'证据坐标'}，${points.length}款有坐标产品。可通过搜索或产品列表选择所有产品。`} tabIndex={0}
      style={{touchAction:camera.zoom>1?'none':'pan-y'}}
      onKeyDown={e=>{if(['+','=','-','Home'].includes(e.key)){e.preventDefault();e.key==='Home'?setCamera({zoom:1,x:0,y:0}):zoom(e.key==='-'?1/1.4:1.4)}}}
      onPointerDown={e=>{if(e.button!==0)return;const p=pointer(e);drag.current={...p,camera,moved:false};e.currentTarget.setPointerCapture(e.pointerId)}}
      onPointerMove={e=>{
        const p=pointer(e),d=drag.current
        if(d){if(Math.hypot(p.x-d.x,p.y-d.y)>4)d.moved=true;if(d.moved){setHover(null);setCamera({...d.camera,x:d.camera.x+(p.x-d.x)/size.width,y:d.camera.y+(p.y-d.y)/size.height})}return}
        const matches=hitsAt(points,p.x,p.y,8);setHover(matches.length?{...p,product:matches[0],count:matches.length}:null)
      }}
      onPointerUp={e=>{const d=drag.current;drag.current=null;if(!d||d.moved)return;const p=pointer(e),matches=hitsAt(points,p.x,p.y,11);setHover(null);if(matches.length===1)onChoose(matches[0]);else if(matches.length>1)onCluster(matches)}}
      onPointerCancel={()=>{drag.current=null}} onPointerLeave={()=>setHover(null)} />
    <span className="space-map-caption">{mode==='semantic'?'成分表语义 · 二维投影':'原始证据维度 · 未知不补零'}</span>
    {hover&&<div className="space-tooltip" style={{left:Math.min(Math.max(12,hover.x+14),size.width-235),top:Math.max(34,hover.y-60)}}><small>{hover.product.brand}</small><strong>{hover.product.name}</strong>{hover.count>1&&<span>此处有 {hover.count} 款，点击展开</span>}</div>}
    <div className="space-zoom" role="group" aria-label="地图视图"><button type="button" aria-label="放大地图" onClick={()=>zoom(1.4)}><Plus size={17}/></button><button type="button" aria-label="缩小地图" onClick={()=>zoom(1/1.4)}><Minus size={17}/></button><button type="button" aria-label="重置地图" onClick={()=>setCamera({zoom:1,x:0,y:0})}><ArrowsOutSimple size={17}/></button></div>
    <div className="space-map-instructions">点击选点 · 按钮缩放 · 拖动查看</div>
  </div>
})
