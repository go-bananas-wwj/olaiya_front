"""A readable price/evidence chart, with a single source for eligibility and axes."""
import datetime
import calendar
import re
import hashlib
import json
import math
from .capability_profile import DIRECTIONS,METHOD_VERSION as INDEX_METHOD
from .product_space import product_space
from .selection_catalog import catalogue_document,verified_items,sample_date,source_url,CATEGORIES

METHOD_VERSION='selection-map-v1'


def _finite(value):return type(value) in (int,float) and math.isfinite(value) and value>=0


def selection_map(session,category='面霜',efficacy='保湿',unit=None,brand=None,max_package_price=None):
    if category not in CATEGORIES or efficacy not in DIRECTIONS or unit not in (None,'g','ml'):
        raise ValueError('不支持的品类、功效方向或单位')
    if max_package_price is not None and not _finite(max_package_price):raise ValueError('预算须为非负有限数值')
    source=product_space(session);document=catalogue_document();verified=verified_items(source['products'],document)
    axis=DIRECTIONS.index(efficacy);today=datetime.date.today();rows=[]
    for p in source['products']:
        audit=verified.get(p['id'])
        if not audit or audit.get('category')!=category:continue
        price=audit.get('price') if isinstance(audit.get('price'),dict) else {};sample=sample_date(price.get('sampled_at'))
        known=p['statuses'][axis]=='scored' and _finite(p['scores'][axis])
        price_ok=(price.get('identity_status')=='verified' and price.get('currency')=='CNY'
                  and _finite(price.get('amount')) and _finite(p.get('price_current'))
                  and price.get('amount')==p.get('price_current') and price.get('spec')==p.get('spec')
                  and sample is not None and price.get('sampled_at')==p.get('price_recorded_at')
                  and source_url(price.get('source_url')) and price.get('source_url')==p.get('price_source')
                  )
        reasons=[]
        if not price_ok:reasons.append('price_unverified')
        if not known:reasons.append('evidence_unavailable')
        if price_ok and (not _finite(p.get('unit_price')) or p.get('unit_price_unit') not in ('g','ml')):reasons.append('unit_unavailable')
        if audit.get('ingredient_list_status','existing_record') not in ('existing_record','official_full'):reasons.append('ingredients_incomplete')
        age=(today-sample).days if sample else None
        age_range=[age,age] if age is not None else None
        age_status=('older_reference' if age is not None and age>30 else 'reference') if price_ok else 'unknown'
        period=price.get('reference_period')
        if price_ok and price.get('reference_precision')=='month':
            age_status='unknown';age_range=None
            if isinstance(period,str) and re.fullmatch(r'\d{4}-\d{2}',period):
                try:
                    year,month=map(int,period.split('-'))
                    start=datetime.date(year,month,1)
                    end=datetime.date(year,month,calendar.monthrange(year,month)[1])
                    age_range=[max(0,(today-end).days),(today-start).days]
                    age_status='older_reference' if age_range[0]>30 else 'monthly_reference'
                except ValueError:pass
        rows.append({**p,'category':category,'category_verified':True,'selection_sample':True,
                     'category_source_url':audit['category_source_url'],'identity_note':audit['match_note'],
                     'ingredient_list_status':audit.get('ingredient_list_status','existing_record'),
                     'ingredient_source_url':audit.get('ingredient_source_url'),
                     'ingredient_names_raw':audit.get('ingredient_names_raw',[]),'unmapped_ingredients':audit.get('unmapped_ingredients',[]),
                     'ingredient_mapping_status':audit.get('ingredient_mapping_status'),'filing_id':audit.get('filing_id'),
                     'evidence_score':p['scores'][axis] if known else None,'evidence_status':p['statuses'][axis],
                     'price_verified':price_ok,'price_age_status':age_status,'price_age_days_range':age_range,
                     'price_reference_period':price.get('reference_period'),'price_reference_precision':price.get('reference_precision'),
                     'price_note':price.get('note','带来源与日期的参考价格，非实时成交价。'),
                     'exclusion_reasons':reasons})
    counts={u:sum(not p['exclusion_reasons'] and p['unit_price_unit']==u for p in rows) for u in ('g','ml')}
    unit=unit or ('g' if counts['g']>=counts['ml'] else 'ml')
    for p in rows:
        if p['price_verified'] and p.get('unit_price_unit') in ('g','ml') and p['unit_price_unit']!=unit:p['exclusion_reasons'].append('different_unit')
        p['plottable']=not p['exclusion_reasons']
        filters=[]
        if brand and p['brand']!=brand:filters.append('different_brand')
        if max_package_price is not None and (not _finite(p.get('price_current')) or p['price_current']>max_package_price):filters.append('over_budget')
        p['filter_reasons']=filters;p['matches_filters']=p['plottable'] and not filters
    plotted=[p for p in rows if p['plottable']]
    payload={'method_version':METHOD_VERSION,'index_method':INDEX_METHOD,'snapshot_revision':source['snapshot_revision'],
             'category':category,'efficacy':efficacy,'unit':unit,'unit_counts':counts,'scope_note':document.get('scope_note',''),
             'available':not document.get('unavailable',False),'products':rows,
             'axes':{'x':{'label':f'参考单价（元/{unit}）','min':0,'max':max([1]+[p['unit_price'] for p in plotted])},
                     'y':{'label':f'{efficacy}方向成分功效证据指数','min':0,'max':max([1]+[p['evidence_score'] for p in plotted])}},
             'coverage':{'catalog_total':source['total'],'verified':len(rows),'plottable':len(plotted),'excluded':len(rows)-len(plotted),
                         'matched':sum(p['matches_filters'] for p in rows)},
             'categories':[c for c in CATEGORIES if any(p.get('category')==c for p in verified.values())],
             'brands':sorted(set(p['brand'] for p in rows)),
             'filters':{'brand':brand,'max_package_price':max_package_price},
             'note':'仅比较已收录成分证据与参考单价。证据指数受资料覆盖影响，不是成品实测效果；缺失不补零。'}
    payload['revision']=hashlib.sha256(json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()).hexdigest()
    return payload
