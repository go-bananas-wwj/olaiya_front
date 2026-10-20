import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { coincidentDisplayOffsets, paperAxes, nearestVisiblePoint } from './projectorPresentation.mjs'
import { radialUniverse,needPlane,similarityRadius,distanceOpacity } from './projectorExplore.mjs'
import { boundedBallOffset, BALL_OFFSET_GLSL } from './projectorBallDisplay.mjs'
import { displayUniverse, depthCue, DISPLAY_AXES } from './projectorDepth.mjs'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { normalizeUniverse, visibleProducts, screenHits, pointColor, layoutLabels, fitPerspective, groupCoincidentPoints, layoutCoincidentBadges } from './projectorGeometry.mjs'

const EMPTY = []
const DEFAULT_AXES = [0, 1, 2]
const ROOT_STYLE = { position: 'relative', width: '100%', height: '100%', minHeight: 220, overflow: 'hidden', background: 'transparent' }
const OVERLAY_STYLE = { position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', padding: 28, gap: 12, textAlign: 'center', background: '#fff', color: '#555', fontSize: 13 }

function circleTexture() {
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = 32
  const context = canvas.getContext('2d')
  context.fillStyle = '#fff'
  context.beginPath(); context.arc(16, 16, 15, 0, Math.PI * 2); context.fill()
  const texture = new THREE.CanvasTexture(canvas)
  texture.minFilter = THREE.LinearFilter
  return texture
}

function disposeGroup(group) {
  for (const child of [...group.children]) {
    group.remove(child)
    child.geometry?.dispose()
    if (Array.isArray(child.material)) child.material.forEach(material => material.dispose())
    else child.material?.dispose()
  }
}

// Each frame is requested by a data/camera/resize event. There is no idle animation loop.
export default forwardRef(function ProjectorCanvas({ products = EMPTY, algorithm = 'umap', dimensions = 2,
  selected = null, neighbors = EMPTY, isolated = false, pointSize = 6, colorBy = 'none', showLabels = true, labelBy = 'name', axisOrder = DEFAULT_AXES,
  onSelect, onClear, onCoincident, spreadCoincident = true, overlayExpanded = true, facet = null, radial = false, similarityRows = EMPTY, threshold = .9, basis = 'composition' }, ref) {
  const root = useRef(null), canvas = useRef(null), runtime = useRef(null)
  const [attempt, setAttempt] = useState(0), [failure, setFailure] = useState(null)
  const [frameInfo, setFrameInfo] = useState({ revision: 0, labels: [], badges: [], coincidentGroups: [], axisLabels: [], spreadLeaders: [], needAxes:null })
  const [hover, setHover] = useState(null)
  const axisKey = JSON.stringify(axisOrder)
  const base = useMemo(() => ({...displayUniverse(normalizeUniverse(products, algorithm, facet?3:dimensions, axisOrder),facet?3:dimensions),catalogProducts:products}), [products, algorithm, dimensions, axisKey,!!facet])
  const unfilteredUniverse=useMemo(()=>facet?needPlane(base,facet,dimensions):base,[base,facet,dimensions])
  const universe=useMemo(()=>radial?radialUniverse(base,selected,similarityRows,basis,dimensions):unfilteredUniverse,[base,unfilteredUniverse,radial,selected,similarityRows,basis,dimensions])
  const effectiveSpread=spreadCoincident||radial
  const displayOffsets=useMemo(()=>{
    const offsets=coincidentDisplayOffsets(universe.points,facet&&!radial?10:18)
    if(facet&&!radial)for(const point of universe.points){const offset=offsets.get(point.product.id)||[0,0],length=Math.hypot(...offset),scale=Math.min(1,16/Math.max(1,length));offsets.set(point.product.id,[offset[0]*scale,point.product.need_score===0?0:offset[1]*scale])}
    return offsets
  },[universe,facet,radial])
  const axisSpec=useMemo(()=>paperAxes(universe,{dimensions,algorithm,axisOrder}),[universe,dimensions,algorithm,axisKey])
  const drawn = useMemo(() => visibleProducts(universe.points, selected, neighbors, isolated), [universe, selected, neighbors, isolated])
  const latest = useRef(null)
  latest.current = { products, selected, neighbors, isolated, pointSize, colorBy, showLabels, labelBy, onSelect, onClear, onCoincident, universe, drawn, dimensions, displayOffsets, spreadCoincident:effectiveSpread, axisSpec,radial,facet,threshold,basis }

  useImperativeHandle(ref, () => ({
    reset: () => runtime.current?.reset(),
    refresh: () => runtime.current?.invalidate(),
    focusSelection: () => runtime.current?.focusSelection(),
    zoom: factor => runtime.current?.zoom(factor),
    getScreenPoint: id => runtime.current?.getScreenPoint(id) ?? null,
  }), [])

  useEffect(() => {
    let renderer
    try { renderer = new THREE.WebGLRenderer({ canvas: canvas.current, antialias: true, alpha: true, powerPreference: 'low-power', preserveDrawingBuffer:true }) }
    catch { setFailure('当前浏览器无法启用 WebGL 图形渲染。'); return }
    setFailure(null)
    renderer.setClearColor(0xffffff, 0)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    const scene = new THREE.Scene(), cloud = new THREE.Group(), axes = new THREE.Group(), envelope = new THREE.Group(), texture = circleTexture()
    const labelMeasure = document.createElement('canvas').getContext('2d')
    scene.add(cloud, axes, envelope)
    const r = { renderer, element:canvas.current, scene, cloud, axes, envelope, texture, morphUniform:{value:1}, bridgeUniform:{value:0}, ballCamera:{value:new THREE.Vector4()}, ballProjection:{value:new THREE.Vector2(1,1)}, ballOffsetLimit:{value:0}, radialUniform:{value:0}, width: 1, height: 1, camera: null, controls: null,
      viewportUniform:{value:new THREE.Vector2(1,1)}, depthUniform:{value:new THREE.Vector2(1,1)}, dimensions: latest.current.dimensions, request: null, disposed: false, drawn: [], observer: null }
    runtime.current = r

    r.positionFor=point=>{const to=r.targetPositions?.get(point.product.id)||point.position,from=r.startPositions?.get(point.product.id)||to,t=r.morphUniform.value
      if(r.bridgeUniform.value>.5){const mid=r.bridgePositions?.get(point.product.id)||to,u=t<.5?t*2:t*2-1,e=u*u*(3-2*u),a=t<.5?from:mid,b=t<.5?mid:to;return a.map((v,i)=>v+(b[i]-v)*e)}
      return from.map((v,i)=>v+(to[i]-v)*t)
    }
    r.project = point => {
      if (!r.camera || r.disposed) return null
      r.camera.updateMatrixWorld()
      const position=r.positionFor(point)
      const vector = new THREE.Vector3(...position).project(r.camera)
      const viewDepth=-new THREE.Vector3(...position).applyMatrix4(r.camera.matrixWorldInverse).z
      const cue=depthCue(viewDepth,r.camera.position.distanceTo(r.controls.target),r.dimensions)
      const x = (vector.x + 1) * r.width / 2, y = (1 - vector.y) * r.height / 2
      const requested=latest.current.spreadCoincident?(latest.current.displayOffsets.get(point.product.id)||[0,0]):[0,0]
      const offset=latest.current.radial?boundedBallOffset([x,y],requested,[r.width,r.height],r.ballCamera.value.toArray(),r.ballProjection.value.toArray(),r.ballOffsetLimit.value,r.dimensions===2):requested
      const displayX=x+offset[0],displayY=y+offset[1]
      return { product: point.product, position, rawX:x,rawY:y, displayOffset:offset,viewDepth,pointScale:cue.scale,x:displayX,y:displayY,depth: vector.z,
        visible: Number.isFinite(x) && Number.isFinite(y) && vector.z >= -1 && vector.z <= 1 && displayX >= 0 && displayX <= r.width && displayY >= 0 && displayY <= r.height }
    }
    r.getScreenPoint = id => {
      const point = r.drawn.find(p => p.product.id === id)
      if (!point) return null
      const projected = r.project(point), rect = canvas.current.getBoundingClientRect()
      return projected ? { x: projected.x, y: projected.y, clientX: rect.left + projected.x, clientY: rect.top + projected.y,
        visible: projected.visible, depth: projected.depth,viewDepth:projected.viewDepth,pointScale:projected.pointScale,rawX:projected.rawX,rawY:projected.rawY,displayOffset:projected.displayOffset,worldPosition:r.positionFor(point),semanticRadius:point.semantic_radius,needMissing:point.need_missing,priceMissing:point.price_missing,displayOpacity:r.opacityById?.get(id)??1 } : null
    }
    r.projectPosition=position=>{
      const v=new THREE.Vector3(...position).project(r.camera)
      return {x:(v.x+1)*r.width/2,y:(1-v.y)*r.height/2,depth:v.z}
    }
    // This DOM method exposes the same actual projection as the React ref for browser acceptance tests.
    canvas.current.getScreenPoint = r.getScreenPoint
    r.paint = () => {
        r.request = null
        if (r.disposed || !r.camera || renderer.getContext().isContextLost()) return
        r.syncClip()
        r.camera.updateMatrixWorld()
        const nativeRadius=latest.current.radial?(latest.current.basis==='evidence'?Math.max(0,1-latest.current.threshold)+1e-6:similarityRadius(latest.current.threshold)):0
        const cameraCenter=new THREE.Vector3(0,0,0).applyMatrix4(r.camera.matrixWorldInverse)
        r.ballCamera.value.set(cameraCenter.x,cameraCenter.y,cameraCenter.z,nativeRadius)
        r.ballProjection.value.set(r.camera.projectionMatrix.elements[0],r.camera.projectionMatrix.elements[5])
        const focal=r.height/(2*Math.tan(THREE.MathUtils.degToRad(r.camera.fov/2))),screenRadius=nativeRadius*focal/Math.max(1e-9,-cameraCenter.z)
        r.ballOffsetLimit.value=Math.min(18,screenRadius*.17)
        r.radialUniform.value=latest.current.radial?(r.dimensions===2?2:1):0
        root.current?.setAttribute('data-sphere-screen-diameter',String(screenRadius*2))
        r.depthUniform.value.set(r.camera.position.distanceTo(r.controls.target),(r.dimensions===3||r.bridgeUniform.value>.5&&r.morphUniform.value<.8)?1:0)
        r.envelope.visible=latest.current.radial&&r.morphUniform.value>=1
        if(r.silhouette&&latest.current.dimensions===3){
          const distance=r.camera.position.length(),radius=nativeRadius
          r.silhouette.visible=distance>radius
          if(distance>radius){
            const direction=r.camera.position.clone().normalize()
            r.silhouette.position.copy(direction).multiplyScalar(radius*radius/distance)
            r.silhouette.quaternion.setFromUnitVectors(new THREE.Vector3(0,0,1),direction)
            r.silhouette.scale.setScalar(Math.sqrt(Math.max(0,1-radius*radius/(distance*distance))))
          }
        }
        renderer.render(scene, r.camera)
        root.current?.setAttribute('data-camera-distance',r.camera.position.distanceTo(r.controls.target).toFixed(6))
        const props = latest.current
        const neighborIds = new Set(props.neighbors.map(p => p.id))
        const rank = new Map(props.neighbors.map((p,i)=>[p.id,i]))
        const screenPoints=r.drawn.map(r.project).filter(p=>p?.visible)
        const groups = props.spreadCoincident?screenPoints.map(p=>({key:String(p.product.id),members:[p]})):groupCoincidentPoints(screenPoints)
        const axisLabels=[]
        let needAxes=null
        if(props.universe.needAxes&&!props.radial){
          const spec=props.universe.needAxes,project=(x,y,z=spec.z0)=>r.projectPosition([x,y,z])
          needAxes={...spec,opacity:Math.max(0,(r.morphUniform.value-(r.bridgeUniform.value>.5?.75:.4))/(r.bridgeUniform.value>.5?.25:.6)),origin:project(spec.x0,spec.y0),topLeft:project(spec.x0,spec.y1),bottomRight:project(spec.x1,spec.y0),corner:project(spec.x1,spec.y1),missing:project(spec.x0,spec.missingY),missingEnd:project(spec.x1,spec.missingY),zEnd:project(spec.x0,spec.y0,spec.z1),noPrice:project(spec.x1,spec.y1,spec.missingZ),noPriceEnd:project(spec.x1,spec.y1,spec.missingZ),zLabel:spec.zLabel,
            zTicks:spec.is3D?Array.from({length:5},(_,i)=>({value:spec.zMax*i/4,...project(spec.x0,spec.y0,spec.z0+(spec.z1-spec.z0)*i/4),end:project(spec.x1,spec.y0,spec.z0+(spec.z1-spec.z0)*i/4)})):[],
            xTicks:Array.from({length:5},(_,i)=>({value:spec.xMax*i/4,...project(spec.x0+(spec.x1-spec.x0)*i/4,spec.y0),end:project(spec.x0+(spec.x1-spec.x0)*i/4,spec.y1)})),
            yTicks:Array.from({length:5},(_,i)=>({value:spec.yMax*i/4,...project(spec.x0,spec.y0+(spec.y1-spec.y0)*i/4),end:project(spec.x1,spec.y0+(spec.y1-spec.y0)*i/4)}))}
        }
        const projected = props.showLabels && props.selected != null ? groups.map(group=>{
          const members=[...group.members].sort((a,b)=>Number(b.product.id===props.selected)-Number(a.product.id===props.selected)
            || (rank.get(a.product.id)??Infinity)-(rank.get(b.product.id)??Infinity))
          return {...members[0],members:group.members,coincidentCount:group.members.length}
        }).filter(p=>p.product.id===props.selected||neighborIds.has(p.product.id))
          .sort((a,b)=>Number(b.product.id===props.selected)-Number(a.product.id===props.selected)
            || (rank.get(a.product.id)??Infinity)-(rank.get(b.product.id)??Infinity)).slice(0,4) : []
        const fontFamily = getComputedStyle(root.current).fontFamily
        const labelOptions={width:r.width,height:r.height,selected:props.selected,pointSize:props.pointSize,labelBy:props.labelBy,
          separateIdentities:props.spreadCoincident,measure:labelMeasure?(text,fontSize,primary)=>{labelMeasure.font=`${primary?600:400} ${fontSize}px ${fontFamily}`;return labelMeasure.measureText(text).width}:undefined}
        const card=root.current.parentElement?.querySelector('.projector-info')?.getBoundingClientRect(),area=root.current.getBoundingClientRect()
        const overlays=card?[{left:card.left-area.left,top:card.top-area.top,width:card.width,height:card.height}]:[]
        const primaryLabels=layoutLabels(projected,{...labelOptions,onlySelected:true,reserved:overlays})
        const badges=props.spreadCoincident?[]:layoutCoincidentBadges(groups,{width:r.width,height:r.height,selected:props.selected,neighborIds,reserved:[...primaryLabels,...overlays]})
        const labels=layoutLabels(projected,{...labelOptions,reserved:[...badges,...overlays]})
        setFrameInfo(old => ({ revision: old.revision + 1, labels, badges, coincidentGroups:groups.filter(group=>group.members.length>1),axisLabels,needAxes,
          spreadLeaders:props.spreadCoincident&&!props.facet?screenPoints.filter(p=>Math.hypot(...p.displayOffset)>.1&&(!props.radial||p.product.id===props.selected||neighborIds.has(p.product.id))):[] }))
    }
    r.invalidate = () => {
      if (r.disposed || r.request != null || renderer.getContext().isContextLost()) return
      r.request = requestAnimationFrame(r.paint)
    }
    r.flush = () => {
      if (r.request != null) cancelAnimationFrame(r.request)
      r.request = null
      r.paint()
    }
    r.updateFrustum = () => {
      if (!r.camera) return
      const aspect = r.width / r.height
      if (r.camera.isOrthographicCamera) {
        const bounds=latest.current.axisSpec.bounds
        const halfHeight=bounds.length?Math.max((bounds[1][1]-bounds[1][0])/2,(bounds[0][1]-bounds[0][0])/2/aspect)/.76:1.25*Math.max(1,1/aspect)
        r.camera.left = -halfHeight * aspect; r.camera.right = halfHeight * aspect
        r.camera.top = halfHeight; r.camera.bottom = -halfHeight
      } else r.camera.aspect = aspect
      r.camera.updateProjectionMatrix()
    }
    r.syncClip = () => {
      if (!r.camera?.isPerspectiveCamera) return
      const distance = r.camera.position.distanceTo(r.controls.target)
      r.camera.near = Math.max(1e-12,distance*1e-5)
      r.camera.far = Math.max(1000,distance*100)
      r.camera.updateProjectionMatrix()
    }
    r.reset = () => {
      if (!r.camera || r.disposed) return
      r.finishMorph?.()
      r.cancelFocus?.()
      r.framingPoints = latest.current.universe.points
      if(latest.current.universe.needAxes&&!latest.current.radial){
        const a=latest.current.universe.needAxes
        r.framingPoints=r.dimensions===2?[{position:[a.x0-.3,a.y0-.45,0]},{position:[a.x1+.2,a.y1+.3,0]}]:[...latest.current.universe.points,...[[a.x0-.25,a.y0,a.z0],[a.x1+.25,a.y0,a.z0],[a.x0-.25,a.y1+.3,a.z0],[a.x1+.25,a.y1+.3,a.z0],[a.x0,a.y0,a.z1+.3],[a.x0,a.missingY-.3,a.z0],[a.x1,a.missingY-.3,a.z0],[a.x1,a.y1+.3,a.missingZ]].map(position=>({position}))]
      }
      r.frameMode = 'universe'; r.axes.visible = false
      r.controls.target.set(0, 0, 0)
      if (r.camera.isOrthographicCamera) { r.camera.position.set(0, 0, 5); r.camera.up.set(0, 1, 0); r.camera.zoom = 1 }
      else {
        const fit = fitPerspective(r.framingPoints.map(point=>point.position),{aspect:r.width/r.height,direction:r.dimensions===2?[0,0,1]:latest.current.facet?[.95,.62,1.35]:[.9,.32,1],fov:r.camera.fov,padding:r.width<600?.1:.055})
        r.controls.target.fromArray(fit.target);r.camera.position.fromArray(fit.position);r.camera.zoom = 1
      }
      r.updateFrustum();r.syncClip(); r.controls.update(); r.invalidate()
    }
    r.switchCamera = dims => {
      r.controls?.dispose()
      r.dimensions = dims
      r.camera = new THREE.PerspectiveCamera(58, r.width / r.height, .01, 1000)
      r.controls = new OrbitControls(r.camera, canvas.current)
      r.controls.enableDamping = false
      r.controls.enableRotate = dims === 3
      r.controls.screenSpacePanning = true
      r.controls.minDistance = 1e-10; r.controls.maxDistance = 1000
      r.controls.minZoom = .08; r.controls.maxZoom = 1e9
      r.controls.mouseButtons.LEFT = dims === 2 ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE
      r.controls.touches.ONE = dims === 2 ? THREE.TOUCH.PAN : THREE.TOUCH.ROTATE
      r.controls.addEventListener('change', r.invalidate)
      r.controls.addEventListener('start',()=>{r.finishMorph?.();r.cancelFocus?.()})
      r.reset()
    }
    r.zoom = factor => {
      r.finishMorph?.();r.cancelFocus?.()
      if (!Number.isFinite(factor) || factor <= 0 || !r.camera || r.disposed) return
      if (r.camera.isOrthographicCamera) r.camera.zoom = THREE.MathUtils.clamp(r.camera.zoom * factor, .08, 1e9)
      else {
        const offset = r.camera.position.clone().sub(r.controls.target)
        const length = THREE.MathUtils.clamp(offset.length() / factor, r.controls.minDistance, r.controls.maxDistance)
        r.camera.position.copy(r.controls.target).add(offset.normalize().multiplyScalar(length))
      }
      r.camera.updateProjectionMatrix(); r.controls.update(); r.invalidate()
    }
    r.focusSelection = () => {
      r.finishMorph?.();if(latest.current.radial){r.focusLocal(true);return}
      r.cancelFocus?.()
      if (!r.camera || r.disposed) return
      const props = latest.current, ids = new Set(props.neighbors.map(p => p.id))
      if (props.selected != null) ids.add(props.selected)
      const subset = r.drawn.filter(p => ids.has(p.product.id))
      if (!subset.length) return
      r.framingPoints = subset
      r.frameMode = 'selection'; r.axes.visible = false
      const box = new THREE.Box3().setFromPoints(subset.map(p => new THREE.Vector3(...p.position)))
      const center = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3())
      const direction = r.camera.position.clone().sub(r.controls.target).normalize()
      r.controls.target.copy(center)
      if (r.camera.isOrthographicCamera) {
        r.camera.position.copy(center).add(new THREE.Vector3(0, 0, 5))
        r.camera.zoom = THREE.MathUtils.clamp(Math.min((r.camera.right-r.camera.left) / Math.max(1e-10, size.x),
          (r.camera.top-r.camera.bottom) / Math.max(1e-10, size.y)) * .8, .08, 1e9)
      } else {
        const fit=fitPerspective(subset.map(point=>point.position),{direction:direction.toArray(),aspect:r.width/r.height,fov:r.camera.fov})
        r.controls.target.fromArray(fit.target);r.camera.position.fromArray(fit.position)
      }
      r.syncClip();r.camera.updateProjectionMatrix(); r.controls.update(); r.invalidate()
    }
    r.cancelFocus = () => {
      if(r.motionRequest!=null)cancelAnimationFrame(r.motionRequest)
      r.motionRequest=null
      root.current?.setAttribute('data-camera-motion','idle')
    }
    r.focusLocal = (immediate=false) => {
      r.cancelFocus()
      const point=latest.current.universe.byId.get(latest.current.selected)
      if(!point||!r.camera)return
      const center=new THREE.Vector3(...point.position)
      const nearest=latest.current.universe.points.map(p=>new THREE.Vector3(...p.position).distanceTo(center)).sort((a,b)=>a-b)
      // The camera explores a bounded local region; semantic neighbours and
      // source coordinates stay untouched. A floor handles coincident vectors.
      const radius=latest.current.radial?Math.max(.08,(latest.current.basis==='evidence'?1-latest.current.threshold+1e-6:similarityRadius(latest.current.threshold))*1.2):Math.max(.12,Math.min(.42,(nearest[Math.min(16,nearest.length-1)]||0)*1.4))
      const startPosition=r.camera.position.clone(), startTarget=r.controls.target.clone(), startZoom=r.camera.zoom
      const direction=startPosition.clone().sub(startTarget).normalize()
      const targetPosition=r.camera.isOrthographicCamera?center.clone().add(new THREE.Vector3(0,0,5)):
        center.clone().add(direction.multiplyScalar(radius/Math.sin(THREE.MathUtils.degToRad(r.camera.fov/2))/Math.min(1,r.width/r.height)))
      const targetZoom=r.camera.isOrthographicCamera?Math.min(r.camera.right-r.camera.left,r.camera.top-r.camera.bottom)/(radius*2.6):1
      if(latest.current.radial&&r.camera.isPerspectiveCamera){
        const mobile=window.matchMedia('(max-width:1000px)').matches
        const cardWidth=mobile?0:(root.current.parentElement?.querySelector('.projector-info')?.getBoundingClientRect().width||320)
        const usableWidth=Math.max(160,r.width-cardWidth-28),usableHeight=mobile?r.height*.48:r.height
        const pixelRadius=Math.max(32,Math.min(usableWidth,usableHeight)*.275),focal=r.height/(2*Math.tan(THREE.MathUtils.degToRad(r.camera.fov/2)))
        const distance=radius*Math.sqrt(1+(focal/pixelRadius)**2)
        targetPosition.copy(center).add(startPosition.clone().sub(startTarget).normalize().multiplyScalar(distance))
      }
      const targetCenter=center.clone()
      // Keep the selected point above the mobile product sheet. This is a
      // camera pan only; product geometry and retrieval remain untouched.
      if(window.matchMedia('(max-width:1000px)').matches){
        const height=r.camera.isOrthographicCamera?(r.camera.top-r.camera.bottom)/targetZoom:
          2*targetPosition.distanceTo(center)*Math.tan(THREE.MathUtils.degToRad(r.camera.fov/2))
        const shift=new THREE.Vector3(0,1,0).applyQuaternion(r.camera.quaternion).multiplyScalar(height*(latest.current.radial ? .26 : .19))
        targetCenter.sub(shift);targetPosition.sub(shift)
      }
      if(latest.current.radial&&!window.matchMedia('(max-width:1000px)').matches){
        const cardWidth=root.current.parentElement?.querySelector('.projector-info')?.getBoundingClientRect().width||320
        const ndc=(Math.max(160,r.width-cardWidth-28)/r.width)-1
        const shift=new THREE.Vector3(1,0,0).applyQuaternion(r.camera.quaternion).multiplyScalar(-ndc*targetPosition.distanceTo(center)*Math.tan(THREE.MathUtils.degToRad(r.camera.fov/2))*r.width/r.height)
        targetCenter.add(shift);targetPosition.add(shift)
      }
      r.frameMode='local'
      r.framingPoints=[{position:center.clone().addScalar(-radius).toArray()},{position:center.clone().addScalar(radius).toArray()}]
      const duration=immediate||window.matchMedia('(prefers-reduced-motion: reduce)').matches?0:640
      const start=performance.now()
      root.current?.setAttribute('data-camera-motion','focusing')
      const step=now=>{
        if(r.disposed)return
        const t=duration?Math.min(1,(now-start)/duration):1, eased=t*t*(3-2*t)
        r.camera.position.lerpVectors(startPosition,targetPosition,eased)
        r.controls.target.lerpVectors(startTarget,targetCenter,eased)
        r.camera.zoom=startZoom+(targetZoom-startZoom)*eased
        r.camera.updateProjectionMatrix();r.controls.update();r.invalidate()
        if(t<1)r.motionRequest=requestAnimationFrame(step)
        else {r.motionRequest=null;root.current?.setAttribute('data-camera-motion','idle')}
      }
      if(duration)r.motionRequest=requestAnimationFrame(step);else step(start)
    }
    r.finishMorph=()=>{
      if(r.morphRequest!=null)cancelAnimationFrame(r.morphRequest)
      r.morphRequest=null;r.morphUniform.value=1
      if(r.morphCamera&&r.camera){r.camera.position.copy(r.morphCamera.position);r.controls.target.copy(r.morphCamera.target);r.camera.zoom=r.morphCamera.zoom;r.camera.updateProjectionMatrix();r.controls.update()}
      r.morphCamera=null;r.bridgeUniform.value=0;root.current?.setAttribute('data-transition-phase','idle');root.current?.setAttribute('data-transition-state','idle');if(r.entryPlayed)root.current?.setAttribute('data-entry-animation','complete')
    }
    r.startMorph=(from,oldCamera,entry=false,bridge=null)=>{
      r.finishMorph()
      r.startPositions=from;r.bridgePositions=bridge?new Map(bridge.points.map(p=>[p.product.id,p.position])):null;r.bridgeUniform.value=bridge?1:0;r.targetPositions=new Map(latest.current.universe.points.map(p=>[p.product.id,p.position]))
      if(!from.size&&!r.entryPlayed&&latest.current.dimensions===3&&!latest.current.facet&&!latest.current.radial){
        r.entryFrom=new Map(latest.current.universe.points.map(p=>[p.product.id,p.position.map(v=>v*.012)]));r.startPositions=r.entryFrom;r.morphUniform.value=0;return
      }
      if(!from.size){r.morphUniform.value=1;return}
      if(entry){r.entryPlayed=true;r.entryFrom=null;root.current?.setAttribute('data-entry-animation','expanding')}
      const destination={position:r.camera.position.clone(),target:r.controls.target.clone(),zoom:r.camera.zoom}
      const bridgeFit=bridge?fitPerspective(bridge.points.map(p=>p.position),{direction:[.9,.32,1],aspect:r.width/r.height,fov:r.camera.fov}):null
      const middle=bridgeFit?{position:new THREE.Vector3(...bridgeFit.position),target:new THREE.Vector3(...bridgeFit.target),zoom:1}:null
      r.morphCamera=destination;r.camera.position.copy(oldCamera.position);r.controls.target.copy(oldCamera.target);r.camera.zoom=oldCamera.zoom;r.controls.update()
      r.morphUniform.value=0;root.current?.setAttribute('data-transition-state','morphing')
      const duration=window.matchMedia('(prefers-reduced-motion: reduce)').matches?0:bridge?1800:entry?1400:760,start=performance.now()
      const step=now=>{if(r.disposed)return;const t=duration?Math.min(1,(now-start)/duration):1,e=entry?1-Math.pow(1-t,3):t*t*(3-2*t);const progress=bridge?(t<.375?t/.375*.5:t<.625?.5:.5+(t-.625)/.375*.5):e;r.morphUniform.value=progress
        const phase=t<.375?'to-overview':t<.625?'overview':'to-need';if(bridge)root.current?.setAttribute('data-transition-phase',phase)
        const u=bridge?(progress<.5?progress*2:progress*2-1):e,k=bridge?u*u*(3-2*u):u,a=bridge&&progress>=.5?middle:oldCamera,b=bridge&&progress<.5?middle:destination
        r.camera.position.lerpVectors(a.position,b.position,k);r.controls.target.lerpVectors(a.target,b.target,k);r.camera.zoom=a.zoom+(b.zoom-a.zoom)*k;r.camera.updateProjectionMatrix();r.controls.update();r.invalidate()
        if(t<1)r.morphRequest=requestAnimationFrame(step);else{r.morphRequest=null;r.morphCamera=null;root.current?.setAttribute('data-transition-phase','idle');root.current?.setAttribute('data-transition-state','idle');if(entry)root.current?.setAttribute('data-entry-animation','complete')}
      }
      if(duration)r.morphRequest=requestAnimationFrame(step);else step(start)
    }
    r.switchCamera(latest.current.dimensions)
    let measured = false
    r.observer = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect
      if (width <= 0 || height <= 0 || r.disposed) return
      r.cancelFocus?.()
      const oldWidth=r.width
      const oldAspect = r.width / r.height
      r.width = width; r.height = height;r.viewportUniform.value.set(width,height)
      renderer.setSize(width, height, false); r.updateFrustum()
      if (!measured) { measured = true; r.reset();if(r.entryFrom){const view={position:r.camera.position.clone(),target:r.controls.target.clone(),zoom:r.camera.zoom};view.position.sub(view.target).applyAxisAngle(new THREE.Vector3(0,1,0),.28).add(view.target);r.startMorph(r.entryFrom,view,true)} }
      else if(latest.current.radial&&(oldWidth!==width||r.morphRequest==null)){r.finishMorph();r.focusLocal(true)}
      else if (r.camera?.isPerspectiveCamera && r.morphRequest==null) {
        // Refit the same true universe/subset while preserving user rotation,
        // pan and zoom relative to its optimal framing at the previous aspect.
        const direction=r.camera.position.clone().sub(r.controls.target).normalize().toArray()
        const positions=(r.framingPoints||latest.current.universe.points).map(point=>point.position)
        const oldFit=fitPerspective(positions,{direction,aspect:oldAspect,fov:r.camera.fov})
        const newFit=fitPerspective(positions,{direction,aspect:width/height,fov:r.camera.fov})
        const pan=r.controls.target.clone().sub(new THREE.Vector3(...oldFit.target))
        const zoomRatio=r.camera.position.distanceTo(r.controls.target)/oldFit.distance
        r.controls.target.fromArray(newFit.target).add(pan)
        r.camera.position.copy(r.controls.target).add(new THREE.Vector3(...direction).multiplyScalar(newFit.distance*zoomRatio))
        r.syncClip()
        r.controls.update()
      }
      // Changing a canvas size clears its drawing buffer. ResizeObserver runs
      // after animation callbacks, so waiting for another RAF leaves one blank
      // paint that fast screenshots/compositors can capture. Draw before paint.
      r.flush()
    })
    r.observer.observe(root.current)
    let down = null
    const pointer = event => { const rect = canvas.current.getBoundingClientRect(); return { x: event.clientX - rect.left, y: event.clientY - rect.top } }
    const hit = event => { const at = pointer(event); return screenHits(r.drawn.map(r.project).filter(Boolean), at.x, at.y, Math.max(7, latest.current.pointSize * 1.5)) }
    const onDown = event => { if (event.button === 0) down = { x: event.clientX, y: event.clientY, moved: false }; setHover(null) }
    const onMove = event => {
      if (down) { if (Math.hypot(event.clientX-down.x, event.clientY-down.y)>5) down.moved=true; return }
      const hits = hit(event), at = pointer(event)
      setHover(hits.length ? { product: hits[0], count:latest.current.spreadCoincident&&!event.shiftKey?1:hits.length,...at } : null)
    }
    const onUp = event => {
      const previous = down; down = null
      if(r.morphRequest!=null)return
      if (!previous || previous.moved || event.button !== 0) return
      const hits = hit(event); setHover(null)
      if(!hits.length&&latest.current.selected!=null){latest.current.onClear?.();return}
      const distinct=hits.map(p=>latest.current.universe.byId.get(p.id)).filter(Boolean)
      if(hits.length&&(latest.current.spreadCoincident||(latest.current.radial&&groupCoincidentPoints(distinct).length===hits.length))&&!event.shiftKey){
        const at=pointer(event),candidates=hits.map(p=>r.project(latest.current.universe.byId.get(p.id))).filter(Boolean)
        const nearest=nearestVisiblePoint(candidates,at.x,at.y,Math.max(7,latest.current.pointSize*1.5))
        if(nearest)latest.current.onSelect?.(nearest)
        return
      }
      if (hits.length === 1) latest.current.onSelect?.(hits[0])
      else if (hits.length > 1) {
        const positions=hits.map(product=>latest.current.universe.byId.get(product.id)).filter(Boolean)
        latest.current.onCoincident?.(hits,{kind:groupCoincidentPoints(positions).length===1?'projection':'screen'})
      }
    }
    const onLeave = () => setHover(null)
    const onCancel = () => { down = null; setHover(null) }
    const onKey = event => {
      if(event.key==='Escape'&&latest.current.selected!=null){event.preventDefault();latest.current.onClear?.();return}
      if(['+','=','-','Home','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)){r.finishMorph();r.cancelFocus()}
      if (['+', '=', '-', 'Home'].includes(event.key)) {
        event.preventDefault(); event.key === 'Home' ? (latest.current.onClear?latest.current.onClear():r.reset()) : r.zoom(event.key === '-' ? 1/1.3 : 1.3); return
      }
      if (!event.key.startsWith('Arrow')) return
      event.preventDefault()
      if (r.dimensions === 3) {
        const spherical = new THREE.Spherical().setFromVector3(r.camera.position.clone().sub(r.controls.target))
        if (event.key === 'ArrowLeft') spherical.theta -= .12
        if (event.key === 'ArrowRight') spherical.theta += .12
        if (event.key === 'ArrowUp') spherical.phi -= .12
        if (event.key === 'ArrowDown') spherical.phi += .12
        spherical.makeSafe(); r.camera.position.copy(r.controls.target).add(new THREE.Vector3().setFromSpherical(spherical))
      } else {
        const step = .12 / r.camera.zoom
        const vector = new THREE.Vector3(event.key === 'ArrowLeft' ? -step : event.key === 'ArrowRight' ? step : 0,
          event.key === 'ArrowUp' ? step : event.key === 'ArrowDown' ? -step : 0, 0)
        r.camera.position.add(vector); r.controls.target.add(vector)
      }
      r.controls.update(); r.invalidate()
    }
    const onLost = event => { event.preventDefault(); setFailure('WebGL 图形上下文已中断。') }
    const listeners = [['pointerdown',onDown],['pointermove',onMove],['pointerup',onUp],['pointerleave',onLeave],['pointercancel',onCancel],['keydown',onKey],['webglcontextlost',onLost]]
    const element = canvas.current
    listeners.forEach(([name, listener]) => element.addEventListener(name, listener))
    return () => {
      r.finishMorph()
      r.cancelFocus()
      r.disposed = true
      if (r.request != null) cancelAnimationFrame(r.request)
      r.observer.disconnect(); r.controls.dispose()
      listeners.forEach(([name, listener]) => element.removeEventListener(name, listener))
      delete element.getScreenPoint
      disposeGroup(cloud); disposeGroup(axes); disposeGroup(envelope);texture.dispose(); renderer.dispose()
      if (runtime.current === r) runtime.current = null
      // StrictMode immediately mounts another renderer on this same canvas. Dispose
      // GPU resources now, but lose the context only after checking it was not reused.
      queueMicrotask(() => { if (runtime.current?.element !== element) renderer.forceContextLoss() })
    }
  }, [attempt])

  useEffect(() => {
    const r = runtime.current
    if (!r || r.disposed) return
    const from=new Map(r.drawn.map(p=>[p.product.id,r.positionFor(p)])),oldCamera={position:r.camera.position.clone(),target:r.controls.target.clone(),zoom:r.camera.zoom}
    r.finishMorph();r.cancelFocus();r.switchCamera(dimensions)
    if(radial)r.focusLocal(true)
    r.cancelFocus()
    const bridge=r.lastFacet&&facet&&r.lastFacet!==facet&&!radial&&!r.lastRadial?base:null
    r.lastFacet=facet;r.lastRadial=radial
    r.startMorph(from,oldCamera,false,bridge)
    disposeGroup(r.axes)
    setHover(null); r.invalidate()
  }, [universe, dimensions, algorithm, attempt])

  useEffect(() => {
    const r = runtime.current
    if (!r || r.disposed) return
    disposeGroup(r.cloud)
    r.drawn = drawn
    r.axes.visible = false
    // Keeping tight selected neighborhoods near a local origin prevents GPU
    // Float32 cancellation at high zoom without altering any world coordinate.
    const origin=universe.byId.get(selected)?.position||[0,0,0]
    r.cloud.position.fromArray(origin)
    const neighborIds = new Set(neighbors.map(p => p.id)), groups = [[], [], []]
    const reference=universe.byId.get(selected)?.position
    const distanceFor=p=>reference?Math.hypot(...p.position.map((v,i)=>v-reference[i])):0
    const fadeScale=Math.max(.001,...drawn.map(distanceFor))*.42
    r.opacityById=new Map()
    let colorMax = 1
    if(colorBy==='need')colorMax=Math.max(1,...products.map(p=>Number.isFinite(p.need_score)?p.need_score:0))
    if (Number.isInteger(colorBy)) for (const p of products) colorMax = Math.max(colorMax, Number.isFinite(p.scores?.[colorBy]) ? p.scores[colorBy] : 0)
    for (const point of drawn) groups[point.product.id === selected ? 2 : facet&&!radial ? (point.price_missing?0:1) : neighborIds.has(point.product.id) ? 1 : 0].push(point)
    groups.forEach((points, index) => {
      if (!points.length) return
      const positions = new Float32Array(points.length * 3), targets=new Float32Array(points.length*3),bridges=new Float32Array(points.length*3),bridgeColors=new Float32Array(points.length*3), colors = new Float32Array(points.length * 3),alphas=new Float32Array(points.length),offsets=new Float32Array(points.length*2),color = new THREE.Color()
      points.forEach((point, i) => {
        const start=r.startPositions?.get(point.product.id)||point.position
        positions.set(start.map((v,axis)=>v-origin[axis]), i * 3)
        targets.set(point.position.map((v,axis)=>v-origin[axis]),i*3)
        bridges.set((r.bridgePositions?.get(point.product.id)||point.position).map((v,axis)=>v-origin[axis]),i*3)
        offsets.set(effectiveSpread?(displayOffsets.get(point.product.id)||[0,0]):[0,0],i*2)
        alphas[i]=(facet&&!radial&&point.need_missing?.38:1)*(reference?distanceOpacity(distanceFor(point),fadeScale):1)
        if(point.product.id===selected)alphas[i]=1
        r.opacityById.set(point.product.id,alphas[i])
        color.set(pointColor(point.product, { selected, neighborIds, colorBy, colorMax })); color.toArray(colors, i * 3)
        color.set(pointColor(point.product,{colorBy:'family'}));color.toArray(bridgeColors,i*3)
      })
      const geometry = new THREE.BufferGeometry()
      geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
      geometry.setAttribute('morphTarget',new THREE.BufferAttribute(targets,3))
      geometry.setAttribute('bridgeTarget',new THREE.BufferAttribute(bridges,3))
      geometry.setAttribute('bridgeColor',new THREE.BufferAttribute(bridgeColors,3))
      geometry.setAttribute('displayOffset',new THREE.BufferAttribute(offsets,2))
      geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3))
      geometry.setAttribute('displayAlpha',new THREE.BufferAttribute(alphas,1))
      const material = new THREE.PointsMaterial({ size: Math.max(1, Math.min(24, pointSize)) * [radial?.75:facet?.7:1, 1.3, 1.9][index], sizeAttenuation: false,
        map: r.texture, vertexColors: true, transparent: true, opacity: selected!=null?1:index ? 1 : facet&&!radial ? (dimensions===2?.78:.38) : radial ? .36 : facet ? .8 : selected != null ? .22 : .85,
        alphaTest: .1, depthWrite: false, depthTest: index === 0 })
      material.onBeforeCompile=shader=>{
        shader.uniforms.cfzViewport=r.viewportUniform
        shader.uniforms.cfzDepth=r.depthUniform
        shader.uniforms.cfzMorph=r.morphUniform
        shader.uniforms.cfzBridge=r.bridgeUniform
        shader.uniforms.cfzBallCamera=r.ballCamera
        shader.uniforms.cfzProjection=r.ballProjection
        shader.uniforms.cfzBallOffsetLimit=r.ballOffsetLimit
        shader.uniforms.cfzRadial=r.radialUniform
        shader.vertexShader=shader.vertexShader.replace('#include <common>','#include <common>\nattribute vec2 displayOffset;\nattribute float displayAlpha;\nvarying float cfzDisplayAlpha;\nattribute vec3 morphTarget;\nattribute vec3 bridgeTarget;\nattribute vec3 bridgeColor;\nuniform float cfzBridge;\nuniform float cfzMorph;\nuniform vec2 cfzViewport;\nuniform vec2 cfzDepth;\nvarying float cfzDepthOpacity;'+BALL_OFFSET_GLSL)
          .replace('#include <color_vertex>','#include <color_vertex>\nvColor.rgb=mix(vColor.rgb,bridgeColor,cfzBridge*smoothstep(0.0,.8,1.0-abs(cfzMorph*2.0-1.0)));')
          .replace('#include <begin_vertex>','float u=cfzMorph<.5?cfzMorph*2.0:cfzMorph*2.0-1.0;float eased=u*u*(3.0-2.0*u);vec3 via=cfzMorph<.5?mix(position,bridgeTarget,eased):mix(bridgeTarget,morphTarget,eased);vec3 transformed = cfzBridge>.5?via:mix(position,morphTarget,cfzMorph); cfzDisplayAlpha = displayAlpha;')
          .replace('#include <project_vertex>','#include <project_vertex>\nvec2 cfzPixel=vec2((gl_Position.x/gl_Position.w+1.0)*cfzViewport.x*.5,(1.0-gl_Position.y/gl_Position.w)*cfzViewport.y*.5);\nvec2 cfzOffset=cfzRadial>.5 ? cfzBoundOffset(cfzPixel,displayOffset) : displayOffset;\ngl_Position.xy += vec2(cfzOffset.x,-cfzOffset.y) * 2.0 / cfzViewport * gl_Position.w;\nfloat cfzScale = cfzDepth.y > .5 ? clamp(cfzDepth.x / max(.000001, -mvPosition.z), .65, 1.55) : 1.0;\ncfzDepthOpacity = cfzDepth.y > .5 ? clamp(.4 + .6 * cfzScale, .55, 1.0) : 1.0;')
        shader.vertexShader=shader.vertexShader.replace('gl_PointSize = size;','gl_PointSize = size * cfzScale;')
        shader.fragmentShader=shader.fragmentShader.replace('#include <common>','#include <common>\nvarying float cfzDepthOpacity;\nvarying float cfzDisplayAlpha;').replace('#include <opaque_fragment>','#include <opaque_fragment>\ngl_FragColor.a *= cfzDepthOpacity * cfzDisplayAlpha;')
      }
      material.customProgramCacheKey=()=> 'projector-display-morph-bridge-v5'
      const mesh = new THREE.Points(geometry, material); mesh.renderOrder = index + 1;mesh.frustumCulled=false
      r.cloud.add(mesh)
    })
    r.invalidate()
  }, [drawn, products, neighbors, selected, pointSize, colorBy, showLabels, labelBy, spreadCoincident,displayOffsets,attempt])

  useEffect(()=>{const r=runtime.current;if(!r)return;r.cancelFocus();return()=>r.cancelFocus()},[selected,universe,attempt])

  useEffect(()=>{runtime.current?.invalidate()},[overlayExpanded])

  useEffect(()=>{
    const r=runtime.current;if(!r)return;disposeGroup(r.envelope);r.silhouette=null
    if(radial&&selected!=null){const radius=basis==='evidence'?Math.max(0,1-threshold)+1e-6:similarityRadius(threshold)
      const surface=new THREE.Mesh((dimensions===2?new THREE.CircleGeometry(radius,64):new THREE.SphereGeometry(radius,48,32)),new THREE.MeshBasicMaterial({color:'#70a6e6',transparent:true,opacity:.065,depthWrite:false,side:dimensions===2?THREE.DoubleSide:THREE.BackSide}));r.envelope.add(surface)
      const rimPoints=Array.from({length:96},(_,i)=>new THREE.Vector3(Math.cos(i/96*Math.PI*2)*radius,Math.sin(i/96*Math.PI*2)*radius,0))
      r.silhouette=new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(rimPoints),new THREE.LineBasicMaterial({color:'#85ade0',transparent:true,opacity:.35,depthWrite:false,depthTest:false}))
      r.silhouette.renderOrder=0;r.envelope.add(r.silhouette)
    }r.invalidate()
  },[radial,selected,threshold,basis,dimensions,attempt])

  const currentLabelIds = new Set(selected == null ? [] : [selected,...neighbors.map(p=>p.id)])
  const activeLabels = showLabels ? frameInfo.labels.filter(label=>currentLabelIds.has(label.product.id)) : []

  return <div ref={root} className="projector-stage" style={ROOT_STYLE} data-testid="projector-stage"
    data-transition-phase="idle" data-entry-animation="pending" data-envelope-style="surface" data-context-opacity={radial?.36:undefined} data-transition-state="idle" data-view-kind={radial?'similarity':facet?'need':'overview'} data-sphere-radius={radial?(basis==='evidence'?1-threshold+1e-6:similarityRadius(threshold)):undefined} data-display-axes={dimensions===3&&!radial?DISPLAY_AXES.join(','):'1,1,1'} data-camera-motion="idle" data-spread-coincident={effectiveSpread} data-rendered-count={failure ? 0 : drawn.length} data-unplaced-count={universe.missingIds.length} data-dimensions={dimensions} data-algorithm={algorithm}
    data-camera-revision={frameInfo.revision} data-renderer-state={failure ? 'unavailable' : frameInfo.revision ? 'ready' : 'starting'}>
    <canvas key={attempt} ref={canvas} data-testid="projector-canvas" tabIndex={failure ? -1 : 0} role="img"
      data-rendered-count={failure ? 0 : drawn.length} data-dimensions={dimensions} data-algorithm={algorithm} data-camera-revision={frameInfo.revision}
      aria-label={`${radial?'原始相似距离范围':facet?`${facet}需求平面`:`${dimensions}D ${algorithm.toUpperCase()} 产品投影`}，${drawn.length} 款有坐标产品。${dimensions === 3 ? '拖动旋转' : '拖动平移'}，滚轮缩放。方向键操作视图，Home 复位。全部产品也可通过搜索和列表选择。`}
      style={{ display:'block', width:'100%', height:'100%', outlineOffset:-3, touchAction:'none', visibility:failure?'hidden':'visible' }}/>
    {!failure && frameInfo.needAxes && <svg data-testid="projector-need-axes" data-scale={`${frameInfo.needAxes.xMax},${frameInfo.needAxes.yMax}`} role="img" aria-label={`${facet}成分证据指数与已收录成分数`} width="100%" height="100%" style={{position:'absolute',inset:0,pointerEvents:'none',zIndex:1,opacity:frameInfo.needAxes.opacity,fontFamily:'inherit',fontSize:10,overflow:'hidden'}}>
      <g fill="#687080" stroke="#e9edf3" strokeWidth=".7">
        {frameInfo.needAxes.zTicks.map(t=><g key={`z-${t.value}`}><line x1={t.x} y1={t.y} x2={t.end.x} y2={t.end.y}/><text x={t.x-7} y={t.y+12} textAnchor="end" stroke="none">¥{Math.round(t.value)}</text></g>)}
        {frameInfo.needAxes.yTicks.map(t=><g key={`y-${t.value}`}><line x1={t.x} y1={t.y} x2={t.end.x} y2={t.end.y}/><text x={t.x-10} y={t.y+3} textAnchor="end" stroke="none">{Number(t.value.toFixed(2))}</text></g>)}
        {frameInfo.needAxes.xTicks.map(t=><g key={`x-${t.value}`}><line x1={t.x} y1={t.y} x2={t.end.x} y2={t.end.y}/><text x={t.x} y={t.y+18} textAnchor="middle" stroke="none">{Number(t.value.toFixed(1))}</text></g>)}
      </g>
      <path d={`M${frameInfo.needAxes.topLeft.x},${frameInfo.needAxes.topLeft.y}L${frameInfo.needAxes.origin.x},${frameInfo.needAxes.origin.y}L${frameInfo.needAxes.bottomRight.x},${frameInfo.needAxes.bottomRight.y}`} stroke="#a9b3c3" strokeWidth="1" fill="none"/>
      {frameInfo.needAxes.is3D&&<line x1={frameInfo.needAxes.origin.x} y1={frameInfo.needAxes.origin.y} x2={frameInfo.needAxes.zEnd.x} y2={frameInfo.needAxes.zEnd.y} stroke="#9aabca" strokeWidth="1"/>}
      <g fill="#4c5564" fontSize="11" fontWeight="500">
        {frameInfo.needAxes.is3D&&<text x={Math.max(8,Math.min((root.current?.clientWidth||600)-115,frameInfo.needAxes.zEnd.x-12))} y={frameInfo.needAxes.zEnd.y+30}>{frameInfo.needAxes.zLabel}</text>}
        <text x={frameInfo.needAxes.origin.x} y={frameInfo.needAxes.corner.y-17}>{frameInfo.needAxes.yLabel||`${facet}成分证据指数`}</text>
        <text x={(frameInfo.needAxes.origin.x+frameInfo.needAxes.corner.x)/2} y={frameInfo.needAxes.origin.y+37} textAnchor="middle">{frameInfo.needAxes.xLabel||'已收录成分数（项）'}</text>
      </g>

    </svg>}
    {!failure && <svg aria-hidden="true" width="100%" height="100%" style={{position:'absolute',inset:0,pointerEvents:'none',zIndex:2}}>
      {frameInfo.spreadLeaders?.map(p=><line key={`spread-${p.product.id}`} x1={p.rawX} y1={p.rawY} x2={p.x} y2={p.y} stroke="#a4adbc" strokeWidth=".6" opacity=".6"/>)}
      {activeLabels.filter(label=>label.leader).map(label=><line key={label.product.id} {...label.leader} stroke={label.product.id===selected?'#96004f':'#b08b45'} strokeWidth=".7" opacity=".65"/>)}
    </svg>}
    {!failure && !effectiveSpread && frameInfo.badges.filter(badge=>!radial||badge.members.some(p=>currentLabelIds.has(p.product.id))).map(badge=><button key={badge.key} type="button" className="projector-coincident-badge"
      data-coincident-count={badge.count} data-testid="projector-coincident-badge"
      aria-label={`同一显示位置 ${badge.count} 款，展开产品记录。投影位置相同不代表同一产品、配方或原始向量。`}
      title={`同一显示位置 ${badge.count} 款，点击展开；不代表同一产品、配方或原始向量。`}
      onClick={()=>latest.current.onCoincident?.(badge.members.map(p=>p.product),{kind:radial?'similarity-position':'projection'})}
      style={{position:'absolute',left:badge.left,top:badge.top,width:badge.width,height:badge.height,zIndex:5,
        border:0,background:'transparent',color:'#555a75',fontFamily:'inherit',fontSize:10,cursor:'pointer',padding:0,whiteSpace:'nowrap',display:'grid',placeItems:'center'}}
    ><span style={{display:'inline-block',border:'1px solid #d3d7e5',borderRadius:12,background:'#fffffff2',padding:'3px 5px',lineHeight:'14px',whiteSpace:'nowrap'}}>{badge.count}款</span></button>)}
    {!failure && !effectiveSpread && !radial && frameInfo.coincidentGroups.length>0 && <button type="button" className="projector-coincident-summary"
      title="查看当前画面中位于同一显示位置的产品记录组；不代表同配方或相同原始向量。"
      onClick={()=>{const groups=frameInfo.coincidentGroups.map(group=>group.members.map(p=>p.product));latest.current.onCoincident?.(groups.flat(),{kind:'projection-groups',groups})}}
      style={{position:'absolute',left:14,bottom:14,zIndex:5,border:'1px solid #e3e5ed',background:'#ffffffed',color:'#777c90',fontFamily:'inherit',fontSize:10,padding:'7px 9px',borderRadius:4,cursor:'pointer'}}
    >同位 {frameInfo.coincidentGroups.length} 组 · 查看记录</button>}
    {!failure && activeLabels.map(label => <button type="button" key={label.product.id} className={`projector-point-label ${label.product.id === selected ? 'is-selected' : ''}`}
      aria-label={`选择 ${label.product.name}`} title={label.product.name} onClick={() => latest.current.onSelect?.(label.product)}
      style={{ position:'absolute', left:label.left, top:label.top, width:label.width, height:label.height, boxSizing:'border-box',
        border:0, padding:'1px 3px', background:label.product.id===selected?'#fffffff2':'#ffffffd9', color:label.product.id===selected?'#4f0030':'#555',
        fontFamily:'inherit',fontSize:label.fontSize, fontWeight:label.product.id===selected?600:400, lineHeight:1.3, textAlign:'left',
        whiteSpace:'nowrap', textOverflow:'ellipsis', overflow:'hidden', zIndex:label.product.id===selected?4:3, cursor:'pointer' }}>{label.text}</button>)}
    {!failure && hover && <div role="status" className="projector-hover" style={{ position:'absolute', left:Math.max(4,Math.min(hover.x+12,(root.current?.clientWidth||300)-238)), top:Math.max(4,hover.y-55),
      pointerEvents:'none', zIndex:5, maxWidth:230, padding:'7px 10px', color:'#555', background:'#fffffff2', boxShadow:'0 1px 5px #0002', fontSize:11 }}>
      <span>{hover.product.name}</span>{facet&&!radial&&<small style={{display:'block'}}>已收录成分 {Number.isFinite(hover.product.ingredient_count)?hover.product.ingredient_count:'未知'} 项 · {facet}证据指数 {Number.isFinite(hover.product.need_score)?hover.product.need_score:'资料不足'} · 参考价 {Number.isFinite(hover.product.price_current)?`¥${hover.product.price_current}`:'未收录'}</small>}{hover.count>1&&<small style={{display:'block'}}>点击范围内 {hover.count} 款记录，点击展开</small>}</div>}
    {!failure && drawn.length === 0 && <p role="status" style={{ ...OVERLAY_STYLE, pointerEvents:'none' }}>当前投影暂无可用坐标。仍可通过搜索或产品列表选择产品。</p>}
    {failure && <div role="alert" style={OVERLAY_STYLE}><strong>{failure}</strong><p>可继续通过搜索和产品列表查看资料、加入对比。</p>
      <button type="button" onClick={() => { setFrameInfo({ revision:0,labels:[],badges:[],coincidentGroups:[] }); setAttempt(n=>n+1) }} style={{border:'1px solid #aaa',borderRadius:3,padding:'8px 14px',background:'#fff',cursor:'pointer'}}>重试图形渲染</button></div>}
  </div>
})
