"""保存计划和读取历史。不会调用模型，不修改收藏的完成状态。"""

import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError

from database import engine

router = APIRouter(tags=["历史学习计划"])


class PlanItemInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    id: int = Field(gt=0, strict=True)
    reason: str = Field(default="", max_length=200)


class SavePlanRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    goal: str = Field(min_length=2, max_length=500)
    budget_minutes: int = Field(ge=1, le=600, strict=True)
    source: Literal["ai", "rule", "manual"] = "manual"
    items: list[PlanItemInput] = Field(min_length=1, max_length=600)


def prepare_snapshot(request, resources):
    """使用保存时的数据库信息构建快照，重新检查状态与预算。"""
    ids = [item.id for item in request.items]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "同一份计划不能重复安排同一条收藏。")
    if request.source == "ai" and len(ids) > 8:
        raise HTTPException(422, "当前 AI 计划最多保存 8 项内容。")

    by_id = {row["id"]: row for row in resources}
    snapshot = []
    total = 0
    for item in request.items:
        row = by_id.get(item.id)
        if row is None:
            raise HTTPException(409, "部分收藏已不存在，请重新生成计划。")
        if row.get("archived_at") is not None:
            raise HTTPException(409, "部分收藏已归档，请重新生成计划或先恢复资料。")
        if row["status"] != "unread":
            raise HTTPException(409, "部分收藏已不处于待学习状态，请重新生成计划。")

        duration = row["estimated_minutes"]
        if not isinstance(duration, int) or isinstance(duration, bool) or not 1 <= duration <= 600:
            raise HTTPException(409, "部分收藏的预计时长无效，请先补充或修正。")
        total += duration
        if total > request.budget_minutes:
            raise HTTPException(409, "当前收藏总时长超出预算，请重新安排计划。")

        snapshot.append({
            "id": row["id"],
            "title": row["title"],
            "url": row["url"],
            "estimated_minutes": duration,
            "reason": item.reason,
        })

    return snapshot, total


def decode_plan(row):
    plan = dict(row)
    # 原生 SQL 查询下，MySQL JSON 列通常以字符串形式返回。
    if isinstance(plan["items"], (str, bytes, bytearray)):
        plan["items"] = json.loads(plan["items"])
    return plan


@router.post("/study-plans", status_code=201)
def save_study_plan(request: SavePlanRequest):
    ids = [item.id for item in request.items]
    # 在查询前先检查重复项和项数，避免不必要的数据库操作。
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "同一份计划不能重复安排同一条收藏。")
    if request.source == "ai" and len(ids) > 8:
        raise HTTPException(422, "当前 AI 计划最多保存 8 项内容。")

    statement = text("""
        SELECT id, title, url, status, estimated_minutes, archived_at
        FROM resources
        WHERE id IN :resource_ids
        ORDER BY id
        FOR UPDATE
    """).bindparams(bindparam("resource_ids", expanding=True))

    try:
        # 查询与写入处于同一事务；短暂锁定涉及的收藏以保持快照一致。
        with engine.begin() as connection:
            rows = connection.execute(
                statement, {"resource_ids": ids}
            ).mappings().all()
            snapshot, total = prepare_snapshot(request, rows)

            result = connection.execute(
                text("""
                    INSERT INTO study_plans
                        (goal, budget_minutes, total_minutes, source, items)
                    VALUES
                        (:goal, :budget_minutes, :total_minutes, :source, :items)
                """),
                {
                    "goal": request.goal,
                    "budget_minutes": request.budget_minutes,
                    "total_minutes": total,
                    "source": request.source,
                    "items": json.dumps(snapshot, ensure_ascii=False),
                },
            )
            row = connection.execute(
                text("""
                    SELECT id, goal, budget_minutes, total_minutes,
                           source, items, created_at
                    FROM study_plans WHERE id = :plan_id
                """),
                {"plan_id": result.lastrowid},
            ).mappings().one()
            plan = decode_plan(row)

        return plan

    except SQLAlchemyError:
        raise HTTPException(503, "保存计划失败，请检查数据库连接和 study_plans 表。") from None


@router.get("/study-plans")
def list_study_plans(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text("""
                    SELECT id, goal, budget_minutes, total_minutes,
                           source, created_at, JSON_LENGTH(items) AS item_count
                    FROM study_plans
                    ORDER BY id DESC
                    LIMIT :limit OFFSET :offset
                """),
                {"limit": limit + 1, "offset": offset},
            ).mappings().all()
            summaries = [dict(row) for row in rows]

        return {
            "items": summaries[:limit],
            "limit": limit,
            "offset": offset,
            "has_more": len(summaries) > limit,
        }
    except SQLAlchemyError:
        raise HTTPException(503, "读取历史计划失败，请检查数据库。") from None


@router.get("/study-plans/{plan_id}")
def get_study_plan(plan_id: int = Path(gt=0)):
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text("""
                    SELECT id, goal, budget_minutes, total_minutes,
                           source, items, created_at
                    FROM study_plans WHERE id = :plan_id
                """),
                {"plan_id": plan_id},
            ).mappings().first()

        if row is None:
            raise HTTPException(404, "这份学习计划不存在。")
        return decode_plan(row)
    except SQLAlchemyError:
        raise HTTPException(503, "读取计划详情失败，请检查数据库。") from None
