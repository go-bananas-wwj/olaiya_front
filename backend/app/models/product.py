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
    position: Mapped[int] = mapped_column()  # 成分表位次（1-based，降序）；微量段内顺序无意义
    is_trace: Mapped[bool] = mapped_column(default=False)  # 是否"其他微量成分"段（≤0.1%）
    # —— 浓度区间推断结果（%），由计划 02 的推断引擎填充 ——
    conc_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    conc_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    conc_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    product = relationship("Product")
    ingredient = relationship("Ingredient")


class PricePoint(Base):
    __tablename__ = "price_points"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    date: Mapped[datetime.date] = mapped_column(Date)
    price: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(200))  # 人工采样/联盟API
    is_manual: Mapped[bool] = mapped_column(default=True)
