import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { normalizeUniverse, visibleProducts, screenHits, pointColor, layoutLabels, fitPerspective } from './projectorGeometry.mjs'

const EMPTY = []
const DEFAULT_AXES = [0, 1, 2]
const ROOT_STYLE = { position: 'relative', width: '100%', height: '100%', minHeight: 320, overflow: 'hidden', background: '#fff' }
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
  onSelect, onCoincident }, ref) {
  const root = useRef(null), canvas = useRef(null), runtime = useRef(null)
  const [attempt, setAttempt] = useState(0), [failure, setFailure] = useState(null)
  const [frameInfo, setFrameInfo] = useState({ revision: 0, labels: [] })
  const [hover, setHover] = useState(null)
  const axisKey = JSON.stringify(axisOrder)
  const universe = useMemo(() => normalizeUniverse(products, algorithm, dimensions, axisOrder), [products, algorithm, dimensions, axisKey])
  const drawn = useMemo(() => visibleProducts(universe.points, selected, neighbors, isolated), [universe, selected, neighbors, isolated])
  const latest = useRef(null)
  latest.current = { products, selected, neighbors, isolated, pointSize, colorBy, showLabels, labelBy, onSelect, onCoincident, universe, drawn, dimensions }

  useImperativeHandle(ref, () => ({
    reset: () => runtime.current?.reset(),
    focusSelection: () => runtime.current?.focusSelection(),
    zoom: factor => runtime.current?.zoom(factor),
    getScreenPoint: id => runtime.current?.getScreenPoint(id) ?? null,
  }), [])

  useEffect(() => {
    let renderer
    try { renderer = new THREE.WebGLRenderer({ canvas: canvas.current, antialias: true, alpha: false, powerPreference: 'low-power', preserveDrawingBuffer:true }) }
    catch { setFailure('当前浏览器无法启用 WebGL 图形渲染。'); return }
    setFailure(null)
    renderer.setClearColor(0xffffff, 1)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    const scene = new THREE.Scene(), cloud = new THREE.Group(), axes = new THREE.Group(), texture = circleTexture()
    const labelMeasure = document.createElement('canvas').getContext('2d')
    scene.add(cloud, axes)
    const r = { renderer, element:canvas.current, scene, cloud, axes, texture, width: 1, height: 1, camera: null, controls: null,
      dimensions: latest.current.dimensions, request: null, disposed: false, drawn: [], observer: null }
    runtime.current = r

    r.project = point => {
      if (!r.camera || r.disposed) return null
      r.camera.updateMatrixWorld()
      const vector = new THREE.Vector3(...point.position).project(r.camera)
      const x = (vector.x + 1) * r.width / 2, y = (1 - vector.y) * r.height / 2
      return { product: point.product, x, y, depth: vector.z,
        visible: Number.isFinite(x) && Number.isFinite(y) && vector.z >= -1 && vector.z <= 1 && x >= 0 && x <= r.width && y >= 0 && y <= r.height }
    }
    r.getScreenPoint = id => {
      const point = r.drawn.find(p => p.product.id === id)
      if (!point) return null
      const projected = r.project(point), rect = canvas.current.getBoundingClientRect()
      return projected ? { x: projected.x, y: projected.y, clientX: rect.left + projected.x, clientY: rect.top + projected.y,
        visible: projected.visible, depth: projected.depth } : null
    }
    // This DOM method exposes the same actual projection as the React ref for browser acceptance tests.
    canvas.current.getScreenPoint = r.getScreenPoint
    r.paint = () => {
        r.request = null
        if (r.disposed || !r.camera || renderer.getContext().isContextLost()) return
        r.syncClip()
        renderer.render(scene, r.camera)
        const props = latest.current
        const neighborIds = new Set(props.neighbors.map(p => p.id))
        const rank = new Map(props.neighbors.map((p,i)=>[p.id,i]))
        const projected = props.showLabels && props.selected != null ? r.drawn
          .filter(p => p.product.id === props.selected || neighborIds.has(p.product.id))
          .sort((a, b) => Number(b.product.id === props.selected) - Number(a.product.id === props.selected)
            || (rank.get(a.product.id) ?? Infinity) - (rank.get(b.product.id) ?? Infinity))
          .slice(0, 101).map(r.project).filter(p => p?.visible) : []
        const fontFamily = getComputedStyle(root.current).fontFamily
        const labels = layoutLabels(projected,{width:r.width,height:r.height,selected:props.selected,pointSize:props.pointSize,labelBy:props.labelBy,
          measure:labelMeasure?(text,fontSize,primary)=>{labelMeasure.font=`${primary?600:400} ${fontSize}px ${fontFamily}`;return labelMeasure.measureText(text).width}:undefined})
        setFrameInfo(old => ({ revision: old.revision + 1, labels }))
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
      if (r.dimensions === 2) {
        const halfHeight = 1.25 * Math.max(1, 1 / aspect)
        r.camera.left = -halfHeight * aspect; r.camera.right = halfHeight * aspect
        r.camera.top = halfHeight; r.camera.bottom = -halfHeight
      } else r.camera.aspect = aspect
      r.camera.updateProjectionMatrix()
    }
    r.syncClip = () => {
      if (r.dimensions !== 3 || !r.camera) return
      const distance = r.camera.position.distanceTo(r.controls.target)
      r.camera.near = Math.max(1e-12,distance*1e-5)
      r.camera.far = Math.max(1000,distance*100)
      r.camera.updateProjectionMatrix()
    }
    r.reset = () => {
      if (!r.camera || r.disposed) return
      r.framingPoints = latest.current.universe.points
      r.frameMode = 'universe'; r.axes.visible = !latest.current.isolated
      r.controls.target.set(0, 0, 0)
      if (r.dimensions === 2) { r.camera.position.set(0, 0, 5); r.camera.up.set(0, 1, 0); r.camera.zoom = 1 }
      else {
        const fit = fitPerspective(r.framingPoints.map(point=>point.position),{aspect:r.width/r.height,fov:r.camera.fov})
        r.controls.target.fromArray(fit.target);r.camera.position.fromArray(fit.position);r.camera.zoom = 1
      }
      r.updateFrustum();r.syncClip(); r.controls.update(); r.invalidate()
    }
    r.switchCamera = dims => {
      r.controls?.dispose()
      r.dimensions = dims
      r.camera = dims === 2 ? new THREE.OrthographicCamera(-2, 2, 2, -2, .01, 1000)
        : new THREE.PerspectiveCamera(42, r.width / r.height, .01, 1000)
      r.controls = new OrbitControls(r.camera, canvas.current)
      r.controls.enableDamping = false
      r.controls.enableRotate = dims === 3
      r.controls.screenSpacePanning = true
      r.controls.minDistance = 1e-10; r.controls.maxDistance = 1000
      r.controls.minZoom = .08; r.controls.maxZoom = 1e9
      r.controls.mouseButtons.LEFT = dims === 2 ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE
      r.controls.touches.ONE = dims === 2 ? THREE.TOUCH.PAN : THREE.TOUCH.ROTATE
      r.controls.addEventListener('change', r.invalidate)
      r.reset()
    }
    r.zoom = factor => {
      if (!Number.isFinite(factor) || factor <= 0 || !r.camera || r.disposed) return
      if (r.dimensions === 2) r.camera.zoom = THREE.MathUtils.clamp(r.camera.zoom * factor, .08, 1e9)
      else {
        const offset = r.camera.position.clone().sub(r.controls.target)
        const length = THREE.MathUtils.clamp(offset.length() / factor, r.controls.minDistance, r.controls.maxDistance)
        r.camera.position.copy(r.controls.target).add(offset.normalize().multiplyScalar(length))
      }
      r.camera.updateProjectionMatrix(); r.controls.update(); r.invalidate()
    }
    r.focusSelection = () => {
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
      if (r.dimensions === 2) {
        r.camera.position.copy(center).add(new THREE.Vector3(0, 0, 5))
        r.camera.zoom = THREE.MathUtils.clamp(Math.min((r.camera.right-r.camera.left) / Math.max(1e-10, size.x),
          (r.camera.top-r.camera.bottom) / Math.max(1e-10, size.y)) * .8, .08, 1e9)
      } else {
        const fit=fitPerspective(subset.map(point=>point.position),{direction:direction.toArray(),aspect:r.width/r.height,fov:r.camera.fov})
        r.controls.target.fromArray(fit.target);r.camera.position.fromArray(fit.position)
      }
      r.syncClip();r.camera.updateProjectionMatrix(); r.controls.update(); r.invalidate()
    }
    r.switchCamera(latest.current.dimensions)
    let measured = false
    r.observer = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect
      if (width <= 0 || height <= 0 || r.disposed) return
      const oldAspect = r.width / r.height
      r.width = width; r.height = height
      renderer.setSize(width, height, false); r.updateFrustum()
      if (!measured) { measured = true; r.reset() }
      else if (r.dimensions === 3) {
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
    const hit = event => { const at = pointer(event); return screenHits(r.drawn.map(r.project).filter(Boolean), at.x, at.y, Math.max(7, latest.current.pointSize * .85)) }
    const onDown = event => { if (event.button === 0) down = { x: event.clientX, y: event.clientY, moved: false }; setHover(null) }
    const onMove = event => {
      if (down) { if (Math.hypot(event.clientX-down.x, event.clientY-down.y)>5) down.moved=true; return }
      const hits = hit(event), at = pointer(event)
      setHover(hits.length ? { product: hits[0], count: hits.length, ...at } : null)
    }
    const onUp = event => {
      const previous = down; down = null
      if (!previous || previous.moved || event.button !== 0) return
      const hits = hit(event); setHover(null)
      if (hits.length === 1) latest.current.onSelect?.(hits[0])
      else if (hits.length > 1) latest.current.onCoincident?.(hits)
    }
    const onLeave = () => setHover(null)
    const onCancel = () => { down = null; setHover(null) }
    const onKey = event => {
      if (['+', '=', '-', 'Home'].includes(event.key)) {
        event.preventDefault(); event.key === 'Home' ? r.reset() : r.zoom(event.key === '-' ? 1/1.3 : 1.3); return
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
      r.disposed = true
      if (r.request != null) cancelAnimationFrame(r.request)
      r.observer.disconnect(); r.controls.dispose()
      listeners.forEach(([name, listener]) => element.removeEventListener(name, listener))
      delete element.getScreenPoint
      disposeGroup(cloud); disposeGroup(axes); texture.dispose(); renderer.dispose()
      if (runtime.current === r) runtime.current = null
      // StrictMode immediately mounts another renderer on this same canvas. Dispose
      // GPU resources now, but lose the context only after checking it was not reused.
      queueMicrotask(() => { if (runtime.current?.element !== element) renderer.forceContextLoss() })
    }
  }, [attempt])

  useEffect(() => {
    const r = runtime.current
    if (!r || r.disposed) return
    r.switchCamera(dimensions)
    disposeGroup(r.axes)
    const colors = ['#e97133', '#68bc20', '#4d79e8']
    for (let axis = 0; axis < dimensions; axis++) {
      const start = [0,0,0], end = [0,0,0]; end[axis] = 1.15
      const geometry = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(...start), new THREE.Vector3(...end)])
      const material = new THREE.LineBasicMaterial({ color: colors[axis], transparent: true, opacity: .8 })
      r.axes.add(new THREE.Line(geometry, material))
    }
    setHover(null); r.invalidate()
  }, [universe, dimensions, algorithm, attempt])

  useEffect(() => {
    const r = runtime.current
    if (!r || r.disposed) return
    disposeGroup(r.cloud)
    r.drawn = drawn
    r.axes.visible = !isolated && r.frameMode !== 'selection'
    // Keeping tight selected neighborhoods near a local origin prevents GPU
    // Float32 cancellation at high zoom without altering any world coordinate.
    const origin=universe.byId.get(selected)?.position||[0,0,0]
    r.cloud.position.fromArray(origin)
    const neighborIds = new Set(neighbors.map(p => p.id)), groups = [[], [], []]
    let colorMax = 1
    if (Number.isInteger(colorBy)) for (const p of products) colorMax = Math.max(colorMax, Number.isFinite(p.scores?.[colorBy]) ? p.scores[colorBy] : 0)
    for (const point of drawn) groups[point.product.id === selected ? 2 : neighborIds.has(point.product.id) ? 1 : 0].push(point)
    groups.forEach((points, index) => {
      if (!points.length) return
      const positions = new Float32Array(points.length * 3), colors = new Float32Array(points.length * 3), color = new THREE.Color()
      points.forEach((point, i) => {
        positions.set(point.position.map((v,axis)=>v-origin[axis]), i * 3)
        color.set(pointColor(point.product, { selected, neighborIds, colorBy, colorMax })); color.toArray(colors, i * 3)
      })
      const geometry = new THREE.BufferGeometry()
      geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
      geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3))
      const material = new THREE.PointsMaterial({ size: Math.max(1, Math.min(24, pointSize)) * [1, 1.3, 1.9][index], sizeAttenuation: false,
        map: r.texture, vertexColors: true, transparent: true, opacity: index ? .95 : selected != null ? .5 : .65,
        alphaTest: .1, depthWrite: false, depthTest: index === 0 })
      const mesh = new THREE.Points(geometry, material); mesh.renderOrder = index + 1
      r.cloud.add(mesh)
    })
    r.invalidate()
  }, [drawn, products, neighbors, selected, pointSize, colorBy, showLabels, labelBy, attempt])

  const currentLabelIds = new Set(selected == null ? [] : [selected,...neighbors.map(p=>p.id)])
  const activeLabels = showLabels ? frameInfo.labels.filter(label=>currentLabelIds.has(label.product.id)) : []

  return <div ref={root} className="projector-stage" style={ROOT_STYLE} data-testid="projector-stage"
    data-rendered-count={failure ? 0 : drawn.length} data-unplaced-count={universe.missingIds.length} data-dimensions={dimensions} data-algorithm={algorithm}
    data-camera-revision={frameInfo.revision} data-renderer-state={failure ? 'unavailable' : frameInfo.revision ? 'ready' : 'starting'}>
    <canvas key={attempt} ref={canvas} data-testid="projector-canvas" tabIndex={failure ? -1 : 0} role="img"
      data-rendered-count={failure ? 0 : drawn.length} data-dimensions={dimensions} data-algorithm={algorithm} data-camera-revision={frameInfo.revision}
      aria-label={`${dimensions}D ${algorithm.toUpperCase()} 产品投影，${drawn.length} 款有坐标产品。${dimensions === 3 ? '拖动旋转' : '拖动平移'}，滚轮缩放。方向键操作视图，Home 复位。全部产品也可通过搜索和列表选择。`}
      style={{ display:'block', width:'100%', height:'100%', outlineOffset:-3, touchAction:'none', visibility:failure?'hidden':'visible' }}/>
    {!failure && <svg aria-hidden="true" width="100%" height="100%" style={{position:'absolute',inset:0,pointerEvents:'none',zIndex:2}}>
      {activeLabels.filter(label=>label.leader).map(label=><line key={label.product.id} {...label.leader} stroke={label.product.id===selected?'#96004f':'#b08b45'} strokeWidth=".7" opacity=".65"/>)}
    </svg>}
    {!failure && activeLabels.map(label => <button type="button" key={label.product.id} className={`projector-point-label ${label.product.id === selected ? 'is-selected' : ''}`}
      aria-label={`选择 ${label.product.name}`} title={label.product.name} onClick={() => latest.current.onSelect?.(label.product)}
      style={{ position:'absolute', left:label.left, top:label.top, width:label.width, height:label.height, boxSizing:'border-box',
        border:0, padding:'1px 3px', background:label.product.id===selected?'#fffffff2':'#ffffffd9', color:label.product.id===selected?'#4f0030':'#555',
        fontFamily:'inherit',fontSize:label.fontSize, fontWeight:label.product.id===selected?600:400, lineHeight:1.3, textAlign:'left',
        whiteSpace:'nowrap', textOverflow:'ellipsis', overflow:'hidden', zIndex:label.product.id===selected?4:3, cursor:'pointer' }}>{label.text}</button>)}
    {!failure && hover && <div role="status" className="projector-hover" style={{ position:'absolute', left:Math.max(4,Math.min(hover.x+12,(root.current?.clientWidth||300)-238)), top:Math.max(4,hover.y-55),
      pointerEvents:'none', zIndex:5, maxWidth:230, padding:'7px 10px', color:'#555', background:'#fffffff2', boxShadow:'0 1px 5px #0002', fontSize:11 }}>
      <span>{hover.product.name}</span>{hover.count>1&&<small style={{display:'block'}}>此处有 {hover.count} 款，点击展开</small>}</div>}
    {!failure && drawn.length === 0 && <p role="status" style={{ ...OVERLAY_STYLE, pointerEvents:'none' }}>当前投影暂无可用坐标。仍可通过搜索或产品列表选择产品。</p>}
    {failure && <div role="alert" style={OVERLAY_STYLE}><strong>{failure}</strong><p>可继续通过搜索和产品列表查看资料、加入对比。</p>
      <button type="button" onClick={() => { setFrameInfo({ revision:0,labels:[] }); setAttempt(n=>n+1) }} style={{border:'1px solid #aaa',borderRadius:3,padding:'8px 14px',background:'#fff',cursor:'pointer'}}>重试图形渲染</button></div>}
  </div>
})
