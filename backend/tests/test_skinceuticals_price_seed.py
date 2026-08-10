"""修丽可价格种子匹配器：归一键、双通道匹配、消歧（拿不准不匹配）。"""

import json

import pytest

from app.models.ingredient import Ingredient
from app.models.product import Product, ProductClaim, ProductIngredient
from data.tools import build_skinceuticals_price_seed as b


def test_slug_and_product_keys():
    assert b.slug_key("TripleLipidRestore242") == "TRIPLELIPIDRESTORE242"
    assert "CEFERULIC" in b.product_keys("SkinCeuticals C E Ferulic")
    # 括号内容单独成键（中文名的英文别名通道）
    assert "HAINTENSIFIER" in b.product_keys("紫米精华（H.A. Intensifier）")
    # 繁体归一 + 品牌前缀剥离
    assert "清润温和洁面乳" in b.product_keys("修丽可清潤温和洁面乳")
    # 重音折叠
    assert "DISCOLORATIONDEFENSESERUM" in b.product_keys(
        "SkinCeuticals Discoloration Defense Sérum")


def _mk_raw(tmp_path, slug, name_cn, price=100.0):
    d = tmp_path / "raw"
    d.mkdir(exist_ok=True)
    (d / f"{slug}.json").write_text(json.dumps({
        "slug": slug, "name_cn": name_cn, "price": price, "spec": "30ml",
        "source": {"url": f"https://www.skinceuticals.com.cn/productdtl/productdtl-{slug}.html"}},
        ensure_ascii=False), encoding="utf-8")
    return d


def test_match_english_channel(session, tmp_path, monkeypatch):
    session.add(Product(name="SkinCeuticals C E Ferulic", brand="修丽可"))
    session.commit()
    raw = _mk_raw(tmp_path, "CEferulic", "修丽可維生素CE复合焕颜精华液", 1720.0)
    monkeypatch.setattr(b, "RAW_DIR", raw)
    result = b.match_all(session)
    assert len(result["matched"]) == 1
    assert result["matched"][0]["product"].name == "SkinCeuticals C E Ferulic"
    assert result["unmatched"] == []


def test_match_chinese_channel_and_disambiguation(session, tmp_path, monkeypatch):
    """中文精确名命中；英文名/中文名双候选时按「有序优先」消歧。"""
    ing = Ingredient(inci_name="AQUA", cn_name="水")
    session.add(ing)
    session.flush()
    en = Product(name="SkinCeuticals Daily Moisture", brand="修丽可")
    cn = Product(name="修丽可海洋精萃保湿霜", brand="修丽可")
    session.add_all([en, cn])
    session.flush()
    # 英文产品有位次关联（有序），中文产品无 → 消歧选英文产品
    session.add(ProductIngredient(product_id=en.id, ingredient_id=ing.id, position=1))
    session.add(ProductIngredient(product_id=cn.id, ingredient_id=ing.id, position=None))
    session.commit()
    raw = _mk_raw(tmp_path, "DailyMoisture", "修丽可海洋精萃保湿霜")
    monkeypatch.setattr(b, "RAW_DIR", raw)
    result = b.match_all(session)
    assert len(result["matched"]) == 1
    assert result["matched"][0]["product"].id == en.id


def test_ambiguous_same_key_unmatched(session, tmp_path, monkeypatch):
    """同归一键两个独立产品（采集重复条目）→ 不猜，unmatched 附候选。"""
    for name in ("SkinCeuticals Advanced Brightening UV Defense Sunscreen SPF50",
                 "SkinCeuticals Advanced Brightening Uv Defense Sunscreen Spf 50"):
        session.add(Product(name=name, brand="修丽可"))
    session.commit()
    raw = _mk_raw(tmp_path, "AdvancedBrighteningUVDefenseSunscreenSPF50", "修丽可臻彩焕亮精华防晒乳")
    monkeypatch.setattr(b, "RAW_DIR", raw)
    result = b.match_all(session)
    assert result["matched"] == []
    assert len(result["unmatched"]) == 1
    assert len(result["unmatched"][0]["candidates"]) == 2


def test_no_candidate_unmatched(session, tmp_path, monkeypatch):
    session.add(Product(name="SkinCeuticals C E Ferulic", brand="修丽可"))
    session.commit()
    raw = _mk_raw(tmp_path, "PhloretinCF", "修丽可臻白焕亮日间精华液")
    monkeypatch.setattr(b, "RAW_DIR", raw)
    result = b.match_all(session)
    assert result["matched"] == []
    assert result["unmatched"][0]["candidates"] == []


def test_discontinued_variant_dropped(session, tmp_path, monkeypatch):
    a = Product(name="SkinCeuticals Metacell Renewal B3", brand="修丽可")
    b2 = Product(name="SkinCeuticals Metacell Renewal B3 (Discontinued)", brand="修丽可")
    session.add_all([a, b2])
    session.commit()
    raw = _mk_raw(tmp_path, "MetacellRenewalB3", "修丽可烟酰胺多重修护乳")
    monkeypatch.setattr(b, "RAW_DIR", raw)
    result = b.match_all(session)
    assert result["matched"][0]["product"].id == a.id
