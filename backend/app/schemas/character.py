from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class CharacterCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    role: str = "supporting"
    description: str = ""
    voice: str = ""
    age: int = 0
    gender: str = "other"
    traits: List[str] = []
    backstory: str = ""


class CharacterUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    role: Optional[str] = None
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    voice: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    traits: Optional[List[str]] = None
    backstory: Optional[str] = None
    reference_image_url: Optional[str] = None
    image_seed: Optional[int] = None
    visual_prompt: Optional[str] = None


class AIGenerateCharacterRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=5000)


class LockFaceRequest(BaseModel):
    """锁定角色脸：选择一张基准图 + 固定 seed + 固化外观描述。

    source_url 省略时用当前 avatar_url；两者都没有则 400（不能凭空锁脸）。
    """

    source_url: Optional[str] = None
    seed: Optional[int] = Field(None, ge=0, le=4294967295)
    visual_prompt: Optional[str] = Field(None, max_length=2000)


class GenerateViewsRequest(BaseModel):
    """三视图：只允许已知视角，避免前端传任意字符串拼进 prompt。"""

    views: List[str] = Field(default_factory=lambda: ["front", "side", "full"])
    seed: Optional[int] = Field(None, ge=0, le=4294967295)


class CharacterResponse(BaseModel):
    id: str
    project_id: str
    name: str
    role: str
    description: str
    avatar_url: Optional[str]
    generated_images: List[str]
    voice: str
    age: int
    gender: str
    traits: List[str]
    backstory: str
    reference_image_url: Optional[str] = None
    image_seed: Optional[int] = None
    visual_prompt: Optional[str] = None
    view_images: dict = {}
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
