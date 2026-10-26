from app.api.routes.projects import router as projects_router
from app.api.routes.scripts import router as scripts_router
from app.api.routes.storyboards import router as storyboards_router
from app.api.routes.characters import router as characters_router
from app.api.routes.render import router as render_router
from app.api.routes.assets import router as assets_router

__all__ = [
    "projects_router",
    "scripts_router",
    "storyboards_router",
    "characters_router",
    "render_router",
    "assets_router",
]
