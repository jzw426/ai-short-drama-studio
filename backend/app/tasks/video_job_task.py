"""AI 视频作业推进（M4-3）：把「提交 → 轮询 → 转存」拆成可重试的独立任务。

为什么不在渲染任务里同步等（旧 render_service._pick_source → generate_video）：
视频 provider 是异步任务制，单条片段要轮询 5 分钟（60 次 × 5s）。一个 30 镜的
分镜有 3 个并发渲染槽，等于把 Celery worker 泡在付费生成里：进度条 8% 卡死、
RENDER_TIMEOUT 直接掀桌、某个镜头失败只能整条重渲、还取消不掉。

现在每次 Celery 调用只推进一小步（提交 或 查一次状态），processing 时
self.retry(countdown=5)。作业状态全部落在 ai_video_jobs 表里，所以 worker 重启、
任务重投、多 worker 并发都不会丢进度；单条作业失败/取消也只影响自己。
"""
import asyncio
import logging
import uuid
from datetime import timedelta
from typing import Optional

from celery import shared_task
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.media_urls import signed_media_url
from app.core.time_utils import utc_now
from app.models.storyboard import Shot
from app.models.video_job import AIVideoJob
from app.services.ai_service import AIUnavailableError, VideoCapabilityError, ai_service
from app.tasks.celery_app import celery_app
from app.services.storage_service import persist_remote_media

logger = logging.getLogger(__name__)

# 轮询节奏：5 秒一次，最多 180 次（15 分钟）——足够 18s 长片出片，
# 也远小于 provider 侧的排队上限，超时就是真超时。
POLL_INTERVAL_SECONDS = 5
MAX_POLLS = 180
# 这些状态不会再推进；写任何终态前都要再确认一次，避免覆盖用户刚下的 cancelled
TERMINAL_STATUSES = ("completed", "failed", "timeout", "cancelled")
# 首帧图给 provider 的签名有效期：worker 提交时签，provider 之后几分钟内抓取
PROVIDER_IMAGE_URL_TTL = 6 * 3600

# worker 里每个任务都是 asyncio.run()，是独立事件循环；池化连接跨循环复用会报
# "got Future attached to a different loop"，所以必须 NullPool（同 render_task.py:39-42）
celery_engine = create_async_engine(
    settings.DATABASE_URL, echo=False, poolclass=NullPool
)
celery_async_session = async_sessionmaker(
    celery_engine, class_=AsyncSession, expire_on_commit=False
)
# 单测直接替换这个工厂，不用为了一个用例去连真实 worker 库
_session_factory = celery_async_session


def _append_warning(job: AIVideoJob, message: str) -> None:
    existing = (job.warnings or "").strip()
    job.warnings = "\n".join([part for part in (existing, message) if part])[:4000]


def _summarize_raw(raw) -> str:
    """把 provider 的失败响应压成一行可读原因（原始响应可能几百 KB）。"""
    if not isinstance(raw, dict):
        return str(raw)[:500]
    for key in ("error", "message", "detail", "fail_reason", "reason"):
        value = raw.get(key)
        if value:
            return str(value)[:500]
    keys = list(raw.keys())[:6]
    return str({key: raw[key] for key in keys})[:500]


async def _provider_image_url(image_url: Optional[str]) -> Optional[str]:
    """把库里存的首帧图换成 provider 抓得到的地址。

    provider 是外部服务，抓不到 localhost 相对路径或私有桶，所以优先给长 TTL 的
    签名地址；若签名结果仍是相对路径（local 存储且没配 MINIO_PUBLIC_ENDPOINT），
    退回库里原值——把地址交给公网可达部署去处理，**绝不静默当成"没有图"**，
    否则图生视频会退化成文生视频但用户看不出来。
    """
    if not image_url:
        return None
    try:
        url = await signed_media_url(image_url, ttl=PROVIDER_IMAGE_URL_TTL)
    except Exception as e:  # noqa: BLE001 - 签名失败不该阻断生成
        logger.warning("[AIVideoJob] 首帧图签名失败，改用原地址: %s", e)
        return image_url
    if url and (url.startswith("http://") or url.startswith("https://")):
        return url
    return image_url


async def _finalize(
    session: AsyncSession,
    job: AIVideoJob,
    status: str,
    error: Optional[str] = None,
) -> bool:
    """写终态，但先回读一次库：用户可能刚取消（revoke 不可靠，协作式取消）。

    返回 False 表示作业已经不在活跃状态，调用方应停止推进（不要覆盖 cancelled）。
    """
    await session.refresh(job)
    if job.status in TERMINAL_STATUSES:
        return False
    job.status = status
    job.error = error[:1024] if error else None
    await session.commit()
    return True


async def _defer(session: AsyncSession, job: AIVideoJob, message: str) -> str:
    """暂时性失败（网络/冷却/额度）：不判死，计数后等下一次重试。"""
    job.poll_count = (job.poll_count or 0) + 1
    if job.poll_count >= MAX_POLLS:
        if await _finalize(
            session,
            job,
            "timeout",
            f"{message}（已尝试 {job.poll_count} 次，约 "
            f"{MAX_POLLS * POLL_INTERVAL_SECONDS // 60} 分钟）",
        ):
            return "failed"
        return "skipped"
    # 还没拿 task_id 说明仍在提交阶段，状态留在 pending
    job.status = "polling" if job.provider_task_id else "pending"
    job.next_poll_at = utc_now() + timedelta(seconds=POLL_INTERVAL_SECONDS)
    await session.commit()
    return "processing"


async def _submit(session: AsyncSession, job: AIVideoJob) -> str:
    """pending → 向 provider 提交一次，拿到 task_id 后转 submitted。"""
    image_url = await _provider_image_url(job.image_url)
    try:
        submitted = await ai_service.submit_video(
            job.prompt or "",
            image_url=image_url,
            duration=job.duration or 5.0,
            project_id=job.project_id,
        )
    except VideoCapabilityError as e:
        # 能力/配置问题，重试一万次也不会好：直接判死，并把修复方向写进 error
        if await _finalize(session, job, "failed", str(e)):
            return "failed"
        return "skipped"
    except AIUnavailableError as e:
        # 冷却期/网络/额度：作业留在 pending，外层重试再提交，别把付费作业判死
        return await _defer(session, job, f"提交视频任务失败: {e}")

    job.provider = submitted["provider"]
    job.model = submitted.get("model") or ""
    job.provider_task_id = submitted["task_id"]
    job.status = "submitted"
    job.poll_count = 0
    job.next_poll_at = utc_now() + timedelta(seconds=POLL_INTERVAL_SECONDS)
    job.error = None
    await session.commit()
    return "processing"


async def _poll(session: AsyncSession, job: AIVideoJob) -> str:
    """submitted/polling → 查一次 provider 状态。"""
    if not job.provider or not job.provider_task_id:
        # submitted/polling 却没 task_id：数据不一致，空转会永远占着这一行
        if await _finalize(
            session, job, "failed", "作业状态异常：缺少 provider 或 task_id，无法轮询"
        ):
            return "failed"
        return "skipped"
    try:
        polled = await ai_service.poll_video(job.provider, job.provider_task_id)
    except AIUnavailableError as e:
        # 查不到状态 ≠ 生成失败，5 秒后再查；但照样计数，防止 provider 挂死时打转
        return await _defer(session, job, f"轮询视频任务失败: {e}")

    status = polled.get("status")
    if status == "completed":
        return await _complete(session, job, polled.get("video_url"))
    if status == "failed":
        if await _finalize(
            session,
            job,
            "failed",
            _summarize_raw(polled.get("raw")) or "视频 provider 报告生成失败",
        ):
            return "failed"
        return "skipped"

    job.poll_count = (job.poll_count or 0) + 1
    if job.poll_count >= MAX_POLLS:
        if await _finalize(
            session,
            job,
            "timeout",
            f"视频生成超时（已轮询 {job.poll_count} 次，约 "
            f"{MAX_POLLS * POLL_INTERVAL_SECONDS // 60} 分钟）",
        ):
            return "failed"
        return "skipped"
    job.status = "polling"
    job.next_poll_at = utc_now() + timedelta(seconds=POLL_INTERVAL_SECONDS)
    await session.commit()
    return "processing"


async def _complete(session: AsyncSession, job: AIVideoJob, video_url: Optional[str]) -> str:
    """completed → 转存到自有存储，并在镜头没绑素材时回填。"""
    if not video_url:
        if await _finalize(
            session, job, "failed", "视频 provider 报告完成但没有返回可下载的视频地址"
        ):
            return "failed"
        return "skipped"

    canonical = video_url
    try:
        # 转存（M4-1 语义）：provider 给的链接是短 TTL 的，过期就再也取不回来
        canonical = await persist_remote_media(
            video_url, f"ai/videos/{job.project_id}/{uuid.uuid4()}"
        )
    except Exception as e:  # noqa: BLE001 - 转存失败不等于生成失败，降级留痕
        logger.warning("[AIVideoJob] 视频转存失败，降级保留第三方链接: %s", e)
        canonical = video_url
        _append_warning(
            job, f"视频转存自有存储失败，已保留第三方临时链接（会过期）：{e}"[:500]
        )

    await session.refresh(job)
    if job.status in TERMINAL_STATUSES:
        return "skipped"
    job.video_url = canonical
    job.status = "completed"
    job.error = None

    if job.shot_id:
        shot = await session.get(Shot, job.shot_id)
        # 只在镜头还没绑过素材时回填：人工挑选/上传的视频优先级更高，绝不覆盖
        if shot is not None and not (shot.video_url or "").strip():
            shot.video_url = canonical
    await session.commit()
    return "completed"


async def advance_video_job(job_id: str) -> str:
    """推进一条视频作业一步。返回 completed / processing / failed / skipped。

    * skipped：作业不存在，或已是终态（cancelled 等）——什么都不做
    * processing：已提交或还在生成，等 POLL_INTERVAL_SECONDS 后再调一次
    * completed / failed：终态，不再推进
    """
    async with _session_factory() as session:
        job = await session.get(AIVideoJob, job_id)
        if job is None:
            logger.info("[AIVideoJob] %s 不存在（可能已被删除），跳过", job_id)
            return "skipped"
        if job.status in TERMINAL_STATUSES:
            return "skipped"
        if job.status == "pending":
            return await _submit(session, job)
        return await _poll(session, job)


async def _mark_timeout(job_id: str) -> None:
    """Celery 重试次数耗尽时的兜底：别让作业永远停在 polling。"""
    async with _session_factory() as session:
        job = await session.get(AIVideoJob, job_id)
        if job is None or job.status in TERMINAL_STATUSES:
            return
        await _finalize(
            session,
            job,
            "timeout",
            f"视频生成超时（已轮询 {job.poll_count or 0} 次）",
        )


def enqueue_video_job(job_id: str):
    """路由层入队入口（单独成函数，测试里直接替换掉，不碰 broker）。

    为什么用 celery_app.send_task 而不是 advance_video_job_task.delay()：
    路由是在 asyncio.to_thread 里调用它的，而 Celery 的 current_app 只在主线程
    指向我们配置过的 app；在子线程里会落到 Celery 默认 app 上，那里没有
    broker_transport_options —— filesystem broker 下它就去找相对路径 data_in/
    并抛 WinError 3，作业被路由标记成"任务队列不可用"（M4-3 E2E 实测复现）。
    send_task 显式绑定 app，与线程环境无关。
    """
    return celery_app.send_task(
        "app.tasks.video_job_task.advance_video_job", args=[str(job_id)]
    )


@shared_task(bind=True, name="app.tasks.video_job_task.advance_video_job")
def advance_video_job_task(self, job_id: str) -> str:
    """Celery 入口：跑一步推进；还在生成就 5 秒后再来一次。"""
    try:
        result = asyncio.run(advance_video_job(str(job_id)))
    except Exception as e:  # noqa: BLE001 - 未预期异常也要重试，不能丢消息
        logger.exception("[AIVideoJob] %s 推进异常，稍后重试", job_id)
        raise self.retry(
            exc=e, countdown=POLL_INTERVAL_SECONDS, max_retries=MAX_POLLS
        )

    if result == "processing":
        if self.request.retries >= MAX_POLLS:
            # 重试预算耗尽：把作业落到 timeout，别留一条永远 polling 的行
            asyncio.run(_mark_timeout(str(job_id)))
            return "timeout"
        raise self.retry(countdown=POLL_INTERVAL_SECONDS, max_retries=MAX_POLLS)
    return result
