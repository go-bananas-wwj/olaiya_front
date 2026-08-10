"""cosing_loader 测试：功能码映射、措辞保守性、幂等、跳过清单、unknown 证据档。"""

import json

import pytest

from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.services.efficacy_canon import canonicalize
from data.loaders.cosing_loader import (
    FUNCTION_MAP, NOTE_DISCLAIMER, SKIP_REASONS, efficacy_text, load_cosing,
)

# 措辞越界词：断言 efficacy 文本绝不允许出现（申报功能 ≠ 功效实证）
FORBIDDEN_WORDS = ("证明", "实证", "临床", "人体", "试验", "研究")

SEED = {
    "source": {"collected_at": "2026-08-10", "entries_in_seed": 3},
    "map": {
        "GLYCERIN": ["HUMECTANT", "MOISTURISING", "SOLVENT", "VISCOSITY CONTROLLING"],
        "TOCOPHEROL": ["ANTIOXIDANT", "MASKING", "SKIN CONDITIONING"],
        "CARBOMER": ["GEL FORMING", "VISCOSITY CONTROLLING"],  # 只有跳过码
    },
}


def _seed_ingredients(session):
    session.add_all([
        Ingredient(inci_name="GLYCERIN", cn_name="甘油"),
        Ingredient(inci_name="tocopherol", cn_name="生育酚"),  # 小写：归一化应命中
        Ingredient(inci_name="CARBOMER", cn_name="卡波姆"),
        Ingredient(inci_name="XY-NOT-IN-COSING", cn_name="未收录"),
    ])
    session.flush()


def test_function_map_covers_only_safe_codes():
    """映射表每个码必须归族到预期规范族，且不在跳过清单中（防重复登记）。"""
    expected_family = {
        "MOISTURISING": "保湿", "HUMECTANT": "保湿", "OCCLUSIVE": "保湿",
        "SKIN CONDITIONING - HUMECTANT": "保湿", "SKIN CONDITIONING - OCCLUSIVE": "保湿",
        "ANTIOXIDANT": "抗氧化", "SOOTHING": "舒缓",
        "EXFOLIATING": "焕肤", "KERATOLYTIC": "焕肤",
        "ANTI-SEBUM": "控油祛痘", "ANTI-SEBORRHEIC": "控油祛痘",
        "PRESERVATIVE": "防腐",
    }
    assert set(FUNCTION_MAP) == set(expected_family)
    for code, family in expected_family.items():
        assert code not in SKIP_REASONS
        assert canonicalize(efficacy_text(FUNCTION_MAP[code])) == family


def test_ambiguous_codes_in_skip_list():
    """ambiguous 功能码必须在跳过清单中，绝不映射。"""
    for code in ("MASKING", "VISCOSITY CONTROLLING", "SKIN CONDITIONING",
                 "SKIN CONDITIONING - EMOLLIENT", "ANTIMICROBIAL", "BLEACHING",
                 "FILM FORMING", "SMOOTHING"):
        assert code in SKIP_REASONS
        assert code not in FUNCTION_MAP


def test_efficacy_wording_conservative():
    """断言措辞：固定「功能分类：XX（CosIng 官方申报功能）」，无越界词。"""
    for cn in FUNCTION_MAP.values():
        text = efficacy_text(cn)
        assert text == f"功能分类：{cn}（CosIng 官方申报功能）"
        for w in FORBIDDEN_WORDS:
            assert w not in text


def test_load_cosing_basic(session):
    _seed_ingredients(session)
    stats = load_cosing(session, json.loads(json.dumps(SEED)))
    session.commit()

    assert stats["ingredients_matched"] == 3  # GLYCERIN/tocopherol/CARBOMER
    assert stats["ingredients_unmatched"] == 1
    # 甘油：HUMECTANT+MOISTURISING 同族去重 → 1 条保湿；SOLVENT/VISCOSITY 跳过
    gly = session.query(Ingredient).filter_by(inci_name="GLYCERIN").one()
    gly_assertions = session.query(EfficacyAssertion).filter_by(ingredient_id=gly.id).all()
    assert len(gly_assertions) == 1
    assert gly_assertions[0].efficacy == "功能分类：保湿（CosIng 官方申报功能）"
    assert gly_assertions[0].efficacy_canonical == "保湿"
    assert NOTE_DISCLAIMER in gly_assertions[0].note
    assert "HUMECTANT" in gly_assertions[0].note or "MOISTURISING" in gly_assertions[0].note
    # 小写 tocopherol 归一化命中 → 抗氧化
    toc = session.query(Ingredient).filter_by(cn_name="生育酚").one()
    toc_assertions = session.query(EfficacyAssertion).filter_by(ingredient_id=toc.id).all()
    assert [a.efficacy for a in toc_assertions] == ["功能分类：抗氧化（CosIng 官方申报功能）"]
    # CARBOMER 全是跳过码 → 无断言
    carb = session.query(Ingredient).filter_by(inci_name="CARBOMER").one()
    assert session.query(EfficacyAssertion).filter_by(ingredient_id=carb.id).count() == 0
    assert stats["functions_skipped"] >= 5  # SOLVENT/VISCOSITY/MASKING/SKIN CONDITIONING/GEL FORMING


def test_evidence_is_database_type_and_unknown_level(session):
    _seed_ingredients(session)
    load_cosing(session, json.loads(json.dumps(SEED)))
    session.commit()

    ev = session.query(Evidence).one()
    assert ev.type == EvidenceType.DATABASE
    assert ev.source == "European Commission CosIng"
    assert ev.url == "https://ec.europa.eu/growth/tools-databases/cosing/"
    assert "CosIng" in ev.title and "2026-08-10" in ev.title
    # database 类型无任何实验信号 → unknown 档（拿不准落 unknown）
    for a in session.query(EfficacyAssertion).all():
        assert a.evidence_level == "unknown"
        assert a.evidence_strength == pytest.approx(0.2)


def test_load_cosing_idempotent(session):
    _seed_ingredients(session)
    seed = json.loads(json.dumps(SEED))
    s1 = load_cosing(session, seed)
    session.commit()
    s2 = load_cosing(session, seed)
    session.commit()

    assert s1["assertions_new"] == 2 and s1["evidence_new"] == 1
    assert s2["assertions_new"] == 0 and s2["evidence_new"] == 0
    assert s2["assertions_existing"] == 2
    assert session.query(EfficacyAssertion).count() == 2
    assert session.query(Evidence).count() == 1


def test_unknown_function_code_not_mapped(session):
    """词表出现 loader 未登记的功能码：绝不猜测映射，如实计数。"""
    session.add(Ingredient(inci_name="FOO", cn_name="FOO"))
    session.flush()
    seed = {"source": {"collected_at": "2026-08-10", "entries_in_seed": 1},
            "map": {"FOO": ["BRAND-NEW-CODE-2099"]}}
    stats = load_cosing(session, seed)
    session.commit()
    assert stats["assertions_new"] == 0
    assert stats["functions_unknown_code"] == 1
    assert stats["skipped_codes"].get("?BRAND-NEW-CODE-2099") == 1
