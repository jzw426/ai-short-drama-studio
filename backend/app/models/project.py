import uuid
from datetime import datetime
from app.core.time_utils import utc_now
from sqlalchemy import String, Text, DateTime, Float, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

import enum


class ProjectStatus(str, enum.Enum):
    DRAFT = "draft"
    EDITING = "editing"
    RENDERING = "rendering"
    COMPLETED = "completed"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[ProjectStatus] = mapped_column(
        SAEnum(ProjectStatus), default=ProjectStatus.DRAFT
    )
    # 项目归属用户（用户体系预留；P3 多租户隔离时启用）
    owner_id: Mapped[str] = mapped_column(String(36), nullable=True, index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    thumbnail: Mapped[str] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )

    # 关联
    scripts = relationship("Script", back_populates="project", cascade="all, delete-orphan")
    storyboard = relationship("Storyboard", back_populates="project", uselist=False, cascade="all, delete-orphan")
    characters = relationship("Character", back_populates="project", cascade="all, delete-orphan")
    assets = relationship("Asset", back_populates="project", cascade="all, delete-orphan")
    render_tasks = relationship("RenderTask", back_populates="project", cascade="all, delete-orphan")
