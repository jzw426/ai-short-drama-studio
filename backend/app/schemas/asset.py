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
    add_bgm: bool = True
    bgm_source: Optional[str] = None
    quality: str = "high"
    ai_model: str = "kling"


class RenderSubmitRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    config: RenderConfigSchema = Field(default_factory=RenderConfigSchema)


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

    class Config:
        from_attributes = True


class RenderStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: float
    output_url: Optional[str]
    error_message: Optional[str]
