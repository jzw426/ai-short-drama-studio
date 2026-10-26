from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List
import json
import secrets


class Settings(BaseSettings):
    """应用配置，从环境变量 / .env 文件读取"""

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),  # 根目录 .env 为权威，backend/.env 可覆盖
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",  # 容忍 .env 中面向前端/文档的超集字段（如 NEXT_PUBLIC_*）
    )

    # 应用
    APP_NAME: str = "AI Short Drama Studio"
    APP_VERSION: str = "0.2.0"
    DEBUG: bool = False
    SECRET_KEY: str = ""
    ENVIRONMENT: str = "development"

    # 数据库
    DATABASE_TYPE: str = "sqlite"  # "postgres" or "sqlite"
    DATABASE_PATH: str = "data/app.db"  # SQLite 文件路径
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "ai_drama_studio"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres_password"

    @property
    def DATABASE_URL(self) -> str:
        if self.DATABASE_TYPE == "sqlite":
            return f"sqlite+aiosqlite:///{self.DATABASE_PATH}"
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def DATABASE_URL_SYNC(self) -> str:
        if self.DATABASE_TYPE == "sqlite":
            return f"sqlite:///{self.DATABASE_PATH}"
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # MinIO / 存储
    STORAGE_TYPE: str = "local"  # "local" or "minio"
    STORAGE_LOCAL_PATH: str = "data/uploads"  # 本地存储路径
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET_NAME: str = "ai-drama-studio-assets"
    MINIO_USE_SSL: bool = False

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    CELERY_TASK_SERIALIZER: str = "json"
    CELERY_RESULT_SERIALIZER: str = "json"
    CELERY_ACCEPT_CONTENT: str = '["json"]'
    # 提交任务到 broker 的最大等待时间（秒）；broker 不可达时快速失败而非挂起接口
    CELERY_SUBMIT_TIMEOUT: float = 5.0

    # 上传限制
    UPLOAD_MAX_SIZE_MB: int = 500
    UPLOAD_ALLOWED_TYPES: List[str] = [
        "image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp",
        "audio/mpeg", "audio/wav", "audio/mp4", "audio/ogg", "audio/aac",
        "video/mp4", "video/webm", "video/quicktime", "video/x-msvideo",
    ]
    # 允许上传的扩展名（与 MIME 白名单配合，双保险）
    UPLOAD_ALLOWED_EXTENSIONS: List[str] = [
        ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp",
        ".mp3", ".wav", ".m4a", ".ogg", ".aac",
        ".mp4", ".webm", ".mov", ".avi",
    ]

    # AI API Keys（Agnes AI 全免费一站式方案）
    # 申请地址：https://platform.agnes-ai.com/settings/apiKeys
    AGNES_API_KEY: str = ""
    AGNES_API_BASE: str = "https://apihub.agnes-ai.com/v1"
    AGNES_TEXT_MODEL: str = "agnes-2.0-flash"
    AGNES_IMAGE_MODEL: str = "agnes-image-2.1-flash"
    AGNES_VIDEO_MODEL: str = "agnes-video-v2.0"
    # 以下为其他免费/付费 API 保留备用
    GEMINI_API_KEY: str = ""
    GEMINI_API_BASE: str = "https://generativelanguage.googleapis.com/v1beta"
    GEMINI_MODEL: str = "gemini-2.0-flash"
    HF_API_TOKEN: str = ""
    HF_IMAGE_MODEL: str = "black-forest-labs/FLUX.1-schnell"
    KLING_API_KEY: str = ""
    KLING_API_BASE: str = "https://api.klingai.com/v1"
    KLING_MODEL: str = "kling-v1.6"
    SEEDANCE_API_KEY: str = ""
    SEEDANCE_API_BASE: str = "https://api.seedance.ai/v1"
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_API_BASE: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = "deepseek-chat"

    # ---- 多模型路由（P3）----
    # 每类能力按顺序尝试多个 provider，全部失败才降级 mock。
    # 默认链仅含 Agnes（免费一站式）；可通过 .env 用 JSON 数组覆盖扩展，
    # 例如 AI_TEXT_PROVIDERS_RAW=[{"name":"deepseek","base":"https://api.deepseek.com/v1","model":"deepseek-chat","api_key":"sk-..."}]
    AI_TEXT_PROVIDERS_RAW: str = ""
    AI_IMAGE_PROVIDERS_RAW: str = ""
    AI_VIDEO_PROVIDERS_RAW: str = ""

    def _default_providers(self, kind: str) -> list:
        """
        构建默认 provider 链：
        - 文本：自动收集所有已配置 Key 的 OpenAI 兼容 provider（agnes → deepseek → gemini），
          配了哪个 Key 就自动纳入调度，未配置的自动跳过。
        - 图片/视频：默认仅 Agnes（其余家协议暂未实现）。
        """
        if kind == "text":
            chain = []
            # Agnes（免费一站式，OpenAI 兼容）
            if self.AGNES_API_KEY:
                chain.append({
                    "name": "agnes",
                    "base": self.AGNES_API_BASE,
                    "model": self.AGNES_TEXT_MODEL,
                    "api_key": self.AGNES_API_KEY,
                })
            # DeepSeek（OpenAI 兼容 chat/completions）
            if self.DEEPSEEK_API_KEY:
                chain.append({
                    "name": "deepseek",
                    "base": self.DEEPSEEK_API_BASE,
                    "model": self.DEEPSEEK_MODEL,
                    "api_key": self.DEEPSEEK_API_KEY,
                })
            # Gemini（OpenAI 兼容端点 /v1beta/openai）
            if self.GEMINI_API_KEY:
                chain.append({
                    "name": "gemini",
                    "base": f"{self.GEMINI_API_BASE.rstrip('/')}/openai",
                    "model": self.GEMINI_MODEL,
                    "api_key": self.GEMINI_API_KEY,
                })
            return chain
        if kind == "image":
            return [{
                "name": "agnes",
                "base": self.AGNES_API_BASE,
                "model": self.AGNES_IMAGE_MODEL,
                "api_key": self.AGNES_API_KEY,
            }]
        if kind == "video":
            return [{
                "name": "agnes",
                "base": self.AGNES_API_BASE,
                "model": self.AGNES_VIDEO_MODEL,
                "api_key": self.AGNES_API_KEY,
            }]
        return []

    @staticmethod
    def _parse_provider_raw(raw: str) -> list:
        if not raw or not raw.strip():
            return []
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValueError("AI_*_PROVIDERS_RAW 必须是 JSON 数组")
        return parsed

    @property
    def AI_TEXT_PROVIDERS(self) -> list:
        raw = self._parse_provider_raw(self.AI_TEXT_PROVIDERS_RAW)
        return raw if raw else self._default_providers("text")

    @property
    def AI_IMAGE_PROVIDERS(self) -> list:
        raw = self._parse_provider_raw(self.AI_IMAGE_PROVIDERS_RAW)
        return raw if raw else self._default_providers("image")

    @property
    def AI_VIDEO_PROVIDERS(self) -> list:
        raw = self._parse_provider_raw(self.AI_VIDEO_PROVIDERS_RAW)
        return raw if raw else self._default_providers("video")

    # ---- AI 用量配额（P3）----
    # 每用户每日 AI 调用上限（文本/图片/视频生成类接口合计），超限返回 429
    AI_DAILY_QUOTA: int = 100

    # ---- AI 调度熔断（本轮优化）----
    # provider 连续失败 AI_PROVIDER_FAILURE_THRESHOLD 次后，进入
    # AI_PROVIDER_COOLDOWN_SECONDS 秒冷却，冷却期内跳过该 provider（避免反复超时拖慢链路）
    AI_PROVIDER_FAILURE_THRESHOLD: int = 3
    AI_PROVIDER_COOLDOWN_SECONDS: int = 60

    # FFmpeg
    FFMPEG_PATH: str = "ffmpeg"
    FFPROBE_PATH: str = "ffprobe"

    # 渲染并发度（并行生成视频片段的上限，避免触发 API 限流）
    RENDER_CONCURRENCY: int = 3

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # 认证 Cookie（httpOnly 会话；生产 https 下建议置 True）
    COOKIE_SECURE: bool = False

    # 日志
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # SECRET_KEY 加固：生产环境必须显式配置，否则拒绝启动
        if not self.SECRET_KEY:
            if self.ENVIRONMENT == "production":
                raise RuntimeError(
                    "生产环境必须通过环境变量或 .env 显式设置 SECRET_KEY（例如 python -c 'import secrets; print(secrets.token_hex(32))'）"
                )
            self.SECRET_KEY = secrets.token_hex(32)
            print(
                "[WARNING] SECRET_KEY 未配置，开发环境已自动生成随机密钥"
                "（重启后已签发 Token 将失效，生产环境请显式配置）"
            )


settings = Settings()
