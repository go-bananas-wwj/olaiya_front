"""一次性回填：efficacy_assertions.evidence_level / evidence_strength。

分类规则见 app.services.evidence_level（与加载器共用）。分类是纯函数，
每次全量重算并覆盖，故天然幂等：重跑不产生不同结果。
存量库若缺列（create_all 不会 ALTER 已存在的表），先自动补列。

CLI：PYTHONPATH=backend .venv/bin/python -m data.tools.backfill_evidence_level
"""

from collections import Counter

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.db import SessionLocal, engine, init_db
from app.models.ingredient import EfficacyAssertion
from app.services.evidence_level import classify_evidence_level, default_strength

_COLUMNS = {"evidence_level": "VARCHAR(30)", "evidence_strength": "FLOAT"}


def ensure_columns() -> None:
    """给存量的 efficacy_assertions 表补列；已存在则跳过（幂等）。"""
    existing = {c["name"] for c in inspect(engine).get_columns("efficacy_assertions")}
    with engine.begin() as conn:
        for name, ddl in _COLUMNS.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE efficacy_assertions ADD COLUMN {name} {ddl}"))


def backfill_session(session: Session) -> Counter:
    """全量重算所有断言的层级/强度，返回层级分布（未提交，调用方负责 commit）。"""
    dist: Counter = Counter()
    for a in session.query(EfficacyAssertion).all():
        level = classify_evidence_level(a.note, a.evidence)
        a.evidence_level = level
        a.evidence_strength = default_strength(level)
        dist[level] += 1
    session.flush()
    return dist


def main() -> None:
    init_db()
    ensure_columns()
    with SessionLocal() as s:
        dist = backfill_session(s)
        s.commit()
    total = sum(dist.values())
    print(f"回填完成，共 {total} 条断言，层级分布：")
    for level, n in sorted(dist.items(), key=lambda kv: -kv[1]):
        print(f"  {level:<12} {n}")


if __name__ == "__main__":
    main()
