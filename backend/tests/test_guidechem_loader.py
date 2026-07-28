"""guidechem_loader 测试：用一份模拟采集 JSON 验证导入与幂等。"""

from data.loaders.guidechem_loader import load_product
from app.models.ingredient import Ingredient
from app.models.product import Product, ProductClaim, ProductIngredient

SAMPLE = {
    "name": "测试胶原多肽精华液",
    "nmpa_id": "国妆网备进字（沪）2024002318",
    "efficacies": ["修护", "保湿", "抗皱", "紧致"],
    "ingredients": [
        {"name": "苯氧乙醇", "safety_risk": "2-4", "is_active": False, "purpose": "防腐剂"},
        {"name": "水", "safety_risk": "1", "is_active": False, "purpose": "溶剂"},
        {"name": "胶原", "safety_risk": "1", "is_active": True, "purpose": "保湿剂;抗氧化剂"},
    ],
    "claims": [
        {"claim": "修护", "eval_category": "人体功效评价试验", "method_name": "化妆品功效的仪器客观评估",
         "method_source": "专业学术杂志、期刊", "metric": "经表皮水分流失率",
         "test_period": "2023年07月26日-2023年08月11日",
         "result_summary": "25名受试者……显著性降低。", "institution": "欧莱雅（中国）有限公司"},
        {"claim": "抗皱", "eval_category": "消费者使用测试", "method_name": "化妆品功效的消费者主观评价",
         "method_source": "自拟方法", "metric": None,
         "test_period": "2023年07月16日-2023年08月14日",
         "result_summary": "62名女性消费者……支持抗皱紧致。", "institution": "欧莱雅（中国）有限公司"},
    ],
    "registration": {"registrant": "欧莱雅（中国）有限公司", "manufacturers": [], "filing_date": "2024-04-03"},
    "source": {"site": "china.guidechem.com", "url": "https://china.guidechem.com/datacenter/hzpdetails-x.html",
               "collected_at": "2026-07-26 13:00:00", "note": "镜像 NMPA 公示数据；成分表为拼音排序"},
    "search_brand": "修丽可",
}


def test_load_product_full(session):
    p = load_product(session, SAMPLE)
    session.commit()
    assert p.nmpa_id == "国妆网备进字（沪）2024002318"
    assert p.brand == "修丽可"
    # 结构化备案字段直接入库列，不依赖 note 反解
    assert p.registrant == "欧莱雅（中国）有限公司"
    assert p.filing_date == "2024-04-03"
    assert p.source_url == "https://china.guidechem.com/datacenter/hzpdetails-x.html"
    links = (session.query(ProductIngredient).filter_by(product_id=p.id)
             .order_by(ProductIngredient.id).all())
    assert len(links) == 3
    # 关键：镜像站顺序非备案降序，位次必须为 NULL，不得伪造
    assert all(l.position is None for l in links)
    assert {l.ingredient.cn_name for l in links} == {"苯氧乙醇", "水", "胶原"}
    claims = session.query(ProductClaim).filter_by(product_id=p.id).all()
    assert len(claims) == 2
    repair = [c for c in claims if c.claim == "修护"][0]
    assert repair.metric == "经表皮水分流失率"
    assert "欧莱雅" in repair.institution


def test_load_product_idempotent(session):
    load_product(session, SAMPLE)
    session.commit()
    load_product(session, SAMPLE)
    session.commit()
    assert session.query(Product).filter_by(nmpa_id=SAMPLE["nmpa_id"]).count() == 1
    assert session.query(ProductClaim).count() == 2
    assert session.query(ProductIngredient).count() == 3
    # 中文名成分不重复建
    assert session.query(Ingredient).filter_by(cn_name="胶原").count() == 1


def test_duplicate_claim_quad_in_one_json(session):
    """同一 JSON 内出现完全相同的宣称四元组时，只能入一条（autoflush 下查询不可见的历史 bug）。"""
    import copy
    data = copy.deepcopy(SAMPLE)
    data["claims"].append(copy.deepcopy(data["claims"][0]))  # 完全重复的一条
    load_product(session, data)
    session.commit()
    assert session.query(ProductClaim).count() == 2
    # 重复加载后仍不爆炸（历史重复数据兼容：first() 而非 one_or_none()）
    load_product(session, data)
    session.commit()
    assert session.query(ProductClaim).count() == 2
