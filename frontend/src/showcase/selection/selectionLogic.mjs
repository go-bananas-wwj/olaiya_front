const NEEDS=['保湿','抗皱','修护','舒缓','抗氧化','美白','控油祛痘','焕肤']
export function addSelectionCandidate(ids,id){return Number.isInteger(id)&&id>0&&!ids.includes(id)&&ids.length<4?[...ids,id]:ids}
export function selectionPoint(p,axes,box){
 if(!p.plottable||![p.unit_price,p.evidence_score].every(Number.isFinite))return null
 return {x:box.left+(p.unit_price-axes.x.min)/(axes.x.max-axes.x.min||1)*box.width,y:box.top+box.height-(p.evidence_score-axes.y.min)/(axes.y.max-axes.y.min||1)*box.height}
}
export function groupSelectionPoints(rows){const groups=new Map();for(const p of rows){if(!p.plottable)continue;const k=JSON.stringify([p.unit_price,p.evidence_score]);if(!groups.has(k))groups.set(k,{key:k,items:[]});groups.get(k).items.push(p)}return [...groups.values()]}
export function selectedRectangleIds(ps,r){return ps.filter(p=>p.matches_filters&&p.x>=Math.min(r.x1,r.x2)&&p.x<=Math.max(r.x1,r.x2)&&p.y>=Math.min(r.y1,r.y2)&&p.y<=Math.max(r.y1,r.y2)).map(p=>p.id)}
export function readSelectionState(url){const p=new URL(url).searchParams,b=p.get('budget');return {view:p.get('view')==='selection'?'selection':'overview',efficacy:NEEDS.includes(p.get('efficacy'))?p.get('efficacy'):'保湿',unit:['g','ml'].includes(p.get('unit'))?p.get('unit'):null,brand:p.get('brand')||'',budget:b!==null&&b!==''&&Number.isFinite(Number(b))&&Number(b)>=0?Number(b):null}}
export function writeSelectionState(url,s){const u=new URL(url);for(const key of ['view','efficacy','unit','brand','budget','category']){if(s[key]===null||s[key]===undefined||s[key]==='')u.searchParams.delete(key);else u.searchParams.set(key,s[key])}return u.href}
export const selectionReasons={price_unverified:'缺少匹配版本的参考价格',unit_unavailable:'规格或单位不可换算',evidence_unavailable:'该方向资料不足',ingredients_incomplete:'完整成分表待核',different_unit:'属于另一单位组',different_brand:'不符品牌筛选',over_budget:'超出整件预算'}
