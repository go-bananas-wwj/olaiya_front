"""成分证据库加载器：把研究产出的证据 JSON（已过核验闸门）导入数据库。

与 seed_loader 的差异：
- 输入为「成分 + 嵌套证据的断言」结构（data/tools/verify_evidence.py 的输出格式）；
- 成分按 inci_name（英文大写）建/取；同时处理**中文名 stub 合并**：
  采集产品里的成分是中文名 stub（inci_name==cn_name==中文名），
  当正式成分（inci_name=英文、cn_name=同一中文名）入库时，
  把 stub 的产品关联全部改指正式成分并删除 stub，保证中文/英文不双头。
- 全部操作幂等。

CLI：PYTHONPATH=backend .venv/bin/python -m data.loaders.evidence_loader 文件1.json [文件2.json ...]
"""

import json
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.models.product import ProductIngredient

PRIOR_FIELDS = ("iecic_max_leave_on", "iecic_max_rinse_off", "legal_cap",
                "cir_conc_low", "cir_conc_high", "sccs_limit")


def _merge_cn_stub(session: Session, canonical: Ingredient) -> int:
    """把与 canonical 中文名相同的中文 stub 合并过来，返回合并的关联数。"""
    if canonical.inci_name == canonical.cn_name:
        return 0  # 自身就是中文条目（无英文 INCI），无需合并
    stub = (session.query(Ingredient)
            .filter(Ingredient.inci_name == canonical.cn_name,
                    Ingredient.id != canonical.id)
            .one_or_none())
    if stub is None:
        return 0
    moved = 0
    for link in session.query(ProductIngredient).filter_by(ingredient_id=stub.id).all():
        # 防重：目标成分已在同一产品下有关联则删 stub 侧
        dup = (session.query(ProductIngredient)
               .filter_by(product_id=link.product_id, ingredient_id=canonical.id)
               .one_or_none())
        if dup is None:
            link.ingredient_id = canonical.id
            moved += 1
        else:
            session.delete(link)
    session.delete(stub)
    session.flush()
    return moved


def load_research(session: Session, data: dict) -> dict:
    """导入一份证据 JSON，返回统计。"""
    stats = {"ingredients": 0, "evidence": 0, "assertions": 0, "merged_links": 0}
    for item in data.get("ingredients", []):
        inci = item["inci_name"].strip()
        cn = item["cn_name"].strip()
        ing = session.query(Ingredient).filter_by(inci_name=inci).one_or_none()
        if ing is None:
            ing = Ingredient(inci_name=inci, cn_name=cn)
            session.add(ing)
            session.flush()
            stats["ingredients"] += 1
        else:
            ing.cn_name = cn  # 以正式中文名为准
        if item.get("cas_no"):
            ing.cas_no = item["cas_no"]
        for f in PRIOR_FIELDS:
            if item.get(f) is not None:
                setattr(ing, f, item[f])
        stats["merged_links"] += _merge_cn_stub(session, ing)

        for a in item.get("assertions", []):
            ev_data = a["evidence"]
            ev = session.query(Evidence).filter_by(title=ev_data["title"]).one_or_none()
            if ev is None:
                ev = Evidence(type=EvidenceType(ev_data["type"]),
                              title=ev_data["title"], source=ev_data["source"],
                              year=ev_data.get("year"), url=ev_data.get("url"),
                              excerpt=ev_data.get("excerpt"))
                session.add(ev)
                session.flush()
                stats["evidence"] += 1
            exists = (session.query(EfficacyAssertion)
                      .filter_by(ingredient_id=ing.id, efficacy=a["efficacy"], evidence_id=ev.id)
                      .one_or_none())
            if exists is None:
                session.add(EfficacyAssertion(
                    ingredient_id=ing.id, efficacy=a["efficacy"], evidence_id=ev.id,
                    effective_conc_low=a.get("effective_conc_low"),
                    effective_conc_high=a.get("effective_conc_high"),
                    note=a.get("note")))
                stats["assertions"] += 1
    return stats


def sweep_all(session: Session) -> int:
    """终扫：把库里所有正式成分（inci_name != cn_name）的中文 stub 合并一遍。

    幂等，可在任意加载完成后重复执行；返回合并的关联总数。
    """
    moved = 0
    canonicals = session.query(Ingredient).filter(Ingredient.inci_name != Ingredient.cn_name).all()
    for ing in canonicals:
        moved += _merge_cn_stub(session, ing)
    return moved


def main() -> None:
    init_db()
    if sys.argv[1:] and sys.argv[1] == "--sweep":
        with SessionLocal() as s:
            moved = sweep_all(s)
            s.commit()
        print(f"终扫完成：合并 {moved} 条产品-成分关联")
        return
    total = {"ingredients": 0, "evidence": 0, "assertions": 0, "merged_links": 0}
    with SessionLocal() as s:
        for path in sys.argv[1:]:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            stats = load_research(s, data)
            for k in total:
                total[k] += stats[k]
            print(f"{path}: {stats}")
        s.commit()
    print(f"合计: {total}")


if __name__ == "__main__":
    main()
