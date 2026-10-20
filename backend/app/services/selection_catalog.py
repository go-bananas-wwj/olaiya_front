"""Audited product-identity metadata; labels alone never confer price eligibility."""
import datetime
import json
from pathlib import Path
from urllib.parse import urlparse
from ..config import settings


CATEGORIES=('面霜','精华','乳液','爽肤水','洁面','面膜','眼霜','防晒','身体护理','颈部护理','唇部护理')

def source_url(value):
    if not isinstance(value,str): return False
    try:p=urlparse(value)
    except ValueError:return False
    return p.scheme in ('http','https') and bool(p.hostname) and not p.username and not p.password


def catalogue_document():
    try:
        path=Path(settings.selection_catalog_path)
        if path.stat().st_size>2_000_000: raise ValueError('oversized catalogue')
        d=json.loads(path.read_text())
        if not isinstance(d,dict) or d.get('version')!='selection-catalog-v1' or not isinstance(d.get('items'),list):
            raise ValueError('invalid catalogue')
        ids=[p.get('product_id') for p in d['items'] if isinstance(p,dict)]
        if len(ids)!=len(d['items']) or any(type(i) is not int for i in ids) or len(set(ids))!=len(ids):
            raise ValueError('duplicate or invalid identity')
        return d
    except (OSError,ValueError,TypeError):
        return {'version':'selection-catalog-v1','items':[], 'scope_note':'样本核验清单暂不可用。','unavailable':True}


def verified_items(products,document=None):
    document=document if document is not None else catalogue_document()
    lookup={p['id'] if isinstance(p,dict) else p.id:p for p in products}
    result={}
    for row in document['items']:
        p=lookup.get(row['product_id'])
        if p is None: continue
        value=lambda key:p.get(key) if isinstance(p,dict) else getattr(p,key,None)
        if (row.get('identity_status')=='verified' and row.get('category') in CATEGORIES
            and row.get('name')==value('name') and row.get('brand')==value('brand')
            and source_url(row.get('category_source_url')) and row.get('match_note')):
            result[row['product_id']]=row
    return result


def sample_date(value):
    if not isinstance(value,str) or len(value)!=10: return None
    try:
        d=datetime.date.fromisoformat(value)
        return d if d<=datetime.date.today() else None
    except ValueError:return None


def product_source_metadata(product):
    """Additive detail fields; raw label completeness is separate from matching."""
    audit=verified_items([product]).get(product.id)
    if not audit:return {}
    price=audit.get('price') or {}
    return {'source_coverage':{k:audit.get(k) for k in ('ingredient_list_status','ingredient_source_url','ingredient_names_raw',
                'unmapped_ingredients','ingredient_mapping_status','filing_id','legal_label_name','ingredient_note')},
            'price_reference_period':price.get('reference_period'),'price_reference_precision':price.get('reference_precision'),
            'price_note':price.get('note')}
