import { useEffect,useRef,useState } from 'react'
import { ArrowLeft,ArrowsLeftRight } from '@phosphor-icons/react'
import { api } from '../api'
import { useResource } from './useResource'
import ProductPicker from './ProductPicker'
import CapabilityChart from './CapabilityChart'
import Contributions from './Contributions'
import SecondaryPanels from './SecondaryPanels'
import EvidenceDrawer from './EvidenceDrawer'
import SimilarPicker from './SimilarPicker'
import { ProductPhoto } from './ReferencePrimitives'
import { compareIngredients } from './logic.mjs'
import './showcase.css'
import './comparison.css'
const CASES=[{label:'黑绷带 / A.G.E.',a:9,b:73},{label:'Serum 10 / C E Ferulic',a:414,b:3202}]
export default function ComparisonView({initialPair={a:9,b:73},onBack,onPairChange}){
 const [pair,setPair]=useState(initialPair),[family,setFamily]=useState('保湿'),[source,setSource]=useState(null),[similar,setSimilar]=useState(null),[sticky,setSticky]=useState(false)
 const cards=useRef(null),contributions=useRef(null)
 const a=useResource(()=>api.product(pair.a),[pair.a]),b=useResource(()=>api.product(pair.b),[pair.b])
 const aProfile=useResource(()=>api.productCapabilityProfile(pair.a),[pair.a]),bProfile=useResource(()=>api.productCapabilityProfile(pair.b),[pair.b])
 const difference=a.data&&b.data?compareIngredients(a.data.ingredients,b.data.ingredients):null
 useEffect(()=>{const previous=document.title;document.title='颜鉴｜两款产品多维对比';document.body.classList.add('reference-compare');return()=>{document.title=previous;document.body.classList.remove('reference-compare')}},[])
 useEffect(()=>{const update=()=>setSticky(Boolean(cards.current&&cards.current.getBoundingClientRect().bottom<72));window.addEventListener('scroll',update,{passive:true});update();return()=>window.removeEventListener('scroll',update)},[])
 function select(side,id){const next={...pair,[side]:id};setPair(next);onPairChange?.(next);setSource(null);setSimilar(null)}
 function showFamily(name){setFamily(name);requestAnimationFrame(()=>contributions.current?.scrollIntoView({block:'start',behavior:'smooth'}))}
 return <main className="comparison-page">
  <div className="comparison-intro"><h1>护肤品功效证据对比</h1><nav aria-label="真实演示案例"><span>试试真实案例</span>{CASES.map(c=><button type="button" key={c.a} aria-pressed={pair.a===c.a&&pair.b===c.b} onClick={()=>{const next={a:c.a,b:c.b};setPair(next);onPairChange?.(next);setFamily('保湿');setSource(null);window.scrollTo({top:0,behavior:'instant'})}}>{c.label}</button>)}</nav></div>
  <section ref={cards} id="overview" className="comparison-products" aria-label="产品概览"><ProductPicker compact side="A" productId={pair.a} state={a} onSelect={id=>select('a',id)}/><span className="comparison-versus"><ArrowsLeftRight size={18}/></span><ProductPicker compact side="B" productId={pair.b} state={b} onSelect={id=>select('b',id)}/></section>
  <CapabilityChart a={aProfile} b={bProfile} aId={pair.a} bId={pair.b} productA={a.data} productB={b.data} family={family} onFamily={showFamily}/>
  <nav className="comparison-section-nav" aria-label="页面目录"><a href="#benefits">功效证据</a><a href="#key-ingredients">贡献成分</a><a href="#ingredients">成分对照</a><a href="#price">参考价格</a></nav>
  {difference&&<div className="comparison-formula-summary"><span>共有 <b>{difference.shared.length}</b> 项成分</span><span>仅A列出 <b>{difference.onlyTarget.length}</b> 项</span><span>仅B列出 <b>{difference.onlyCandidate.length}</b> 项</span></div>}
  <section ref={contributions} id="key-ingredients" className="comparison-contributions"><div className="comparison-subtitle"><h2>{family}，依据在哪里？</h2><span>同一套规则，两边都可追溯</span></div><Contributions a={aProfile} b={bProfile} family={family} onSource={setSource}/></section>
  <SecondaryPanels key={`${pair.a}-${pair.b}`} a={a.data} b={b.data} onIngredient={setSource}/>
  <section id="alternatives" className="comparison-alternatives"><h2>想继续找相近产品？</h2><div>{[[a,'A','b'],[b,'B','a']].map(([p,side,replace])=><button type="button" key={side} disabled={!p.data} aria-label={side==='A'?'找相似产品':'查找与产品 B 相似的候选'} onClick={()=>setSimilar({id:p.data.id,side,replace})}>查找与产品 {side} 成分接近的产品</button>)}</div></section>
  <footer className="comparison-footer">成分证据不等于成品功效；相近不代表等同。参考图用于产品识别，历史价格不等于实时售价。{onBack&&<button type="button" onClick={onBack}><ArrowLeft size={14}/>返回产品空间</button>}</footer>
  <div className="ss-sticky-products" data-testid="comparison-sticky" hidden={!sticky}><div className="ss-two-columns">{[[a.data,'A'],[b.data,'B']].map(([p,side])=><a href="#overview" key={side}><ProductPhoto product={p} side={side} mini/><span>产品 {side} · {p?.brand}<strong>{p?.name||`产品 ${side}`}</strong></span></a>)}</div></div>
  {source&&<EvidenceDrawer key={`${source.ingredientId}-${source.contribution?.assertion_id||''}`} ingredientId={source.ingredientId} context={source} onClose={()=>setSource(null)}/>}
  {similar&&<SimilarPicker targetId={similar.id} referenceLabel={similar.side} onClose={()=>setSimilar(null)} onSelect={id=>select(similar.replace,id)}/>}
 </main>
}
