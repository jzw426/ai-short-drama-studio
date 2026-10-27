"""场景资产（M4-3）：场景四视图 + 首帧图复用池。

M4-2 只做了角色一致性，场景「崩」的表现不是换脸而是换建筑/换灯光（同一个咖啡馆
第一镜是木质暖光、第三镜变成冷白水泥）。场景四视图把「一个场景长什么样」固化，
首帧出图时作为参考图注入。
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.time_utils import utc_now


class SceneAsset(Base):
    __tablename__ = "scene_assets"
    __table_args__ = (
        # 同一项目同一场景同一视角只保留一张（重新生成即覆盖，避免池子无限膨胀）
        Index(
            "uq_scene_assets_project_scene_view",
            "project_id",
            "scene_ref",
            "view",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # 场景标识：既可能是 scenes.title，也可能是分镜里的 scene_ref 字符串
    scene_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    # wide / medium / close / establishing（scene 的"四视图"是机位视角，不是角色正侧背）
    view: Mapped[str] = mapped_column(String(20), default="wide")
    url: Mapped[str] = mapped_column(String(2048), default="")
    # ai / upload
    source: Mapped[str] = mapped_column(String(20), default="ai")
    prompt: Mapped[str] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
