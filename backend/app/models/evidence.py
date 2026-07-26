"""证据：论文 / 专利 / 法规 / 白皮书。每条功效断言必须挂一条证据。"""

import enum

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class EvidenceType(str, enum.Enum):
    PAPER = "paper"
    PATENT = "patent"
    REGULATION = "regulation"
    WHITE_PAPER = "white_paper"


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[EvidenceType] = mapped_column(SAEnum(EvidenceType), index=True)
    title: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(300))  # 期刊/专利局/法规发布方
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    excerpt: Mapped[str | None] = mapped_column(String(2000), nullable=True)  # 支撑结论的原文摘录
