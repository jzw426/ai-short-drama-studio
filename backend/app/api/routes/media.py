"""受控媒体访问端点（M1）: GET /uploads/{object_name}

替换 T0 之前 main.py 里的 StaticFiles 公开挂载 —— 那个挂载意味着
任何拿到 URL 的人无需登录即可下载全部素材与成片（尽调中已实测 200）。

现在的放行条件（二选一）：
1. 合法签名 URL：`?exp=<unix>&sig=<hmac>`（前端 <img>/<video>/下载链接用）；
2. 已登录（Bearer 或 httpOnly Cookie）且 object_name 的项目前缀属于该用户。
"""
import mimetypes
import os
from typing import Iterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_optional_user
from app.core.media_urls import verify_media_signature
from app.models.project import Project
from app.services.storage_service import _secure_local_path

router = APIRouter(tags=["Media"])

_STREAM_CHUNK = 256 * 1024


def _iter_file(path: str, start: int, length: int) -> Iterator[bytes]:
    with open(path, "rb") as f:
        f.seek(start)
        remaining = length
        while remaining > 0:
            chunk = f.read(min(_STREAM_CHUNK, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _parse_range(header: str, size: int) -> Optional[tuple[int, int]]:
    """解析单段 Range（视频拖动进度条必需）；无法解析时返回 None。"""
    if not header or not header.startswith("bytes=") or size <= 0:
        return None
    spec = header[len("bytes="):].split(",", 1)[0].strip()
    start_s, _, end_s = spec.partition("-")
    try:
        if not start_s:
            if not end_s:
                return None
            length = int(end_s)
            if length <= 0:
                return None
            start = max(0, size - length)
            end = size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else size - 1
    except ValueError:
        return None
    if start < 0 or start >= size or end < start:
        return None
    return start, min(end, size - 1)


async def _authorized_as_owner(object_name: str, request: Request, db: AsyncSession) -> bool:
    user = await get_optional_user(request=request, db=db)
    if user is None:
        return False
    project_id = object_name.split("/", 1)[0]
    if not project_id:
        return False
    row = await db.execute(
        select(Project.id).where(
            Project.id == project_id, Project.owner_id == user.id
        )
    )
    return row.scalar_one_or_none() is not None


@router.get("/uploads/{object_name:path}")
async def get_uploaded_file(
    object_name: str,
    request: Request,
    exp: Optional[int] = Query(default=None),
    sig: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """受控读取本地存储中的素材/成片。"""
    if settings.STORAGE_TYPE != "local":
        raise HTTPException(status_code=404, detail="当前部署未启用本地媒体端点")

    signature_ok = verify_media_signature(object_name, exp, sig)
    if not signature_ok:
        if not await _authorized_as_owner(object_name, request, db):
            raise HTTPException(
                status_code=401,
                detail="需要登录或有效的媒体签名 URL",
                headers={"WWW-Authenticate": "Bearer"},
            )

    try:
        file_path = _secure_local_path(object_name)
    except ValueError:
        # 越界或非法名字一律当作不存在，不回显具体原因
        raise HTTPException(status_code=404, detail="文件不存在")

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    size = os.path.getsize(file_path)
    media_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=300",
        "Content-Disposition": f'inline; filename="{os.path.basename(file_path)}"',
    }

    range_header = request.headers.get("range", "")
    if range_header:
        parsed = _parse_range(range_header, size)
        if parsed is None:
            raise HTTPException(
                status_code=416,
                detail="请求的字节范围不合法",
                headers={"Content-Range": f"bytes */{size}"},
            )
        start, end = parsed
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        headers["Accept-Ranges"] = "bytes"
        headers["Content-Length"] = str(end - start + 1)
        return StreamingResponse(
            _iter_file(file_path, start, end - start + 1),
            status_code=206,
            media_type=media_type,
            headers=headers,
        )

    headers["Accept-Ranges"] = "bytes"
    return FileResponse(file_path, media_type=media_type, headers=headers)
