"""产品档案：产品-成分有序关联（位次即备案成分表降序）、价格采样点。"""

import datetime

from sqlalchemy import Date, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300), index=True)
    brand: Mapped[str] = mapped_column(String(200), index=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    nmpa_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)  # 备案编号
    price_current: Mapped[float | None] = mapped_column(Float, nullable=True)  # 人民币元，人工采样
    note: Mapped[str | None] = mapped_column(Text, nullable=True)  # 如"品牌公布 15%VC+1%VE"


class ProductIngredient(Base):
    __tablename__ = "product_ingredients"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    # 成分表位次（1-based，备案降序）；微量段内顺序无意义。
    # NULL = 顺序未知（部分数据源的成分为拼音排序，不得伪造位次）
    position: Mapped[int | None] = mapped_column(nullable=True)
    is_trace: Mapped[bool] = mapped_column(default=False)  # 是否"其他微量成分"段（≤0.1%）
    # —— 浓度区间推断结果（%），由计划 02 的推断引擎填充 ——
    conc_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    conc_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    conc_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # —— 来源侧成分属性（盖德镜像的展示列，随产品成分表采集） ——
    safety_risk: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 安全风险（如 "2-4"）
    is_active: Mapped[bool | None] = mapped_column(nullable=True)               # 是否活性成分
    purpose: Mapped[str | None] = mapped_column(String(200), nullable=True)     # 使用目的（如 "保湿剂;抗氧化剂"）

    product = relationship("Product")
    ingredient = relationship("Ingredient")


class ProductClaim(Base):
    """产品功效宣称（NMPA「功效宣称依据摘要」镜像）——核验 Agent 的核验对象。"""

    __tablename__ = "product_claims"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    claim: Mapped[str] = mapped_column(String(100))  # 宣称功效：修护/保湿/抗皱...
    # 评价类别：人体功效评价试验/消费者使用测试/研究数据/文献资料/实验室试验
    eval_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    method_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    method_source: Mapped[str | None] = mapped_column(String(300), nullable=True)
    metric: Mapped[str | None] = mapped_column(String(200), nullable=True)  # 功效判定指标
    test_period: Mapped[str | None] = mapped_column(String(100), nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # 试验结果简述
    institution: Mapped[str | None] = mapped_column(String(300), nullable=True)  # 评价机构

    product = relationship("Product")


class PricePoint(Base):
    __tablename__ = "price_points"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    date: Mapped[datetime.date] = mapped_column(Date)
    price: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(200))  # 人工采样/联盟API
    is_manual: Mapped[bool] = mapped_column(default=True)
