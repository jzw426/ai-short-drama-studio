from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ===== AI 视频作业（M4-3） =====

class VideoJobCreate(BaseModel):
    """提交一条视频作业。所有字段都可省略：省略时从镜头继承。

    prompt 省略 → 用 shot.video_prompt（AI 优化过的提示词），再退到 shot.description；
    image_url 省略 → 用 shot.image_url（镜头首帧图，图生视频的关键）。
    """

    prompt: Optional[str] = Field(default=None, max_length=4000)
    # provider 只接受 8n+1 帧、对应 3/5/7/10/15/18 秒，schema 先卡住非法时长
    duration: float = Field(default=5.0, ge=3, le=18)
    image_url: Optional[str] = Field(default=None, max_length=2048)


class VideoJobResponse(BaseModel):
    id: str
    project_id: str
    shot_id: Optional[str] = None
    prompt: str = ""
    image_url: Optional[str] = None
    status: str
    provider: str = ""
    model: str = ""
    poll_count: int = 0
    # 库里存规范地址，响应时才签名（M1 媒体受控），所以路由里会覆盖成签名链接
    video_url: Optional[str] = None
    duration: Optional[float] = None
    error: Optional[str] = None
    # 非致命问题（例如转存失败、降级为第三方临时链接），换行分隔
    warnings: str = ""
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
