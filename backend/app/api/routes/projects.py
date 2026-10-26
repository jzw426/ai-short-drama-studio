from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.project import Project, ProjectStatus
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse

router = APIRouter(tags=["Projects"])


async def _get_owned_project_or_404(
    project_id: str, owner_id: str, db: AsyncSession
) -> Project:
    """按归属校验获取项目；不存在或不属于当前用户均返回 404"""
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


@router.get("/projects", response_model=List[ProjectResponse])
async def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的项目列表，支持分页和状态过滤"""
    from sqlalchemy import select

    stmt = select(Project).where(Project.owner_id == current_user.id)
    if status:
        stmt = stmt.where(Project.status == status)
    stmt = stmt.order_by(Project.updated_at.desc()).limit(page_size).offset((page - 1) * page_size)

    result = await db.execute(stmt)
    projects = result.scalars().all()
    return list(projects)


@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(
    data: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建新项目（归属当前用户）"""
    project = Project(
        title=data.title,
        description=data.description,
        status=ProjectStatus.DRAFT,
        progress=0.0,
        owner_id=current_user.id,
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    return project


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取单个项目详情"""
    return await _get_owned_project_or_404(project_id, current_user.id, db)


@router.put("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    data: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新项目信息"""
    project = await _get_owned_project_or_404(project_id, current_user.id, db)

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if key == "status" and value:
            value = ProjectStatus(value)
        setattr(project, key, value)

    await db.flush()
    await db.refresh(project)
    return project


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除项目（级联删除关联数据，并物理清理素材与渲染输出文件，仅限归属用户）"""
    from sqlalchemy import select

    from app.models.asset import Asset, RenderTask
    from app.services.storage_service import storage_service, extract_object_name

    project = await _get_owned_project_or_404(project_id, current_user.id, db)

    # 物理删除项目下所有素材文件
    result = await db.execute(select(Asset).where(Asset.project_id == project_id))
    for asset in result.scalars().all():
        object_name = extract_object_name(asset.url)
        if object_name:
            try:
                await storage_service.delete_file(object_name)
            except Exception as e:
                print(f"[WARNING] 清理素材文件失败: {e}")

    # 物理删除项目下所有渲染输出
    result = await db.execute(select(RenderTask).where(RenderTask.project_id == project_id))
    for task in result.scalars().all():
        if task.output_url:
            object_name = extract_object_name(task.output_url)
            if object_name:
                try:
                    await storage_service.delete_file(object_name)
                except Exception as e:
                    print(f"[WARNING] 清理渲染输出失败: {e}")

    # 数据库记录级联删除（Project.assets / Project.render_tasks 均配置 delete-orphan）
    await db.delete(project)
    await db.flush()
    return None
