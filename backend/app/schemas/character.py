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
    voice: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    traits: Optional[List[str]] = None
    backstory: Optional[str] = None


class AIGenerateCharacterRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=5000)


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
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
