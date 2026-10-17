"""展示模式的圆桌事实约束：模型选择工具事实，不把自由生成文本当成结论。"""
import json


def product_evidence_ingredient(session, product_id: int) -> str | None:
    """Select only a documented ingredient actually listed for this product."""
    from sqlalchemy import select
    from ..models.ingredient import EfficacyAssertion, Ingredient
    from ..models.product import ProductIngredient
    ingredient = session.query(Ingredient).join(ProductIngredient, ProductIngredient.ingredient_id == Ingredient.id).filter(
        ProductIngredient.product_id == product_id,
        Ingredient.id.in_(select(EfficacyAssertion.ingredient_id)),
    ).order_by(ProductIngredient.disclosed_conc.is_(None), ProductIngredient.position.is_(None),
               ProductIngredient.position, ProductIngredient.id).first()
    return (ingredient.cn_name or ingredient.inci_name) if ingredient else None


def select_facts(gateway, facts: list[str]) -> str:
    """Only validated integer IDs select server-rendered facts; prose is never used."""
    raw = gateway.chat([
        {"role": "system", "content": '从给定事实中选择最有解释价值的最多两项，只输出 JSON：{"fact_ids":[0,1]}。编号必须来自列表，不输出新事实。'},
        {"role": "user", "content": json.dumps(list(enumerate(facts)), ensure_ascii=False)},
    ], max_tokens=128, response_format={"type": "json_object"})
    try:
        selected = json.loads(raw).get("fact_ids", [])
        if not isinstance(selected, list):
            selected = []
        indices = list(dict.fromkeys(i for i in selected if type(i) is int and 0 <= i < len(facts)))[:2]
    except (ValueError, AttributeError, TypeError):
        indices = []
    return "\n".join(facts[i] for i in indices or range(min(2, len(facts))))


def role_facts(role: str, data: dict) -> list[str]:
    if role == "ingredient_expert":
        p = data["product_lookup"]["products"][0]
        return [
            f"产品库收录「{p['name']}」的 {p['ingredient_count']} 项成分；完整成分表可在上方展开。",
            "相似候选来自成分集合或嵌入检索，不能据此推导功效等同、配方相同或协同作用。",
        ]
    if role == "regulation_officer":
        claims = data.get("claims", [])
        if not claims:
            return ["本库未收录该产品的功效宣称依据摘要，无法核对具体宣称；这不代表产品没有备案或未进行评价。"]
        return [f"本库收录宣称「{c['claim']}」，评价类别记录为「{c.get('eval_category') or '未知'}」；摘要记录不能替代完整评价材料。" for c in claims]
    if role == "evidence_verifier":
        evidence = data["ingredient_evidence"]
        assertions = evidence.get("assertions", [])
        if not assertions:
            return ["本次未检索到关键成分的关联证据，无法据此支持或反驳成品功效。"]
        name = (evidence.get("ingredient") or {}).get("cn_name") or data["key_ingredient"]
        return [f"「{name}」的关联资料《{a['evidence']['title']}》记载：「{a['efficacy']}」。资料类型：{a['evidence']['type']}；层级：{a.get('evidence_level') or 'unknown'}。备注：{a.get('note') or '未记录'}。成分资料不能直接证明成品功效；分类、安全、法规和供应商资料不是临床功效实证。" for a in assertions]
    if not data.get("inferred"):
        return ["该产品没有可用的浓度估计结果，无法判断剂量，不补设位次、浓度或起效门槛。"]
    facts = []
    rows = sorted(data.get("estimates", []), key=lambda row: (
        row.get("disclosed_conc") is None,
        not any(d.get("eff_low") is not None or d.get("eff_high") is not None for d in row.get("dose", [])),
    ))
    for row in rows:
        name = row.get("cn_name") or row["inci_name"]
        if row.get("disclosed_conc") is not None:
            sentence = f"「{name}」记录有 {row['disclosed_conc']:g}% 披露锚点；披露口径需结合来源查看，不能用估计区间反证真实添加量。"
        else:
            sentence = f"「{name}」的浓度估计区间为 {row['low']:.2f}%–{row['high']:.2f}%，不是实测值。"
        unknown = sum(d.get("eff_low") is None and d.get("eff_high") is None for d in row.get("dose", []))
        if unknown:
            sentence += f"其 {unknown} 条关联记录缺少研究浓度，不能据此补设功效起效门槛。"
        facts.append(sentence)
    return facts or ["浓度资料不足，无法作出剂量判断。"]
