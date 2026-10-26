import uuid
from datetime import datetime
from app.core.time_utils import utc_now
from sqlalchemy import String, Text, DateTime, Integer, Float, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Storyboard(Base):
    __tablename__ = "storyboards"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    canvas_state: Mapped[str] = mapped_column(Text, default="{}")  # JSON string
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    project = relationship("Project", back_populates="storyboard")
    shots: Mapped[list["Shot"]] = relationship(
        "Shot", back_populates="storyboard", cascade="all, delete-orphan",
        order_by="Shot.sort_order"
    )


class Shot(Base):
    __tablename__ = "shots"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    storyboard_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("storyboards.id", ondelete="CASCADE"), nullable=False
    )
    shot_number: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    duration: Mapped[float] = mapped_column(Float, default=3.0)
    camera_angle: Mapped[str] = mapped_column(String(100), default="medium")
    transition: Mapped[str] = mapped_column(String(100), default="cut")
    scene_ref: Mapped[str] = mapped_column(String(255), nullable=True)
    character_refs: Mapped[list] = mapped_column(JSON, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    storyboard = relationship("Storyboard", back_populates="shots")
