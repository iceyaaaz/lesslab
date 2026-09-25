from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from database import engine

from pathlib import Path
from fastapi.responses import FileResponse

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from typing import Literal

app = FastAPI(title="留白 LessLab", version="0.1.0")


@app.get("/", response_class=FileResponse)
def home():
    html_path = Path(__file__).with_name("index.html")
    return FileResponse(html_path)


@app.get("/health")
def health():
    return {"status": "ok", "project": "LessLab"}



@app.get("/health/db")
def database_health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()

        return {"status": "ok", "database": "connected"}

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="数据库连接失败，请检查 MySQL 服务和 .env 配置。",
        ) from None


@app.get("/resources")
def list_resources():
    try:
        with engine.connect() as connection:
            result = connection.execute(
                text("""
                    SELECT id, title, url, status, created_at, estimated_minutes
                    FROM resources
                    ORDER BY id DESC
                    LIMIT 100
                """)
            )

            resources = [
                dict(row) for row in result.mappings().all()
            ]

        return {"items": resources}

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="读取收藏失败，请检查数据库连接和收藏表。",
        ) from None

class ResourceCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    url: HttpUrl
    estimated_minutes: int | None = Field(
        default=None,
        ge=1,
        le=600,
    )


@app.post("/resources", status_code=201)
def create_resource(resource: ResourceCreate):
    try:
        with engine.begin() as connection:
            result = connection.execute(
                text("""
                    INSERT INTO resources (
                        title, url, estimated_minutes
                    )
                    VALUES (
                        :title, :url, :estimated_minutes
                    )
                """),
                {
                    "title": resource.title,
                    "url": str(resource.url),
                    "estimated_minutes": resource.estimated_minutes,
                },
            )

            resource_id = result.lastrowid

        return {
            "id": resource_id,
            "title": resource.title,
            "url": str(resource.url),
            "status": "unread",
            "estimated_minutes": resource.estimated_minutes,
        }

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="保存收藏失败，请稍后重试。",
        ) from None

class ResourceStatusUpdate(BaseModel):
    status: Literal["unread", "done"]


@app.patch("/resources/{resource_id}/status")
def update_resource_status(
    resource_id: int,
    resource: ResourceStatusUpdate,
):
    try:
        with engine.begin() as connection:
            result = connection.execute(
                text("""
                    UPDATE resources
                    SET status = :status
                    WHERE id = :resource_id
                """),
                {
                    "status": resource.status,
                    "resource_id": resource_id,
                },
            )

            if result.rowcount == 0:
                raise HTTPException(
                    status_code=404,
                    detail="这条收藏不存在。",
                )

        return {
            "id": resource_id,
            "status": resource.status,
        }

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="修改状态失败，请稍后重试。",
        ) from None

@app.get("/study-plan")
def create_study_plan(
    minutes: int = Query(default=30, ge=1, le=600),
):
    try:
        with engine.connect() as connection:
            result = connection.execute(
                text("""
                    SELECT id, title, url, estimated_minutes
                    FROM resources
                    WHERE status = 'unread'
                      AND estimated_minutes BETWEEN 1 AND :minutes
                    ORDER BY estimated_minutes ASC, id ASC
                    LIMIT 600
                """),
                {"minutes": minutes},
            )

            candidates = [
                dict(row) for row in result.mappings().all()
            ]

        selected = []
        remaining_minutes = minutes

        for resource in candidates:
            duration = resource["estimated_minutes"]

            if duration > remaining_minutes:
                break

            selected.append(resource)
            remaining_minutes -= duration

        return {
            "budget_minutes": minutes,
            "total_minutes": minutes - remaining_minutes,
            "remaining_minutes": remaining_minutes,
            "strategy": "优先安排耗时短的待学习内容",
            "items": selected,
        }

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="生成学习计划失败，请稍后重试。",
        ) from None