# 确保所有模型都被导入，以便 Alembic 能检测到
from app.models.project import Project
from app.models.script import Script, Scene, AIPromptHistory
from app.models.storyboard import Storyboard, Shot
from app.models.character import Character
from app.models.asset import Asset, RenderTask
from app.models.user import User
from app.models.ai_usage import AIUsage

__all__ = [
    "Project",
    "Script",
    "Scene",
    "AIPromptHistory",
    "Storyboard",
    "Shot",
    "Character",
    "Asset",
    "RenderTask",
    "User",
    "AIUsage",
]
