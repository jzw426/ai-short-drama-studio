from pathlib import Path
import json
import secrets

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---- 路径锚定（T0）----
# 所有路径一律以本文件位置为基准解析，禁止依赖"当前工作目录"。
# 原实现用 env_file=("../.env", ".env") 与 DATABASE_PATH="data/app.db"，
# 从仓库根启动时会把数据库创建到 E:\data\app.db、并读不到根目录 .env。
_BACKEND_DIR = Path(__file__).resolve().parents[2]   # backend/
_PROJECT_ROOT = _BACKEND_DIR.parent                  # 仓库根

# 占位密钥黑名单：这些值在历史 .env / .env.example / docker-compose 中都出现过，
# 且已被证明可以用来伪造任意用户的 JWT（见 T0 事故报告）。
_PLACEHOLDER_SECRETS = frozenset({
    "",
    "change-me-to-a-random-secret-key",
    "change-me-in-production",
    "changeme",
    "secret",
    "test",
    "your-secret-key",
    "replace-me",
    "dev-secret-key",
})


class Settings(BaseSettings):
    """应用配置，从环境变量 / .env 文件读取"""

    model_config = SettingsConfigDict(
        env_file=(str(_PROJECT_ROOT / ".env"), str(_BACKEND_DIR / ".env")),
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
    DATABASE_PATH: str = str(_BACKEND_DIR / "data" / "app.db")  # SQLite 文件路径（绝对）
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "ai_drama_studio"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres_password"

    @field_validator("DATABASE_PATH", "STORAGE_LOCAL_PATH", mode="after")
    @classmethod
    def _resolve_path(cls, v: str) -> str:
        """相对路径按 backend/ 解析，避免随启动目录漂移。"""
        p = Path(v).expanduser()
        if not p.is_absolute():
            p = _BACKEND_DIR / p
        return str(p.resolve())

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
    STORAGE_LOCAL_PATH: str = str(_BACKEND_DIR / "data" / "uploads")  # 本地存储路径（绝对）
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET_NAME: str = "ai-drama-studio-assets"
    MINIO_USE_SSL: bool = False
    MINIO_REGION: str = "us-east-1"
    # 浏览器可达的 endpoint（host[:port]）。M1 起桶是私有的，链接一律是预签名 URL，
    # 而 SigV4 的签名覆盖 Host 头 —— 所以"签名用的主机名"必须就是浏览器访问的主机名。
    # 留空则沿用 MINIO_ENDPOINT（要求它本身对浏览器可达）。容器里常写成 minio:9000，
    # 那个名字浏览器解析不了，此时必须在这里填 localhost:9000 或对外域名。
    MINIO_PUBLIC_ENDPOINT: str = ""
    MINIO_PUBLIC_USE_SSL: bool = False

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    CELERY_TASK_SERIALIZER: str = "json"
    CELERY_RESULT_SERIALIZER: str = "json"
    CELERY_ACCEPT_CONTENT: str = '["json"]'
    # 提交任务到 broker 的最大等待时间（秒）；broker 不可达时快速失败而非挂起接口
    CELERY_SUBMIT_TIMEOUT: float = 5.0
    # 本机没有 Redis 时的真实 worker 验证通道：broker 设为 filesystem:// 后，
    # 队列文件落在该目录（producer 与 worker 必须指向同一目录）。
    # 生产环境不要用 filesystem 传输（无持久化/无重投递保证）。
    CELERY_FILESYSTEM_DIR: str = ""

    # 上传限制
    UPLOAD_MAX_SIZE_MB: int = 500
    UPLOAD_ALLOWED_TYPES: list = [
        "image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp",
        "audio/mpeg", "audio/wav", "audio/mp4", "audio/ogg", "audio/aac",
        "video/mp4", "video/webm", "video/quicktime", "video/x-msvideo",
    ]
    # 允许上传的扩展名（与 MIME 白名单配合，双保险）
    UPLOAD_ALLOWED_EXTENSIONS: list = [
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

    # ---- 媒体访问控制（M1）----
    # 签名 URL 有效期（秒）。本地存储不再公开挂载 /uploads，
    # 未签名请求必须"已登录 + 是该项目的 owner"才放行。
    MEDIA_URL_TTL_SECONDS: int = 21600

    # ---- 登录限流（M1）----
    # 同一 "IP+用户名" 连续失败 LOGIN_MAX_FAILURES 次后锁定 LOGIN_LOCKOUT_SECONDS 秒。
    LOGIN_MAX_FAILURES: int = 5
    LOGIN_LOCKOUT_SECONDS: int = 300
    # 登录限流后端：auto（Redis 可达则用 Redis，否则进程内）/ redis（不可用即报错）/ memory
    RATE_LIMIT_BACKEND: str = "auto"

    # FFmpeg
    FFMPEG_PATH: str = "ffmpeg"
    FFPROBE_PATH: str = "ffprobe"

    # 渲染并发度（并行生成视频片段的上限，避免触发 API 限流）
    RENDER_CONCURRENCY: int = 3

    # CORS
    CORS_ORIGINS: list = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # 认证 Cookie（httpOnly 会话；生产 https 下必须置 True，见 __init__ 校验）
    COOKIE_SECURE: bool = False

    # 日志
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._validate_runtime_secrets()

    def _validate_runtime_secrets(self) -> None:
        """T0 加固：密钥不合法直接拒绝启动（fail closed），不再静默降级。

        背景：旧实现在非 production 下对空 SECRET_KEY 生成随机值，
        而 .env 里写死的是与 .env.example 完全相同的占位串，
        结果任何人都能用公开的占位密钥签发管理员 Token（已实测成功）。
        """
        env = (self.ENVIRONMENT or "development").strip().lower()
        key = (self.SECRET_KEY or "").strip()

        if env in {"test", "testing"} and not key:
            self.SECRET_KEY = secrets.token_hex(32)
            return

        if not key or key.lower() in _PLACEHOLDER_SECRETS or key.lower().startswith("change-me"):
            raise RuntimeError(
                "SECRET_KEY 未配置或仍为占位值（当前：%s）。拒绝启动。\n"
                "占位密钥等同于公开密钥，可用于伪造任意用户 Token。\n"
                "生成：python -c \"import secrets; print(secrets.token_hex(32))\"\n"
                "轮换后所有已签发 Token 失效，属于预期行为。"
                % ("<空>" if not key else repr(key))
            )
        if len(key) < 32:
            raise RuntimeError(
                "SECRET_KEY 长度不足 32 字符（当前 %d），拒绝启动。" % len(key)
            )
        if env == "production":
            if self.DEBUG:
                raise RuntimeError("生产环境 DEBUG 必须为 false。")
            if not self.COOKIE_SECURE:
                raise RuntimeError("生产环境必须设置 COOKIE_SECURE=true（会话 Cookie 需走 HTTPS）。")


settings = Settings()
