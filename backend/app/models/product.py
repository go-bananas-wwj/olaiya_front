"""产品档案：产品-成分有序关联（位次即备案成分表降序）、价格采样点、去重审计日志。"""

import datetime

from sqlalchemy import Date, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300), index=True)
    brand: Mapped[str] = mapped_column(String(200), index=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    nmpa_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)  # 备案编号
    registrant: Mapped[str | None] = mapped_column(String(300), nullable=True)   # 备案人
    filing_date: Mapped[str | None] = mapped_column(String(20), nullable=True)   # 备案日期（源站字符串原样存）
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)   # 备案数据来源页
    price_current: Mapped[float | None] = mapped_column(Float, nullable=True)  # 人民币元，人工采样
    spec: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 主规格（如 "30ml"/"50g"），随价格采样
    buy_url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # 官方购买页（如品牌官网产品页）
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
    # 品牌披露浓度锚点（%），仅用于校准验收
    disclosed_conc: Mapped[float | None] = mapped_column(Float, nullable=True)
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
    source: Mapped[str] = mapped_column(String(200))  # 人工采样/联盟API/smzdm 好价（含渠道）
    is_manual: Mapped[bool] = mapped_column(default=True)


class MarketSnapshot(Base):
    """口碑/好价时间序列快照（公开渠道采集，当前来源为 smzdm 好价页）。

    value_ratio 是 smzdm「值」投票百分比（值友投票 0-100），不是电商好评率；
    展示字段命名「值率（smzdm 投票）」。date 可能只有月日、年份按采集日推断
    （估计值），推断与匹配说明记入 estimate_note（含原始页面 URL）。"""

    __tablename__ = "market_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    date: Mapped[datetime.date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(200))  # 如 "smzdm/京东"（来源/渠道）
    price: Mapped[float | None] = mapped_column(Float, nullable=True)  # 好价成交价（元）
    value_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)  # 值率（smzdm 投票）0-100
    comment_count: Mapped[int | None] = mapped_column(nullable=True)
    estimate_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    product = relationship("Product")


class MergeLog(Base):
    """产品去重审计日志（data/loaders/product_dedup.py 写入）：
    每合并/归一一行留一条，(kind, dup_id) 唯一保证幂等，detail 存动作明细 JSON。"""

    __tablename__ = "merge_log"
    __table_args__ = (UniqueConstraint("kind", "dup_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # merge / brand_normalize
    keeper_id: Mapped[int | None] = mapped_column(nullable=True)
    dup_id: Mapped[int | None] = mapped_column(nullable=True)
    keeper_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    dup_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(200), nullable=True)
    jaccard: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(30))  # ISO 时间串
