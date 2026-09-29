"""学习计划执行进度；保留原始计划快照，不改收藏状态，不调用模型。"""
import json

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from database import engine

router = APIRouter(tags=["计划执行进度"])


class TaskCompletion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    completed: StrictBool


def read_items(connection, plan_id, lock=False):
    statement = "SELECT items FROM study_plans WHERE id = :id"
    if lock:
        statement += " FOR UPDATE"
    row = connection.execute(text(statement), {"id": plan_id}).mappings().first()
    if row is None:
        raise HTTPException(404, "这份计划不存在。")
    items = row["items"]
    if isinstance(items, (str, bytes, bytearray)):
        items = json.loads(items)
    return items


def progress_summary(connection, plan_id, items):
    rows = connection.execute(text("""
        SELECT resource_id, completed, completed_at
        FROM study_plan_progress WHERE plan_id = :id
    """), {"id": plan_id}).mappings().all()
    saved = {row["resource_id"]: row for row in rows}
    states = []
    for item in items:
        row = saved.get(item["id"])
        states.append({
            "resource_id": item["id"],
            "completed": bool(row["completed"]) if row else False,
            "completed_at": row["completed_at"] if row else None,
        })
    return {
        "plan_id": plan_id,
        "total_count": len(states),
        "completed_count": sum(state["completed"] for state in states),
        "items": states,
    }


@router.get("/study-plans/{plan_id}/progress")
def get_progress(plan_id: int = Path(gt=0)):
    try:
        with engine.connect() as connection:
            items = read_items(connection, plan_id)
            return progress_summary(connection, plan_id, items)
    except SQLAlchemyError:
        raise HTTPException(503, "读取计划进度失败，请检查数据库和 study_plan_progress 表。") from None


@router.put("/study-plans/{plan_id}/tasks/{resource_id}/completion")
def set_completion(
    request: TaskCompletion,
    plan_id: int = Path(gt=0),
    resource_id: int = Path(gt=0),
):
    try:
        with engine.begin() as connection:
            # 同一计划的更新串行进行，避免首次写入时发生重复插入。
            items = read_items(connection, plan_id, lock=True)
            if resource_id not in {item["id"] for item in items}:
                raise HTTPException(404, "这条任务不属于该计划。")
            params = {"plan_id": plan_id, "resource_id": resource_id, "completed": int(request.completed)}
            existing = connection.execute(text("""
                SELECT resource_id FROM study_plan_progress
                WHERE plan_id = :plan_id AND resource_id = :resource_id
            """), params).mappings().first()
            if existing is None:
                connection.execute(text("""
                    INSERT INTO study_plan_progress (plan_id, resource_id, completed, completed_at)
                    VALUES (:plan_id, :resource_id, :completed,
                        CASE WHEN :completed = 1 THEN CURRENT_TIMESTAMP ELSE NULL END)
                """), params)
            else:
                connection.execute(text("""
                    UPDATE study_plan_progress
                    SET completed = :completed,
                        completed_at = CASE WHEN :completed = 1
                            THEN COALESCE(completed_at, CURRENT_TIMESTAMP) ELSE NULL END
                    WHERE plan_id = :plan_id AND resource_id = :resource_id
                """), params)
            summary = progress_summary(connection, plan_id, items)
        return summary
    except SQLAlchemyError:
        raise HTTPException(503, "保存完成状态失败，请检查数据库。") from None
