"""密码散列、数据库会话与请求校验；本模块不读取环境变量或创建数据库连接。"""
from dataclasses import dataclass
import hashlib
import hmac
import re
import secrets
import time
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

COOKIE_NAME = "lesslab_session"
PASSWORD_ROUNDS = 600_000
SESSION_SECONDS = 8 * 60 * 60
USERNAME_RE = re.compile(r"[a-zA-Z0-9_]{3,32}\Z")


@dataclass(frozen=True)
class AuthConfig:
    origin: str = "http://127.0.0.1:8000"
    cookie_secure: bool = False
    allow_registration: bool = False

    def __post_init__(self):
        parsed = urlsplit(self.origin)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.path
                or parsed.query or parsed.fragment):
            raise ValueError("APP_ORIGIN 须为不带尾部斜线、路径或账号信息的网站地址。")
        if parsed.scheme == "https" and not self.cookie_secure:
            raise ValueError("HTTPS 站点须设置 AUTH_COOKIE_SECURE=true。")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1", "testserver"}:
            raise ValueError("非本机地址须使用 HTTPS 并开启安全 Cookie。")


def now_seconds():
    return int(time.time())


def normalize_username(value):
    value = value.strip()
    if not USERNAME_RE.fullmatch(value):
        raise ValueError("用户名须为 3—32 位英文字母、数字或下划线。")
    return value.lower()


def validate_new_password(password):
    if not isinstance(password, str) or not 15 <= len(password) <= 128:
        raise ValueError("密码须为 15—128 个字符，可使用便于记忆的长短语。")


def hash_password(password):
    validate_new_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ROUNDS)
    return f"pbkdf2_sha256${PASSWORD_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password, encoded):
    try:
        algorithm, rounds, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or rounds != str(PASSWORD_ROUNDS):
            return False
        if len(salt) != 32 or len(expected) != 64:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PASSWORD_ROUNDS)
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError, AttributeError):
        return False


# 不存在的用户名也进行相同成本的散列验证，降低账号枚举的时间差。
DUMMY_HASH = hash_password("not-a-real-user-password")


def token_digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def check_origin(request):
    if request.headers.get("origin") != request.app.state.auth_config.origin:
        raise HTTPException(403, "请求来源不匹配，请从配置的网站地址打开页面。")


def require_user(request: Request):
    token = request.cookies.get(COOKIE_NAME, "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise HTTPException(401, "请先登录。")
    try:
        with request.app.state.engine.connect() as connection:
            row = connection.execute(text("""
                SELECT u.id, u.username, s.csrf_token
                FROM user_sessions s JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = :token AND s.expires_at > :now
            """), {"token": token_digest(token), "now": now_seconds()}).mappings().first()
    except SQLAlchemyError:
        raise HTTPException(503, "暂时无法验证登录状态，请稍后重试。") from None
    if row is None:
        raise HTTPException(401, "登录已过期，请重新登录。")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request)
        csrf = request.headers.get("x-csrf-token", "")
        if len(csrf) > 128 or not hmac.compare_digest(csrf.encode("utf-8"), row["csrf_token"].encode("utf-8")):
            raise HTTPException(403, "登录验证已变化，请刷新页面后重试。")
    return dict(row)


def lock_control(connection, ready=True):
    row = connection.execute(text("SELECT owner_id FROM auth_control WHERE id = 1 FOR UPDATE")).mappings().first()
    if row is None or (ready and row["owner_id"] is None):
        raise HTTPException(503, "服务尚未初始化，请联系站点维护者。")
    return row


def consume_auth_attempt(connection, category, identity, limit):
    """调用者持有 auth_control 行锁，使检查与计数在 MySQL 中串行生效。"""
    now = now_seconds()
    key = token_digest(category + ":" + identity)
    row = connection.execute(text("SELECT attempts, window_start FROM auth_throttle WHERE bucket_key = :key"), {"key": key}).mappings().first()
    if row and now - row["window_start"] < 900:
        if row["attempts"] >= limit:
            retry = max(1, 900 - (now - row["window_start"]))
            raise HTTPException(429, "尝试次数过多，请稍后再试。", headers={"Retry-After": str(retry)})
        connection.execute(text("UPDATE auth_throttle SET attempts = attempts + 1 WHERE bucket_key = :key"), {"key": key})
    elif row:
        connection.execute(text("UPDATE auth_throttle SET attempts = 1, window_start = :now WHERE bucket_key = :key"), {"key": key, "now": now})
    else:
        connection.execute(text("INSERT INTO auth_throttle(bucket_key, attempts, window_start) VALUES(:key, 1, :now)"), {"key": key, "now": now})
    connection.execute(text("DELETE FROM auth_throttle WHERE window_start < :cutoff"), {"cutoff": now - 3600})


def create_account(connection, username, password_hash):
    result = connection.execute(text("INSERT INTO users(username, password_hash) VALUES(:username, :password_hash)"), {"username": username, "password_hash": password_hash})
    user_id = result.lastrowid
    connection.execute(text("INSERT INTO user_goals(user_id) VALUES(:user_id)"), {"user_id": user_id})
    return user_id


def initialize_owner(engine, username, password):
    """仅由本机命令行执行；账号创建、旧数据归属、目标复制在同一事务中完成。"""
    username = normalize_username(username)
    password_hash = hash_password(password)
    with engine.begin() as connection:
        control = lock_control(connection, ready=False)
        if control["owner_id"] is not None:
            raise ValueError("初始账号已经创建，本次没有改动数据。")
        user_id = create_account(connection, username, password_hash)
        connection.execute(text("UPDATE resources SET owner_id = :user_id WHERE owner_id IS NULL"), {"user_id": user_id})
        connection.execute(text("UPDATE study_plans SET owner_id = :user_id WHERE owner_id IS NULL"), {"user_id": user_id})
        old = connection.execute(text("SELECT title, success_criteria, due_date, daily_minutes, version FROM current_goal WHERE id = 1")).mappings().first()
        if old is None:
            raise ValueError("旧目标表未初始化，请先确认 003 迁移已执行；本次修改已回滚。")
        connection.execute(text("""
            UPDATE user_goals SET title = :title, success_criteria = :success_criteria,
                due_date = :due_date, daily_minutes = :daily_minutes, version = :version
            WHERE user_id = :user_id
        """), {**dict(old), "user_id": user_id})
        connection.execute(text("UPDATE auth_control SET owner_id = :user_id WHERE id = 1"), {"user_id": user_id})
    return user_id
