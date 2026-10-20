import json
from types import SimpleNamespace

from app.services.product_presentation import product_presentation, settings
from data.tools.build_product_presentations import parse_presentation


def test_cached_page_extracts_its_product_image_and_a_bounded_source_excerpt():
    slug='same-version'
    html=f'''<div id="product-main-image"><picture><source type="image/webp" srcset="https://incidecoder-content.storage.googleapis.com/a/products/{slug}/{slug}_front_photo_300x300@1x.webp 1x"><img src="https://incidecoder-content.storage.googleapis.com/a/products/{slug}/{slug}_front_photo_original.jpeg"></picture></div><span id="product-details">A source description <b>with</b> {'words '*40}</span>'''
    result=parse_presentation(html,slug)
    assert result['image_url'].endswith('@1x.webp')
    assert len(result['summary_excerpt'].split())==25
    assert result['summary_truncated'] is True
    assert parse_presentation(html,'different-version')['image_url'] is None


def test_presentation_is_bound_to_exact_product_identity_and_source(tmp_path,monkeypatch):
    entry={'id':7,'name':'版本甲','brand':'品牌甲','source_url':'https://incidecoder.com/products/same-version','image_url':'https://incidecoder-content.storage.googleapis.com/a/products/same-version/img.webp','summary_excerpt':'Source page description','source_kind':'community_product_page','recorded_at':'2026-08-05'}
    path=tmp_path/'presentations.json';path.write_text(json.dumps({'version':'product-presentations-v1','records':{'7':entry}}))
    monkeypatch.setattr(settings,'product_presentations_path',str(path))
    p=SimpleNamespace(id=7,name='版本甲',brand='品牌甲',source_url=entry['source_url'])
    assert product_presentation(p)['image_url']==entry['image_url']
    p.name='版本乙';assert product_presentation(p) is None
    p.name='版本甲';p.source_url='https://incidecoder.com/products/different';assert product_presentation(p) is None


def test_bad_or_missing_optional_presentation_does_not_break_product_data(tmp_path,monkeypatch):
    path=tmp_path/'broken.json';path.write_text('{broken')
    monkeypatch.setattr(settings,'product_presentations_path',str(path))
    assert product_presentation(SimpleNamespace(id=7,name='a',brand='b',source_url='https://example.com')) is None


def test_optional_wrong_shape_metadata_is_ignored(tmp_path,monkeypatch):
    p=SimpleNamespace(id=7,name='a',brand='b',source_url='https://example.com')
    for n,content in enumerate(['[]','null','{"version":"product-presentations-v1","records":[]}']):
        path=tmp_path/f'wrong-{n}.json';path.write_text(content)
        monkeypatch.setattr(settings,'product_presentations_path',str(path))
        assert product_presentation(p) is None


def test_incomplete_identity_cannot_make_optional_asset_break_product(tmp_path,monkeypatch):
    entry={'id':7,'name':'a','brand':'b'}
    path=tmp_path/'incomplete.json';path.write_text(json.dumps({'version':'product-presentations-v1','records':{'7':entry}}))
    monkeypatch.setattr(settings,'product_presentations_path',str(path))
    assert product_presentation(SimpleNamespace(id=7,name='a',brand='b',source_url=None)) is None
