import uuid
from datetime import datetime
from app.core.time_utils import utc_now
from sqlalchemy import (
    String, Text, DateTime, Integer, Float, JSON, Boolean, ForeignKey, Index, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # image/audio/video
    mime_type: Mapped[str] = mapped_column(String(100), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    url: Mapped[str] = mapped_column(String(2048), default="")
    thumbnail_url: Mapped[str] = mapped_column(String(2048), nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    duration: Mapped[float] = mapped_column(Float, nullable=True)
    width: Mapped[int] = mapped_column(Integer, nullable=True)
    height: Mapped[int] = mapped_column(Integer, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    project = relationship("Project", back_populates="assets")


class RenderTask(Base):
    __tablename__ = "render_tasks"
    # 幂等键唯一约束（部分索引：只约束非 NULL）。旧实现靠"先查后插"，并发下
    # 两个请求都能通过检查，各排一次队、各烧一遍 AI 钱。
    __table_args__ = (
        Index(
            "uq_render_tasks_project_idempotency",
            "project_id",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL"),
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued/processing/completed/failed
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    # Celery 任务真实 ID（用于 revoke 取消），与数据库记录 ID 相互独立
    celery_task_id: Mapped[str] = mapped_column(String(64), nullable=True, index=True)
    # 幂等键：同一项目内同 key 的重复提交返回同一任务，避免重复扣 AI 费用
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=True, index=True)
    # 协作式取消：接口置 true，worker 在每个可中断点检查后自行退出
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0", index=True
    )
    # 已尝试次数（retry 不重置，用于判定是否超限）
    attempt: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )
    # 断点：已生成的片段清单（shot_number/video_url），重试时复用，不重新调用 AI
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    output_url: Mapped[str] = mapped_column(String(2048), nullable=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    duration: Mapped[float] = mapped_column(Float, nullable=True)  # rendering duration in seconds
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    project = relationship("Project", back_populates="render_tasks")
