"""AI 视频生成作业（M4-3）：把「提交 → 轮询 → 转存」从渲染任务里拆出来。

为什么要有这张表：
旧实现 `render_service._pick_source` 在渲染任务里同步调用 `generate_video`，
而视频 provider 是异步任务制，单条片段要轮询 5 分钟（60 次 × 5s）。一个 30 镜的
分镜有 3 个并发的渲染槽，等于把 Celery worker 泡在付费生成里，进度条 8% 卡死、
`RENDER_TIMEOUT` 直接掀桌，还无法单独重试某个镜头。

现在：前置生成（出图 → 出视频）走本表的作业，渲染只消费已完成作业的产物或
显式绑定的素材，一次渲染里不再出现任何付费生成调用。
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.time_utils import utc_now


class AIVideoJob(Base):
    __tablename__ = "ai_video_jobs"
    __table_args__ = (
        Index("ix_ai_video_jobs_project_created", "project_id", "created_at"),
        # 轮询任务按 status 扫描活跃作业；completed/failed 的作业不会再被扫到
        Index("ix_ai_video_jobs_status_poll", "status", "next_poll_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # 关联镜头（可为空：允许先批量生成、后绑定）；不级联删除，删镜头不销毁已付费产物
    shot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shots.id", ondelete="SET NULL"), nullable=True
    )
    prompt: Mapped[str] = mapped_column(Text, default="")
    # 首帧图（图生视频的入参）。必须是 provider 能取到的地址：公有桶预签名或在
    # MINIO_PUBLIC_ENDPOINT 下可直连；私有 localhost 地址会让 provider 400/抓取失败。
    image_url: Mapped[str] = mapped_column(String(2048), nullable=True)
    # pending → submitted → polling → completed / failed / timeout / cancelled
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    provider: Mapped[str] = mapped_column(String(50), default="")
    model: Mapped[str] = mapped_column(String(100), default="")
    provider_task_id: Mapped[str] = mapped_column(String(255), nullable=True)
    poll_count: Mapped[int] = mapped_column(Integer, default=0)
    next_poll_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    # 成功后的规范化地址（已转存自有存储，M4-1 语义）
    video_url: Mapped[str] = mapped_column(String(2048), nullable=True)
    duration: Mapped[float] = mapped_column(Float, nullable=True)
    error: Mapped[str] = mapped_column(String(1024), nullable=True)
    # 转存失败只降级为第三方链接，但要留痕：断点续渲会因 TTL 失效
    warnings: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )

    project = relationship("Project")
    shot = relationship("Shot")
