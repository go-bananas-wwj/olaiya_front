"""证据层级/强度结构化：分类规则、默认强度映射、回填幂等、加载器联动。

分类原则：note 标注优先、证据类型兜底、拿不准一律 unknown（数据铁律，禁止猜测）。
"""

from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.services.evidence_level import (
    DEFAULT_EVIDENCE_STRENGTH,
    EVIDENCE_LEVELS,
    classify_evidence_level,
    default_strength,
)
from data.loaders.evidence_loader import load_research
from data.tools.backfill_evidence_level import backfill_session


def _ev(type_="paper", excerpt=None):
    return Evidence(type=EvidenceType(type_), title="某证据", source="某期刊", excerpt=excerpt)


# —— 分类规则：note 关键词 ——

def test_note_oral():
    assert classify_evidence_level("口服（系统性）证据而非外用", _ev()) == "oral"
    assert classify_evidence_level("口服 + 开放试验（弱证据）", _ev()) == "oral"


def test_note_oral_beats_animal():
    """口服与动物并存时取口服（更保守的降级优先）。"""
    assert classify_evidence_level("动物 + 口服研究（弱证据）；外用人体功效证据缺乏", _ev()) == "oral"


def test_note_animal():
    assert classify_evidence_level("动物实验（Skh:2小鼠），外用5%浓度", _ev()) == "animal"
    assert classify_evidence_level("0.5% 为豚鼠外用实验浓度", _ev()) == "animal"  # 豚鼠=动物
    assert classify_evidence_level("体外细胞及动物实验，未给出化妆品配方起效浓度", _ev()) == "animal"


def test_note_in_vitro():
    assert classify_evidence_level("体外研究", _ev()) == "in_vitro"
    assert classify_evidence_level("体外细胞研究，未涉及人体外用浓度。", _ev()) == "in_vitro"


def test_note_review():
    assert classify_evidence_level("叙述性综述，证据等级较低。", _ev()) == "review"


def test_note_human_ct():
    assert classify_evidence_level("消费者使用测试，自评问卷", _ev()) == "human_ct"


def test_note_human_rct():
    assert classify_evidence_level("随机双盲人体试验", _ev()) == "human_rct"
    assert classify_evidence_level("人体随机对照试验（市售成品制剂）", _ev()) == "human_rct"
    assert classify_evidence_level("临床试验常用浓度 2%-5%", _ev()) == "human_rct"
    assert classify_evidence_level("ppm 级起效；双盲分脸人体试验", _ev()) == "human_rct"


def test_observational_not_human_rct():
    """观察性人体研究不是干预试验，落 unknown 而非拔高为 human_rct。"""
    note = "弱证据：人体皮肤活检/UV照射机制观察性研究，非外用SOD功效干预试验"
    assert classify_evidence_level(note, _ev()) == "unknown"


# —— 证据类型兜底与 excerpt 推断 ——

def test_regulation_type():
    assert classify_evidence_level(None, _ev("regulation")) == "regulation"
    note = "法定最大允许使用浓度 1.0%（法规限值，非功效起效浓度）"
    assert classify_evidence_level(note, _ev("regulation")) == "regulation"


def test_empty_note_excerpt_keywords():
    assert classify_evidence_level(None, _ev(excerpt="体外细胞实验证实抗氧化")) == "in_vitro"
    assert classify_evidence_level(None, _ev(excerpt="随机双盲安慰剂对照试验")) == "human_rct"


def test_excerpt_explant_not_human_rct():
    """「人体皮肤外植体」是离体语境，excerpt 里裸「人体」不得升级为 human_rct。"""
    excerpt = "人体皮肤外植体与重建表皮模型实验：1.8% AA2G 被皮肤完全代谢"
    assert classify_evidence_level(None, _ev(excerpt=excerpt)) == "unknown"


def test_note_without_keyword_falls_to_excerpt():
    note = "0.1% 即可显著改善皮肤水合"
    assert classify_evidence_level(note, _ev(excerpt="体外重建皮肤模型")) == "in_vitro"
    assert classify_evidence_level(note, _ev(excerpt=None)) == "unknown"


def test_unknown_when_no_signal():
    assert classify_evidence_level(None, _ev()) == "unknown"
    assert classify_evidence_level(None, _ev("patent")) == "unknown"
    assert classify_evidence_level("摘要未披露具体浓度", _ev()) == "unknown"


# —— 默认强度映射 ——

def test_strength_map_complete():
    assert set(DEFAULT_EVIDENCE_STRENGTH) == set(EVIDENCE_LEVELS)
    for level, score in DEFAULT_EVIDENCE_STRENGTH.items():
        assert 0.0 <= score <= 1.0, level
        assert default_strength(level) == score
    assert DEFAULT_EVIDENCE_STRENGTH["human_rct"] == 1.0
    assert DEFAULT_EVIDENCE_STRENGTH["unknown"] == 0.2


# —— 回填脚本 ——

def _mk_assertion(session, note, excerpt=None, type_="paper"):
    ing = Ingredient(inci_name=f"INCI-{note}-{excerpt}", cn_name="测试成分")
    ev = Evidence(type=EvidenceType(type_), title=f"标题-{note}-{excerpt}",
                  source="某期刊", excerpt=excerpt)
    session.add_all([ing, ev])
    session.flush()
    a = EfficacyAssertion(ingredient_id=ing.id, efficacy="测试功效",
                          evidence_id=ev.id, note=note)
    session.add(a)
    session.flush()
    return a


def test_backfill_fills_and_idempotent(session):
    a1 = _mk_assertion(session, "口服（系统性）证据而非外用")
    a2 = _mk_assertion(session, "体外研究（弱证据）")
    a3 = _mk_assertion(session, None, excerpt="随机双盲安慰剂对照")

    dist1 = backfill_session(session)
    session.commit()
    got = {a.id: (a.evidence_level, a.evidence_strength) for a in (a1, a2, a3)}
    assert got[a1.id] == ("oral", DEFAULT_EVIDENCE_STRENGTH["oral"])
    assert got[a2.id] == ("in_vitro", DEFAULT_EVIDENCE_STRENGTH["in_vitro"])
    assert got[a3.id] == ("human_rct", DEFAULT_EVIDENCE_STRENGTH["human_rct"])
    assert dist1["oral"] == 1 and dist1["in_vitro"] == 1 and dist1["human_rct"] == 1

    dist2 = backfill_session(session)  # 重跑结果不变
    session.commit()
    assert dist1 == dist2
    assert {a.id: (a.evidence_level, a.evidence_strength) for a in (a1, a2, a3)} == got


# —— 加载器联动 ——

def test_loader_autofills_level(session):
    data = {"ingredients": [{
        "cn_name": "测试酰胺", "inci_name": "TESTAMIDE",
        "assertions": [
            {"efficacy": "测试功效A",
             "evidence": {"type": "paper", "title": "双盲试验文献", "source": "某期刊"},
             "note": "随机双盲人体试验，2%浓度。"},
            {"efficacy": "测试功效B",
             "evidence": {"type": "paper", "title": "细胞实验文献", "source": "某期刊",
                          "excerpt": "体外细胞实验"},
             "note": None},
        ],
    }]}
    load_research(session, data)
    session.commit()
    a = session.query(EfficacyAssertion).filter_by(efficacy="测试功效A").one()
    assert a.evidence_level == "human_rct"
    assert a.evidence_strength == DEFAULT_EVIDENCE_STRENGTH["human_rct"]
    b = session.query(EfficacyAssertion).filter_by(efficacy="测试功效B").one()
    assert b.evidence_level == "in_vitro"
    assert b.evidence_strength == DEFAULT_EVIDENCE_STRENGTH["in_vitro"]
