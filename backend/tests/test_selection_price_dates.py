import datetime
import json

from app.models.product import Product, PricePoint
from data.loaders.price_loader import load_prices


def test_price_date_is_actual_sample_date_not_import_day(session, tmp_path):
    p = Product(name='日期核验面霜', brand='测试品牌')
    session.add(p); session.flush()
    f = tmp_path/'prices.json'
    f.write_text(json.dumps({'items':[{'product_id':p.id,'match':p.name,'brand':p.brand,
        'price':200,'spec':'50g','source_url':'https://example.com/cream','sampled_at':'2025-03-12'}]}))
    load_prices(session, f); session.flush()
    assert session.query(PricePoint).one().date == datetime.date(2025,3,12)


def test_undated_prices_are_not_given_a_fictitious_sample_date(session, tmp_path):
    p=Product(name='未知日期',brand='测试品牌',price_current=90)
    session.add(p);session.flush()
    f=tmp_path/'undated.json';f.write_text(json.dumps({'items':[{'product_id':p.id,'match':p.name,
        'brand':p.brand,'price':100,'spec':'50g','source_url':'https://example.com/cream'}]}))
    stats=load_prices(session,f);session.flush()
    assert session.query(PricePoint).count()==0
    assert p.price_current==90
    assert stats['invalid_dates']==[p.name]


def test_future_or_month_only_sample_dates_do_not_mutate_prices(session,tmp_path):
    p=Product(name='异常日期',brand='测试品牌');session.add(p);session.flush()
    for index, date in enumerate(['2099-01-01','2025-03','bad-date']):
        f=tmp_path/f'date{index}.json';f.write_text(json.dumps({'items':[{'product_id':p.id,
            'match':p.name,'brand':p.brand,'price':100,'spec':'50g','source_url':'https://example.com','sampled_at':date}]}))
        stats=load_prices(session,f)
        assert stats['matched']==0
    assert p.price_current is None and session.query(PricePoint).count()==0
