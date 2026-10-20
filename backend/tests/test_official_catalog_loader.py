import json
import datetime
import pytest
from app.models.product import Product,ProductIngredient,PricePoint
from app.models.ingredient import Ingredient


def record(**overrides):
    return {'official_id':'C001','name':'官方保湿霜','brand':'核验品牌','category':'面霜',
            'source_url':'https://example.com/product/C001','sampled_at':'2025-03-12',
            'category_source_url':'https://example.com/face','identity_note':'官方具体商品与单品规格',
            'reference_price':100,'currency':'CNY','spec':'50g','terms_status':'metadata_facts_only',
            'ingredient_list_status':'official_full','ingredient_names':['甘油','烟酰胺','品牌复合物'],
            'ingredient_source_url':'https://example.com/product/C001',**overrides}


def test_official_identity_is_idempotent_and_does_not_borrow_an_old_formula(session,tmp_path):
    from data.loaders.official_catalog_loader import import_catalogue
    old=Product(name='官方保湿霜',brand='核验品牌',source_url='https://example.com/old-version');session.add(old);session.flush()
    g=Ingredient(inci_name='GLYCERIN',cn_name='甘油');session.add(g);session.flush()
    result=import_catalogue(session,[record()]);session.flush()
    p=session.query(Product).filter_by(source_url=record()['source_url']).one()
    assert p.id!=old.id and p.price_current==100
    assert session.query(ProductIngredient).filter_by(product_id=p.id).count()==2
    assert all(x.position is None for x in session.query(ProductIngredient).filter_by(product_id=p.id))
    assert session.query(PricePoint).one().date==datetime.date(2025,3,12)
    assert result['items'][0]['unmapped_ingredients']==['品牌复合物']
    assert result['items'][0]['ingredient_list_status']=='official_full'
    import_catalogue(session,[record()]);session.flush()
    assert session.query(Product).count()==2 and session.query(PricePoint).count()==1


def test_missing_ingredients_are_missing_not_replaced_by_marketing_claims(session):
    from data.loaders.official_catalog_loader import import_catalogue
    result=import_catalogue(session,[record(ingredient_names=[],ingredient_list_status='missing')]);session.flush()
    assert session.query(ProductIngredient).count()==0
    assert result['items'][0]['ingredient_list_status']=='missing'


def test_restricted_sources_invalid_dates_and_bundles_fail_before_mutation(session):
    from data.loaders.official_catalog_loader import import_catalogue
    for bad in [record(terms_status='restricted_collection_and_republication'),record(sampled_at='2026-09'),record(is_bundle=True),record(reference_price=0)]:
        with pytest.raises(ValueError):import_catalogue(session,[bad])
        assert session.query(Product).count()==0


def test_two_products_can_share_a_catalogue_pdf_without_sharing_identity(session):
    from data.loaders.official_catalog_loader import import_catalogue
    a=record(official_id='PDF001',name='官方面霜甲',source_url='https://example.com/catalogue.pdf',price_source_url='https://example.com/catalogue.pdf',ingredient_list_status='missing',ingredient_names=[])
    b=record(official_id='PDF002',name='官方面霜乙',source_url=a['source_url'],ingredient_list_status='missing',ingredient_names=[])
    import_catalogue(session,[a,b]);session.flush()
    assert session.query(Product).count()==2
    import_catalogue(session,[a,b]);session.flush()
    assert session.query(Product).count()==2


def test_price_and_ingredient_provenance_can_differ_from_product_landing_page(session):
    from data.loaders.official_catalog_loader import import_catalogue
    result=import_catalogue(session,[record(price_source_url='https://example.com/catalogue.pdf')]);session.flush()
    assert session.query(PricePoint).one().source=='https://example.com/catalogue.pdf'
    assert result['items'][0]['price']['source_url']=='https://example.com/catalogue.pdf'


def test_changed_formula_is_not_silently_union_merged(session):
    from data.loaders.official_catalog_loader import import_catalogue
    import_catalogue(session,[record()]);session.flush()
    with pytest.raises(ValueError,match='formula'):
        import_catalogue(session,[record(ingredient_names=['烟酰胺'])])


def test_changed_unmapped_formula_or_filing_cannot_reuse_an_old_identity(session):
    from data.loaders.official_catalog_loader import import_catalogue
    initial=record(ingredient_names=['GLYCERIN','UNKNOWN-OLD'],filing_id='国妆2023000001')
    import_catalogue(session,[initial]);session.flush()
    for changed in [dict(initial,ingredient_names=['GLYCERIN','UNKNOWN-NEW']),dict(initial,filing_id='国妆2026000002')]:
        with pytest.raises(ValueError,match='formula|version'):
            import_catalogue(session,[changed])
