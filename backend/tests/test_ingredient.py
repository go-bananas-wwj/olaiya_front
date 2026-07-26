import pytest
from sqlalchemy.exc import IntegrityError

from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import EfficacyAssertion, Ingredient


def _make_evidence(session) -> Evidence:
    e = Evidence(type=EvidenceType.PAPER, title="某论文", source="某期刊", year=2020)
    session.add(e)
    session.commit()
    return e


def test_ingredient_with_priors(session):
    ing = Ingredient(inci_name="NIACINAMIDE", cn_name="烟酰胺", cas_no="98-92-0",
                     iecic_max_leave_on=20.0, legal_cap=None)
    session.add(ing)
    session.commit()
    got = session.query(Ingredient).filter_by(inci_name="NIACINAMIDE").one()
    assert got.cn_name == "烟酰胺"
    assert got.iecic_max_leave_on == 20.0


def test_assertion_requires_evidence(session):
    ing = Ingredient(inci_name="RETINOL", cn_name="视黄醇")
    session.add(ing)
    session.commit()
    # 铁律验证：evidence_id 为空必须入库失败
    session.add(EfficacyAssertion(ingredient_id=ing.id, efficacy="抗皱", evidence_id=None))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_assertion_links_evidence(session):
    ing = Ingredient(inci_name="RETINOL", cn_name="视黄醇")
    ev = _make_evidence(session)
    session.add(ing)
    session.commit()
    a = EfficacyAssertion(ingredient_id=ing.id, efficacy="抗皱", evidence_id=ev.id,
                          effective_conc_low=0.1, effective_conc_high=0.4)
    session.add(a)
    session.commit()
    got = session.query(EfficacyAssertion).one()
    assert got.evidence.title == "某论文"
    assert got.ingredient.inci_name == "RETINOL"


def test_assertion_rejects_dangling_evidence(session):
    """铁律补全：指向不存在证据的 evidence_id 必须被拒（外键约束生效）。"""
    ing = Ingredient(inci_name="DUMMY", cn_name="dummy")
    session.add(ing)
    session.commit()
    session.add(EfficacyAssertion(ingredient_id=ing.id, efficacy="测试", evidence_id=99999))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
