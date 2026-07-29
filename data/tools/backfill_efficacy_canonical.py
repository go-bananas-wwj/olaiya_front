"""一次性回填：efficacy_assertions.efficacy_canonical。

映射规则见 app.services.efficacy_canon（与 evidence_loader 共用）。映射是纯函数，
每次全量重算并覆盖，故天然幂等：重跑不产生不同结果。
存量库若缺列（create_all 不会 ALTER 已存在的表），先自动补列。

CLI：PYTHONPATH=backend .venv/bin/python -m data.tools.backfill_efficacy_canonical
"""

from collections import Counter

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.db import SessionLocal, engine, init_db
from app.models.ingredient import EfficacyAssertion
from app.services.efficacy_canon import canonicalize


def ensure_column() -> None:
    """给存量的 efficacy_assertions 表补 efficacy_canonical 列；已存在则跳过（幂等）。"""
    existing = {c["name"] for c in inspect(engine).get_columns("efficacy_assertions")}
    if "efficacy_canonical" not in existing:
        with engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE efficacy_assertions ADD COLUMN efficacy_canonical VARCHAR(50)"))


def backfill_session(session: Session) -> Counter:
    """全量重算所有断言的规范功效族，返回分布（未提交，调用方负责 commit）。"""
    dist: Counter = Counter()
    for a in session.query(EfficacyAssertion).all():
        canonical = canonicalize(a.efficacy)
        a.efficacy_canonical = canonical
        dist[canonical] += 1
    session.flush()
    return dist


def main() -> None:
    init_db()
    ensure_column()
    with SessionLocal() as s:
        dist = backfill_session(s)
        s.commit()
    total = sum(dist.values())
    print(f"回填完成，共 {total} 条断言，canonical 分布：")
    for canonical, n in sorted(dist.items(), key=lambda kv: -kv[1]):
        print(f"  {canonical:<8} {n}")


if __name__ == "__main__":
    main()
