from pydantic import BaseModel, Field
from typing import Literal, Optional, List
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
    # 不带签名的稳定存储地址（local: /uploads/<object>；minio: 桶内规范 URL）。
    # 素材「绑定到镜头」时必须用这个值：url 是短期签名链接，存进 shots.video_url
    # 后过期就再也取不到素材了。
    canonical_url: Optional[str] = None
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
    """渲染参数。

    M2 之前这些字段除了 add_subtitles/add_bgm/bgm_source 之外**全部被渲染链路忽略**
    （分辨率永远跟输入走、帧率硬编码 24、画质与风格不影响任何一帧）。现在每一项都
    有明确语义，见 `backend/app/services/render_service.py` 的 _build_spec：

    * resolution + aspect_ratio → 统一画布（不匹配时按 aspect_ratio 取长边重算，
      scale 后 pad 黑边，绝不裁剪用户画面）。
    * fps → 归一化帧率，也是成片帧率。
    * quality → H.264 CRF/preset（low/medium/high）。
    * visual_style → 归一化时套用的轻量调色（未知风格不调色，不做假动作）。
    * subtitle_source → dialogue（剧本台词，正解）/ description（画面描述，历史行为）/ label / none。
    * subtitle_mode → hard（烧进画面，兼容一切播放器）/ soft（mov_text 软字幕轨，画质无损）/ both。
    """

    resolution: str = Field(default="1920x1080", pattern=r"^\d{3,4}x\d{3,4}$")
    aspect_ratio: str = Field(default="9:16", pattern=r"^\d{1,2}:\d{1,2}$")
    fps: int = Field(default=24, ge=12, le=60)
    visual_style: str = "电影级（Cinematic）"
    add_subtitles: bool = True
    subtitle_source: Literal["dialogue", "description", "label", "none"] = "dialogue"
    subtitle_mode: Literal["hard", "soft", "both"] = "hard"
    add_bgm: bool = True
    bgm_source: Optional[str] = Field(default=None, max_length=2048)
    quality: Literal["low", "medium", "high"] = "high"
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
    subtitle_url: Optional[str] = None
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
    subtitle_url: Optional[str] = None
    error_message: Optional[str]
