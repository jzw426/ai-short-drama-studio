import uuid
from datetime import datetime
from app.core.time_utils import utc_now
from sqlalchemy import String, Text, DateTime, Integer, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="supporting")  # protagonist/antagonist/supporting/extra
    description: Mapped[str] = mapped_column(Text, default="")
    avatar_url: Mapped[str] = mapped_column(String(1024), nullable=True)
    generated_images: Mapped[list] = mapped_column(JSON, default=list)

    # ---- M4-2 角色一致性（锁脸）----
    # reference_image_url：角色卡主图（锁脸基准，规范 URL，永远指向我们自己的存储）
    # image_seed：出图种子，同一个角色后续所有图都复用它，provider 支持时才有确定性
    # visual_prompt：结构化外观描述（发型/服装/配色/体态），不靠 description 自由发挥
    # view_images：三视图 {"front": url, "side": url, "full": url, "back": url}
    reference_image_url: Mapped[str] = mapped_column(String(1024), nullable=True)
    image_seed: Mapped[int] = mapped_column(Integer, nullable=True)
    visual_prompt: Mapped[str] = mapped_column(Text, nullable=True)
    view_images: Mapped[dict] = mapped_column(JSON, default=dict, nullable=True)
    voice: Mapped[str] = mapped_column(String(255), default="")
    age: Mapped[int] = mapped_column(Integer, default=0)
    gender: Mapped[str] = mapped_column(String(20), default="other")
    traits: Mapped[list] = mapped_column(JSON, default=list)
    backstory: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    project = relationship("Project", back_populates="characters")
