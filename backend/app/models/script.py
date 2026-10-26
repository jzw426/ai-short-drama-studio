import uuid
from datetime import datetime
from app.core.time_utils import utc_now
from sqlalchemy import String, Text, DateTime, Integer, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Script(Base):
    __tablename__ = "scripts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    project = relationship("Project", back_populates="scripts")
    scenes: Mapped[list["Scene"]] = relationship(
        "Scene", back_populates="script", cascade="all, delete-orphan",
        order_by="Scene.sort_order"
    )
    ai_prompts: Mapped[list["AIPromptHistory"]] = relationship(
        "AIPromptHistory", back_populates="script", cascade="all, delete-orphan"
    )


class Scene(Base):
    __tablename__ = "scenes"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    script_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False
    )
    scene_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="")
    location: Mapped[str] = mapped_column(String(255), default="")
    time_of_day: Mapped[str] = mapped_column(String(50), default="day")
    interior: Mapped[bool] = mapped_column(Boolean, default=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    # 台词（M2 新增）：渲染烧字幕的唯一正确来源。为空时 render_service 会尝试从
    # content 的引号文本里提取；仍为空则回退画面描述并记为 warning。
    dialogue: Mapped[str] = mapped_column(Text, default="")
    duration: Mapped[int] = mapped_column(Integer, default=0)  # seconds
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    script = relationship("Script", back_populates="scenes")


class AIPromptHistory(Base):
    __tablename__ = "ai_prompt_history"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    script_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, default="")
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    script = relationship("Script", back_populates="ai_prompts")
