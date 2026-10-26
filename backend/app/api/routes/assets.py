import os
import tempfile
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.asset import Asset
from app.models.project import Project
from app.models.user import User
from app.schemas.asset import AssetResponse
from app.services.storage_service import storage_service, extract_object_name

router = APIRouter(tags=["Assets"])


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


async def _get_owned_asset_or_404(
    asset_id: str, owner_id: str, db: AsyncSession
) -> Asset:
    """按项目归属校验素材"""
    from sqlalchemy import select

    result = await db.execute(
        select(Asset)
        .join(Project, Project.id == Asset.project_id)
        .where(Asset.id == asset_id, Project.owner_id == owner_id)
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")
    return asset


def _determine_asset_type(mime_type: str) -> str:
    if mime_type.startswith("image/"):
        return "image"
    elif mime_type.startswith("audio/"):
        return "audio"
    elif mime_type.startswith("video/"):
        return "video"
    return "other"


@router.get("/projects/{project_id}/assets", response_model=List[AssetResponse])
async def list_assets(
    project_id: str,
    asset_type: Optional[str] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取项目素材列表"""
    from sqlalchemy import select

    await _get_project_or_404(project_id, current_user.id, db)

    stmt = select(Asset).where(Asset.project_id == project_id)

    if asset_type:
        stmt = stmt.where(Asset.type == asset_type)

    if search:
        stmt = stmt.where(Asset.name.ilike(f"%{search}%"))

    stmt = stmt.order_by(Asset.uploaded_at.desc())

    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/projects/{project_id}/assets/upload", status_code=201)
async def upload_asset(
    project_id: str,
    file: UploadFile = File(...),
    tags: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传素材文件（类型白名单 + 大小上限校验）"""
    await _get_project_or_404(project_id, current_user.id, db)

    # ---- 安全校验 ----
    # T0：文件名只用于展示，不再参与存储路径；路径穿越由
    #      "不含客户端字符的对象名 + 存储层越界校验" 双重封堵。
    raw_name = (file.filename or "").strip().replace("\\", "/")
    filename = os.path.basename(raw_name)[:200] or "untitled"
    ext = os.path.splitext(filename)[1].lower()
    content_type = (file.content_type or "").lower()

    if ext not in settings.UPLOAD_ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"不支持的文件扩展名: {ext or '(无)'}",
        )
    if content_type and content_type not in settings.UPLOAD_ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"不支持的文件类型: {content_type}",
        )

    # T0：边写盘边计数，超限立即中断。
    # 旧实现先 await file.read() 把整包读进内存再比较大小，
    # 500MB 上限在"读完之后"才生效，并发上传可把进程内存打爆。
    max_size = settings.UPLOAD_MAX_SIZE_MB * 1024 * 1024
    tmp_dir = os.path.join(settings.STORAGE_LOCAL_PATH, ".tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix="upload_", suffix=ext, dir=tmp_dir)
    total = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_size:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件过大，最大允许 {settings.UPLOAD_MAX_SIZE_MB}MB",
                    )
                out.write(chunk)
        if total == 0:
            raise HTTPException(status_code=400, detail="文件内容为空")

        object_name = f"{project_id}/{uuid.uuid4().hex}{ext}"
        url = await storage_service.upload_from_path(
            object_name=object_name,
            src_path=tmp_path,
            content_type=content_type or "application/octet-stream",
        )
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    asset = Asset(
        project_id=project_id,
        name=filename or "untitled",
        type=_determine_asset_type(content_type),
        mime_type=content_type,
        size=total,
        url=url,
        tags=[t.strip() for t in tags.split(",") if t.strip()],
    )
    db.add(asset)
    await db.flush()
    await db.refresh(asset)

    return AssetResponse.model_validate(asset)


@router.delete("/assets/{asset_id}", status_code=204)
async def delete_asset(
    asset_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除素材（仅限归属用户）"""
    asset = await _get_owned_asset_or_404(asset_id, current_user.id, db)

    # 从存储删除（提取 object_name；local/minio 双模式）
    try:
        object_name = extract_object_name(asset.url)
        if object_name:
            await storage_service.delete_file(object_name)
    except Exception as e:
        print(f"[WARNING] Failed to delete storage object: {e}")

    await db.delete(asset)
    await db.flush()
    return None


@router.get("/assets/{asset_id}/url")
async def get_asset_url(
    asset_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取素材的访问 URL（仅限归属用户）"""
    asset = await _get_owned_asset_or_404(asset_id, current_user.id, db)

    # 生成访问 URL（有效期 1 小时）
    object_name = asset.url.split("ai-drama-studio-assets/", 1)[-1] if "ai-drama-studio-assets/" in asset.url else ""
    presigned_url = await storage_service.get_presigned_url(object_name)

    return {"url": presigned_url}
