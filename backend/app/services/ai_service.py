import json
import asyncio
import httpx
from typing import List, Optional

from app.core.config import settings


class AIUnavailableError(RuntimeError):
    """所有 AI provider 均失败，或返回内容不可用。

    调用方必须转成 5xx 明确告知用户；**禁止**用 mock/占位内容假装成功，
    否则用户为假结果付费、前端无法区分真假、排障时无法定位。
    """


class AIService:
    """
    AI 服务封装（多模型路由）
    - 文本生成：provider 链按顺序尝试（默认 agnes-2.0-flash → 剧本、角色、分镜）
    - 图片生成：provider 链（默认 agnes-image-2.1-flash → 角色形象、场景图）
    - 视频生成：provider 链（默认 agnes-video-v2.0 → 视频片段，异步轮询）
    路由规则：每个能力按 settings.AI_*_PROVIDERS 顺序尝试，
    某 provider 失败自动切换下一个；全部失败抛 AIUnavailableError（绝不返回假数据）。
    API Key 申请：https://platform.agnes-ai.com/settings/apiKeys
    """

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
            print(f"[AI Router] provider '{name}'({kind}) 连续失败 {st['failures']} 次，"
                  f"进入 {settings.AI_PROVIDER_COOLDOWN_SECONDS}s 冷却")
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
    ) -> Optional[str]:
        """
        按 provider 链顺序调用 chat/completions（OpenAI 兼容）。
        返回首个成功 provider 的文本内容；全部失败返回 None（由调用方降级）。
        """
        client = await self._get_client()
        last_error: Optional[Exception] = None

        for provider in settings.AI_TEXT_PROVIDERS:
            name = provider.get("name", "unknown")
            api_key = provider.get("api_key", "")
            base = provider.get("base", "").rstrip("/")
            model = provider.get("model", "")
            if not api_key:
                print(f"[AI Router] text provider '{name}' 未配置 API Key，跳过")
                continue
            if not base or not model:
                print(f"[AI Router] text provider '{name}' 配置不完整，跳过")
                continue
            if self._is_cooling("text", name):
                print(f"[AI Router] text provider '{name}' 处于冷却期，跳过")
                continue

            payload: dict = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if response_format:
                payload["response_format"] = response_format

            try:
                response = await client.post(
                    f"{base}/chat/completions",
                    headers=self._auth_headers(api_key),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                self._report_success("text", name)
                print(f"[AI Router] text provider '{name}' 成功 (model={model})")
                return content
            except Exception as e:
                last_error = e
                self._report_failure("text", name)
                print(f"[AI Router] text provider '{name}' 失败: {e}，切换下一个")

        if last_error:
            print(f"[AI Router] 全部文本 provider 失败，最近错误: {last_error}")
        return None

    async def generate_script(self, prompt: str, context: str = "") -> str:
        """使用文本 provider 链生成剧本"""
        system_prompt = (
            "你是一位专业的短剧编剧，擅长创作节奏紧凑、情绪饱满的微短剧剧本。"
            "根据用户的需求，生成符合短剧叙事规律的剧本片段。"
            "格式要求：使用场景标题（如【场景1：咖啡厅 - 白天】），"
            "包含对白和简短的动作描写，每场景不超过200字。"
        )

        messages = [{"role": "system", "content": system_prompt}]
        if context:
            messages.append({"role": "user", "content": f"现有剧本的前文：\n{context}\n\n请续写：{prompt}"})
        else:
            messages.append({"role": "user", "content": prompt})

        content = await self._chat_completions(
            messages, max_tokens=2000, temperature=0.8
        )
        if not content or not content.strip():
            print("[AI Service] script generation failed: 所有文本 provider 均失败")
            raise AIUnavailableError("所有文本 AI provider 均不可用，未生成任何内容")
        return content

    async def generate_character(self, description: str) -> dict:
        """使用文本 provider 链生成角色设定"""
        system_prompt = (
            "你是一位专业的短剧角色设计师。根据用户的描述，生成一个完整的角色设定。"
            "返回 JSON 格式，包含以下字段：name(姓名), role(主角/反派/配角/龙套), "
            "description(外貌与性格描述), voice(声音特征), age(年龄), "
            "gender(male/female/other), traits(特质列表), backstory(背景故事)。"
            "只返回 JSON，不要有任何其他文字。"
        )

        content = await self._chat_completions(
            [{"role": "system", "content": system_prompt},
             {"role": "user", "content": description}],
            max_tokens=1000,
            temperature=0.9,
            response_format={"type": "json_object"},
        )
        if not content:
            print("[AI Service] character generation failed: 所有文本 provider 均失败")
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

    async def generate_storyboard(self, prompt: str) -> List[dict]:
        """
        使用文本 provider 链将剧本场景转换为分镜镜头列表。
        返回 JSON 列表，每个元素：
        {label, description, duration, camera_angle, transition}
        全部 provider 失败时返回 mock 分镜。
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

        content = await self._chat_completions(
            [{"role": "system", "content": system_prompt},
             {"role": "user", "content": prompt}],
            max_tokens=1500,
            temperature=0.7,
            response_format={"type": "json_object"},
        )
        if not content:
            print("[AI Service] storyboard generation failed: 所有文本 provider 均失败")
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
                print(f"[AI Router] image provider '{name}' 暂未实现，跳过")
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
                    print(f"[AI Router] image provider '{name}' 成功 (model={model})")
                    return urls
                print(f"[AI Router] image provider '{name}' 返回空 URL 列表")
                self._report_failure("image", name)
            except Exception as e:
                self._report_failure("image", name)
                print(f"[AI Router] image provider '{name}' 失败: {e}，切换下一个")

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
                print(f"[AI Router] video provider '{name}' 暂未实现，跳过")
                continue
            if self._is_cooling("video", name):
                continue

            # 根据时长选择合适的 num_frames（必须满足 8n+1 且 ≤441）
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
                    print(f"[AI Router] video provider '{name}' submit failed: no task_id")
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
                                print(f"[AI Router] video provider '{name}' 成功")
                                return video_url
                            self._report_failure("video", name)
                            print(f"[AI Router] video provider '{name}' completed but no valid URL")
                            break
                        elif status == "failed":
                            self._report_failure("video", name)
                            print(f"[AI Router] video provider '{name}' task failed: {poll_data}")
                            break
                        # else: still processing, continue polling
                    except Exception:
                        continue

                self._report_failure("video", name)
                print(f"[AI Router] video provider '{name}' timed out")
            except Exception as e:
                self._report_failure("video", name)
                print(f"[AI Router] video provider '{name}' 失败: {e}，切换下一个")

        return None

    async def generate_video(
        self,
        prompt: str,
        image_url: Optional[str] = None,
        duration: float = 5.0,
    ) -> Optional[str]:
        """使用视频 provider 链生成视频片段（文生视频/图生视频）"""
        return await self._video_generations(prompt, image_url, duration)


ai_service = AIService()
