from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# ===== 素材 =====

class AssetResponse(BaseModel):
    id: str
    project_id: str
    name: str
    type: str
    mime_type: str
    size: int
    url: str
    thumbnail_url: Optional[str]
    tags: List[str]
    duration: Optional[float]
    width: Optional[int]
    height: Optional[int]
    uploaded_at: datetime

    class Config:
        from_attributes = True


# ===== 渲染 =====

class RenderConfigSchema(BaseModel):
    resolution: str = "1920x1080"
    aspect_ratio: str = "9:16"
    fps: int = 24
    visual_style: str = "电影级（Cinematic）"
    add_subtitles: bool = True
    # 字幕文本来源：description=镜头画面描述（历史行为，语义上不准确）/ label=镜头标签 / none=不烧字幕
    subtitle_source: str = "description"
    add_bgm: bool = True
    bgm_source: Optional[str] = None
    quality: str = "high"
    ai_model: str = "kling"


class RenderSubmitRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    config: RenderConfigSchema = Field(default_factory=RenderConfigSchema)
    # 幂等键：前端为同一次"点击渲染"生成一个 UUID，重试/双击都复用同一个值，
    # 服务端据此返回已存在的任务而不是再排一次队（每次重排都是真金白银的 AI 调用）
    idempotency_key: Optional[str] = Field(default=None, max_length=100)


class RenderTaskResponse(BaseModel):
    id: str
    project_id: str
    name: str
    status: str
    progress: float
    config: dict
    output_url: Optional[str]
    error_message: Optional[str]
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    duration: Optional[float]
    created_at: datetime
    cancel_requested: bool = False

    class Config:
        from_attributes = True


class RenderStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: float
    output_url: Optional[str]
    error_message: Optional[str]
