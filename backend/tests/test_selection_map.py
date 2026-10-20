import datetime
import json
import pytest
from fastapi.testclient import TestClient
from app.main import app,get_db
from app.config import settings
from app.models.product import Product, ProductIngredient, PricePoint
from app.models.ingredient import Ingredient
from backend.tests.test_capability_profile import assertion


@pytest.fixture
def catalogue(session,tmp_path,monkeypatch):
    ps=[Product(name=f'已核验面霜{i}',brand='甲品牌' if i<3 else '乙品牌',category='面霜',price_current=100+i*100,spec='50g' if i!=2 else '50ml') for i in range(5)]
    ing=Ingredient(inci_name='SELECT-TEST',cn_name='测试成分');session.add_all(ps+[ing]);session.flush()
    for p in ps[:4]:session.add(ProductIngredient(product_id=p.id,ingredient_id=ing.id))
    assertion(session,ing,weight=0,efficacy='保湿')
    rows=[]
    for p in ps:
        session.add(PricePoint(product_id=p.id,date=datetime.date(2025,3,12),price=p.price_current,source='https://example.com/price',is_manual=True))
        rows.append({'product_id':p.id,'name':p.name,'brand':p.brand,'category':'面霜','identity_status':'verified',
            'category_source_url':'https://example.com/category','match_note':'核验样本',
            'price':{'amount':p.price_current,'currency':'CNY','spec':p.spec,'sampled_at':'2025-03-12',
                     'source_url':'https://example.com/price','identity_status':'verified'}})
    rows[1]['price']['identity_status']='unresolved'
    f=tmp_path/'catalog.json';f.write_text(json.dumps({'version':'selection-catalog-v1','scope_note':'测试核验范围','items':rows}));session.commit()
    monkeypatch.setattr(settings,'selection_catalog_path',str(f),raising=False)
    from app.services.product_space import reset_space_cache
    reset_space_cache();app.dependency_overrides[get_db]=lambda:session
    with TestClient(app) as c:yield c,ps,f
    app.dependency_overrides.clear();reset_space_cache()


def test_single_direction_real_zero_is_plottable_and_unknown_is_not(catalogue):
    c,ps,_=catalogue;r=c.get('/api/selection-map?efficacy=保湿&unit=g');assert r.status_code==200
    d=r.json();assert d['coverage']['verified']==5
    rows={p['id']:p for p in d['products']}
    assert rows[ps[0].id]['plottable'] and rows[ps[0].id]['evidence_score']==0
    assert rows[ps[0].id]['price_age_status']=='older_reference'
    assert not rows[ps[1].id]['plottable'] and 'price_unverified' in rows[ps[1].id]['exclusion_reasons']
    assert not rows[ps[2].id]['plottable'] and 'different_unit' in rows[ps[2].id]['exclusion_reasons']
    assert not rows[ps[4].id]['plottable'] and rows[ps[4].id]['evidence_score'] is None
    assert d['coverage']['plottable']==2


def test_filters_do_not_change_axes_or_remove_context(catalogue):
    c,ps,_=catalogue
    all_=c.get('/api/selection-map?unit=g').json()
    limited=c.get('/api/selection-map?unit=g&max_package_price=150&brand=甲品牌').json()
    assert all_['axes']==limited['axes']
    assert len(all_['products'])==len(limited['products'])==5
    rows={p['id']:p for p in limited['products']}
    assert rows[ps[0].id]['matches_filters']
    assert rows[ps[3].id]['plottable'] and not rows[ps[3].id]['matches_filters']
    assert limited['coverage']['matched']==1


def test_unit_default_uses_more_eligible_products_and_ties_prefer_g(catalogue):
    c,_,_=catalogue;d=c.get('/api/selection-map').json()
    assert d['unit']=='g' and d['unit_counts']=={'g':2,'ml':1}


def test_provenance_must_match_database_price_spec_and_sample_day(catalogue,session):
    c,ps,_=catalogue;ps[0].price_current=999;session.commit()
    d=c.get('/api/selection-map?unit=g').json();row=next(p for p in d['products'] if p['id']==ps[0].id)
    assert not row['plottable'] and 'price_unverified' in row['exclusion_reasons']


def test_full_space_exposes_only_verified_sample_markers(catalogue):
    c,ps,f=catalogue;d=c.get('/api/product-space').json()
    assert all(p['selection_sample'] and p['category_verified'] for p in d['products'])
    content=json.loads(f.read_text());content['items'][0]['name']='另一个版本';f.write_text(json.dumps(content))
    updated=c.get('/api/product-space').json();row=next(p for p in updated['products'] if p['id']==ps[0].id)
    assert not row['selection_sample']


def test_invalid_filters_are_rejected(catalogue):
    c,_,_=catalogue
    for query in ['unit=kg','efficacy=未知功效','max_package_price=-1','max_package_price=inf']:
        assert c.get('/api/selection-map?'+query).status_code==422


def test_month_precision_never_becomes_an_invented_day_age(catalogue,monkeypatch):
    import importlib
    from types import SimpleNamespace
    class FixedDate(datetime.date):
        @classmethod
        def today(cls):return cls(2026,10,20)
    monkeypatch.setattr(importlib.import_module('app.services.selection_map'),'datetime',SimpleNamespace(date=FixedDate))
    c,ps,f=catalogue
    content=json.loads(f.read_text());content['items'][0]['price'].update(reference_period='2026-09',reference_precision='month')
    f.write_text(json.dumps(content))
    row=next(p for p in c.get('/api/selection-map?unit=g').json()['products'] if p['id']==ps[0].id)
    assert row['price_age_status']=='monthly_reference'
    assert row['price_age_days_range']==[20,49]


def test_partial_formula_stays_out_even_if_known_components_have_evidence(catalogue):
    c,ps,f=catalogue
    content=json.loads(f.read_text());content['items'][0]['ingredient_list_status']='official_partial';f.write_text(json.dumps(content))
    row=next(p for p in c.get('/api/selection-map?unit=g').json()['products'] if p['id']==ps[0].id)
    assert not row['plottable'] and 'ingredients_incomplete' in row['exclusion_reasons']


def test_product_detail_preserves_label_coverage_and_catalogue_price_precision(catalogue):
    c,ps,f=catalogue;doc=json.loads(f.read_text());row=doc['items'][0]
    row.update(ingredient_list_status='official_partial',ingredient_names_raw=['甘油','未核项'],unmapped_ingredients=['未核项'],ingredient_source_url='https://example.com/label')
    row['price'].update(reference_period='2026-09',reference_precision='month',note='九月目录参考价')
    f.write_text(json.dumps(doc))
    d=c.get(f'/api/products/{ps[0].id}').json()
    assert d['source_coverage']['ingredient_list_status']=='official_partial'
    assert d['source_coverage']['unmapped_ingredients']==['未核项']
    assert d['price_reference_period']=='2026-09' and d['price_note']=='九月目录参考价'


def test_unknown_formula_coverage_status_fails_closed(catalogue):
    c,ps,f=catalogue;doc=json.loads(f.read_text());doc['items'][0]['ingredient_list_status']='unreviewed_source';f.write_text(json.dumps(doc))
    row=next(p for p in c.get('/api/selection-map?unit=g').json()['products'] if p['id']==ps[0].id)
    assert not row['plottable'] and 'ingredients_incomplete' in row['exclusion_reasons']
