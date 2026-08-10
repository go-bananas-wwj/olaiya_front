"""CosIng 功能分类断言加载器：把 data/seed/cosing_functions.json 的功能分类批量入库。

数据源：欧盟委员会 CosIng 官方词表导出（seed 文件 source 字段记录来源链与抽查核对）。

映射规则（FUNCTION_MAP，保守原则：只映射语义明确的皮肤功效码）：
- MOISTURISING / HUMECTANT / OCCLUSIVE / SKIN CONDITIONING - HUMECTANT / - OCCLUSIVE → 保湿
- ANTIOXIDANT → 抗氧化；SOOTHING → 舒缓；EXFOLIATING / KERATOLYTIC → 焕肤
- ANTI-SEBUM / ANTI-SEBORRHEIC → 控油；PRESERVATIVE → 防腐
- 其余功能码（配方/工艺功能、语义含糊、无对应功效族）一律跳过，见 SKIP_REASONS；
  ambiguous 码（MASKING、VISCOSITY CONTROLLING、SKIN CONDITIONING 等）绝不猜测映射。

措辞铁律：申报功能 ≠ 功效实证。
- efficacy 一律「功能分类：XX（CosIng 官方申报功能）」，不含「证明/实证/临床」等越界词；
- evidence_level 走 evidence_level.py 统一规则：database 类型无任何人体/实验信号 → unknown；
- note 固定注明「CosIng 功能字段为官方申报功能分类，非功效实证」并附原功能码；
- efficacy_canonical 走 efficacy_canon.py 现有规则（canonicalize）。

幂等：evidence 按 title 去重、断言按 (ingredient_id, efficacy, evidence_id) 去重，
与 evidence_loader 同款幂等键；重复执行不增生。

运行：PYTHONPATH="backend:." .venv/bin/python data/loaders/cosing_loader.py [--seed 路径] [--dry-run]
"""

import argparse
import json
import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.models.product import ProductIngredient
from app.services.efficacy_canon import canonicalize
from app.services.evidence_level import classify_evidence_level, default_strength

DEFAULT_SEED = Path(__file__).resolve().parents[1] / "seed" / "cosing_functions.json"

EVIDENCE_SOURCE = "European Commission CosIng"
COSING_URL = "https://ec.europa.eu/growth/tools-databases/cosing/"
NOTE_DISCLAIMER = "CosIng 功能字段为官方申报功能分类，非功效实证"

# 功能码 → 功效中文名（保守子集； efficacy 文本走 efficacy_canon 归族）
FUNCTION_MAP: dict[str, str] = {
    "MOISTURISING": "保湿",                    # 增加皮肤含水量并保持柔软光滑
    "HUMECTANT": "保湿",                       # 吸湿保水
    "OCCLUSIVE": "保湿",                       # 减缓皮肤表面水分蒸发（封闭锁水）
    "SKIN CONDITIONING - HUMECTANT": "保湿",   # 增加角质层含水量
    "SKIN CONDITIONING - OCCLUSIVE": "保湿",   # 延缓皮肤表面水分蒸发
    "ANTIOXIDANT": "抗氧化",                   # 抑制氧化反应
    "SOOTHING": "舒缓",                        # 减轻皮肤/头皮不适
    "EXFOLIATING": "焕肤",                     # 加速去除死皮细胞层
    "KERATOLYTIC": "焕肤",                     # 帮助去除角质层死细胞
    "ANTI-SEBUM": "控油",                      # 帮助控制皮脂分泌
    "ANTI-SEBORRHEIC": "控油",                 # 预防/缓解皮脂溢症状
    "PRESERVATIVE": "防腐",                    # 抑制化妆品中微生物滋生
}

# 跳过清单：功能码 → 跳过原因（全部如实列出，不静默丢弃）
SKIP_REASONS: dict[str, str] = {
    # —— 配方/工艺功能（对产品性状而非皮肤功效） ——
    "ABRASIVE": "配方功能（磨擦剂）",
    "ABSORBENT": "配方功能（吸收剂）",
    "ADHESIVE": "配方功能（粘合剂）",
    "ANTICAKING": "配方功能（抗结块）",
    "ANTICORROSIVE": "配方功能（防包装腐蚀）",
    "ANTIFOAMING": "配方功能（消泡）",
    "BINDING": "配方功能（粘合）",
    "BUFFERING": "配方功能（缓冲）",
    "BULKING": "配方功能（填充）",
    "CHELATING": "配方功能（螯合）",
    "DENATURANT": "配方功能（变性剂）",
    "DISPERSING NON-SURFACTANT": "配方功能（分散）",
    "EMULSION STABILISING": "配方功能（乳液稳定）",
    "FILM FORMING": "配方功能（成膜，语义含糊，可能为物理遮盖）",
    "FOAMING": "配方功能（发泡）",
    "GEL FORMING": "配方功能（成胶）",
    "LIGHT STABILIZER": "配方功能（保护产品避光变质）",
    "LYTIC": "配方功能（裂解）",
    "OPACIFYING": "配方功能（遮光）",
    "OXIDISING": "配方功能（氧化剂，染发工艺）",
    "PEARLESCENT": "配方功能（珠光外观）",
    "PH ADJUSTERS": "配方功能（调 pH；词表原文 pH ADJUSTERS，键统一大写）",
    "PLASTICISER": "配方功能（增塑）",
    "PROPELLANT": "配方功能（推进剂）",
    "REDUCING": "配方功能（还原剂，染发/烫发工艺）",
    "SLIP MODIFIER": "配方功能（助流）",
    "SOLVENT": "配方功能（溶剂）",
    "SURFACE MODIFIER": "配方功能（表面改性）",
    "SURFACTANT": "配方功能（表面活性剂，泛类）",
    "SURFACTANT - DISPERSING": "配方功能（分散）",
    "SURFACTANT - EMULSIFYING": "配方功能（乳化）",
    "SURFACTANT - FOAM BOOSTING": "配方功能（增泡）",
    "SURFACTANT - HYDROTROPE": "配方功能（助溶）",
    "SURFACTANT - SOLUBILIZING": "配方功能（增溶）",
    "VISCOSITY CONTROLLING": "配方功能（增稠/降粘，语义含糊不映射）",
    # —— 语义含糊/多义，禁止猜测 ——
    "ANTIMICROBIAL": "语义含糊（防腐与抗菌功效两可，不映射）",
    "ASTRINGENT": "语义含糊（收敛，无对应功效族规则关键词）",
    "BLEACHING": "语义含糊（漂发与皮肤美白两可，不映射）",
    "MASKING": "语义含糊（掩味，非皮肤功效）",
    "REFATTING": "语义含糊（头发与皮肤两可，不映射）",
    "SKIN CONDITIONING": "语义含糊（泛皮肤调理，不拔高为具体功效）",
    "SKIN CONDITIONING - EMOLLIENT": "语义含糊（润肤≠保湿功效实证，不映射）",
    "SKIN CONDITIONING - MISCELLANEOUS": "语义含糊（杂项调理，不映射）",
    "SKIN PROTECTING": "语义含糊（泛防护，不拔高为修护功效）",
    "SMOOTHING": "语义含糊（物理抚平，不映射）",
    "REFRESHING": "语义含糊（清凉感，非功效族）",
    "TONIC": "语义含糊（爽肤感，非功效族）",
    # —— 无对应功效族（规范族表无此族，入库只会碎裂进「其他」） ——
    "ANTIPERSPIRANT": "无对应功效族（止汗）",
    "ANTIPLAQUE": "无对应功效族（口腔）",
    "CLEANSING": "无对应功效族（清洁）",
    "COLORANT": "无对应功效族（着色剂）",
    "DEODORANT": "无对应功效族（除臭）",
    "DEPILATORY": "无对应功效族（脱毛）",
    "EPILATING": "无对应功效族（拔毛）",
    "EYELASH CONDITIONING": "无对应功效族（睫毛）",
    "FLAVOURING": "无对应功效族（调味）",
    "FRAGRANCE": "无对应功效族（香料）",
    "HAIR CONDITIONING": "无对应功效族（护发）",
    "HAIR DYEING": "无对应功效族（染发）",
    "HAIR FIXING": "无对应功效族（定型）",
    "HAIR WAVING OR STRAIGHTENING": "无对应功效族（烫/直发）",
    "NAIL CONDITIONING": "无对应功效族（护甲）",
    "NAIL SCULPTING": "无对应功效族（美甲造型）",
    "NOT REPORTED": "无申报功能",
    "ORAL CARE": "无对应功效族（口腔）",
    "PERFUMING": "无对应功效族（加香）",
    "SURFACTANT - CLEANSING": "无对应功效族（清洁）",
    "TANNING": "无对应功效族（美黑）",
    "UV ABSORBER": "无对应功效族（防晒；且保护对象为产品本身）",
    "UV FILTER": "无对应功效族（防晒）",
    "ANTISTATIC": "无对应功效族（抗静电）",
    "DETANGLING": "无对应功效族（护发）",
}

_WS = re.compile(r"\s+")


def normalize_inci(name: str) -> str:
    """匹配用归一化：压空白 + 大写（CosIng 词表键为全大写 INCI）。"""
    return _WS.sub(" ", name.strip()).upper()


def efficacy_text(cn_efficacy: str) -> str:
    """断言措辞：申报功能分类，固定格式，绝不含功效实证措辞。"""
    return f"功能分类：{cn_efficacy}（CosIng 官方申报功能）"


def evidence_title(source_meta: dict) -> str:
    """证据标题内嵌导出日期与条目数：词表未来更新重新采集时会生成新 evidence，
    旧断言仍以旧 evidence_id 并存（幂等键惯例与 evidence_loader 一致）。
    若要做词表更新，需先清理旧 CosIng 断言或改 update-in-place，注意这点。"""
    return (f"CosIng 化妆品成分功能分类词表"
            f"（官方导出 {source_meta.get('collected_at', '?')}，"
            f"{source_meta.get('entries_in_seed', '?')} 条目）")


def _get_or_create_evidence(session: Session, seed: dict, stats: dict) -> Evidence:
    title = evidence_title(seed["source"])
    ev = session.query(Evidence).filter_by(title=title).one_or_none()
    if ev is None:
        ev = Evidence(
            type=EvidenceType.DATABASE, title=title, source=EVIDENCE_SOURCE,
            year=None, url=COSING_URL,
            excerpt=("CosIng INCI 词表的功能字段为欧盟化妆品法规框架下的官方申报功能分类"
                     "（declared cosmetic functions），用于标识成分在产品中的用途类别，"
                     "不构成功效的临床/实验实证。"))
        session.add(ev)
        session.flush()
        stats["evidence_new"] += 1
    return ev


def load_cosing(session: Session, seed: dict, stats: dict | None = None) -> dict:
    """按 seed 词表对库内成分批量生成功能分类断言。幂等，返回统计。"""
    if stats is None:
        stats = {}
    for k in ("ingredients_matched", "ingredients_unmatched", "assertions_new",
              "assertions_existing", "evidence_new", "functions_skipped",
              "functions_unknown_code"):
        stats.setdefault(k, 0)
    stats.setdefault("skipped_codes", {})

    cos_map: dict = seed["map"]
    evidence = _get_or_create_evidence(session, seed, stats)

    for ing in session.query(Ingredient).all():
        functions = cos_map.get(normalize_inci(ing.inci_name))
        if not functions:
            stats["ingredients_unmatched"] += 1
            continue
        stats["ingredients_matched"] += 1
        seen: set[str] = set()  # 同成分同功效去重（多码同族）
        for code in functions:
            cn = FUNCTION_MAP.get(code)
            if cn is None:
                if code in SKIP_REASONS:
                    stats["functions_skipped"] += 1
                    stats["skipped_codes"][code] = stats["skipped_codes"].get(code, 0) + 1
                else:
                    # 未知码：绝不猜测映射，如实计数告警
                    stats["functions_unknown_code"] += 1
                    stats["skipped_codes"][f"?{code}"] = \
                        stats["skipped_codes"].get(f"?{code}", 0) + 1
                continue
            if cn in seen:
                continue
            seen.add(cn)
            efficacy = efficacy_text(cn)
            exists = (session.query(EfficacyAssertion)
                      .filter_by(ingredient_id=ing.id, efficacy=efficacy,
                                 evidence_id=evidence.id)
                      .one_or_none())
            if exists is not None:
                stats["assertions_existing"] += 1
                continue
            note = f"{NOTE_DISCLAIMER}（{code}）"
            level = classify_evidence_level(note, evidence)
            session.add(EfficacyAssertion(
                ingredient_id=ing.id, efficacy=efficacy, evidence_id=evidence.id,
                note=note,
                evidence_level=level, evidence_strength=default_strength(level),
                efficacy_canonical=canonicalize(efficacy)))
            stats["assertions_new"] += 1
    session.flush()
    return stats


def coverage_report(session: Session) -> dict:
    """加权覆盖率：按产品-成分关联计，关联成分有 CosIng 断言的链接占比。"""
    links = session.query(ProductIngredient).all()
    with_cosing = 0
    for link in links:
        hit = (session.query(EfficacyAssertion)
               .filter_by(ingredient_id=link.ingredient_id)
               .filter(EfficacyAssertion.efficacy.like("功能分类：%（CosIng 官方申报功能）"))
               .count())
        if hit:
            with_cosing += 1
    total = len(links)
    return {"product_links_total": total, "links_with_cosing_assertion": with_cosing,
            "weighted_coverage": round(with_cosing / total, 4) if total else 0.0}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default=str(DEFAULT_SEED))
    ap.add_argument("--dry-run", action="store_true", help="只统计不落库（事务回滚）")
    args = ap.parse_args()

    init_db()
    seed = json.loads(Path(args.seed).read_text(encoding="utf-8"))
    with SessionLocal() as s:
        stats = load_cosing(s, seed)
        cov = coverage_report(s)
        if args.dry_run:
            s.rollback()
            print("DRY-RUN：已回滚，未落库")
        else:
            s.commit()
    print(f"命中成分={stats['ingredients_matched']} 未命中={stats['ingredients_unmatched']} "
          f"新增断言={stats['assertions_new']} 已存在跳过={stats['assertions_existing']} "
          f"新增证据={stats['evidence_new']} 功能码跳过={stats['functions_skipped']} "
          f"未知功能码={stats['functions_unknown_code']}")
    print(f"加权覆盖率（按产品关联）: {cov['links_with_cosing_assertion']}/{cov['product_links_total']}"
          f" = {cov['weighted_coverage']:.1%}")
    top = sorted(stats["skipped_codes"].items(), key=lambda kv: -kv[1])[:15]
    print("跳过功能码 TOP15: " + (", ".join(f"{k}×{v}" for k, v in top) or "无"))


if __name__ == "__main__":
    main()
