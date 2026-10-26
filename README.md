# AI Short Drama Studio

面向AI短剧创作者的一站式工作流平台。从剧本创作到一键成片，全流程AI赋能。

## 核心工作流

```
剧本工坊 → 分镜设计 → 角色管理 → 一键成片 → 素材库
```

| 模块 | 功能 | 核心能力 |
|------|------|---------|
| 剧本工坊 | AI辅助剧本创作 | 多场景编辑、AI续写/改写、对话管理 |
| 分镜设计 | 可视化分镜编排 | Fabric.js 画布、拖拽角色、镜头管理 |
| 角色管理 | AI角色形象生成 | 角色档案、形象图生成、一致性维护 |
| 一键成片 | 全网素材合成渲染 | 异步任务队列、进度追踪、视频预览 |
| 素材库 | 统一素材管理中心 | 本地/MinIO 存储、分类标签、上传/检索 |

## 技术栈

### 前端
- **框架**：Next.js 14 (App Router) + TypeScript
- **样式**：Tailwind CSS
- **画布**：Fabric.js（分镜编辑器）
- **状态管理**：Zustand
- **数据请求**：Axios（带 JWT 拦截器 + 401 自动跳转登录）

### 后端
- **框架**：FastAPI (Python 3.12)
- **数据库**：SQLite（默认，开箱即用）/ PostgreSQL（可选）+ SQLAlchemy 2.0 (async)
- **迁移**：Alembic（含 baseline 迁移，新库 `alembic upgrade head` 即可建表）
- **缓存/队列**：Redis + Celery（broker 不可达时任务快速失败，不阻塞接口）
- **认证**：JWT（PyJWT, HS256, 7 天有效期）+ PBKDF2-SHA256 密码哈希；业务路由全部要求登录；登录同时下发 **httpOnly Cookie**（前端以 Cookie 为会话主通道，Token 不再存入 localStorage，XSS 不可窃取；`POST /auth/logout` 清除会话）
- **存储**：本地文件（默认）/ MinIO（可选）；删除项目/素材时**物理同步清理文件与空目录**（不再残留孤儿文件）
  - 媒体一律**受控访问**：本地模式下 `/uploads/*` 需要「有效 HMAC 签名」或「登录 + 项目归属」，MinIO 模式下桶为**私有**、链接一律预签名（TTL 见 `MEDIA_URL_TTL_SECONDS`）。数据库只存规范 URL，签名在响应阶段生成，所以链接会过期、旧链接泄露不等于永久泄露。
  - 切 MinIO 时注意 `MINIO_PUBLIC_ENDPOINT`：SigV4 签名覆盖 Host 头，签名用的主机名必须是浏览器实际访问的主机名（容器内 `minio:9000` 浏览器解析不了），否则预签名链接 403。
- **视频处理**：FFmpeg（拼接前统一转码 H.264/yuv420p/24fps，避免编码不一致花屏）

### AI 能力（Agnes AI 全免费一站式）
| API | 用途 |
|-----|------|
| agnes-2.0-flash | 剧本智能创作、角色生成（OpenAI 兼容 chat/completions） |
| agnes-image-2.1-flash | 角色形象图、场景图生成 |
| agnes-video-v2.0 | 视频片段生成（异步轮询） |

> API Key 申请：https://platform.agnes-ai.com/settings/apiKeys（免费）

## 快速启动（本地开发，推荐）

### 环境要求

- Python 3.12+
- Node.js 18+
- FFmpeg（`ffmpeg -version` 可用即可）
- Redis（仅渲染任务队列需要；无 Redis 时提交渲染任务会快速失败并标记原因，其他功能不受影响）

### 1. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入 AGNES_API_KEY（可选，不填则 AI 功能降级为报错提示）
```

### 2. 启动后端

```bash
cd backend
python -m venv venv
venv\Scripts\activate            # Windows
source venv/bin/activate         # macOS/Linux
pip install -r requirements.txt
alembic upgrade head             # 初始化数据库（已有 app.db 则自动跳过）
uvicorn app.main:app --reload --port 8000
```

后端文档：http://localhost:8000/docs

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

访问 http://localhost:3000 ，注册账号后即可使用。

### 4. Celery Worker（渲染任务需要）

```bash
cd backend
celery -A app.tasks.celery_app worker --loglevel=info --pool=solo
```

## 运行测试

```bash
cd backend
venv\Scripts\python -m pytest tests -q        # 单元测试
venv\Scripts\python scripts\verify_p0_fix.py   # 渲染链路回归
venv\Scripts\python scripts\verify_p0_auth.py  # 认证+上传回归
venv\Scripts\python scripts\verify_p3_features.py  # P3 回归（多模型路由/监控指标/用户配额）
```

## P3 商业化进阶（v0.2）

- **多模型路由**：文本/图片/视频三类能力均支持 provider 链配置（AI_TEXT_PROVIDERS_RAW / AI_IMAGE_PROVIDERS_RAW / AI_VIDEO_PROVIDERS_RAW，JSON 数组），按顺序尝试、失败自动切换，全部失败才降级 mock。默认链仅含 Agnes（免费一站式）；DeepSeek/Gemini 等 OpenAI 兼容接口可通过 .env 追加，无需改代码
- **监控指标**：新增 GET /api/v1/metrics（请求总数/在途/5xx/4xx/平均耗时/按状态码/TOP 路径）；所有业务请求输出结构化 JSON 日志（方法/路径/状态/耗时/用户）
- **增强健康检查**：GET /api/v1/health 现含数据库连通、存储磁盘剩余、Redis 状态（不可达仅提示不降级）、运行时长
- **用户 AI 配额**：新增 ai_usage 表（每用户每日计数，Alembic 迁移 cef2afd76e33），AI_DAILY_QUOTA=100 可配；剧本/分镜/角色生成类接口超限返回 429 并提示剩余额度

## AI 模型调度（v0.2）

- **当前实际调度**：Agnes（文本 agnes-2.0-flash / 图片 agnes-image-2.1-flash / 视频 agnes-video-v2.0），Key 已配置即自动纳入调度链
- **自动收集**：文本链默认自动包含所有已配置 Key 的 OpenAI 兼容 provider（agnes → deepseek → gemini），配哪个 Key 就自动启用，未配置自动跳过；图片/视频默认仅 Agnes（其余家协议待实现）
- **失败熔断**：provider 连续失败 `AI_PROVIDER_FAILURE_THRESHOLD=3` 次后进入 `AI_PROVIDER_COOLDOWN_SECONDS=60` 秒冷却，冷却期内跳过，成功一次即恢复——避免反复超时拖慢整条链路
- **调度清单**：`GET /api/v1/ai/providers`（需登录）返回三类能力的 provider 链、模型名、端点、是否已配置/是否冷却中（Key 已脱敏），用于确认当前实际调度哪些大模型
- **扩展新模型**：文本类在 `.env` 配置 `DEEPSEEK_API_KEY` / `GEMINI_API_KEY`（或通过 `AI_TEXT_PROVIDERS_RAW` 以 JSON 数组自定义任意 OpenAI 兼容 provider）即可，无需改代码

## P2 功能增强（v0.2）

- **项目归属隔离**：所有业务路由（项目/剧本/分镜/角色/素材/渲染）按登录用户隔离，访问他人资源一律 404；新建项目自动写入 owner_id
- **剧本→分镜一键生成**：`POST /projects/{id}/storyboard/generate-from-script` 按剧本场景逐场景 AI 生成镜头并批量入库（替换旧镜头）
- **角色形象追加生成**：`POST /projects/{id}/characters/{cid}/generate-image` 基于角色设定生成形象图，追加进 generated_images
- **并行渲染**：同一渲染任务的视频片段并发生成（`RENDER_CONCURRENCY=3`，可配置），显著缩短成片时间
- **导出能力**：剧本导出 `GET /projects/{id}/script/export?format=markdown|txt`（附件下载）、分镜导出 `GET /projects/{id}/storyboard/export?format=json`
- **前端联动**：首页展示真实项目列表、新建项目入口；分镜页「从剧本生成分镜」、剧本页「导出 Markdown」按钮；API 客户端已暴露全部新接口
- **分镜编辑器（完整可用）**：`StoryboardCanvas` 三栏式编辑器（工具栏 / 画布 / 属性面板 + 图层列表），fabric@5 客户端动态加载（webpack CJS interop 自动解包 `m.fabric ?? m.default.fabric`，规避服务端构建期 node-canvas/jsdom 依赖）；支持添加文字/场景框/圆形/箭头/上传图片、缩放平移（空格+拖拽）、双击编辑、属性实时编辑、图层排序、撤销/重做（操作前同步 `storyboardCanvasState` 保证 redo 栈可用）、保存画布 / 导出 PNG；画布状态自动持久化（防抖 800ms 自动 PUT 至后端 `canvas_state`，进入页面自动恢复；添加/删除/拖拽/属性编辑/撤销重做均触发保存，控制条显示 保存中/已自动保存/保存失败）

## 项目结构

```
ai-short-drama-studio/
├── .env.example              # 环境变量模板
├── README.md
├── frontend/                 # Next.js 14 前端
│   ├── src/
│   │   ├── app/              # App Router 页面（含 /login）
│   │   ├── components/       # 通用组件（AppShell 路由守卫）
│   │   ├── lib/              # API 客户端 / auth 工具
│   │   ├── types/            # TypeScript 类型
│   │   └── store/            # Zustand 状态
│   ├── package.json
│   └── next.config.js
├── backend/                  # FastAPI 后端
│   ├── app/
│   │   ├── api/routes/       # API 路由（业务路由均需认证）
│   │   ├── models/           # ORM 模型
│   │   ├── schemas/          # Pydantic Schema
│   │   ├── services/         # 业务逻辑（渲染/存储/AI）
│   │   ├── tasks/            # Celery 任务
│   │   └── core/             # 配置/安全/时间工具
│   ├── alembic/              # 数据库迁移
│   ├── tests/                # pytest 单元测试
│   ├── scripts/              # 回归验证脚本
│   └── requirements.txt
└── docker-compose.yml        # 可选：PostgreSQL/Redis/MinIO 服务编排
```

## 认证说明

- 注册：`POST /api/v1/auth/register`（username/email/password/display_name）
- 登录：`POST /api/v1/auth/login` → 返回 `access_token`
- 请求头：`Authorization: Bearer <token>`
- 未登录访问业务接口返回 401；前端自动跳转 /login
- 上传白名单：图片/音频/视频共 15 种扩展名 + MIME 双校验，单文件上限 500MB

## License

MIT License
