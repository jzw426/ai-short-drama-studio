from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# ===== 镜头 =====

class ShotCreate(BaseModel):
    shot_number: int
    label: str = ""
    description: str = ""
    duration: float = 3.0
    camera_angle: str = "medium"
    transition: str = "cut"
    scene_ref: Optional[str] = None
    character_refs: List[str] = []
    # 镜头素材规范 URL；为空则渲染回退 AI 视频生成
    video_url: Optional[str] = Field(default=None, max_length=2048)
    sort_order: int = 0


class ShotUpdate(BaseModel):
    shot_number: Optional[int] = None
    label: Optional[str] = None
    description: Optional[str] = None
    duration: Optional[float] = None
    camera_angle: Optional[str] = None
    transition: Optional[str] = None
    scene_ref: Optional[str] = None
    character_refs: Optional[List[str]] = None
    video_url: Optional[str] = Field(default=None, max_length=2048)
    sort_order: Optional[int] = None


class ShotResponse(BaseModel):
    id: str
    storyboard_id: str
    shot_number: int
    label: str
    description: str
    duration: float
    camera_angle: str
    transition: str
    scene_ref: Optional[str]
    character_refs: List[str]
    video_url: Optional[str] = None
    sort_order: int
    created_at: datetime

    class Config:
        from_attributes = True


# ===== 分镜 =====

class StoryboardUpdate(BaseModel):
    canvas_state: Optional[str] = None


class StoryboardResponse(BaseModel):
    id: str
    project_id: str
    canvas_state: str
    shots: List[ShotResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
