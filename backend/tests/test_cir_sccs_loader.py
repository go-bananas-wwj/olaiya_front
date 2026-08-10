"""cir_sccs_loader 测试：三部分入库规则、幂等、不覆盖、专利降级通道强制 unknown。"""

import json
from pathlib import Path

from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import EfficacyAssertion, Ingredient
from data.loaders.cir_sccs_loader import load_cir, load_patent, load_sccs

CIR_BATCH = {
    "ingredients": [
        {"cn_name": "曲酸", "inci_name": "KOJIC ACID", "cas_no": None,
         "cir_conc_low": 0.1, "cir_conc_high": 1.0,
         "assertions": [
             {"efficacy": "安全评估：现行使用方式和浓度下安全（CIR 评估；行业调查使用浓度 0.1%-1.0%）",
              "evidence": {"type": "white_paper",
                           "title": "Safety Assessment of Kojic Acid（IJT 1(Suppl. 1):1-1, 2020）",
                           "source": "Cosmetic Ingredient Review", "year": 2020,
                           "url": "https://cir-reports.cir-safety.org/view-attachment?id=abc",
                           "excerpt": "The Panel concluded that kojic acid is safe in cosmetics in the present practices of use and concentration."},
              "effective_conc_low": None, "effective_conc_high": None,
              "note": "CIR（美国化妆品原料评价委员会）专家小组安全评估结论，为行业自评机构意见而非监管限值；浓度来自 PCPC 行业使用调查，非功效起效浓度"}]},
        {"cn_name": "不存在成分", "inci_name": "NO-SUCH-CIR-XYZ", "cas_no": None,
         "cir_conc_low": 1.0, "cir_conc_high": 2.0, "assertions": []},
    ]
}

SCCS_SEED = {
    "entries": [
        {"inci_name": "KOJIC ACID", "opinion_no": "SCCS/1637/21", "title": "Kojic acid",
         "url": "https://health.ec.europa.eu/publications/kojic-acid_en",
         "adopted": "2022-06-13", "conclusion_kind": "safe", "sccs_limit": 1.0,
         "scope": "用作美白剂（skin lightening agent）最高 1%",
         "excerpt": "the SCCS is of the opinion that Kojic acid is safe when used as a skin lightening agent in cosmetic products at concentrations of up to 1%.",
         "note": "SCCS 安全评估上限（美白用途 1%），非功效起效浓度。",
         "assertion": "安全评估：SCCS 认为曲酸用作美白剂最高 1% 安全（SCCS/1637/21）"},
        {"inci_name": "NO-SUCH-SCCS-XYZ", "opinion_no": "SCCS/0000/00", "title": "X",
         "url": "https://health.ec.europa.eu/x_en", "adopted": "2020-01-01",
         "conclusion_kind": "safe", "sccs_limit": 1.0, "scope": "x",
         "excerpt": "x", "note": "x", "assertion": "安全评估：x"},
    ]
}

PATENT_BATCH = {
    "ingredients": [
        {"cn_name": "羟丙基四氢吡喃三醇（玻色因）", "inci_name": "HYDROXYPROPYL TETRAHYDROPYRANTRIOL",
         "cas_no": "439685-79-7",
         "assertions": [
             {"efficacy": "促糖胺聚糖（GAGs）合成（体外成纤维细胞，专利申请人自述）",
              "evidence": {"type": "patent",
                           "title": "WO2002051828A2 / EP1345919B1 Novel C-glycoside derivatives（L'Oréal）",
                           "source": "WIPO/EPO（L'Oréal 专利申请）", "year": 2002,
                           "url": "https://data.epo.org/publication-server/rest/v1.2/patents/EP1345919NWB1/document.pdf",
                           "excerpt": "la C-β-D-xylopyranoside-2-hydroxy-propane stimule l'incorporation de glucosamine radioactive"},
              "effective_conc_low": None, "effective_conc_high": None,
              "note": "专利申请人自述数据，未经同行评议；体外实验（成纤维细胞放射性葡萄糖胺掺入）"}]},
    ]
}


def _seed_ingredients(session):
    session.add_all([
        Ingredient(inci_name="KOJIC ACID", cn_name="曲酸"),
        Ingredient(inci_name="HYDROXYPROPYL TETRAHYDROPYRANTRIOL", cn_name="羟丙基四氢吡喃三醇（玻色因）"),
    ])
    session.flush()


def test_cir_backfill_and_assertion(session):
    """CIR：cir_conc 回填 + white_paper 证据 + 断言落 unknown 档、canonical 固定「其他」。"""
    _seed_ingredients(session)
    st = load_cir(session, CIR_BATCH)
    assert st["evidence_new"] == 1
    assert st["assertions_new"] == 1
    assert st["cir_conc_low_set"] == 1 and st["cir_conc_high_set"] == 1
    assert st["unmatched"] == ["NO-SUCH-CIR-XYZ"]

    ing = session.query(Ingredient).filter_by(inci_name="KOJIC ACID").one()
    assert ing.cir_conc_low == 0.1 and ing.cir_conc_high == 1.0
    a = session.query(EfficacyAssertion).filter_by(ingredient_id=ing.id).one()
    assert a.efficacy.startswith("安全评估：")
    assert a.evidence_level == "unknown"  # white_paper 无关键词信号 → unknown
    assert a.evidence_strength == 0.2
    assert a.efficacy_canonical == "其他"  # 安全评估固定「其他」，不被子串规则归族
    ev = session.get(Evidence, a.evidence_id)
    assert ev.type == EvidenceType.WHITE_PAPER
    assert ev.source == "Cosmetic Ingredient Review"


def test_cir_no_overwrite_and_idempotent(session):
    """cir_conc 已有值不覆盖、不同记冲突；幂等重跑不增生。"""
    session.add(Ingredient(inci_name="KOJIC ACID", cn_name="曲酸",
                           cir_conc_low=0.5, cir_conc_high=1.0))
    session.flush()
    st = load_cir(session, CIR_BATCH)
    assert st["cir_conc_low_set"] == 0
    assert st["cir_conc_low_conflict"] == 1  # 0.5 vs 0.1 冲突不覆盖
    assert st["cir_conc_high_set"] == 0      # 1.0 已存在且同值：不 set 也不算冲突
    assert st["cir_conc_high_conflict"] == 0
    ing = session.query(Ingredient).filter_by(inci_name="KOJIC ACID").one()
    assert ing.cir_conc_low == 0.5  # 未覆盖

    st2 = load_cir(session, CIR_BATCH)
    assert st2["evidence_new"] == 0 and st2["assertions_new"] == 0
    assert st2["evidence_existing"] == 1 and st2["assertions_existing"] == 1
    assert session.query(EfficacyAssertion).count() == 1


def test_sccs_backfill_and_assertion(session):
    """SCCS：sccs_limit 回填 + regulation 证据 + 断言落 regulation 档、canonical 固定「其他」。"""
    _seed_ingredients(session)
    st = load_sccs(session, SCCS_SEED)
    assert st["evidence_new"] == 1
    assert st["assertions_new"] == 1
    assert st["sccs_limit_set"] == 1
    assert st["unmatched"] == ["NO-SUCH-SCCS-XYZ"]

    ing = session.query(Ingredient).filter_by(inci_name="KOJIC ACID").one()
    assert ing.sccs_limit == 1.0
    a = session.query(EfficacyAssertion).filter_by(ingredient_id=ing.id).one()
    assert a.evidence_level == "regulation"
    assert a.evidence_strength == 0.9
    assert a.efficacy_canonical == "其他"  # 断言含「美白剂」字样仍固定「其他」
    ev = session.get(Evidence, a.evidence_id)
    assert ev.type == EvidenceType.REGULATION
    assert "SCCS/1637/21" in ev.title
    assert ev.year == 2022


def test_sccs_legal_cap_coexist_and_idempotent(session):
    """sccs_limit 与 legal_cap 并存不互相覆盖（两列语义不同），不一致记日志；幂等。"""
    session.add(Ingredient(inci_name="KOJIC ACID", cn_name="曲酸", legal_cap=2.0))
    session.flush()
    st = load_sccs(session, SCCS_SEED)
    ing = session.query(Ingredient).filter_by(inci_name="KOJIC ACID").one()
    assert ing.legal_cap == 2.0 and ing.sccs_limit == 1.0  # 并存
    assert any("口径差异" in line for line in st["log"])

    st2 = load_sccs(session, SCCS_SEED)
    assert st2["evidence_new"] == 0 and st2["assertions_new"] == 0
    assert st2["sccs_limit_set"] == 0 and st2["sccs_limit_conflict"] == 0  # 同值不算冲突
    assert session.query(EfficacyAssertion).count() == 1


def test_patent_forced_unknown(session):
    """专利降级通道：note 含「体外」也不走 classify 升级，层级强制 unknown/0.2。"""
    _seed_ingredients(session)
    st = load_patent(session, PATENT_BATCH)
    assert st["evidence_new"] == 1 and st["assertions_new"] == 1
    ing = session.query(Ingredient).filter_by(
        inci_name="HYDROXYPROPYL TETRAHYDROPYRANTRIOL").one()
    a = session.query(EfficacyAssertion).filter_by(ingredient_id=ing.id).one()
    assert "体外" in a.note  # classify 会判 in_vitro 的前提成立
    assert a.evidence_level == "unknown"  # 降级通道强制最低档
    assert a.evidence_strength == 0.2
    assert "未经同行评议" in a.note
    ev = session.get(Evidence, a.evidence_id)
    assert ev.type == EvidenceType.PATENT

    st2 = load_patent(session, PATENT_BATCH)
    assert st2["evidence_existing"] == 1 and st2["assertions_existing"] == 1
    assert session.query(EfficacyAssertion).count() == 1


def test_stale_assertion_synced(session):
    """seed/batch 措辞修订后重跑：陈旧断言按 (ingredient_id, evidence_id) 原地同步。"""
    _seed_ingredients(session)
    load_sccs(session, SCCS_SEED)
    a = session.query(EfficacyAssertion).one()
    a.efficacy = "安全评估：旧版措辞"
    a.efficacy_canonical = "美白"  # 模拟被误归的历史行
    session.flush()
    st = load_sccs(session, SCCS_SEED)
    assert st["assertions_new"] == 0 and st["assertions_updated"] == 1
    a2 = session.get(EfficacyAssertion, a.id)
    assert a2.efficacy == SCCS_SEED["entries"][0]["assertion"]
    assert a2.efficacy_canonical == "其他"
    assert session.query(EfficacyAssertion).count() == 1


def test_shared_evidence_across_ingredients(session):
    """同一报告覆盖多成分（如熊果苷对）：证据共享一条，断言各自挂。"""
    session.add_all([
        Ingredient(inci_name="ALPHA-ARBUTIN", cn_name="α-熊果苷"),
        Ingredient(inci_name="ARBUTIN", cn_name="熊果苷"),
    ])
    session.flush()
    seed = {"entries": [
        dict(SCCS_SEED["entries"][0], inci_name="ALPHA-ARBUTIN", sccs_limit=2.0,
             opinion_no="SCCS/1642/22", title="Safety of alpha-arbutin and beta-arbutin",
             assertion="安全评估：SCCS 认为 α-熊果苷用于面霜最高 2% 安全（SCCS/1642/22）"),
        dict(SCCS_SEED["entries"][0], inci_name="ARBUTIN", sccs_limit=7.0,
             opinion_no="SCCS/1642/22", title="Safety of alpha-arbutin and beta-arbutin",
             assertion="安全评估：SCCS 认为 β-熊果苷用于面霜最高 7% 安全（SCCS/1642/22）"),
    ]}
    st = load_sccs(session, seed)
    assert st["evidence_new"] == 1  # 同 title 共享
    assert st["assertions_new"] == 2
    assert session.query(EfficacyAssertion).count() == 2
    ev_ids = {a.evidence_id for a in session.query(EfficacyAssertion).all()}
    assert len(ev_ids) == 1


def test_allow_correction_overwrites(session):
    """核订修正模式：allow_correction=True 时旧值被核订值覆盖并记日志；默认 False 不覆盖。"""
    session.add(Ingredient(inci_name="KOJIC ACID", cn_name="曲酸",
                           cir_conc_low=4.0, cir_conc_high=79.2, sccs_limit=2.0))
    session.flush()
    st = load_cir(session, CIR_BATCH, allow_correction=True)
    assert st["cir_conc_low_corrected"] == 1 and st["cir_conc_low_conflict"] == 0
    assert st["cir_conc_high_corrected"] == 1
    assert any("核订修正" in line and "4.0" in line for line in st["log"])
    ing = session.query(Ingredient).filter_by(inci_name="KOJIC ACID").one()
    assert ing.cir_conc_low == 0.1 and ing.cir_conc_high == 1.0  # 已覆盖为核订值

    st2 = load_sccs(session, SCCS_SEED, allow_correction=True)
    assert st2["sccs_limit_corrected"] == 1
    assert ing.sccs_limit == 1.0

    # 修正后重跑幂等：同值不再修正、不算冲突
    st3 = load_cir(session, CIR_BATCH, allow_correction=True)
    assert st3["cir_conc_low_corrected"] == 0 and st3["cir_conc_low_conflict"] == 0


def test_allow_correction_clears_on_explicit_null(session):
    """核订数据显式 null（经核对无报告浓度）：allow_correction=True 清掉旧值；
    默认 False 不动；清完重跑幂等。"""
    session.add(Ingredient(inci_name="KOJIC ACID", cn_name="曲酸",
                           cir_conc_low=3.0, cir_conc_high=39.9))
    session.flush()
    raw = {"ingredients": [
        {"cn_name": "曲酸", "inci_name": "KOJIC ACID",
         "cir_conc_low": None, "cir_conc_high": 39.9, "assertions": []},
    ]}
    # 默认模式：显式 null 不清旧值
    st0 = load_cir(session, {"ingredients": []}, conc_batch=raw)
    ing = session.query(Ingredient).filter_by(inci_name="KOJIC ACID").one()
    assert ing.cir_conc_low == 3.0 and st0["cir_conc_low_corrected"] == 0
    # 核订模式：清掉旧值并记日志
    st = load_cir(session, {"ingredients": []}, conc_batch=raw, allow_correction=True)
    assert ing.cir_conc_low is None and ing.cir_conc_high == 39.9
    assert st["cir_conc_low_corrected"] == 1
    assert any("核订修正" in line and "新值 None" in line for line in st["log"])
    # 清完重跑幂等
    st2 = load_cir(session, {"ingredients": []}, conc_batch=raw, allow_correction=True)
    assert st2["cir_conc_low_corrected"] == 0 and st2["cir_conc_low_conflict"] == 0


def test_cir_conc_from_raw_batch(session):
    """浓度回填走完整件（conc_batch）：verify 通过件丢弃的无断言成分也能回填。"""
    _seed_ingredients(session)
    verified = {"ingredients": []}  # verify 输出只留有断言成分
    raw = {"ingredients": [
        {"cn_name": "曲酸", "inci_name": "KOJIC ACID",
         "cir_conc_low": None, "cir_conc_high": 1.0, "assertions": []},
    ]}
    st = load_cir(session, verified, conc_batch=raw)
    ing = session.query(Ingredient).filter_by(inci_name="KOJIC ACID").one()
    assert ing.cir_conc_high == 1.0
    assert st["cir_conc_high_set"] == 1
    assert session.query(EfficacyAssertion).count() == 0


def test_real_files_assertion_texts_fit_column():
    """真数据所有断言 efficacy ≤100 字（efficacy 列 String(100)）。"""
    for path, key in (("data/research/batch-9-cir.verified.json", "assertions"),
                      ("data/research/batch-9-patent.verified.json", "assertions")):
        batch = json.loads(Path(path).read_text(encoding="utf-8"))
        for item in batch["ingredients"]:
            for a in item[key]:
                assert len(a["efficacy"]) <= 100, f"{item['inci_name']} 断言超长：{a['efficacy']}"
    seed = json.loads(Path("data/seed/sccs_opinions.json").read_text(encoding="utf-8"))
    for e in seed["entries"]:
        assert len(e["assertion"]) <= 100, f"{e['inci_name']} assertion 超长：{len(e['assertion'])}"
