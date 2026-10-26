"""AI 服务：多 provider 路由 + 每次调用的用量/成本记账（M3-4）。

记账口径：
- 每次**逻辑调用**（script/character/storyboard/video）记一条 ai_usage_events；
  provider/model 取"实际服务该次调用的那个"（失败时取最后尝试的那个）。
- 成功/失败/超时都记：成功带 token 与估算成本；失败带 error_kind；
  全部 provider 超时或轮询超时记 status=timeout。
- 记账本身**绝不影响业务**：写库异常由 record_ai_usage_event 捕获后 logger.warning。

响应没有 usage 字段（图片/视频）时 token 记 0，成本按 usage_pricing 的 per_call 估算。
"""
import asyncio
import json
import logging
import time
from typing import List, Optional

import httpx

from app.core.config import settings
from app.core.metrics import metrics
from app.core.usage_pricing import estimate_cost
from app.models.ai_usage import AIUsageEvent

logger = logging.getLogger(__name__)

# ai_usage_events.operation 的合法取值
AI_OPERATIONS = ("script", "character", "storyboard", "video")

# ai_usage_events.status 的合法取值
AI_STATUS_SUCCESS = "success"
AI_STATUS_FAILURE = "failure"
AI_STATUS_TIMEOUT = "timeout"

_OPERATION_MAX = 20
_STATUS_MAX = 16
_ERROR_KIND_MAX = 64
_PROVIDER_MAX = 64
_MODEL_MAX = 128


class AIUnavailableError(RuntimeError):
    """所有 AI provider 均失败，或返回内容不可用。

    调用方必须转成 5xx 明确告知用户；**禁止**用 mock/占位内容假装成功，
    否则用户为假结果付费、前端无法区分真假、排障时无法定位。
    """


def _extract_token_usage(data) -> tuple:
    """从 OpenAI 兼容响应里取 token 用量；没有就返回 (0, 0)。"""
    if not isinstance(data, dict):
        return 0, 0
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return 0, 0

    def _pick(*keys) -> int:
        for key in keys:
            try:
                value = int(usage.get(key) or 0)
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
        return 0

    return _pick("prompt_tokens", "input_tokens"), _pick("completion_tokens", "output_tokens")


def _is_timeout_error(exc: BaseException) -> bool:
    return isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException))


def _error_kind(exc: Optional[BaseException]) -> str:
    """异常 -> error_kind（落库用的错误类型枚举）。"""
    if exc is None:
        return ""
    if isinstance(exc, AIUnavailableError):
        return "ai_unavailable"
    if _is_timeout_error(exc):
        return "timeout"
    return type(exc).__name__[: _ERROR_KIND_MAX]


async def record_ai_usage_event(
    *,
    operation: str,
    status: str,
    provider: str = "",
    model: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    duration_ms: int = 0,
    error_kind: str = "",
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    session=None,
    session_factory=None,
) -> Optional[AIUsageEvent]:
    """写一条 AI 调用明细账。

    设计约束：**任何异常都只 logger.warning，绝不向上抛**——记账是旁路，
    数据库抖动/迁移未跑/表不存在都不能让一次已经付过费的 AI 调用失败。

    参数：
    - session：已有的 AsyncSession（调用方事务内复用，测试可直接注入内存库）
    - session_factory：无 session 时用来开独立会话；默认全局 async_session
    """
    operation = (str(operation or "").strip() or "unknown")[: _OPERATION_MAX]
    status = (str(status or "").strip() or AI_STATUS_FAILURE)[: _STATUS_MAX]

    # 进程内指标与落库解耦：库挂了也要能看到调用量与失败率
    try:
        metrics.record_ai_call(operation, status)
    except Exception:  # noqa: BLE001 - 指标失败同样不能影响业务
        pass

    try:
        prompt_tokens = max(0, int(prompt_tokens or 0))
        completion_tokens = max(0, int(completion_tokens or 0))
        duration_ms = max(0, int(duration_ms or 0))
        cost = estimate_cost(
            provider,
            model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            operation=operation,
        )
        event = AIUsageEvent(
            user_id=(str(user_id) if user_id else None),
            project_id=(str(project_id) if project_id else None),
            operation=operation,
            provider=str(provider or "")[: _PROVIDER_MAX],
            model=str(model or "")[: _MODEL_MAX],
            status=status,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_ms=duration_ms,
            estimated_cost_usd=cost,
            error_kind=str(error_kind or "")[: _ERROR_KIND_MAX],
        )
        if session is not None:
            session.add(event)
            await session.commit()
            return event

        factory = session_factory
        if factory is None:
            # 延迟导入：避免模块导入期就绑定数据库引擎
            from app.core.database import async_session as factory  # noqa: PLC0415

        async with factory() as own_session:
            own_session.add(event)
            await own_session.commit()
        return event
    except Exception as exc:  # noqa: BLE001 - 记账失败绝不能冒泡到业务
        logger.warning("[AI Usage] 记账失败（忽略，不影响业务）: %s", exc)
        if session is not None:
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass
        return None


class AIService:
    """
    AI 服务封装（多模型路由）
    - 文本生成：provider 链按顺序尝试（默认 agnes-2.0-flash -> 剧本、角色、分镜）
    - 图片生成：provider 链（默认 agnes-image-2.1-flash -> 角色形象、场景图）
    - 视频生成：provider 链（默认 agnes-video-v2.0 -> 视频片段，异步轮询）
    路由规则：每个能力按 settings.AI_*_PROVIDERS 顺序尝试，
    某 provider 失败自动切换下一个；全部失败抛 AIUnavailableError（绝不返回假数据）。
    API Key 申请：https://platform.agnes-ai.com/settings/apiKeys

    记账：每次逻辑调用（M3-4）走 _traced_call，无论成功/失败/超时都落一条
    ai_usage_events；usage_session_factory 供单测注入临时库（生产为 None）。
    """

    # 记账会话工厂：None = 用全局 async_session（生产默认）；测试可注入临时库工厂
    usage_session_factory = None

    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None
        # 熔断状态：{"text:agnes": {"failures": 2, "cooldown_until": 1750000000.0}}
        self._provider_states: dict = {}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=httpx.Timeout(300.0))
        return self._http_client

    def _auth_headers(self, api_key: str) -> dict:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    # ==================== 用量记账（M3-4） ====================

    async def _record_call(
        self,
        operation: str,
        trace: dict,
        started: float,
        status: str,
        error_kind: str = "",
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> None:
        """把一次逻辑调用的结果落成 ai_usage_events 一行。失败只 warning。"""
        duration_ms = int(round((time.perf_counter() - started) * 1000))
        await record_ai_usage_event(
            operation=operation,
            status=status,
            provider=trace.get("provider", "") or "",
            model=trace.get("model", "") or "",
            prompt_tokens=trace.get("prompt_tokens", 0) or 0,
            completion_tokens=trace.get("completion_tokens", 0) or 0,
            duration_ms=duration_ms,
            error_kind=error_kind,
            user_id=user_id,
            project_id=project_id,
            session_factory=self.usage_session_factory,
        )

    async def _traced_call(
        self,
        operation: str,
        trace: dict,
        func,
        *,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ):
        """统一埋点外壳：成功 / 失败 / 超时三条路径都记一条账。"""
        started = time.perf_counter()
        try:
            result = await func()
        except AIUnavailableError:
            timed_out = bool(trace.get("timed_out"))
            await self._record_call(
                operation,
                trace,
                started,
                AI_STATUS_TIMEOUT if timed_out else AI_STATUS_FAILURE,
                "timeout" if timed_out else "ai_unavailable",
                user_id=user_id,
                project_id=project_id,
            )
            raise
        except (asyncio.TimeoutError, httpx.TimeoutException):
            await self._record_call(
                operation,
                trace,
                started,
                AI_STATUS_TIMEOUT,
                "timeout",
                user_id=user_id,
                project_id=project_id,
            )
            raise
        except Exception as exc:  # noqa: BLE001 - 记完账继续原样抛给调用方
            await self._record_call(
                operation,
                trace,
                started,
                AI_STATUS_FAILURE,
                _error_kind(exc),
                user_id=user_id,
                project_id=project_id,
            )
            raise

        if not result:
            timed_out = bool(trace.get("timed_out"))
            await self._record_call(
                operation,
                trace,
                started,
                AI_STATUS_TIMEOUT if timed_out else AI_STATUS_FAILURE,
                "timeout" if timed_out else "empty_result",
                user_id=user_id,
                project_id=project_id,
            )
        else:
            await self._record_call(
                operation,
                trace,
                started,
                AI_STATUS_SUCCESS,
                user_id=user_id,
                project_id=project_id,
            )
        return result

    # ==================== 熔断状态管理（P3+ 调度优化） ====================

    def _state_key(self, kind: str, name: str) -> str:
        return f"{kind}:{name}"

    def _is_cooling(self, kind: str, name: str) -> bool:
        """是否处于冷却期（连续失败超阈值后临时跳过）"""
        import time as _time

        st = self._provider_states.get(self._state_key(kind, name))
        if not st:
            return False
        return st.get("cooldown_until", 0) > _time.time()

    def _report_failure(self, kind: str, name: str):
        """记录一次失败，达到阈值后进入冷却"""
        import time as _time

        key = self._state_key(kind, name)
        st = self._provider_states.get(key, {"failures": 0, "cooldown_until": 0.0})
        st["failures"] = st.get("failures", 0) + 1
        threshold = settings.AI_PROVIDER_FAILURE_THRESHOLD
        if st["failures"] >= threshold:
            st["cooldown_until"] = _time.time() + settings.AI_PROVIDER_COOLDOWN_SECONDS
            logger.warning(
                "[AI Router] provider '%s'(%s) 连续失败 %s 次，进入 %ss 冷却",
                name,
                kind,
                st["failures"],
                settings.AI_PROVIDER_COOLDOWN_SECONDS,
            )
        self._provider_states[key] = st

    def _report_success(self, kind: str, name: str):
        """一次成功即清零失败计数、解除冷却"""
        self._provider_states.pop(self._state_key(kind, name), None)

    def provider_status(self) -> dict:
        """
        返回当前 provider 链与调度状态（用于展示，Key 脱敏）。
        结构：{"text": [{"name","model","base","configured","cooling"}], "image": [...], "video": [...]}
        """
        import time as _time

        result = {}
        for kind, providers in (
            ("text", settings.AI_TEXT_PROVIDERS),
            ("image", settings.AI_IMAGE_PROVIDERS),
            ("video", settings.AI_VIDEO_PROVIDERS),
        ):
            items = []
            for p in providers:
                name = p.get("name", "unknown")
                st = self._provider_states.get(self._state_key(kind, name))
                cooling = bool(st and st.get("cooldown_until", 0) > _time.time())
                items.append({
                    "name": name,
                    "model": p.get("model", ""),
                    "base": p.get("base", ""),
                    "configured": bool(p.get("api_key")),
                    "cooling": cooling,
                })
            result[kind] = items
        return result

    # ==================== 文本生成（多 provider 路由） ====================

    async def _chat_completions(
        self,
        messages: list,
        max_tokens: int = 2000,
        temperature: float = 0.8,
        response_format: Optional[dict] = None,
        trace: Optional[dict] = None,
    ) -> Optional[str]:
        """
        按 provider 链顺序调用 chat/completions（OpenAI 兼容）。
        返回首个成功 provider 的文本内容；全部失败返回 None（由调用方降级）。

        trace 由调用方传入，用于记账：记录实际服务的 provider/model 与 token 用量、
        是否出现过超时（全部失败时据此区分 timeout / ai_unavailable）。
        """
        client = await self._get_client()
        last_error: Optional[Exception] = None

        for provider in settings.AI_TEXT_PROVIDERS:
            name = provider.get("name", "unknown")
            api_key = provider.get("api_key", "")
            base = provider.get("base", "").rstrip("/")
            model = provider.get("model", "")
            if not api_key:
                logger.info("[AI Router] text provider '%s' 未配置 API Key，跳过", name)
                continue
            if not base or not model:
                logger.info("[AI Router] text provider '%s' 配置不完整，跳过", name)
                continue
            if self._is_cooling("text", name):
                logger.info("[AI Router] text provider '%s' 处于冷却期，跳过", name)
                continue

            payload: dict = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if response_format:
                payload["response_format"] = response_format

            if trace is not None:
                trace["provider"] = name
                trace["model"] = model

            try:
                response = await client.post(
                    f"{base}/chat/completions",
                    headers=self._auth_headers(api_key),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                if trace is not None:
                    prompt_tokens, completion_tokens = _extract_token_usage(data)
                    trace["prompt_tokens"] = prompt_tokens
                    trace["completion_tokens"] = completion_tokens
                self._report_success("text", name)
                logger.info("[AI Router] text provider '%s' 成功 (model=%s)", name, model)
                return content
            except Exception as e:
                last_error = e
                if trace is not None and _is_timeout_error(e):
                    trace["timed_out"] = True
                self._report_failure("text", name)
                logger.warning("[AI Router] text provider '%s' 失败: %s，切换下一个", name, e)

        if last_error:
            logger.warning("[AI Router] 全部文本 provider 失败，最近错误: %s", last_error)
        return None

    async def generate_script(
        self,
        prompt: str,
        context: str = "",
        *,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> str:
        """使用文本 provider 链生成剧本"""
        system_prompt = (
            "你是一位专业的短剧编剧，擅长创作节奏紧凑、情绪饱满的微短剧剧本。"
            "根据用户的需求，生成符合短剧叙事规律的剧本片段。"
            "格式要求：使用场景标题（如【场景1：咖啡厅 - 白天】），"
            "包含对白和简短的动作描写，每场景不超过200字。"
        )
        trace: dict = {}

        async def _call() -> str:
            messages = [{"role": "system", "content": system_prompt}]
            if context:
                messages.append({"role": "user", "content": f"现有剧本的前文：\n{context}\n\n请续写：{prompt}"})
            else:
                messages.append({"role": "user", "content": prompt})

            content = await self._chat_completions(
                messages, max_tokens=2000, temperature=0.8, trace=trace
            )
            if not content or not content.strip():
                logger.warning("[AI Service] script generation failed: 所有文本 provider 均失败")
                raise AIUnavailableError("所有文本 AI provider 均不可用，未生成任何内容")
            return content

        return await self._traced_call(
            "script", trace, _call, user_id=user_id, project_id=project_id
        )

    async def generate_character(
        self,
        description: str,
        *,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> dict:
        """使用文本 provider 链生成角色设定"""
        system_prompt = (
            "你是一位专业的短剧角色设计师。根据用户的描述，生成一个完整的角色设定。"
            "返回 JSON 格式，包含以下字段：name(姓名), role(主角/反派/配角/龙套), "
            "description(外貌与性格描述), voice(声音特征), age(年龄), "
            "gender(male/female/other), traits(特质列表), backstory(背景故事)。"
            "只返回 JSON，不要有任何其他文字。"
        )
        trace: dict = {}

        async def _call() -> dict:
            content = await self._chat_completions(
                [{"role": "system", "content": system_prompt},
                 {"role": "user", "content": description}],
                max_tokens=1000,
                temperature=0.9,
                response_format={"type": "json_object"},
                trace=trace,
            )
            if not content:
                logger.warning("[AI Service] character generation failed: 所有文本 provider 均失败")
                raise AIUnavailableError("所有文本 AI provider 均不可用，未生成角色设定")

            text = content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("\n```", 1)[0]
            try:
                parsed = json.loads(text)
            except (ValueError, TypeError) as e:
                raise AIUnavailableError(f"AI 返回的角色设定不是合法 JSON: {e}") from e
            if not isinstance(parsed, dict) or not str(parsed.get("name") or "").strip():
                raise AIUnavailableError("AI 返回的角色设定缺少 name 字段")
            return parsed

        return await self._traced_call(
            "character", trace, _call, user_id=user_id, project_id=project_id
        )

    async def generate_storyboard(
        self,
        prompt: str,
        *,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> List[dict]:
        """
        使用文本 provider 链将剧本场景转换为分镜镜头列表。
        返回 JSON 列表，每个元素：
        {label, description, duration, camera_angle, transition}
        全部 provider 失败时抛 AIUnavailableError（绝不返回 mock 分镜）。
        """
        system_prompt = (
            "你是一位专业的短剧分镜师。根据给定的剧本场景，将其拆解为合适的镜头列表。"
            "要求：每个场景 1-3 个镜头，镜头描述必须具体到画面动作与构图，"
            "适合直接作为 AI 视频生成的提示词。"
            '只返回 JSON 数组，每个元素包含字段：'
            'label(镜头标题，如"开场全景")、description(详细画面描述，60字内)、'
            'duration(秒数，2-8 的整数)、camera_angle(景别/角度，如"全景"、"中景"、"特写")、'
            'transition(转场，如"硬切"、"淡入")。不要有任何其他文字。'
        )
        trace: dict = {}

        async def _call() -> List[dict]:
            content = await self._chat_completions(
                [{"role": "system", "content": system_prompt},
                 {"role": "user", "content": prompt}],
                max_tokens=1500,
                temperature=0.7,
                response_format={"type": "json_object"},
                trace=trace,
            )
            if not content:
                logger.warning("[AI Service] storyboard generation failed: 所有文本 provider 均失败")
                raise AIUnavailableError("所有文本 AI provider 均不可用，未生成分镜")

            text = content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("\n```", 1)[0]
            try:
                parsed = json.loads(text)
            except (ValueError, TypeError) as e:
                raise AIUnavailableError(f"AI 返回的分镜不是合法 JSON: {e}") from e
            # 兼容 {"shots": [...]} 与直接数组两种返回
            if isinstance(parsed, dict):
                parsed = parsed.get("shots") or parsed.get("data") or []
            if not isinstance(parsed, list):
                raise AIUnavailableError("AI 返回的分镜结构无法识别")

            cleaned = self._sanitize_shots(parsed)
            if not cleaned:
                raise AIUnavailableError("AI 返回的分镜为空")
            return cleaned

        return await self._traced_call(
            "storyboard", trace, _call, user_id=user_id, project_id=project_id
        )

    @staticmethod
    def _sanitize_shots(shots: list) -> List[dict]:
        """清洗 AI 返回的镜头数据，保证字段完整"""
        result = []
        for s in shots:
            if not isinstance(s, dict):
                continue
            duration = int(s.get("duration", 3) or 3)
            duration = max(2, min(8, duration))
            result.append({
                "label": str(s.get("label", "镜头"))[:100],
                "description": str(s.get("description", ""))[:200],
                "duration": duration,
                "camera_angle": str(s.get("camera_angle", "全景"))[:50],
                "transition": str(s.get("transition", "硬切"))[:50],
            })
        return result

    # ==================== 图片生成（多 provider 路由） ====================

    async def _image_generations(
        self, prompt: str, size: str = "1024x1024"
    ) -> List[str]:
        """
        按 provider 链顺序生成图片，返回图片 URL 列表。
        当前实现：agnes（OpenAI 兼容 /images/generations）；
        其他 provider 若配置但未实现，跳过并提示。
        """
        client = await self._get_client()

        for provider in settings.AI_IMAGE_PROVIDERS:
            name = provider.get("name", "unknown")
            api_key = provider.get("api_key", "")
            base = provider.get("base", "").rstrip("/")
            model = provider.get("model", "")
            if not api_key:
                continue
            if name != "agnes":
                logger.info("[AI Router] image provider '%s' 暂未实现，跳过", name)
                continue
            if self._is_cooling("image", name):
                continue
            try:
                response = await client.post(
                    f"{base}/images/generations",
                    headers=self._auth_headers(api_key),
                    json={
                        "model": model,
                        "prompt": prompt,
                        "n": 1,
                        "size": size,
                        "response_format": "url",
                    },
                    timeout=httpx.Timeout(180.0),
                )
                response.raise_for_status()
                data = response.json()
                images = data.get("data", [])
                urls = [img.get("url", "") for img in images if img.get("url")]
                if urls:
                    self._report_success("image", name)
                    logger.info("[AI Router] image provider '%s' 成功 (model=%s)", name, model)
                    return urls
                logger.warning("[AI Router] image provider '%s' 返回空 URL 列表", name)
                self._report_failure("image", name)
            except Exception as e:
                self._report_failure("image", name)
                logger.warning("[AI Router] image provider '%s' 失败: %s，切换下一个", name, e)

        return []

    async def generate_image(self, prompt: str, style: str = "anime-portrait") -> List[str]:
        """使用图片 provider 链生成图片，返回图片 URL 列表"""
        # style 参数保留用于未来风格化扩展
        return await self._image_generations(prompt)

    # ==================== 视频生成（多 provider 路由，异步轮询） ====================

    async def _video_generations(
        self,
        prompt: str,
        image_url: Optional[str] = None,
        duration: float = 5.0,
        trace: Optional[dict] = None,
    ) -> Optional[str]:
        """
        按 provider 链顺序生成视频片段（异步任务，轮询获取结果）。
        当前实现：agnes（提交 /videos + 轮询任务状态）；
        其他 provider 若配置但未实现，跳过并提示。
        """
        client = await self._get_client()

        for provider in settings.AI_VIDEO_PROVIDERS:
            name = provider.get("name", "unknown")
            api_key = provider.get("api_key", "")
            base = provider.get("base", "").rstrip("/")
            model = provider.get("model", "")
            if not api_key:
                continue
            if name != "agnes":
                logger.info("[AI Router] video provider '%s' 暂未实现，跳过", name)
                continue
            if self._is_cooling("video", name):
                continue

            # 根据时长选择合适的 num_frames（必须满足 8n+1 且 <=441）
            duration_to_frames = {
                3: 81,    # ~3.4s
                5: 121,   # ~5.0s
                7: 161,   # ~6.7s
                10: 241,  # ~10.0s
                15: 361,  # ~15.0s
                18: 441,  # ~18.4s
            }
            target_sec = int(duration)
            num_frames = duration_to_frames.get(target_sec, 121)

            payload = {
                "model": model,
                "prompt": prompt,
                "num_frames": num_frames,
                "frame_rate": 24,
            }
            if image_url:
                payload["image"] = image_url

            if trace is not None:
                trace["provider"] = name
                trace["model"] = model

            try:
                # Step 1: 提交生成任务
                submit_resp = await client.post(
                    f"{base}/videos",
                    headers=self._auth_headers(api_key),
                    json=payload,
                    timeout=httpx.Timeout(60.0),
                )
                submit_resp.raise_for_status()
                task_data = submit_resp.json()
                task_id = task_data.get("id") or task_data.get("task_id", "")

                if not task_id:
                    logger.warning("[AI Router] video provider '%s' submit failed: no task_id", name)
                    continue

                # Step 2: 轮询获取结果（最多等待 5 分钟）
                for attempt in range(60):
                    await asyncio.sleep(5)
                    try:
                        poll_resp = await client.get(
                            f"{base}/videos/{task_id}",
                            headers=self._auth_headers(api_key),
                        )
                        poll_resp.raise_for_status()
                        poll_data = poll_resp.json()

                        status = poll_data.get("status", "")
                        if status == "completed":
                            video_url = poll_data.get("remixed_from_video_id") or poll_data.get("video_url", "")
                            if video_url and video_url.startswith("http"):
                                self._report_success("video", name)
                                logger.info("[AI Router] video provider '%s' 成功", name)
                                return video_url
                            self._report_failure("video", name)
                            logger.warning("[AI Router] video provider '%s' completed but no valid URL", name)
                            break
                        elif status == "failed":
                            self._report_failure("video", name)
                            logger.warning("[AI Router] video provider '%s' task failed: %s", name, poll_data)
                            break
                        # else: still processing, continue polling
                    except Exception as e:
                        if trace is not None and _is_timeout_error(e):
                            trace["timed_out"] = True
                        continue

                self._report_failure("video", name)
                if trace is not None:
                    trace["timed_out"] = True
                logger.warning("[AI Router] video provider '%s' timed out", name)
            except Exception as e:
                if trace is not None and _is_timeout_error(e):
                    trace["timed_out"] = True
                self._report_failure("video", name)
                logger.warning("[AI Router] video provider '%s' 失败: %s，切换下一个", name, e)

        return None

    async def generate_video(
        self,
        prompt: str,
        image_url: Optional[str] = None,
        duration: float = 5.0,
        *,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Optional[str]:
        """使用视频 provider 链生成视频片段（文生视频/图生视频）"""
        trace: dict = {}

        async def _call() -> Optional[str]:
            return await self._video_generations(prompt, image_url, duration, trace=trace)

        return await self._traced_call(
            "video", trace, _call, user_id=user_id, project_id=project_id
        )


ai_service = AIService()
