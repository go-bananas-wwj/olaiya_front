"""Idempotent official commercial records, never fuzzy-joined to an older formula.

Only audited metadata facts are imported. Ingredient presence creates no efficacy
assertion. Source-provided full/partial coverage and unknown order are retained.
"""
import datetime
import hashlib
import math
import re
import unicodedata
from pathlib import Path
import json
from urllib.parse import urlparse
from app.models.product import Product,ProductIngredient,PricePoint
from app.models.ingredient import Ingredient
from app.services.selection_catalog import sample_date,source_url,CATEGORIES

_MAP=Path(__file__).resolve().parents[1]/'seed'/'inci_cn_map.json'

def _norm(s):return re.sub(r'\s+','',unicodedata.normalize('NFKC',s)).upper()

def _ingredient_index(session):
    mapping=json.loads(_MAP.read_text())['map'];forward={_norm(k):k for k in mapping};reverse={}
    for inci,row in mapping.items():reverse.setdefault(_norm(row['cn_name']),set()).add(inci)
    return mapping,forward,reverse,{_norm(i.inci_name):i for i in session.query(Ingredient).all()}

def import_catalogue(session,records,*,allow_partial=False):
    validated=[];seen=set()
    for row in records:
        url=row.get('source_url');key=(row.get('brand'),row.get('official_id'))
        if (not source_url(url) or len(url)>200 or not row.get('official_id') or key in seen
            or not isinstance(row.get('name'),str) or not 0<len(row['name'])<=300
            or row.get('category') not in CATEGORIES or not source_url(row.get('category_source_url'))
            or not row.get('identity_note') or row.get('terms_status') not in ('metadata_facts_only','public_disclosure')
            or row.get('is_bundle') is True):raise ValueError(f'not an audited single commercial product: {key}')
        seen.add(key);day=sample_date(row.get('sampled_at'))
        if day is None:raise ValueError('unknown or invalid actual observation day')
        amount=row.get('reference_price')
        if amount is not None and (type(amount) not in (int,float) or not math.isfinite(amount) or amount<=0 or row.get('currency')!='CNY'):
            raise ValueError('unverified price/currency; zero placeholders are not retail prices')
        price_url=row.get('price_source_url',url)
        if amount is not None and (not source_url(price_url) or len(price_url)>200):raise ValueError('price source missing')
        raw_names=row.get('ingredient_names') or []
        if (not isinstance(raw_names,list) or not all(isinstance(n,str) for n in raw_names)
            or (raw_names and not source_url(row.get('ingredient_source_url')))):
            raise ValueError('ingredient presence needs names and source')
        validated.append((row,day))
    mapping,forward,reverse,ingredients=_ingredient_index(session)
    output=[];added=0
    for row,day in validated:
        key='official:'+row.get('source_namespace',urlparse(row['source_url']).netloc+':'+row['brand'])+':'+row['official_id']
        if len(key)>220:raise ValueError('source identity too long')
        raw_names=row.get('ingredient_names') or []
        signature=hashlib.sha256(json.dumps([[_norm(n) for n in raw_names],row.get('filing_id'),row.get('legal_label_name')],ensure_ascii=False,separators=(',',':')).encode()).hexdigest() if raw_names else None
        stored_key=key+('|formula:'+signature if signature else '')
        hits=session.query(Product).filter((Product.source_key==key)|Product.source_key.startswith(key+'|formula:',autoescape=True)).all()
        if len(hits)>1:raise ValueError('ambiguous existing official source identity')
        p=hits[0] if hits else None
        if p and (p.name!=row['name'] or p.brand!=row['brand']):raise ValueError('official source changed identity; review required')
        if p and '|formula:' in p.source_key and p.source_key!=stored_key:
            raise ValueError('official formula/version changed; review required')
        if p is None:
            p=Product(name=row['name'],brand=row['brand'],category=row['category'],source_url=row['source_url'],source_key=stored_key,
                      note='官方商品资料；请结合成分资料覆盖与价格日期阅读，不是成品功效验证。')
            session.add(p);session.flush();added+=1
        p.source_key=stored_key
        p.category=row['category']
        status=row.get('ingredient_list_status','missing')
        raw_names=row.get('ingredient_names') or []
        if not isinstance(raw_names,list) or not all(isinstance(n,str) for n in raw_names):raise ValueError('invalid ingredient names')
        unmapped=[];resolved=[]
        for name in raw_names:
            key=_norm(name);inci=forward.get(key)
            if inci is None and len(reverse.get(key,set()))==1:inci=next(iter(reverse[key]))
            if inci is None and key in ingredients:inci=ingredients[key].inci_name
            if inci is None:unmapped.append(name);continue
            ing=ingredients.get(_norm(inci))
            if ing is None:
                ing=Ingredient(inci_name=inci,cn_name=mapping[inci]['cn_name']);session.add(ing);session.flush();ingredients[_norm(inci)]=ing
            resolved.append(ing)
        imported=(status=='official_full' or (status=='official_partial' and allow_partial))
        if imported and resolved:
            if not source_url(row.get('ingredient_source_url')):raise ValueError('ingredient presence needs a source')
            existing={i for i, in session.query(ProductIngredient.ingredient_id).filter_by(product_id=p.id)}
            if existing and existing!={ing.id for ing in resolved}:
                raise ValueError('official formula changed; review required before replacement')
            for ing in resolved:
                if ing.id not in existing:
                    session.add(ProductIngredient(product_id=p.id,ingredient_id=ing.id,position=None));existing.add(ing.id)
            result_status=status
        else:result_status='missing'
        price=None
        if row.get('reference_price') is not None:
            p.price_current=row['reference_price'];p.spec=row.get('spec');p.buy_url=row['source_url']
            price_url=row.get('price_source_url',row['source_url'])
            point=session.query(PricePoint).filter_by(product_id=p.id,date=day,source=price_url).one_or_none()
            if point is None:session.add(PricePoint(product_id=p.id,date=day,source=price_url,price=p.price_current,is_manual=True))
            else:point.price=p.price_current
            price={'identity_status':'verified','amount':p.price_current,'currency':'CNY','spec':p.spec,
                   'source_url':price_url,'sampled_at':day.isoformat(),
                   'reference_period':row.get('price_reference_period'),'reference_precision':row.get('price_reference_precision'),
                   'note':row.get('price_note','官网公开人民币参考价；非实时成交价，实际购买条件以来源页面为准。')}
        output.append({'product_id':p.id,'official_id':row['official_id'],'name':p.name,'brand':p.brand,'category':p.category,
                       'identity_status':'verified','category_source_url':row['category_source_url'],'match_note':row['identity_note'],
                       'price':price,'ingredient_list_status':result_status,'ingredient_source_url':row.get('ingredient_source_url'),
                       'ingredient_names_raw':raw_names,'unmapped_ingredients':unmapped,
                       'ingredient_mapping_status':'partial' if unmapped else 'complete','terms_status':row['terms_status'],
                       'observed_at':day.isoformat(),'source_sha256':row.get('source_sha256'),
                       'filing_id':row.get('filing_id'),'legal_label_name':row.get('legal_label_name'),'ingredient_note':row.get('ingredient_note')})
    return {'added':added,'items':output}


if __name__ == '__main__':
    import argparse
    from app.db import SessionLocal,init_db
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    args=parser.parse_args();document=json.loads(args.input.read_text())
    init_db()
    with SessionLocal.begin() as session:
        result=import_catalogue(session,document['records'])
    args.manifest.parent.mkdir(parents=True,exist_ok=True)
    args.manifest.write_text(json.dumps({'version':'selection-catalog-v1','scope_note':document['scope_note'],'items':result['items']},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'added':result['added'],'verified_records':len(result['items'])}))
