"""用户名登录。会话保存在数据库，浏览器仅持有 HttpOnly 随机令牌。"""
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from security import (COOKIE_NAME, DUMMY_HASH, SESSION_SECONDS, check_origin,
                      consume_auth_attempt, create_account, hash_password,
                      lock_control, normalize_username, now_seconds, require_user,
                      token_digest, verify_password)

router = APIRouter(prefix="/auth", tags=["账号"])


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def username_format(cls, value):
        return normalize_username(value)


class RegisterInput(LoginInput):
    password: str = Field(min_length=15, max_length=128)


def charge_attempt(request, category, username=None):
    # 不读取未经服务器信任的 X-Forwarded-For；代理部署需配置可信代理。
    address = request.client.host if request.client else "unknown"
    with request.app.state.engine.begin() as connection:
        lock_control(connection)
        consume_auth_attempt(connection, category + "-ip", address, 20 if category == "login" else 5)
        if username is not None:
            consume_auth_attempt(connection, category + "-user", username, 10)


@router.get("/status")
def auth_status(request: Request):
    try:
        with request.app.state.engine.connect() as connection:
            control = connection.execute(text("SELECT owner_id FROM auth_control WHERE id = 1")).mappings().first()
        ready = control is not None and control["owner_id"] is not None
        return {"setup_required": not ready, "registration_enabled": ready and request.app.state.auth_config.allow_registration}
    except SQLAlchemyError:
        raise HTTPException(503, "账号服务尚未就绪，请联系站点维护者。") from None


@router.post("/register", status_code=201)
def register(payload: RegisterInput, request: Request):
    check_origin(request)
    if not request.app.state.auth_config.allow_registration:
        raise HTTPException(403, "当前未开放注册。")
    try:
        charge_attempt(request, "register")
        password_hash = hash_password(payload.password)
        with request.app.state.engine.begin() as connection:
            user_id = create_account(connection, payload.username, password_hash)
        return {"id": user_id, "username": payload.username}
    except IntegrityError:
        raise HTTPException(409, "这个用户名暂不可用，请更换后重试。") from None
    except SQLAlchemyError:
        raise HTTPException(503, "注册暂时不可用，请稍后重试。") from None


@router.post("/login")
def login(payload: LoginInput, request: Request, response: Response):
    check_origin(request)
    engine = request.app.state.engine
    try:
        # 单独提交尝试次数，验证密码失败也不能回滚计数。
        charge_attempt(request, "login", payload.username)
        with engine.connect() as connection:
            account = connection.execute(text("SELECT id, username, password_hash FROM users WHERE username = :username"), {"username": payload.username}).mappings().first()
        valid = verify_password(payload.password, account["password_hash"] if account else DUMMY_HASH)
        if not account or not valid:
            raise HTTPException(401, "用户名或密码不正确。")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        old_token = request.cookies.get(COOKIE_NAME, "")
        now = now_seconds()
        with engine.begin() as connection:
            # 用用户行锁限制同时有效的会话数量，支持多进程部署。
            connection.execute(text("SELECT id FROM users WHERE id = :id FOR UPDATE"), {"id": account["id"]}).first()
            connection.execute(text("DELETE FROM user_sessions WHERE expires_at <= :now OR token_hash = :old"), {"now": now, "old": token_digest(old_token)})
            sessions = connection.execute(text("SELECT token_hash FROM user_sessions WHERE user_id = :id ORDER BY expires_at, token_hash"), {"id": account["id"]}).mappings().all()
            for row in sessions[:max(0, len(sessions) - 4)]:
                connection.execute(text("DELETE FROM user_sessions WHERE token_hash = :token"), {"token": row["token_hash"]})
            connection.execute(text("""
                INSERT INTO user_sessions(token_hash, user_id, csrf_token, expires_at)
                VALUES(:token, :user_id, :csrf, :expires)
            """), {"token": token_digest(token), "user_id": account["id"], "csrf": csrf, "expires": now + SESSION_SECONDS})
        response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True,
                            secure=request.app.state.auth_config.cookie_secure, samesite="lax", path="/")
        return {"id": account["id"], "username": account["username"]}
    except SQLAlchemyError:
        raise HTTPException(503, "登录暂时不可用，请稍后重试。") from None


@router.get("/me")
def me(user: dict = Depends(require_user)):
    return {"id": user["id"], "username": user["username"], "csrf_token": user["csrf_token"]}


@router.post("/logout")
def logout(request: Request, response: Response, user: dict = Depends(require_user)):
    try:
        with request.app.state.engine.begin() as connection:
            connection.execute(text("DELETE FROM user_sessions WHERE token_hash = :token AND user_id = :id"), {"token": token_digest(request.cookies[COOKIE_NAME]), "id": user["id"]})
    except SQLAlchemyError:
        raise HTTPException(503, "退出失败，请稍后重试。") from None
    response.delete_cookie(COOKIE_NAME, path="/", secure=request.app.state.auth_config.cookie_secure, httponly=True, samesite="lax")
    return {"status": "ok"}
