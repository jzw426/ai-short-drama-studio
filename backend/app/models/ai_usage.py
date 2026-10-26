"""AI 用量记录。

两张表，职责不同：

- `ai_usage`：每用户每日"调用次数"计数，供配额扣减（P3）。只关心次数，不含成本。
- `ai_usage_events`：每次 AI 调用的明细账（M3-4）——operation/status/token/耗时/
  估算成本/错误类型。用于 `/api/v1/ops/usage` 的成本与成功率观测。

为什么不合并：配额扣减是热点路径（每次生成都要 UPDATE 一行），塞进明细字段会让
唯一约束行变成写热点，且历史数据无法回填 token/成本。拆表后配额路径零改动。

记账失败绝不影响业务：写库异常由 ai_service 里的 helper 捕获并 logger.warning。
"""
import uuid
from datetime import datetime

from sqlalchemy import String, Integer, Float, DateTime, Index, UniqueConstraint
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


class AIUsageEvent(Base):
    """一次 AI 调用的明细账（成功/失败/超时都记）。

    user_id / project_id 允许为空：渲染 worker 里的视频生成没有请求上下文，
    记为空仍保留 operation/status/token/成本，按日聚合不受影响。
    """

    __tablename__ = "ai_usage_events"
    __table_args__ = (
        Index("ix_ai_usage_events_user_created", "user_id", "created_at"),
        Index("ix_ai_usage_events_operation_created", "operation", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=True)
    # script / character / storyboard / video
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    # 实际服务该次调用的 provider（失败时为最后尝试的那个）
    provider: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    model: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    # success / failure / timeout
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 按 usage_pricing 估算，非结算依据
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # ai_unavailable / timeout / empty_result / 异常类名 等
    error_kind: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=False, index=True
    )
