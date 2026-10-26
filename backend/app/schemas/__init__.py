from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse
from app.schemas.script import (
    ScriptUpdate, ScriptResponse, SceneCreate, SceneUpdate, SceneResponse,
    AIGenerateRequest, AIGenerateResponse, AIPromptHistoryResponse,
)
from app.schemas.storyboard import (
    StoryboardUpdate, StoryboardResponse, ShotCreate, ShotUpdate, ShotResponse,
)
from app.schemas.character import CharacterCreate, CharacterUpdate, CharacterResponse, AIGenerateCharacterRequest
from app.schemas.asset import (
    AssetResponse, RenderConfigSchema, RenderSubmitRequest, RenderTaskResponse, RenderStatusResponse,
)
