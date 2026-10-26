import uuid
from datetime import datetime
from app.core.time_utils import utc_now
from sqlalchemy import String, DateTime, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    username: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # 会话代际：+1 即让该用户此前签发的全部 Token 失效（登出/改密/踢人）
    token_version: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
