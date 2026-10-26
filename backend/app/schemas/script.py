from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# ===== 场景 =====

class SceneCreate(BaseModel):
    scene_number: int
    title: str = ""
    location: str = ""
    time_of_day: str = "day"
    interior: bool = True
    summary: str = ""
    content: str = ""
    duration: int = 0
    sort_order: int = 0


class SceneUpdate(BaseModel):
    scene_number: Optional[int] = None
    title: Optional[str] = None
    location: Optional[str] = None
    time_of_day: Optional[str] = None
    interior: Optional[bool] = None
    summary: Optional[str] = None
    content: Optional[str] = None
    duration: Optional[int] = None
    sort_order: Optional[int] = None


class SceneResponse(BaseModel):
    id: str
    script_id: str
    scene_number: int
    title: str
    location: str
    time_of_day: str
    interior: bool
    summary: str
    content: str
    duration: int
    sort_order: int

    class Config:
        from_attributes = True


# =====剧本 =====

class ScriptUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    word_count: Optional[int] = None


class AIGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=5000)


class AIGenerateResponse(BaseModel):
    generated_content: str
    prompt: str
    usage: Optional[dict] = None


class AIPromptHistoryResponse(BaseModel):
    id: str
    prompt: str
    response: str
    timestamp: datetime

    class Config:
        from_attributes = True


class ScriptResponse(BaseModel):
    id: str
    project_id: str
    title: str
    content: str
    word_count: int
    scenes: List[SceneResponse] = []
    ai_prompt_history: List[AIPromptHistoryResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
