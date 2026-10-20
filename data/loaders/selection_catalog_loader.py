"""Import audited existing product identities; market corrections are explicit and dated.

No fuzzy matching and no ingredient/claim mutations. Callers own transactions.
"""
import argparse
import json
from pathlib import Path
from app.models.product import Product,PricePoint
from app.services.selection_catalog import sample_date,source_url
from app.services.comparison_metadata import price_fields


def load_selection_catalog(session,path,*,apply_verified_updates=False):
    document=json.loads(Path(path).read_text())
    if document.get('version')!='selection-catalog-v1' or not isinstance(document.get('items'),list):
        raise ValueError('invalid selection catalogue')
    planned=[];seen=set()
    # Validate the whole document before mutating even one record.
    for row in document['items']:
        pid=row.get('product_id')
        if type(pid) is not int or pid in seen:raise ValueError('invalid or duplicate product identity')
        seen.add(pid);p=session.get(Product,pid)
        if (p is None or row.get('name')!=p.name or row.get('brand')!=p.brand or row.get('category')!='面霜'
            or row.get('identity_status')!='verified' or not source_url(row.get('category_source_url')) or not row.get('match_note')):
            raise ValueError(f'product identity/category not verified: {pid}')
        price=row.get('price');day=None
        if price is not None:
            if not isinstance(price,dict):raise ValueError('invalid price record')
            if price.get('identity_status')=='verified':
                day=sample_date(price.get('sampled_at'))
                if day is None or price.get('currency')!='CNY' or not source_url(price.get('source_url')):
                    raise ValueError(f'price provenance/date not verified: {pid}')
                class Example:pass
                example=Example();example.price_current=price.get('amount');example.spec=price.get('spec');example.source_url=None;example.buy_url=None
                if type(example.price_current) not in (int,float) or price_fields(example)['unit_price'] is None:
                    raise ValueError(f'invalid price/spec: {pid}')
        planned.append((p,row,price,day))
    stats={'verified':len(planned),'categories_updated':0,'prices_updated':0,'changes':[]}
    for p,row,price,day in planned:
        if p.category is None or apply_verified_updates:
            if p.category!=row['category']:p.category=row['category'];stats['categories_updated']+=1
        if day is None:continue
        if p.price_current is not None and not apply_verified_updates:continue
        previous=p.price_current
        p.price_current=price['amount'];p.spec=price['spec'];p.buy_url=price['source_url']
        point=session.query(PricePoint).filter_by(product_id=p.id,date=day,source=price['source_url']).one_or_none()
        if point is None:session.add(PricePoint(product_id=p.id,date=day,source=price['source_url'],price=price['amount'],is_manual=True))
        elif point.price!=price['amount']:point.price=price['amount']
        if previous!=price['amount']:
            stats['prices_updated']+=1
            stats['changes'].append({'product_id':p.id,'previous_price':previous,'price':price['amount'],
                                    'sampled_at':day.isoformat(),'source_url':price['source_url']})
    return stats


if __name__=='__main__':
    from app.db import SessionLocal
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('path',type=Path)
    parser.add_argument('--apply-verified-updates',action='store_true');args=parser.parse_args()
    with SessionLocal() as session:
        stats=load_selection_catalog(session,args.path,apply_verified_updates=args.apply_verified_updates)
        session.commit();print(json.dumps(stats,ensure_ascii=False))
