"""evidence_loader 测试：正式成分入库、中文 stub 合并、幂等。"""

from data.loaders.evidence_loader import load_research
from app.models.evidence import Evidence
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.models.product import Product, ProductIngredient

RESEARCH = {
    "ingredients": [
        {
            "cn_name": "烟酰胺", "inci_name": "NIACINAMIDE", "cas_no": "98-92-0",
            "iecic_max_leave_on": 20.0,
            "assertions": [
                {"efficacy": "美白（抑制黑素小体转运）",
                 "evidence": {"type": "paper",
                              "title": "The effect of niacinamide on reducing cutaneous pigmentation and suppression of melanosome transfer",
                              "source": "British Journal of Dermatology, 2002;147(1):20-31",
                              "year": 2002,
                              "url": "https://pubmed.ncbi.nlm.nih.gov/12100180/",
                              "excerpt": "5% niacinamide moisturizer significantly decreased hyperpigmentation."},
                 "effective_conc_low": 2.0, "effective_conc_high": 5.0, "note": "临床常用 2%-5%"}
            ],
        },
        {
            # 无英文 INCI 的纯中文成分：不应触发合并也不应报错
            "cn_name": "积雪草提取物", "inci_name": "积雪草提取物", "cas_no": None,
            "assertions": [],
        },
    ]
}


def _mk_product_with_stub(session):
    """构造：一个产品含中文 stub 成分「烟酰胺」。"""
    stub = Ingredient(inci_name="烟酰胺", cn_name="烟酰胺")
    p = Product(name="测试精华", brand="测试牌")
    session.add_all([stub, p])
    session.flush()
    session.add(ProductIngredient(product_id=p.id, ingredient_id=stub.id, position=None))
    session.commit()
    return p, stub


def test_merge_cn_stub_into_canonical(session):
    p, stub = _mk_product_with_stub(session)
    stats = load_research(session, RESEARCH)
    session.commit()
    canonical = session.query(Ingredient).filter_by(inci_name="NIACINAMIDE").one()
    assert canonical.cn_name == "烟酰胺"
    assert canonical.iecic_max_leave_on == 20.0
    # stub 被删除，产品关联改指正式成分
    assert session.query(Ingredient).filter_by(inci_name="烟酰胺").count() == 0
    link = session.query(ProductIngredient).filter_by(product_id=p.id).one()
    assert link.ingredient_id == canonical.id
    assert stats["merged_links"] == 1
    # 断言与证据入库
    a = session.query(EfficacyAssertion).filter_by(ingredient_id=canonical.id).one()
    assert a.evidence.url.endswith("12100180/")
    assert a.effective_conc_low == 2.0


def test_load_research_idempotent(session):
    load_research(session, RESEARCH)
    session.commit()
    stats2 = load_research(session, RESEARCH)
    session.commit()
    assert stats2["evidence"] == 0 and stats2["assertions"] == 0
    assert session.query(EfficacyAssertion).count() == 1
    assert session.query(Ingredient).filter_by(inci_name="积雪草提取物").count() == 1


def test_merge_migrates_stub_assertions(session):
    """stub 上预先挂有断言时，合并必须把断言迁移到正式成分，不得随 stub 删除。"""
    from app.models.evidence import Evidence, EvidenceType

    stub = Ingredient(inci_name="烟酰胺", cn_name="烟酰胺")
    ev = Evidence(type=EvidenceType.PAPER, title="临时证据", source="某期刊", year=2020,
                  url="https://example.com/x")
    session.add_all([stub, ev])
    session.flush()
    session.add(EfficacyAssertion(ingredient_id=stub.id, efficacy="临时功效", evidence_id=ev.id))
    session.commit()

    load_research(session, RESEARCH)
    session.commit()
    canonical = session.query(Ingredient).filter_by(inci_name="NIACINAMIDE").one()
    assert session.query(Ingredient).filter_by(inci_name="烟酰胺").count() == 0
    moved = (session.query(EfficacyAssertion)
             .filter_by(ingredient_id=canonical.id, efficacy="临时功效").one())
    assert moved.evidence.title == "临时证据"
