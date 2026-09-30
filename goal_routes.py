"""按账号隔离的当前目标；版本号防止不同窗口覆盖彼此的修改。"""
from datetime import date
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from fastapi import Depends
from security import require_user

from database import engine

router = APIRouter(tags=["当前目标"])


class GoalUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    title: str = Field(min_length=2, max_length=200)
    success_criteria: str = Field(default="", max_length=250)
    due_date: date | None = None
    daily_minutes: int = Field(default=30, ge=1, le=600, strict=True)
    version: int = Field(ge=0, strict=True)

    @field_validator("due_date", mode="before")
    @classmethod
    def date_format(cls, value):
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)):
            raise ValueError("日期须为 YYYY-MM-DD 或 null。")
        return value


SELECT_GOAL = text("""
    SELECT title, success_criteria, due_date, daily_minutes, version
    FROM user_goals WHERE user_id = :user_id
""")


def serialize_goal(row):
    if row is None:
        raise HTTPException(503, "账号目标尚未初始化，请联系站点维护者。")
    data = dict(row)
    version = data.pop("version")
    return {"goal": data if data["title"] is not None else None, "version": version}


@router.get("/current-goal")
def get_current_goal(user: dict = Depends(require_user)):
    try:
        with engine.connect() as connection:
            row = connection.execute(SELECT_GOAL, {"user_id": user["id"]}).mappings().first()
        return serialize_goal(row)
    except SQLAlchemyError:
        raise HTTPException(503, "读取当前目标失败，请检查数据库和 user_goals 表。") from None


@router.put("/current-goal")
def save_current_goal(request: GoalUpdate, user: dict = Depends(require_user)):
    try:
        with engine.begin() as connection:
            row = connection.execute(SELECT_GOAL, {"user_id": user["id"]}).mappings().first()
            serialize_goal(row)
            result = connection.execute(text("""
                UPDATE user_goals
                SET title = :title, success_criteria = :criteria,
                    due_date = :due_date, daily_minutes = :minutes,
                    version = version + 1
                WHERE user_id = :user_id AND version = :version
            """), {
                "title": request.title,
                "criteria": request.success_criteria,
                "due_date": request.due_date.isoformat() if request.due_date else None,
                "minutes": request.daily_minutes,
                "version": request.version,
                "user_id": user["id"],
            })
            if result.rowcount != 1:
                raise HTTPException(409, "目标已在其他窗口更新，请先重新读取，再决定如何修改。")
            saved = serialize_goal(connection.execute(SELECT_GOAL, {"user_id": user["id"]}).mappings().one())
        return saved
    except SQLAlchemyError:
        raise HTTPException(503, "保存当前目标失败，请检查数据库。") from None
