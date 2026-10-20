import json
import datetime
import pytest
from app.models.product import Product,PricePoint


def test_verified_updates_require_explicit_mode_and_keep_sampling_day(session,tmp_path):
    from data.loaders.selection_catalog_loader import load_selection_catalog
    p=Product(name='精确面霜（版本A）',brand='测试品牌',price_current=90,spec='50g');session.add(p);session.flush()
    row={'product_id':p.id,'name':p.name,'brand':p.brand,'identity_status':'verified','category':'面霜',
         'category_source_url':'https://example.com/cream','match_note':'核验具体版本',
         'price':{'identity_status':'verified','amount':100,'currency':'CNY','spec':'50g','source_url':'https://example.com/price','sampled_at':'2025-03-12'}}
    f=tmp_path/'sample.json';f.write_text(json.dumps({'version':'selection-catalog-v1','items':[row]}))
    first=load_selection_catalog(session,f)
    assert p.price_current==90 and first['prices_updated']==0
    result=load_selection_catalog(session,f,apply_verified_updates=True);session.flush()
    assert p.price_current==100 and session.query(PricePoint).one().date==datetime.date(2025,3,12)
    assert result['changes'][0]['previous_price']==90
    load_selection_catalog(session,f,apply_verified_updates=True);session.flush()
    assert session.query(PricePoint).count()==1


def test_identity_mismatch_does_not_fall_back_to_fuzzy_name(session,tmp_path):
    from data.loaders.selection_catalog_loader import load_selection_catalog
    p=Product(name='面霜版本A',brand='测试品牌');session.add(p);session.flush()
    f=tmp_path/'sample.json';f.write_text(json.dumps({'version':'selection-catalog-v1','items':[{
        'product_id':p.id,'name':'面霜版本B','brand':p.brand,'identity_status':'verified','category':'面霜',
        'category_source_url':'https://example.com','match_note':'版本不符'}]}))
    with pytest.raises(ValueError):load_selection_catalog(session,f,apply_verified_updates=True)
    assert p.category is None and p.price_current is None
