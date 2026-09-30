"""归档是可恢复的资料整理操作，不改变原来的学习状态。"""

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from fastapi import Depends
from security import require_user

from database import engine

router = APIRouter(tags=["资料归档"])


class ArchiveUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    archived: StrictBool


@router.patch("/resources/{resource_id}/archive")
def update_archive(request: ArchiveUpdate, resource_id: int = Path(gt=0), user: dict = Depends(require_user)):
    try:
        with engine.begin() as connection:
            row = connection.execute(
                text("SELECT id FROM resources WHERE id = :id AND owner_id = :user_id FOR UPDATE"),
                {"id": resource_id, "user_id": user["id"]},
            ).mappings().first()
            if row is None:
                raise HTTPException(404, "这条收藏不存在。")

            # 重复提交同一目标状态也是成功；再次归档不重置归档时间。
            connection.execute(
                text("""
                    UPDATE resources
                    SET archived_at = CASE WHEN :archived = 1
                        THEN COALESCE(archived_at, CURRENT_TIMESTAMP)
                        ELSE NULL END
                    WHERE id = :id AND owner_id = :user_id
                """),
                {"id": resource_id, "archived": int(request.archived), "user_id": user["id"]},
            )
            row = connection.execute(
                text("SELECT id, status, archived_at FROM resources WHERE id = :id AND owner_id = :user_id"),
                {"id": resource_id, "user_id": user["id"]},
            ).mappings().one()
            result = dict(row)
        return result
    except SQLAlchemyError:
        raise HTTPException(503, "更新归档状态失败，请检查数据库和 archived_at 字段。") from None
