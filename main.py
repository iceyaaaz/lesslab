from fastapi import FastAPI, HTTPException, Query
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from urllib.parse import urlsplit
from database import auth_config
from auth_routes import router as auth_router

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from fastapi import Depends
from security import require_user

from database import engine

from pathlib import Path
from fastapi.responses import FileResponse

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from typing import Literal

from ai_routes import router as ai_router

from fastapi.staticfiles import StaticFiles

from plan_routes import router as plan_router
from archive_routes import router as archive_router
from goal_routes import router as goal_router
from progress_routes import router as progress_router

app = FastAPI(title="留白 LessLab", version="0.2.0")
app.state.engine = engine
app.state.auth_config = auth_config
app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(auth_config.origin).hostname])
app.include_router(auth_router)


@app.middleware("http")
async def private_response_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


@app.exception_handler(RequestValidationError)
async def safe_validation_errors(request: Request, error: RequestValidationError):
    # FastAPI 默认验证响应会包含 input；避免把密码等请求内容回显。
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": list(item["loc"]), "msg": item["msg"], "type": item["type"]}
        for item in error.errors()
    ]})

app.include_router(ai_router)
app.include_router(plan_router)
app.include_router(archive_router)
app.include_router(goal_router)
app.include_router(progress_router)
app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).parent / "static"),
    name="static",
)


@app.get("/", response_class=FileResponse)
def home(request: Request):
    try:
        require_user(request)
    except HTTPException as error:
        if error.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        raise
    html_path = Path(__file__).with_name("index.html")
    return FileResponse(html_path)


@app.get("/login", response_class=FileResponse)
def login_page():
    return FileResponse(Path(__file__).with_name("login.html"))


@app.get("/health")
def health():
    return {"status": "ok", "project": "LessLab"}



@app.get("/health/db")
def database_health(user: dict = Depends(require_user)):
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
def list_resources(archived: bool = Query(default=False), user: dict = Depends(require_user)):
    try:
        with engine.connect() as connection:
            result = connection.execute(
                text("""
                    SELECT id, title, url, status, created_at, estimated_minutes, archived_at
                    FROM resources
                    WHERE owner_id = :user_id
                      AND ((:archived = 1 AND archived_at IS NOT NULL)
                       OR (:archived = 0 AND archived_at IS NULL))
                    ORDER BY id DESC
                    LIMIT 100
                """),
                {"archived": int(archived), "user_id": user["id"]},
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
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    url: HttpUrl
    estimated_minutes: int | None = Field(
        default=None,
        ge=1,
        le=600,
    )


@app.post("/resources", status_code=201)
def create_resource(resource: ResourceCreate, user: dict = Depends(require_user)):
    try:
        with engine.begin() as connection:
            result = connection.execute(
                text("""
                    INSERT INTO resources (
                        title, url, estimated_minutes, owner_id
                    )
                    VALUES (
                        :title, :url, :estimated_minutes, :user_id
                    )
                """),
                {
                    "title": resource.title,
                    "url": str(resource.url),
                    "estimated_minutes": resource.estimated_minutes,
                    "user_id": user["id"],
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
    user: dict = Depends(require_user),
):
    try:
        with engine.begin() as connection:
            result = connection.execute(
                text("""
                    UPDATE resources
                    SET status = :status
                    WHERE id = :resource_id AND owner_id = :user_id
                """),
                {
                    "status": resource.status,
                    "resource_id": resource_id,
                    "user_id": user["id"],
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
    user: dict = Depends(require_user),
):
    try:
        with engine.connect() as connection:
            result = connection.execute(
                text("""
                    SELECT id, title, url, estimated_minutes
                    FROM resources
                    WHERE owner_id = :user_id AND status = 'unread'
                      AND archived_at IS NULL
                      AND estimated_minutes BETWEEN 1 AND :minutes
                    ORDER BY estimated_minutes ASC, id ASC
                    LIMIT 600
                """),
                {"minutes": minutes, "user_id": user["id"]},
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