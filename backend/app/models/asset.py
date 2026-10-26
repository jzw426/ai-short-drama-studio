import uuid
from datetime import datetime
from app.core.time_utils import utc_now
from sqlalchemy import String, Text, DateTime, Integer, Float, JSON, ForeignKey
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
    output_url: Mapped[str] = mapped_column(String(2048), nullable=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    duration: Mapped[float] = mapped_column(Float, nullable=True)  # rendering duration in seconds
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    project = relationship("Project", back_populates="render_tasks")
