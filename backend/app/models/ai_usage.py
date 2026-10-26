"""AI 用量记录：每用户每日 AI 调用计数（P3 配额）"""
import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.time_utils import utc_now


class AIUsage(Base):
    __tablename__ = "ai_usage"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_ai_usage_user_date"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    date: Mapped[str] = mapped_column(String(10), index=True, nullable=False)  # YYYY-MM-DD
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )
