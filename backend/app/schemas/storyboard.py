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
    # 镜头素材规范 URL；为空则渲染优先复用已完成视频作业，其次才看内联开关
    video_url: Optional[str] = Field(default=None, max_length=2048)
    # 首帧图（图生视频的输入；由 /first-frame 端点写入）
    image_url: Optional[str] = Field(default=None, max_length=2048)
    # 固化下来的视频提示词（首帧图 + 提示词 = 图生视频的入参）
    video_prompt: Optional[str] = None
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
    image_url: Optional[str] = Field(default=None, max_length=2048)
    video_prompt: Optional[str] = None
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
    image_url: Optional[str] = None
    video_prompt: Optional[str] = None
    sort_order: int
    created_at: datetime

    class Config:
        from_attributes = True


# ===== 首帧 / 视频提示词 =====

class FirstFrameRequest(BaseModel):
    # 默认复用已生成的首帧（不花配额）；显式 True 才重新出图
    regenerate: bool = False


class FirstFrameResponse(BaseModel):
    image_url: Optional[str] = None
    prompt: str = ""
    characters_used: List[str] = []
    # True 表示命中已有首帧、本次没有调用 AI
    reused: bool = False


class VideoPromptUpdate(BaseModel):
    video_prompt: str = ""


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
