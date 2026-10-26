from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# ===== 项目 =====

class ProjectCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str = ""


class ProjectUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    status: Optional[str] = None
    progress: Optional[float] = Field(None, ge=0, le=100)


class ProjectResponse(BaseModel):
    id: str
    title: str
    description: str
    status: str
    progress: float
    thumbnail: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
