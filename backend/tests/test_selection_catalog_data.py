import json
from pathlib import Path

def records():return json.loads(Path('data/research/selection_catalog_20261020.json').read_text())['records']

def test_official_sample_is_at_least_200_distinct_audited_skincare_products():
    rows=records();assert len(rows)>=200
    assert len({(r['brand'],r['official_id']) for r in rows})==len(rows)
    assert len({r['brand'] for r in rows})>=5
    assert all(r['is_bundle'] is False and r['sampled_at']=='2026-10-20' for r in rows)
    assert all(r['ingredient_source_url'] and r['ingredient_names'] for r in rows if r['ingredient_list_status']=='official_full')


def test_precise_product_type_overrides_broad_navigation_category():
    lookup={(r['brand'],r['official_id']):r for r in records()}
    expected={('巴黎欧莱雅','SC019'):'乳液',('巴黎欧莱雅','SC540'):'乳液',('资生堂','s18409'):'乳液',
              ('兰蔻','LAN00333'):'乳液',('娇韵诗','80082062'):'洁面',('娇韵诗','80100184'):'精华',('资生堂','1221'):'面膜'}
    for key,category in expected.items():assert lookup[key]['category']==category
    assert ('SK-II','genoptics-airy-uv-cream-cc-primer') not in lookup
