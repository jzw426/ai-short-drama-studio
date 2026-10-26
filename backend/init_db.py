"""数据库初始化脚本 - 创建所有表"""
import asyncio
import os


async def init_db():
    os.makedirs("data", exist_ok=True)

    from app.core.config import settings
    from app.core.database import engine, Base
    from app.models import (  # noqa: F401 - 确保所有模型被导入
        project,
        script,
        storyboard,
        character,
        asset,
    )

    print(f"[InitDB] 数据库类型: {settings.DATABASE_TYPE}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[InitDB] 所有表创建完成")


if __name__ == "__main__":
    asyncio.run(init_db())
