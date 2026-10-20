// Projection geometry only. Evidence indices are metadata, never replacement coordinates.
export function coordinatesFor(product, algorithm = 'umap', dimensions = 2, axisOrder = [0, 1, 2]) {
  if (![2, 3].includes(dimensions) || !['umap', 'pca'].includes(algorithm)) return null
  let source = algorithm === 'pca' ? product.pca_coordinates : dimensions === 3 ? product.coordinates_3d : product.coordinates
  if (algorithm === 'pca') {
    if (!Array.isArray(axisOrder) || axisOrder.length !== 3 || new Set(axisOrder).size !== 3 || !axisOrder.every(i => Number.isInteger(i) && i >= 0 && i <= 2)) return null
    source = Array.isArray(source) ? axisOrder.map(i => source[i]) : null
  }
  if (!Array.isArray(source) || source.length < dimensions || !source.slice(0, dimensions).every(Number.isFinite)) return null
  return dimensions === 2 ? [source[0], source[1], 0] : source.slice(0, 3)
}

export function normalizeUniverse(products, algorithm = 'umap', dimensions = 2, axisOrder = [0, 1, 2]) {
  const valid = [], missingIds = []
  const low = [Infinity, Infinity, Infinity], high = [-Infinity, -Infinity, -Infinity]
  for (const product of products) {
    const xyz = coordinatesFor(product, algorithm, dimensions, axisOrder)
    if (!xyz) { missingIds.push(product.id); continue }
    valid.push({ product, xyz })
    for (let axis = 0; axis < 3; axis++) { low[axis] = Math.min(low[axis], xyz[axis]); high[axis] = Math.max(high[axis], xyz[axis]) }
  }
  const center = valid.length ? low.map((v, i) => v / 2 + high[i] / 2) : [0, 0, 0]
  const extent = valid.length ? Math.max(...high.map((v, i) => v - low[i])) : 0
  const scale = extent > 0 && Number.isFinite(extent) ? 2 / extent : 1
  const points = valid.map(({ product, xyz }) => ({ product, position: xyz.map((v, i) => (v - center[i]) * scale) }))
  return { points, byId: new Map(points.map(p => [p.product.id, p])), missingIds, center, scale }
}

export function visibleProducts(points, selected, neighbors = [], isolated = false) {
  if (!isolated) return points
  const ids = new Set(neighbors.map(p => p.id))
  if (selected != null) ids.add(selected)
  return points.filter(p => ids.has(p.product.id))
}

export function screenHits(points, x, y, radius = 9) {
  return points.filter(p => p.visible && Number.isFinite(p.x) && Number.isFinite(p.y))
    .map(p => ({ ...p, distance: (p.x - x) ** 2 + (p.y - y) ** 2 }))
    .filter(p => p.distance <= radius ** 2)
    .sort((a, b) => a.distance - b.distance || (a.depth ?? 0) - (b.depth ?? 0) || a.product.id - b.product.id)
    .map(p => p.product)
}

const BRAND_COLORS = ['#5f6bc4', '#49a197', '#c67c45', '#ac60ad', '#759b41', '#508dbd', '#be6983', '#a18e40']
export function pointColor(product, { selected = null, neighborIds = new Set(), colorBy = 'none', colorMax = 1 } = {}) {
  if (product.id === selected) return '#96004f'
  if (neighborIds.has(product.id)) return '#e9a023'
  if (selected != null) return '#c8c8cc'
  if(colorBy==='sample'&&product.id!==selected&&!neighborIds.has(product.id))return product.selection_sample&&product.category==='面霜'?'#25876c':'#c4d1cc'
  if (colorBy === 'brand') {
    if (!product.brand) return '#b9bdc6'
    let hash = 0
    for (const c of product.brand) hash = ((hash << 5) - hash + c.charCodeAt(0)) | 0
    return BRAND_COLORS[(hash >>> 0) % BRAND_COLORS.length]
  }
  if (Number.isInteger(colorBy)) {
    const value = product.scores?.[colorBy]
    if (!Number.isFinite(value)) return '#b9bdc6'
    const t = Math.max(0, Math.min(1, value / Math.max(1, colorMax)))
    const from = [192, 189, 235], to = [70, 55, 186]
    return `rgb(${from.map((v, i) => Math.round(v + (to[i] - v) * t)).join(',')})`
  }
  return '#6256dc'
}

export function shortProductLabel(product, labelBy = 'name') {
  if (labelBy === 'brand') return product.brand || '品牌未收录'
  const original = String(product.name || '')
  return original.replace(/^SkinCeuticals\s+/i, '').trim() || original
}

// Only identical coordinates in this requested projection count as coincidence.
// Screen pixels/depth and names must never be used as identity or vector equality.
export function groupCoincidentPoints(points) {
  const groups = new Map()
  points.forEach((point,index)=>{
    const xyz = point.position
    const key = Array.isArray(xyz) && xyz.length === 3 && xyz.every(Number.isFinite)
      ? `position:${JSON.stringify(xyz)}` : `ungrouped:${index}`
    if (!groups.has(key)) groups.set(key,{key,members:[]})
    groups.get(key).members.push(point)
  })
  return [...groups.values()]
}

// Badges are annotations, never moved data points. They remain independent of
// the optional name labels so coincident records are reachable with labels off.
export function layoutCoincidentBadges(groups,{width,height,selected,neighborIds=new Set(),reserved=[],limit=8}={}) {
  if (!(width>56&&height>52)) return []
  const placed=[]
  const order=groups.filter(group=>group.members.length>1&&group.members.some(p=>p.visible))
    .sort((a,b)=>Number(b.members.some(p=>p.product.id===selected))-Number(a.members.some(p=>p.product.id===selected))
      ||Number(b.members.some(p=>neighborIds.has(p.product.id)))-Number(a.members.some(p=>neighborIds.has(p.product.id))))
  for (const group of order) {
    if(placed.length>=limit)break
    const point=group.members.find(p=>p.product.id===selected&&p.visible)||group.members.find(p=>neighborIds.has(p.product.id)&&p.visible)||group.members.find(p=>p.visible)
    if (!Number.isFinite(point.x)||!Number.isFinite(point.y)) continue
    const w=44,h=44,candidates=[]
    for(const radius of [4,12]) for(const [dx,dy] of [[1,0],[-1,0],[0,-1],[0,1],[1,-1],[-1,-1],[1,1],[-1,1]]) {
      candidates.push({left:Math.max(4,Math.min(width-w-4,point.x+dx*radius-(dx<0?w:dx===0?w/2:0))),
        top:Math.max(4,Math.min(height-h-4,point.y+dy*radius-(dy<0?h:dy===0?h/2:0))),width:w,height:h})
    }
    const rect=candidates.find(slot=>![...placed,...reserved].some(prior=>rectsOverlap(slot,prior)))
    if(!rect)continue
    placed.push({...rect,key:group.key,count:group.members.length,members:group.members,product:point.product,
      leader:null})
  }
  return placed
}

const rectsOverlap = (a, b, gap = 3) => a.left < b.left + b.width + gap && a.left + a.width + gap > b.left
  && a.top < b.top + b.height + gap && a.top + a.height + gap > b.top
const closestOnRect = (point, rect) => ({ x:Math.max(rect.left,Math.min(point.x,rect.left+rect.width)), y:Math.max(rect.top,Math.min(point.y,rect.top+rect.height)) })

// Screen-space annotation placement never changes product coordinates. Dense
// neighborhoods keep their true points; names without a clear slot are omitted.
export function layoutLabels(points, { width, height, selected, pointSize = 6, labelBy = 'name', measure, reserved = [], onlySelected = false } = {}) {
  if (!(width > 16 && height > 16)) return []
  const nodes = points.filter(p => p.visible && Number.isFinite(p.x) && Number.isFinite(p.y))
  const order = groupCoincidentPoints(nodes).map(group=>{
    const point=group.members.find(p=>p.product.id===selected)||group.members[0]
    return {...point,members:point.members||group.members,coincidentCount:point.coincidentCount||group.members.length}
  }).sort((a,b)=>Number(b.product.id===selected)-Number(a.product.id===selected))
  const placed = []
  for (const point of order) {
    if(onlySelected&&point.product.id!==selected)continue
    const primary = point.product.id === selected, fontSize = primary ? 14 : 12, text = shortProductLabel(point.product,labelBy)
    const measured = measure ? measure(text,fontSize,primary) : [...text].reduce((sum,c)=>sum+fontSize*(/[\u2e80-\uffff]/.test(c)?1:.6),0)
    const w = Math.ceil(Math.min(primary?260:190, width-8, Math.max(12,measured)+6)), h = primary ? 22 : 20
    const radius = Math.max(1, Math.min(24,pointSize)) * (primary?1.9:1.3) / 2 + 2
    const gaps = primary ? [4,12,24,40,64,96,144,208,288,400] : [4,12,24]
    const candidates = []
    for (const gap of gaps) {
      const d = radius + gap, x=point.x, y=point.y
      candidates.push(
        {left:x+d,top:y-h/2}, {left:x-d-w,top:y-h/2},
        {left:x-w/2,top:y-d-h}, {left:x-w/2,top:y+d},
        {left:x+d,top:y-d-h}, {left:x-d-w,top:y-d-h},
        {left:x+d,top:y+d}, {left:x-d-w,top:y+d},
      )
    }
    const rect = candidates.map(slot=>({...slot,left:Math.max(4,Math.min(width-w-4,slot.left)),top:Math.max(4,Math.min(height-h-4,slot.top)),width:w,height:h})).find(slot => {
      if (slot.left<4||slot.top<4||slot.left+w>width-4||slot.top+h>height-4) return false
      if (placed.some(prior=>rectsOverlap(slot,prior))) return false
      if (reserved.some(prior=>rectsOverlap(slot,prior))) return false
      return !nodes.some(node=>{
        const near=closestOnRect(node,slot),r=Math.max(1,Math.min(24,pointSize))*(node.product.id===selected?1.9:1.3)/2+2
        return (near.x-node.x)**2+(near.y-node.y)**2<r*r
      })
    })
    if (!rect) continue
    const near=closestOnRect(point,rect),distance=Math.hypot(near.x-point.x,near.y-point.y)
    const leader=distance>radius+9?{x1:point.x,y1:point.y,x2:near.x,y2:near.y}:null
    placed.push({...point,...rect,text,fontSize,leader})
  }
  return placed
}

const dot3=(a,b)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2]
const cross3=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
const unit3=v=>{const n=Math.hypot(...v)||1;return v.map(x=>x/n)}

// Fit the actual perspective frustum, not an enclosing sphere. For each axis,
// |x - targetX| <= k * (cameraZ - pointZ). The intersection of these intervals
// gives the minimum distance and a centered target without stretching any axis.
export function fitPerspective(positions,{direction=[.5,.3,1],aspect=1,fov=42,padding=.1}={}) {
  const forward=unit3(direction),upReference=Math.abs(forward[1])>.99?[0,0,1]:[0,1,0]
  const right=unit3(cross3(upReference,forward)),up=unit3(cross3(forward,right))
  const tangent=Math.tan(fov*Math.PI/360),fraction=1-2*padding,kx=tangent*Math.max(1e-6,aspect)*fraction,ky=tangent*fraction
  let ax=-Infinity,bx=Infinity,ay=-Infinity,by=Infinity,minZ=Infinity,maxZ=-Infinity
  for(const position of positions) {
    const x=dot3(position,right),y=dot3(position,up),z=dot3(position,forward)
    ax=Math.max(ax,x+kx*z);bx=Math.min(bx,x-kx*z)
    ay=Math.max(ay,y+ky*z);by=Math.min(by,y-ky*z)
    minZ=Math.min(minZ,z);maxZ=Math.max(maxZ,z)
  }
  if(!positions.length)return {target:[0,0,0],position:forward.map(v=>v*3),distance:3,direction:forward,right,up}
  const z=(minZ+maxZ)/2,x=(ax+bx)/2,y=(ay+by)/2
  const epsilon=Math.max(1e-8,(maxZ-minZ)*1e-6)
  const absoluteDistance=Math.max((ax-bx)/(2*kx),(ay-by)/(2*ky),maxZ+epsilon)
  const distance=absoluteDistance-z,target=right.map((v,i)=>v*x+up[i]*y+forward[i]*z)
  return {target,position:target.map((v,i)=>v+forward[i]*distance),distance,direction:forward,right,up}
}
