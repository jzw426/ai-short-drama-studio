from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.media_urls import signed_media_url
from app.models.character import Character
from app.models.project import Project
from app.models.user import User
from app.schemas.character import (
    CharacterCreate, CharacterUpdate, CharacterResponse,
    AIGenerateCharacterRequest,
)
from app.services.ai_service import AIUnavailableError, ai_service
from app.core.quota import acquire_ai_quota_or_429, refund_ai_quota

router = APIRouter(tags=["Characters"])


async def _to_response(character: Character) -> CharacterResponse:
    """ORM → 响应模型，媒体链接（头像/形象图）在此签名，数据库只存规范 URL。

    M1：MinIO 模式下这里生成的是预签名 URL（桶已私有），所以必须 await。
    """
    resp = CharacterResponse.model_validate(character)
    resp.avatar_url = await signed_media_url(resp.avatar_url)
    signed_images = [
        await signed_media_url(x) for x in (resp.generated_images or [])
    ]
    resp.generated_images = [u for u in signed_images if u]
    return resp


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
        await refund_ai_quota(db, current_user.id)
        raise HTTPException(status_code=503, detail=f"AI 角色生成失败：{e}") from e

    # 生成角色形象图（失败不影响角色设定落库，前端可稍后单独重试）
    image_urls = await ai_service.generate_image(
        prompt=f"Character portrait: {char_info.get('name', '')} - {char_info.get('description', request.description)}",
        style="anime-portrait",
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
    """为已有角色生成/追加形象图（一致性形象生成，受每日配额限制）"""
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

    # 基于角色设定生成形象图
    prompt = (
        f"Character portrait: {character.name} - {character.description}"
        f" (性别: {character.gender}, 年龄: {character.age}, 性格: {', '.join(character.traits or [])})"
    )
    await acquire_ai_quota_or_429(db, current_user.id)
    image_urls = await ai_service.generate_image(prompt=prompt, style="anime-portrait")
    if not image_urls:
        await refund_ai_quota(db, current_user.id)
        raise HTTPException(
            status_code=503,
            detail="AI 形象生成失败：未获得任何图片（请检查 AGNES_API_KEY 或 provider 状态）",
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
