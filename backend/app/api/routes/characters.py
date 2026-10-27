import logging
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.media_urls import signed_media_url
from app.models.character import Character
from app.models.project import Project
from app.models.user import User
from app.schemas.character import (
    CharacterCreate, CharacterUpdate, CharacterResponse,
    AIGenerateCharacterRequest, GenerateViewsRequest, LockFaceRequest,
)
from app.services.ai_service import (
    AIUnavailableError,
    ImageCapabilityError,
    ai_service,
)
from app.services.storage_service import extract_object_name, persist_remote_media
from app.core.quota import acquire_ai_quota_or_429, refund_ai_quota_and_commit

router = APIRouter(tags=["Characters"])
logger = logging.getLogger(__name__)


async def _to_response(character: Character) -> CharacterResponse:
    """ORM → 响应模型，媒体链接（头像/形象图）在此签名，数据库只存规范 URL。

    M1：MinIO 模式下这里生成的是预签名 URL（桶已私有），所以必须 await。
    """
    resp = CharacterResponse.model_validate(character)
    resp.avatar_url = await signed_media_url(resp.avatar_url)
    resp.reference_image_url = await signed_media_url(resp.reference_image_url)
    signed_images = [
        await signed_media_url(x) for x in (resp.generated_images or [])
    ]
    resp.generated_images = [u for u in signed_images if u]
    signed_views = {}
    for key, url in (character.view_images or {}).items():
        signed = await signed_media_url(url)
        if signed:
            signed_views[key] = signed
    resp.view_images = signed_views
    return resp


async def _persist_images(image_urls: List[str], project_id: str) -> List[str]:
    """把 AI 出图的第三方链接转存到我们自己的存储（M4-1）。

    provider 的链接带 TTL，写进库第二天就 403；转存失败时不阻塞业务，
    回退成原链接并留 warning —— 素材没了总比角色设定一起丢掉好。
    """
    if not image_urls:
        return []
    persisted: List[str] = []
    for url in image_urls:
        try:
            persisted.append(
                await persist_remote_media(url, f"ai/images/{project_id}/{uuid.uuid4()}")
            )
        except Exception as exc:  # noqa: BLE001 - 单张失败不能拖垮整次生成
            logger.warning("AI 图片转存失败，回退第三方链接: %s (%s)", url[:120], exc)
            persisted.append(url)
    return persisted

# ---- M4-2 角色一致性：锁脸与三视图 ----

# 只允许这几个视角，前端传任意字符串会被拒绝（不能让它拼进 prompt 污染形象）
VIEW_PROMPTS = {
    "front": "front view, full body, facing camera, neutral expression",
    "side": "side profile view, full body, neutral pose",
    "full": "full body character sheet, standing, neutral pose",
    "back": "back view, full body, neutral pose",
}


def _default_visual_prompt(
    name: str, gender: str, age: int, traits: List[str], description: str
) -> str:
    """把角色设定压成可复用的外观描述。

    为什么不用 description 直接拼：description 是"人物小传"（性格/欲望/关系），
    里面没有外观约束；每镜直接拼它，同一角色会随机换发型/换衣服。这里只保留
    外观锚点，并要求"与参考图保持一致"，让锁脸真正起作用。
    """
    parts = [f"角色 {name}", f"{gender}", f"{age}岁" if age else "", "与参考图同一角色"]
    if traits:
        parts.append("性格外化：" + "、".join(str(t) for t in traits[:5]))
    if description:
        parts.append("外形要点：" + description[:200])
    parts.append("固定发型、固定服装配色、固定体型，动漫漫剧风格")
    return "；".join(p for p in parts if p)


async def _lock_face_or_error(
    project_id: str, character: Character, source_url: str
) -> str:
    """把锁脸基准图落到我们自己的存储，返回规范 URL。"""
    if extract_object_name(source_url):
        return source_url
    return await persist_remote_media(
        source_url, f"ai/characters/{project_id}/{character.id}/reference"
    )


async def _generate_image_checked(
    *,
    prompt: str,
    reference_image_url: Optional[str],
    seed: Optional[int],
    user_id: str,
    project_id: str,
) -> List[str]:
    """出图 + 配额语义：失败必须退配额，能力不支持必须 501。"""
    try:
        return await ai_service.generate_image(
            prompt=prompt,
            reference_image_url=reference_image_url,
            seed=seed,
            user_id=user_id,
            project_id=project_id,
        )
    except ImageCapabilityError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except AIUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"AI 出图失败：{exc}") from exc



async def _get_project_or_404(
    project_id: str, owner_id: str, db: AsyncSession
) -> Project:
    from sqlalchemy import select

    result = await db.execute(
        select(Project).where(
            Project.id == project_id, Project.owner_id == owner_id
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@router.get("/projects/{project_id}/characters", response_model=List[CharacterResponse])
async def list_characters(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取项目所有角色"""
    from sqlalchemy import select

    await _get_project_or_404(project_id, current_user.id, db)
    result = await db.execute(
        select(Character)
        .where(Character.project_id == project_id)
        .order_by(Character.created_at.desc())
    )
    return [await _to_response(c) for c in result.scalars().all()]


@router.post("/projects/{project_id}/characters", response_model=CharacterResponse, status_code=201)
async def create_character(
    project_id: str,
    data: CharacterCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建角色"""
    await _get_project_or_404(project_id, current_user.id, db)

    character = Character(
        project_id=project_id,
        name=data.name,
        role=data.role,
        description=data.description,
        voice=data.voice,
        age=data.age,
        gender=data.gender,
        traits=data.traits,
        backstory=data.backstory,
    )
    db.add(character)
    await db.flush()
    await db.refresh(character)
    return await _to_response(character)


@router.put("/projects/{project_id}/characters/{character_id}", response_model=CharacterResponse)
async def update_character(
    project_id: str,
    character_id: str,
    data: CharacterUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新角色信息"""
    from sqlalchemy import select

    await _get_project_or_404(project_id, current_user.id, db)
    result = await db.execute(
        select(Character).where(
            Character.id == character_id,
            Character.project_id == project_id,
        )
    )
    character = result.scalar_one_or_none()
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(character, key, value)

    await db.flush()
    await db.refresh(character)
    return await _to_response(character)


@router.delete("/projects/{project_id}/characters/{character_id}", status_code=204)
async def delete_character(
    project_id: str,
    character_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除角色"""
    from sqlalchemy import select

    await _get_project_or_404(project_id, current_user.id, db)
    result = await db.execute(
        select(Character).where(
            Character.id == character_id,
            Character.project_id == project_id,
        )
    )
    character = result.scalar_one_or_none()
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")

    await db.delete(character)
    await db.flush()
    return None


@router.post("/projects/{project_id}/characters/ai-generate", response_model=CharacterResponse)
async def ai_generate_character(
    project_id: str,
    request: AIGenerateCharacterRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI 生成角色形象（生成角色描述 + 形象图，受每日配额限制）

    配额先占后用：AI 失败退回；AI 全失败返回 503，绝不返回伪造的角色设定。
    """
    from sqlalchemy import select

    await _get_project_or_404(project_id, current_user.id, db)
    await acquire_ai_quota_or_429(db, current_user.id)

    # AI 生成角色描述
    try:
        char_info = await ai_service.generate_character(
            description=request.description,
            user_id=current_user.id,
            project_id=project_id,
        )
    except AIUnavailableError as e:
        await refund_ai_quota_and_commit(db, current_user.id)
        raise HTTPException(status_code=503, detail=f"AI 角色生成失败：{e}") from e

    # 生成角色形象图（失败不影响角色设定落库，前端可稍后单独重试）
    try:
        image_urls = await ai_service.generate_image(
            prompt=f"Character portrait: {char_info.get('name', '')} - {char_info.get('description', request.description)}",
            style="anime-portrait",
            user_id=current_user.id,
            project_id=project_id,
        )
    except AIUnavailableError as exc:  # 形象图失败不影响角色设定落库，但要说清楚
        logger.warning("AI 形象图生成失败（角色设定仍落库，可稍后重试）: %s", exc)
        image_urls = []
    image_urls = await _persist_images(image_urls, project_id)

    # 首次出图即自动锁脸：把这张图、种子、外观描述固化成角色卡，
    # 后续所有形象图/三视图都以它为基准，避免每镜换人。
    auto_seed = secrets.randbelow(2**32) if image_urls else None
    visual_prompt = _default_visual_prompt(
        name=str(char_info.get("name", "")),
        gender=str(char_info.get("gender", "other")),
        age=int(char_info.get("age", 0) or 0),
        traits=list(char_info.get("traits") or []),
        description=str(char_info.get("description", request.description)),
    )

    character = Character(
        project_id=project_id,
        name=str(char_info["name"])[:255],
        role=char_info.get("role", "supporting"),
        description=char_info.get("description", request.description),
        voice=char_info.get("voice", ""),
        age=char_info.get("age", 0),
        gender=char_info.get("gender", "other"),
        traits=char_info.get("traits", []),
        backstory=char_info.get("backstory", ""),
        avatar_url=image_urls[0] if image_urls else None,
        generated_images=image_urls,
        reference_image_url=image_urls[0] if image_urls else None,
        image_seed=auto_seed,
        visual_prompt=visual_prompt,
        view_images={},
    )
    db.add(character)
    await db.flush()
    await db.refresh(character)
    return await _to_response(character)


@router.post("/projects/{project_id}/characters/{character_id}/generate-image", response_model=CharacterResponse)
async def generate_character_image(
    project_id: str,
    character_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """为已有角色生成/追加形象图（锁脸后走图生图，受每日配额限制）。"""
    from sqlalchemy import select

    await _get_project_or_404(project_id, current_user.id, db)
    result = await db.execute(
        select(Character).where(
            Character.id == character_id,
            Character.project_id == project_id,
        )
    )
    character = result.scalar_one_or_none()
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")

    # 有锁脸基准图就带参考图 + seed + 固化外观描述；没有才退回文生图
    locked = bool(character.reference_image_url)
    prompt = (character.visual_prompt or "").strip() if locked else ""
    if not prompt:
        prompt = (
            f"Character portrait: {character.name} - {character.description}"
            f" (性别: {character.gender}, 年龄: {character.age}, 性格: {', '.join(character.traits or [])})"
        )

    await acquire_ai_quota_or_429(db, current_user.id)
    try:
        image_urls = await _generate_image_checked(
            prompt=prompt,
            reference_image_url=character.reference_image_url if locked else None,
            seed=character.image_seed if locked else None,
            user_id=current_user.id,
            project_id=project_id,
        )
    except HTTPException:
        await refund_ai_quota_and_commit(db, current_user.id)
        raise
    except Exception as exc:  # noqa: BLE001
        await refund_ai_quota_and_commit(db, current_user.id)
        raise HTTPException(status_code=503, detail=f"AI 形象生成失败：{exc}") from exc

    image_urls = await _persist_images(image_urls, project_id)
    if not image_urls:
        await refund_ai_quota_and_commit(db, current_user.id)
        raise HTTPException(
            status_code=503,
            detail="AI 形象生成失败：未获得任何图片（请检查 AGNES_API_KEY 或 provider 状态）",
        )

    # 未锁脸的旧角色：首次成功出图后自动锁脸，后续才有基准可依
    if not locked:
        character.reference_image_url = image_urls[0]
        if character.image_seed is None:
            character.image_seed = secrets.randbelow(2**32)
        character.visual_prompt = character.visual_prompt or _default_visual_prompt(
            name=character.name,
            gender=character.gender or "other",
            age=int(character.age or 0),
            traits=list(character.traits or []),
            description=character.description or "",
        )

    # 追加到形象库，并同步头像（无头像时）
    existing = list(character.generated_images or [])
    existing.extend(image_urls)
    character.generated_images = existing
    if not character.avatar_url:
        character.avatar_url = image_urls[0]

    await db.flush()
    await db.refresh(character)
    return await _to_response(character)


@router.post(
    "/projects/{project_id}/characters/{character_id}/lock-face",
    response_model=CharacterResponse,
)
async def lock_character_face(
    project_id: str,
    character_id: str,
    request: LockFaceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """锁定角色脸：基准图 + 固定 seed + 固化外观描述（不调用 AI，不占配额）。

    锁脸之后，生成形象图/三视图都会带 reference_image_url 走图生图；provider
    不支持时明确 501，而不是悄悄换一张脸。
    """
    from sqlalchemy import select

    await _get_project_or_404(project_id, current_user.id, db)
    result = await db.execute(
        select(Character).where(
            Character.id == character_id,
            Character.project_id == project_id,
        )
    )
    character = result.scalar_one_or_none()
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")

    source = (request.source_url or character.avatar_url or "").strip()
    if not source:
        raise HTTPException(
            status_code=400,
            detail="没有可用的基准图：请先生成一张形象图，或在请求里提供 source_url",
        )
    try:
        character.reference_image_url = await _lock_face_or_error(
            project_id, character, source
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"基准图转存失败：{exc}") from exc

    if request.seed is not None:
        character.image_seed = int(request.seed)
    elif character.image_seed is None:
        character.image_seed = secrets.randbelow(2**32)

    character.visual_prompt = (
        (request.visual_prompt or character.visual_prompt or "").strip()
        or _default_visual_prompt(
            name=character.name,
            gender=character.gender or "other",
            age=int(character.age or 0),
            traits=list(character.traits or []),
            description=character.description or "",
        )
    )

    await db.flush()
    await db.refresh(character)
    return await _to_response(character)


@router.post(
    "/projects/{project_id}/characters/{character_id}/views",
    response_model=CharacterResponse,
)
async def generate_character_views(
    project_id: str,
    character_id: str,
    request: GenerateViewsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """生成角色三视图（front/side/full/back 的任意子集，逐张占配额）。

    必须先锁脸：没有基准图的三视图没有一致性意义，直接 400 而不是浪费用户的钱。
    单张失败退该张配额并继续其余视角；全部失败才 503。
    """
    from sqlalchemy import select

    await _get_project_or_404(project_id, current_user.id, db)
    result = await db.execute(
        select(Character).where(
            Character.id == character_id,
            Character.project_id == project_id,
        )
    )
    character = result.scalar_one_or_none()
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")

    if not character.reference_image_url:
        raise HTTPException(
            status_code=400,
            detail="请先锁脸（POST /lock-face）：没有基准图的三视图无法保证是同一个角色",
        )

    views = [v.strip().lower() for v in (request.views or []) if v and v.strip()]
    if not views:
        raise HTTPException(status_code=400, detail="views 不能为空")
    unknown = [v for v in views if v not in VIEW_PROMPTS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的视角 {unknown}，只允许 {sorted(VIEW_PROMPTS)}",
        )

    seed = request.seed if request.seed is not None else character.image_seed
    base_prompt = (character.visual_prompt or "").strip() or _default_visual_prompt(
        name=character.name,
        gender=character.gender or "other",
        age=int(character.age or 0),
        traits=list(character.traits or []),
        description=character.description or "",
    )

    view_images = dict(character.view_images or {})
    gallery = list(character.generated_images or [])
    errors: List[str] = []

    for view in views:
        await acquire_ai_quota_or_429(db, current_user.id)
        try:
            urls = await _generate_image_checked(
                prompt=f"{base_prompt}；{VIEW_PROMPTS[view]}",
                reference_image_url=character.reference_image_url,
                seed=seed,
                user_id=current_user.id,
                project_id=project_id,
            )
        except HTTPException:
            await refund_ai_quota_and_commit(db, current_user.id)
            raise
        except Exception as exc:  # noqa: BLE001 - 失败退配额，继续其余视角
            await refund_ai_quota_and_commit(db, current_user.id)
            logger.warning("角色 %s 的 %s 视角生成失败: %s", character.id, view, exc)
            errors.append(f"{view}: {exc}")
            continue

        if not urls:
            await refund_ai_quota_and_commit(db, current_user.id)
            errors.append(f"{view}: 未获得图片")
            continue

        persisted = await _persist_images(urls[:1], project_id)
        if not persisted:
            await refund_ai_quota_and_commit(db, current_user.id)
            errors.append(f"{view}: 转存失败")
            continue
        view_images[view] = persisted[0]
        gallery.append(persisted[0])

    if not (set(views) & set(view_images.keys())):
        raise HTTPException(
            status_code=503,
            detail="三视图全部生成失败：" + "；".join(errors or ["未获得任何图片"]),
        )

    character.view_images = view_images
    character.generated_images = gallery
    await db.flush()
    await db.refresh(character)
    return await _to_response(character)
