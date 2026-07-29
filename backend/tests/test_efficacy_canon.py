"""efficacy 规范名映射与回填：自由文本功效归一到有限功效族（总纲 I3 数据底座）。

canonicalize 规则化映射（关键词子串命中，按序返回；控油祛痘须在舒缓之前，
因祛痘类断言常带「抗炎」字样）；均不命中落「其他」，不猜测细分类目。
backfill_session 全量重算并覆盖，天然幂等。
"""

import pytest

from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.services.efficacy_canon import canonicalize
from data.tools.backfill_efficacy_canonical import backfill_session


@pytest.mark.parametrize(
    "raw,expected",
    [
        # 美白族：美白/提亮/淡斑/黑素/酪氨酸酶
        ("美白", "美白"),
        ("美白（抑制黑素小体转运）", "美白"),
        ("抗氧化/美白提亮", "美白"),
        ("美白淡斑（黄褐斑）", "美白"),
        ("抑制黑素合成（减少人皮肤细胞黑素生成与酪氨酸酶活性）", "美白"),
        ("淡化黄褐斑（疗效接近2%氢醌且副作用更少）", "美白"),
        ("黄褐斑维持期改善（复方制剂，组间差异未达统计学显著）", "美白"),
        # 控油祛痘族：控油/祛痘/痤疮/粉刺/痘；须在舒缓前命中（祛痘类常带「抗炎」字样）
        ("控油祛痘", "控油祛痘"),
        ("祛痘（抗菌抗炎）", "控油祛痘"),
        ("祛痘（杀灭痤疮丙酸杆菌、抗炎）", "控油祛痘"),
        ("祛痘（化学剥脱治疗痤疮）", "控油祛痘"),  # 含「剥脱」但仍属痤疮功效
        ("改善痤疮（减少炎性/非炎性皮损、控油、改善炎症后色沉）", "控油祛痘"),
        ("祛痘（维A类调节角化、减少粉刺）", "控油祛痘"),
        # 抗皱族：抗皱/抗老/细纹/皱纹/胶原/紧致/光老化
        ("抗皱", "抗皱"),
        ("抗皱（改善光老化面部细纹与皱纹）", "抗皱"),
        ("抗老/保湿（临床提升皮肤透明质酸含量与I型胶原表达）", "抗皱"),
        ("促胶原合成", "抗皱"),
        ("抗皱紧致（促进真皮弹性纤维形成）", "抗皱"),
        ("抗光老化（改善皱纹与皮肤弹性）", "抗皱"),
        # 抗氧化族：抗氧化/光防护/自由基/抗氧
        ("抗氧化", "抗氧化"),
        ("光防护（减少UV诱导的DNA损伤与细胞凋亡）", "抗氧化"),
        ("抗氧化（淬灭单线态氧、保护皮脂免于过氧化）", "抗氧化"),
        # 保湿族：保湿/水合/锁水
        ("保湿", "保湿"),
        ("保湿（提升角质层含水量）", "保湿"),
        ("保湿（改善皮肤水合、降低经皮水分流失）", "保湿"),
        # 修护族：修护/屏障/修复
        ("修护", "修护"),
        ("屏障修护（改善特应性皮炎屏障功能）", "修护"),
        ("皮肤修复（改善妊娠纹萎缩外观）", "修护"),
        # 舒缓族：舒缓/抗敏/镇静/抗炎/消炎/泛红
        ("舒缓", "舒缓"),
        ("舒缓抗炎（止痒）", "舒缓"),
        ("抗炎（抑制巨噬细胞炎症通路）", "舒缓"),
        ("改善毛孔、粗糙与泛红（减小日间波动）", "舒缓"),
        # 焕肤族：焕肤/去角质/剥脱/换肤
        ("焕肤", "焕肤"),
        # 防腐族：防腐
        ("防腐（准用防腐剂）", "防腐"),
        ("防腐增效（与苯乙醇/甘油辛酸酯协同，广谱抗菌并通过防腐挑战测试）", "防腐"),
        # 均不命中 → 其他
        ("抗糖化（抑制皮肤晚期糖基化终末产物AGEs生成）", "其他"),
        ("抗细胞衰老（促进巨噬细胞清除衰老皮肤细胞）", "其他"),
        ("角质层渗透（低分子HA可穿透角质层，高分子HA不能）", "其他"),
        ("", "其他"),
    ],
)
def test_canonicalize_rules(raw, expected):
    assert canonicalize(raw) == expected


def _mk_assertion(session, efficacy, canonical=None):
    ev = Evidence(type=EvidenceType.PAPER, title=f"证据-{efficacy}", source="期刊", year=2020)
    ing = Ingredient(inci_name=f"INCI-{efficacy}", cn_name=f"成分-{efficacy}")
    session.add_all([ev, ing])
    session.flush()
    a = EfficacyAssertion(ingredient_id=ing.id, efficacy=efficacy, evidence_id=ev.id,
                          efficacy_canonical=canonical)
    session.add(a)
    session.commit()
    return a


def test_backfill_fills_and_overwrites(session):
    """全量重算：NULL 填充、陈旧错误值纠正；返回分布计数。"""
    _mk_assertion(session, "美白（抑制黑素小体转运）")
    _mk_assertion(session, "防腐（准用防腐剂）", canonical="美白")  # 陈旧错误值须被纠正
    dist = backfill_session(session)
    session.commit()
    rows = session.query(EfficacyAssertion).order_by(EfficacyAssertion.id).all()
    assert [r.efficacy_canonical for r in rows] == ["美白", "防腐"]
    assert dist == {"美白": 1, "防腐": 1}


def test_backfill_idempotent(session):
    """重跑不产生不同结果。"""
    _mk_assertion(session, "美白（抑制黑素小体转运）")
    _mk_assertion(session, "祛痘（抗菌抗炎）")
    backfill_session(session)
    session.commit()
    snapshot = [r.efficacy_canonical for r in
                session.query(EfficacyAssertion).order_by(EfficacyAssertion.id)]
    dist2 = backfill_session(session)
    session.commit()
    after = [r.efficacy_canonical for r in
             session.query(EfficacyAssertion).order_by(EfficacyAssertion.id)]
    assert after == snapshot
    assert sum(dist2.values()) == 2
