import { useEffect, useMemo, useRef, useState } from 'react'
import { Flask, MagnifyingGlass, X, SlidersHorizontal, ArrowRight, Info, List, ArrowLeft } from '@phosphor-icons/react'
import { api } from '../../api'
import { useResource } from '../useResource'
import ComparisonView from '../ComparisonView'
import EvidenceDrawer from '../EvidenceDrawer'
import SimilarPicker from '../SimilarPicker'
import MapCanvas from './MapCanvas'
import ProductPanel, { ResponsivePanel } from './ProductPanel'
import { addComparison, coordinatesFor, matchingProducts, pointTone } from './space.mjs'
import WorkspaceHeader from './WorkspaceHeader'
import './space.css'
import './fresh.css'

function comparisonFromUrl() {
  const value=new URLSearchParams(window.location.search).get('compare')||''
  if(!/^\d+,\d+$/.test(value))return []
  const ids=value.split(',').map(Number)
  return ids.every(id=>Number.isSafeInteger(id)&&id>0)?ids:[]
}

function ProductList({ items, title, narrow, onClose, onChoose }) {
  const [limit,setLimit]=useState(40)
  return <ResponsivePanel name="产品列表" narrow={narrow} onClose={onClose}><div className="space-panel-header"><span>{title} · {items.length}</span><button type="button" aria-label="关闭产品列表" onClick={onClose}><X size={18}/></button></div>
    <p className="space-caption">每款都可单独查看；位置重叠不代表配方或功效等同。</p>
    <div className="space-catalog-list">{items.slice(0,limit).map(p=><button type="button" aria-label={`查看 ${p.name}`} key={p.id} onClick={()=>onChoose(p)}><small>{p.brand}</small><strong>{p.name}</strong><span>{p.ingredient_count} 项成分 · {p.evidence_ingredient_count} 项可计分</span></button>)}</div>
    {!items.length&&<p className="space-caption">当前集合暂无产品。</p>}
    {items.length>limit&&<button type="button" className="space-secondary" onClick={()=>setLimit(n=>n+40)}>继续显示产品</button>}
  </ResponsivePanel>
}

function MethodDialog({ projection, onClose }) {
  const dialog=useRef(null)
  useEffect(()=>dialog.current.showModal(),[])
  const recall=projection?.quality?.neighbor_recall_10
  return <dialog ref={dialog} className="space-method-dialog" aria-label="地图方法与局限" onClose={onClose}><div className="space-panel-header"><span>地图怎么读</span><button type="button" aria-label="关闭方法说明" onClick={()=>dialog.current.close()}><X size={20}/></button></div>
    <h2>位置用来探索，证据用来核对。</h2>
    <p>数字圆圈是屏幕范围内的真实产品集合，放大后逐步展开，不是单个产品的评分。参照产品和检索出的候选有独立标记与连线。成分表语义地图将既有成分表嵌入投影到二维。横纵方向没有保湿、抗皱等含义，群落大小也不是质量或功效分类。坐标固定，不随搜索或筛选重新排列。</p>
    <p>二维必然丢失信息。{Number.isFinite(recall)&&<>本版全库 10 近邻平均保留率约 {(recall*100).toFixed(1)}%。</>}“找相似”使用原始高维向量，不按屏幕距离排名；相近不代表成分完全一致或功效等同。</p>
    <p>“功效证据接近”只比较参照产品已有评级的方向，至少需要三个方向，候选必须覆盖同一组方向；按全库共同尺度计算轮廓距离，不显示为功效百分比。</p><p>切换“证据坐标”，可直接选择八个功效方向作为横纵轴；没有合格资料的维度不填零，未定位产品仍可检索。真实零分、未评级与资料不足分别保留。</p>
    <p>成分功效证据指数沿用 evidence-index-v1：同一成分、同一方向只取最高合格证据权重，再按成分相加。工具书为低强度行业参考；分类、法规、安全和供应商资料不作功效实证。</p>
    <p>价格为历史参考，仅同单位规格可比；没有价格或类别时不猜测。每款产品都可追到贡献成分及原始来源。</p>
    <small>投影方法 {projection?.method||'尚未配置'} · 固定数据快照 · 主流程无需模型生成</small>
  </dialog>
}

export default function ProductSpace() {
  const atlas=useResource(()=>api.productSpace(),[])
  const products=atlas.data?.products||[],directions=atlas.data?.directions||[]
  const [query,setQuery]=useState(''),[searchOpen,setSearchOpen]=useState(false),[active,setActive]=useState(0)
  const [brand,setBrand]=useState(''),[filters,setFilters]=useState(false)
  const [requestedMode,setMode]=useState('semantic'),[axes,setAxes]=useState([0,2]),[color,setColor]=useState(0)
  const [selected,setSelected]=useState(9),[comparison,setComparison]=useState(comparisonFromUrl),[compareOpen,setCompareOpen]=useState(()=>comparisonFromUrl().length===2)
  const [source,setSource]=useState(null),[similar,setSimilar]=useState(null),[list,setList]=useState(null),[method,setMethod]=useState(false)
  const [basis,setBasis]=useState('composition')
  const [viewportCount,setViewportCount]=useState(0)
  const [narrow,setNarrow]=useState(()=>window.innerWidth<=1000),[focus,setFocus]=useState(null)
  const searchBox=useRef(null),map=useRef(null)
  const mode=atlas.data?.projection.status==='ready'?requestedMode:'axes'
  const allResults=useMemo(()=>matchingProducts(products,query),[products,query])
  const results=allResults.slice(0,8)
  const visible=useMemo(()=>brand?products.filter(p=>p.brand===brand):products,[products,brand])
  const brands=useMemo(()=>[...new Set(products.map(p=>p.brand))].filter(Boolean).sort((a,b)=>a.localeCompare(b,'zh')),[products])
  const unplaced=visible.filter(p=>!coordinatesFor(p,mode,axes))
  const selectedProduct=selected==null?null:products.find(p=>p.id===selected)||products[0]
  const targetId=compareOpen?undefined:selectedProduct?.id
  const composition=useResource(()=>targetId?api.productSimilar(targetId,{k:3}):Promise.resolve(null),[targetId])
  const evidence=useResource(()=>targetId?api.productEvidenceNeighbors(targetId,{limit:3}):Promise.resolve(null),[targetId])
  const resource=basis==='composition'?composition:evidence
  const byId=useMemo(()=>new Map(products.map(p=>[p.id,p])),[products])
  const raw=basis==='composition'?composition.data?.similar:evidence.data?.items
  const neighbors=useMemo(()=>(raw||[]).filter(p=>byId.has(p.id)).map(p=>({...byId.get(p.id),...p})),[raw,byId])
  const related={...resource,data:resource.data?{...resource.data,items:neighbors,available:basis==='composition'?composition.data.similar!=null:evidence.data.available}:null}
  const colorMax=Math.max(1,...products.map(p=>p.scores[color]??0))
  const profileScale=useMemo(()=>Math.max(1,...products.flatMap(p=>p.scores.filter(Number.isFinite))),[products])
  useEffect(()=>{if(searchOpen&&query.trim())document.getElementById(`space-result-${active}`)?.scrollIntoView({block:'nearest'})},[active,searchOpen,query])
  useEffect(()=>{
    const previous=document.title;document.title='颜鉴｜护肤品成分地图';document.body.classList.add('product-space-body')
    const mq=window.matchMedia('(max-width: 1000px)'),update=()=>setNarrow(mq.matches)
    mq.addEventListener('change',update)
    const outside=e=>{if(!searchBox.current?.contains(e.target))setSearchOpen(false)}
    document.addEventListener('pointerdown',outside)
    return()=>{document.title=previous;document.body.classList.remove('product-space-body');mq.removeEventListener('change',update);document.removeEventListener('pointerdown',outside)}
  },[])
  function choose(product,locate=false){setSelected(product.id);setSource(null);setList(null);setQuery('');setSearchOpen(false);if(brand&&brand!==product.brand)setBrand('');if(locate)setFocus({id:product.id,sequence:Date.now()});if(narrow)requestAnimationFrame(()=>document.querySelector('.fresh-inspector')?.scrollIntoView({block:'start',behavior:'smooth'}))}
  function setAxis(which,value){setAxes(old=>{const next=[...old];next[which]=value;if(next[1-which]===value)next[1-which]=old[which];return next})}
  function openCompare(requested){
    const a=selectedProduct?.id||9
    const ids=Array.isArray(requested)?requested:comparison.length===2?comparison:[a,a===73?9:73]
    setComparison(ids);const url=new URL(window.location.href);url.searchParams.set('compare',ids.join(','));window.history.replaceState({},'',url);setCompareOpen(true);setSource(null);setSimilar(null);window.scrollTo({top:0,behavior:'instant'})
  }
  function syncComparison(pair){
    setComparison(previous=>previous[0]===pair.a&&previous[1]===pair.b?previous:[pair.a,pair.b])
    const url=new URL(window.location.href);url.searchParams.set('compare',`${pair.a},${pair.b}`);window.history.replaceState({},'',url)
  }
  function showRelated(){document.querySelector('.fresh-inspector')?.scrollIntoView({block:'start',behavior:'smooth'})}
  function closeCompare(){const url=new URL(window.location.href);url.searchParams.delete('compare');window.history.replaceState({},'',url);setCompareOpen(false);window.scrollTo({top:0,behavior:'instant'})}
  return <>
    <WorkspaceHeader compareOpen={compareOpen} onMap={closeCompare} onCompare={()=>openCompare()} onMethod={()=>setMethod(true)}/>
    <main className="space-app" hidden={compareOpen}>
      <div className="space-main">
        <div className="space-intro"><div><h1>护肤品成分地图</h1><p>探索成分与证据的相近之处，一键比较两款产品。</p></div>
          <div className="space-search" ref={searchBox}><MagnifyingGlass size={18}/><input role="combobox" aria-label="搜索全部产品" aria-controls="space-search-results" aria-autocomplete="list" aria-expanded={searchOpen&&Boolean(query.trim())} aria-activedescendant={searchOpen&&results[active]?`space-result-${active}`:undefined} value={query} placeholder="搜索全库产品或品牌" onFocus={()=>setSearchOpen(true)} onChange={e=>{setQuery(e.target.value);setSearchOpen(true);setActive(0)}} onKeyDown={e=>{if(e.key==='Escape')setSearchOpen(false);if(e.key==='ArrowDown'){e.preventDefault();setActive(n=>Math.min(n+1,results.length-1));setSearchOpen(true)}if(e.key==='ArrowUp'){e.preventDefault();setActive(n=>Math.max(0,n-1))}if(e.key==='Enter'&&!e.nativeEvent.isComposing&&results[active]){e.preventDefault();choose(results[active],true)}}}/>
            {query&&<button type="button" aria-label="清空搜索" onClick={()=>setQuery('')}><X size={14}/></button>}
            {searchOpen&&query.trim()&&<div className="space-search-results" id="space-search-results" role="listbox" aria-label="全库搜索结果">{!results.length&&<p>未找到产品，试试品牌或其他名称。</p>}{results.map((p,i)=><button type="button" role="option" id={`space-result-${i}`} key={p.id} aria-selected={active===i} aria-label={`查看 ${p.name}`} onClick={()=>choose(p,true)}><small>{p.brand}</small><strong>{p.name}</strong></button>)}{allResults.length>8&&<button type="button" className="space-search-more" onClick={()=>{setList({title:'搜索结果',items:allResults});setSelected(null);setSearchOpen(false)}}>查看全部 {allResults.length} 个结果 <ArrowRight size={13}/></button>}</div>}
          </div>
        </div>
        {atlas.loading?<div className="space-loading" role="status"><Flask size={26}/><p>正在展开全库产品地图…</p><small>读取真实成分与证据，不生成产品资料。</small></div>:atlas.error?<section className="space-loading" role="alert"><h2>地图资料暂未读取</h2><p>{atlas.error}</p><button type="button" className="space-secondary" onClick={()=>window.location.reload()}>重新加载</button></section>:<>
          <div className="space-workspace">
            <section className={`space-map-area ${filters?'is-settings-open':''}`} aria-label="全库产品探索">
              <div className="space-toolbar"><div className="space-modes" role="group" aria-label="地图展示方式"><button type="button" aria-pressed={mode==='semantic'} disabled={atlas.data.projection.status!=='ready'} onClick={()=>setMode('semantic')}>成分地图</button><button type="button" aria-pressed={mode==='axes'} onClick={()=>setMode('axes')}>证据坐标</button></div>
                <div className="space-toolbar-right"><button type="button" className="map-overview-button" onClick={()=>map.current?.reset()}>全库概览</button><label>着色<select aria-label="地图着色维度" value={color} onChange={e=>setColor(Number(e.target.value))}>{directions.map((d,i)=><option key={d} value={i}>{d}证据</option>)}</select></label><button type="button" aria-label="筛选品牌" aria-expanded={filters} onClick={()=>setFilters(v=>!v)}><SlidersHorizontal size={17}/>{brand&&<span className="space-filter-active"/>}</button></div>
              </div>
              {filters&&<div className="space-filter-row"><label>品牌<select aria-label="品牌筛选" value={brand} onChange={e=>setBrand(e.target.value)}><option value="">全部品牌</option>{brands.map(b=><option key={b} value={b}>{b}</option>)}</select></label>{brand&&<button type="button" onClick={()=>setBrand('')}>清除筛选</button>}</div>}
              {mode==='axes'&&<div className="space-axis-selectors"><label>横轴<select aria-label="横轴维度" value={axes[0]} onChange={e=>setAxis(0,Number(e.target.value))}>{directions.map((d,i)=><option key={d} value={i}>{d}证据指数</option>)}</select></label><span>×</span><label>纵轴<select aria-label="纵轴维度" value={axes[1]} onChange={e=>setAxis(1,Number(e.target.value))}>{directions.map((d,i)=><option key={d} value={i}>{d}证据指数</option>)}</select></label></div>}
              <MapCanvas ref={map} products={products} visible={visible} directions={directions} mode={mode} axes={axes} color={color} selected={selectedProduct?.id} neighbors={neighbors} comparison={comparison} focus={focus} onViewportChange={setViewportCount} onChoose={p=>choose(p)} onCluster={items=>{setSelected(null);setList({title:'这一处的产品',items})}}/>
              {selectedProduct&&<div className="map-focus-summary" aria-label="当前参照与候选"><span><b>参照</b>{selectedProduct.name.split('（')[0].replace(/^SkinCeuticals (?:Prevent )?/,'').replace(/® With.*$/,'')}</span><button type="button" aria-label="查看相近产品" onClick={showRelated}>查看 {neighbors.length} 款相近产品 <ArrowRight size={14}/></button></div>}
              {neighbors.length>0&&<div className="map-mobile-neighbor-names">{neighbors.map((p,i)=><button type="button" key={p.id} aria-label={`定位候选 ${p.name}`} onClick={()=>choose(p,true)}><b>{i+1}</b><span>{p.name.split('（')[0].replace(/^SkinCeuticals (?:Prevent )?/,'').replace(/® With.*$/,'')}</span></button>)}</div>}
              <div className="space-map-bottom"><span><b>全库 {atlas.data.total.toLocaleString()}</b> 款 · 当前视野 {viewportCount.toLocaleString()} 款{unplaced.length>0&&<> · {visible.length-unplaced.length} 款可定位</>}</span><span className="map-aggregation-key">数字圆圈：仅表示集合数量</span><div className="space-color-legend"><span className="space-unknown-dot"/>资料不足<span className="space-tone" style={{background:pointTone(0,colorMax)}}/>0<span className="space-tone" style={{background:pointTone(colorMax,colorMax)}}/>{colorMax.toFixed(2)}</div></div>
              <div className="space-map-note"><p>{mode==='semantic'?'数字圆圈代表产品集合，点击可展开；连线标出真实检索候选。':'坐标为已收录成分证据的参考指数；资料不足不等于没有功效。'}</p><button type="button" onClick={()=>setMethod(true)}>方法与局限</button></div>
              <div className="space-browse-links"><button type="button" onClick={()=>{setSelected(null);setList({title:'全部产品',items:products})}}><List size={15}/>浏览全库产品</button>{unplaced.length>0&&<button type="button" aria-label="查看未定位产品" onClick={()=>{setSelected(null);setList({title:'所选维度资料不足',items:unplaced})}}>未定位 {unplaced.length} 款 <ArrowRight size={13}/></button>}</div>
            </section>
            {!compareOpen&&list?<ProductList key={list.title} items={list.items} title={list.title} narrow={narrow} onClose={()=>setList(null)} onChoose={p=>choose(p,true)}/>:!compareOpen&&selectedProduct?<ProductPanel key={selected} item={selectedProduct} narrow={narrow} comparison={comparison} scale={profileScale} onClose={()=>setSelected(null)} onAdd={id=>setComparison(ids=>addComparison(ids,id))} onSource={setSource} onSimilar={setSimilar} related={related} basis={basis} onBasis={setBasis} onChoose={p=>choose(p,true)} onCompare={(a,b)=>openCompare([a,b])} onStartCompare={id=>openCompare([id,comparison.find(p=>p!==id)||(id===73?9:73)])}/>:<aside className="space-empty-panel"><span className="space-quiet-label">从一个产品开始</span><h2>点选，再看依据。</h2><p>地图展示成分关系。选中一款产品，查看八个功效方向的成分证据；加入两款，就能并排核对。</p><div className="space-starting-points"><span>试着定位</span>{[9,414].map(id=>{const p=products.find(p=>p.id===id);return p&&<button type="button" key={id} onClick={()=>choose(p,true)}>{id===9?'黑绷带面霜':'Serum 10'}<ArrowRight size={14}/></button>})}</div><p className="space-quiet-note">只有证据，不替成品效果下结论。</p></aside>}
          </div>
          <footer className="space-footer">颜鉴 · 成分与证据，分开看清楚。<span>{atlas.data.method_version}</span></footer>
        </>}
      </div>
      {comparison.length>0&&<div className="space-comparison-tray" data-testid="comparison-tray"><div><span className="space-tray-label">已选 {comparison.length}/2</span>{comparison.map((id,i)=>{const p=products.find(p=>p.id===id);return <span className="space-tray-product" key={id}><b>{i===0?'A':'B'}</b><span title={p?.name}>{p?.name}</span><button type="button" aria-label={`移除产品 ${i===0?'A':'B'}`} onClick={()=>setComparison(ids=>ids.filter(v=>v!==id))}><X size={14}/></button></span>})}<button type="button" className="space-primary" disabled={comparison.length!==2} onClick={openCompare}>对比这两款 <ArrowRight size={15}/></button></div></div>}
    </main>
    {compareOpen&&<ComparisonView initialPair={{a:comparison[0],b:comparison[1]}} onPairChange={syncComparison} onBack={closeCompare}/>}
    {method&&<MethodDialog projection={atlas.data?.projection} onClose={()=>setMethod(false)}/>}
    {similar&&<SimilarPicker targetId={similar.id} initialMethod="embedding" selectionMode="locate" onClose={()=>setSimilar(null)} onSelect={id=>{const item=products.find(p=>p.id===id);setSimilar(null);if(item)choose(item,true)}}/>}
    {source&&<EvidenceDrawer key={`${source.ingredientId}-${source.contribution?.assertion_id||''}`} ingredientId={source.ingredientId} context={source} onClose={()=>setSource(null)}/>}
  </>
}
