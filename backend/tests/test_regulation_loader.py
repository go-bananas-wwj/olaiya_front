"""regulation_loader 测试：功效族定义只入证据不建断言、表3 限用回填与措辞、幂等、冲突不覆盖。"""

import json
from pathlib import Path

from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import EfficacyAssertion, Ingredient
from data.loaders.inci_cn_loader import InciResolver
from data.loaders.regulation_loader import (
    load_efficacy_definitions, load_restricted, _spec_evidence_title,
)

EFF_SEED = {
    "source": {"official_url_49": "https://www.nmpa.gov.cn/xxgk/fgwj/xzhgfxwj/20210409160151122.html"},
    "categories": [
        {"code": "03", "name": "祛斑美白",
         "definition": "有助于减轻或减缓皮肤色素沉着，达到皮肤美白增白效果",
         "eval_requirement": "human_required",
         "eval_note": "附1 第1项：人体功效评价试验为必做（√）"},
        {"code": "11", "name": "保湿",
         "definition": "用于补充或增强施用部位水分、油脂等成分含量",
         "eval_requirement": "any_method",
         "eval_note": "附1 第14项：四栏均画*，任选其一即可"},
    ],
}

RES_SEED = {
    "source": {"official_url": "https://www.nmpa.gov.cn/example.pdf"},
    "entries": [
        {"no": 13, "cn_name": "间苯二酚", "en_name": "Resorcinol", "inci_name": "Resorcinol",
         "scope": "发露和香波", "max_conc": "0.5%", "other_limits": "",
         "label_warning": "含间苯二酚", "note_refs": [],
         "match_inci": ["RESORCINOL"], "legal_cap": 0.5,
         "assertion": "法定限用：发露和香波最高 0.5%；标签须标印「含间苯二酚」（《化妆品安全技术规范2015》表3）"},
        {"no": 8, "cn_name": "水杨酸", "en_name": "Salicylic acid", "inci_name": "Salicylic acid",
         "scope": "(a) 驻留类产品和淋洗类肤用产品；(b) 淋洗类发用产品",
         "max_conc": "(a) 2.0%；(b) 3.0%", "other_limits": "除香波外，不得用于三岁以下儿童使用的产品中",
         "label_warning": "含水杨酸；三岁以下儿童勿用", "note_refs": ["1", "2"],
         "match_inci": ["SALICYLIC ACID"], "legal_cap": None,
         "assertion": "法定限用：驻留类产品和淋洗类肤用产品最高 2.0%、淋洗类发用产品最高 3.0%（《化妆品安全技术规范2015》表3）"},
        {"no": 37, "cn_name": "α-羟基酸及其盐类和酯类", "en_name": "α-Hydroxy acids", "inci_name": "",
         "scope": "", "max_conc": "总量 6%（以酸计）", "other_limits": "pH≥3.5",
         "label_warning": "", "note_refs": ["6"],
         "match_inci": [], "legal_cap": None, "assertion": ""},  # 族类条目：不建证据不猜匹配
        {"no": 99, "cn_name": "不存在物质", "en_name": "X", "inci_name": "X",
         "scope": "", "max_conc": "1%", "other_limits": "", "label_warning": "", "note_refs": [],
         "match_inci": ["NO-SUCH-INCI-XYZ"], "legal_cap": 1.0,
         "assertion": "法定限用：最高 1.0%"},  # 候选不命中：不建证据
    ],
}


def _resolver():
    return InciResolver({"RESORCINOL": {"cn_name": "间苯二酚"},
                         "SALICYLIC ACID": {"cn_name": "水杨酸"}})


def _seed_ingredients(session):
    session.add_all([
        Ingredient(inci_name="RESORCINOL", cn_name="间苯二酚"),
        Ingredient(inci_name="SALICYLIC ACID", cn_name="水杨酸"),
    ])
    session.flush()


def test_efficacy_definitions_evidence_only(session):
    """功效族定义：每类 1 条 regulation 证据，不建任何断言；幂等。"""
    st = load_efficacy_definitions(session, EFF_SEED)
    assert st == {"evidence_new": 2, "evidence_existing": 0}
    evs = session.query(Evidence).filter_by(type=EvidenceType.REGULATION).all()
    assert len(evs) == 2
    assert session.query(EfficacyAssertion).count() == 0
    ev = next(e for e in evs if "祛斑美白" in e.title)
    assert ev.year == 2021
    assert "有助于减轻或减缓皮肤色素沉着" in ev.excerpt
    assert "人体功效评价试验为必做" in ev.excerpt
    st2 = load_efficacy_definitions(session, EFF_SEED)
    assert st2 == {"evidence_new": 0, "evidence_existing": 2}


def test_restricted_backfill_and_assertion(session):
    """表3：单上限条目回填 legal_cap + 法定限用断言（regulation 档）；多档条目只断不回填。"""
    _seed_ingredients(session)
    st = load_restricted(session, RES_SEED, resolver=_resolver())
    assert st["entries_matched"] == 2  # 族类与未命中候选不建证据
    assert st["evidence_new"] == 2
    assert st["assertions_new"] == 2
    assert st["legal_cap_set"] == 1
    assert st["unmatched_candidates"] == ["第99项 NO-SUCH-INCI-XYZ"]

    resorcinol = session.query(Ingredient).filter_by(inci_name="RESORCINOL").one()
    assert resorcinol.legal_cap == 0.5
    salicylic = session.query(Ingredient).filter_by(inci_name="SALICYLIC ACID").one()
    assert salicylic.legal_cap is None  # 多档分场景上限不回填

    a = session.query(EfficacyAssertion).filter_by(ingredient_id=resorcinol.id).one()
    assert a.efficacy.startswith("法定限用：")
    assert "法规限值，非功效起效浓度" in a.note
    assert a.evidence_level == "regulation"
    assert a.evidence_strength == 0.9
    assert a.efficacy_canonical == "其他"  # regulation 断言固定「其他」，不走子串规则
    ev = session.get(Evidence, a.evidence_id)
    assert ev.type == EvidenceType.REGULATION
    assert ev.year == 2015
    assert "最大允许浓度：0.5%" in ev.excerpt
    assert "间苯二酚" in ev.title


def test_restricted_legal_cap_conflict_not_overwritten(session):
    """legal_cap 已有值的行不覆盖，记冲突日志；幂等重跑不增生。"""
    session.add(Ingredient(inci_name="RESORCINOL", cn_name="间苯二酚", legal_cap=9.9))
    session.add(Ingredient(inci_name="SALICYLIC ACID", cn_name="水杨酸"))
    session.flush()
    st = load_restricted(session, RES_SEED, resolver=_resolver())
    assert st["legal_cap_set"] == 0
    assert st["legal_cap_conflict"] == 1
    ing = session.query(Ingredient).filter_by(inci_name="RESORCINOL").one()
    assert ing.legal_cap == 9.9  # 未覆盖

    st2 = load_restricted(session, RES_SEED, resolver=_resolver())
    assert st2["evidence_new"] == 0 and st2["assertions_new"] == 0
    assert st2["evidence_existing"] == 2 and st2["assertions_existing"] == 2
    assert session.query(Evidence).count() == 2
    assert session.query(EfficacyAssertion).count() == 2


def test_spec_title_uses_short_cn_name():
    entry = {"no": 19, "cn_name": "过氧化氢和其他释放过氧化氢的化合物或混合物，如过氧化脲和过氧化锌"}
    title = _spec_evidence_title(entry)
    assert "第19项" in title and "，如过氧化脲" not in title


def test_real_seed_assertion_texts_fit_column():
    """真 seed 所有 assertion 文本 ≤100 字（efficacy 列 String(100)，PostgreSQL 会硬校验）。"""
    seed = json.loads(Path("data/seed/restricted_ingredients.json").read_text(encoding="utf-8"))
    assert len(seed["entries"]) == 47
    for e in seed["entries"]:
        assert len(e["assertion"]) <= 100, f"第{e['no']}项 assertion 超长：{len(e['assertion'])}"


def test_regulation_canonical_forced_other(session):
    """断言文本含「非防腐用途」等字样时，canonical 仍固定「其他」（不被子串规则误归防腐族）。"""
    seed = {
        "source": {"official_url": "https://example.com/x.pdf"},
        "entries": [
            {"no": 4, "cn_name": "苯甲酸及其钠盐", "en_name": "Benzoic acid; Sodium benzoate",
             "inci_name": "Benzoic acid; Sodium benzoate", "scope": "淋洗类产品",
             "max_conc": "总量 2.5%（以酸计）", "other_limits": "", "label_warning": "",
             "note_refs": ["1"], "match_inci": ["BENZOIC ACID"], "legal_cap": None,
             "assertion": "法定限用：淋洗类产品总量最高 2.5%（以酸计，非防腐用途；《化妆品安全技术规范2015》表3）"},
        ],
    }
    resolver = InciResolver({"BENZOIC ACID": {"cn_name": "苯甲酸"}})
    session.add(Ingredient(inci_name="BENZOIC ACID", cn_name="苯甲酸"))
    session.flush()
    load_restricted(session, seed, resolver=resolver)
    a = session.query(EfficacyAssertion).one()
    assert "非防腐用途" in a.efficacy  # 子串规则会误判的前提成立
    assert a.efficacy_canonical == "其他"


def test_stale_assertion_migrated_in_place(session):
    """seed 文本/规则修订后重跑：陈旧断言按 (ingredient_id, evidence_id) 原地同步，不增生。"""
    _seed_ingredients(session)
    load_restricted(session, RES_SEED, resolver=_resolver())
    a = (session.query(EfficacyAssertion)
         .filter_by(efficacy=RES_SEED["entries"][0]["assertion"]).one())
    a.efficacy = "法定限用：旧版超长措辞……"
    a.efficacy_canonical = "防腐"  # 模拟子串规则误归的历史行
    session.flush()

    st = load_restricted(session, RES_SEED, resolver=_resolver())
    assert st["assertions_new"] == 0
    assert st["assertions_updated"] == 1
    assert st["assertions_existing"] == 1  # 另一条水杨酸断言未动
    assert session.query(EfficacyAssertion).count() == 2  # 无新旧并存
    a2 = session.get(EfficacyAssertion, a.id)
    assert a2.efficacy == RES_SEED["entries"][0]["assertion"]
    assert a2.efficacy_canonical == "其他"

    st2 = load_restricted(session, RES_SEED, resolver=_resolver())  # 再次重跑全同步
    assert st2["assertions_updated"] == 0
    assert st2["assertions_existing"] == 2
