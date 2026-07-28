"""成分与功效断言。铁律：功效断言的 evidence_id 不可为空 —— 无证据不入库。"""

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class Ingredient(Base):
    __tablename__ = "ingredients"

    id: Mapped[int] = mapped_column(primary_key=True)
    inci_name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    cn_name: Mapped[str] = mapped_column(String(200), index=True)
    cas_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # —— 浓度先验（单位 %），来自 IECIC2021 / 安全技术规范 / CIR / SCCS，未知留空 ——
    iecic_max_leave_on: Mapped[float | None] = mapped_column(Float, nullable=True)   # IECIC 最高历史使用量·驻留类
    iecic_max_rinse_off: Mapped[float | None] = mapped_column(Float, nullable=True)  # 淋洗类
    legal_cap: Mapped[float | None] = mapped_column(Float, nullable=True)            # 安全技术规范法定上限
    cir_conc_low: Mapped[float | None] = mapped_column(Float, nullable=True)         # CIR 使用浓度区间
    cir_conc_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    sccs_limit: Mapped[float | None] = mapped_column(Float, nullable=True)           # SCCS 安全上限


class EfficacyAssertion(Base):
    __tablename__ = "efficacy_assertions"

    id: Mapped[int] = mapped_column(primary_key=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    efficacy: Mapped[str] = mapped_column(String(100), index=True)  # 美白/保湿/抗皱...
    evidence_id: Mapped[int] = mapped_column(ForeignKey("evidence.id"), nullable=False)  # 铁律
    # 文献起效浓度区间（%），未知留空；剂量判定的基准
    effective_conc_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    effective_conc_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # —— 证据层级/强度（总纲 I1/I3 数据底座）：由 app.services.evidence_level 的统一规则
    # 在加载器新建断言与 data/tools/backfill_evidence_level.py 回填时填充 ——
    evidence_level: Mapped[str | None] = mapped_column(String(30), nullable=True)    # human_rct/oral/.../unknown
    evidence_strength: Mapped[float | None] = mapped_column(Float, nullable=True)    # 0-1，层级默认分

    ingredient = relationship("Ingredient")
    evidence = relationship("Evidence")
