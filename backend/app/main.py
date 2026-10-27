import os
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.logging_config import configure_logging
from app.core.database import engine, Base
from app.core.deps import get_current_user
from app.core.middleware import RequestLogMiddleware
from app.api.routes import (
    projects,
    scripts,
    storyboards,
    characters,
    render,
    assets,
    auth,
    ops,
    media,
    video_jobs,
    scene_assets,
)

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动与关闭时的生命周期管理"""
    # 启动时：SQLite 模式下自动创建表
    if settings.DATABASE_TYPE == "sqlite":
        os.makedirs(os.path.dirname(settings.DATABASE_PATH) or ".", exist_ok=True)
        # T0：显式导入 user，避免 create_all 依赖 deps 的副作用导入
        from app.models import (  # noqa: F401
            project, script, storyboard, character, asset, ai_usage, user,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print(f"[Startup] SQLite 数据库已就绪: {settings.DATABASE_PATH}")

    # 启动时：初始化存储
    try:
        from app.services.storage_service import storage_service
        await storage_service.ensure_bucket()
    except Exception as e:
        print(f"[WARNING] 存储初始化跳过: {e}")

    print(
        f"[Startup] AI 路由配置：文本 {len(settings.AI_TEXT_PROVIDERS)} 个 provider，"
        f"图片 {len(settings.AI_IMAGE_PROVIDERS)} 个，视频 {len(settings.AI_VIDEO_PROVIDERS)} 个，"
        f"每日配额 {settings.AI_DAILY_QUOTA}/用户"
    )

    yield

    # 关闭时：释放数据库连接
    await engine.dispose()


app = FastAPI(
    title="AI Short Drama Studio API",
    description="面向AI短剧创作者的一站式工作流平台后端服务",
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    openapi_url="/api/v1/openapi.json",
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 请求日志 + 指标采集中间件（放在 CORS 之后，metrics/health 自排除）
app.add_middleware(RequestLogMiddleware)

# 本地存储：只保证目录存在，不再公开挂载。
# M1 起 /uploads 由受控端点提供（签名 URL 或"登录 + 项目归属"），
# 见 app/api/routes/media.py。
if settings.STORAGE_TYPE == "local":
    os.makedirs(os.path.abspath(settings.STORAGE_LOCAL_PATH), exist_ok=True)

# 注册路由
# 业务路由统一要求登录（Bearer Token），auth/ops 路由开放
app.include_router(auth.router, prefix="/api/v1")
app.include_router(ops.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(scripts.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(storyboards.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(characters.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(render.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(assets.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(video_jobs.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(scene_assets.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
# 媒体端点挂在根路径（/uploads/...），鉴权在端点内部完成（签名 或 登录+归属）
app.include_router(media.router)
