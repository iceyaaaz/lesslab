from pathlib import Path
import os
import ssl
from security import AuthConfig

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL, create_engine


class Settings(BaseSettings):
    db_host: str
    db_port: int = 3306
    db_user: str
    db_password: SecretStr
    db_name: str
    db_ssl_ca: str = ""
    app_origin: str = Field(default_factory=lambda: os.environ.get("RENDER_EXTERNAL_URL") or "http://127.0.0.1:8000")
    auth_cookie_secure: bool = Field(default_factory=lambda: bool(os.environ.get("RENDER_EXTERNAL_URL")))
    auth_allow_registration: bool = False

    model_config = SettingsConfigDict(
        env_file=Path(__file__).with_name(".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
auth_config = AuthConfig(origin=settings.app_origin, cookie_secure=settings.auth_cookie_secure, allow_registration=settings.auth_allow_registration)

database_url = URL.create(
    drivername="mysql+pymysql",
    username=settings.db_user,
    password=settings.db_password.get_secret_value(),
    host=settings.db_host,
    port=settings.db_port,
    database=settings.db_name,
    query={"charset": "utf8mb4"},
)

# 云数据库使用提供的 CA 验证证书与主机名；证书错误时启动失败，不降级为明文。
connect_args = {"connect_timeout": 10}
if os.environ.get("RENDER_EXTERNAL_URL") and not settings.db_ssl_ca.strip():
    raise ValueError("Render 部署须配置 DB_SSL_CA，指向 Aiven 的 CA 证书文件。")
if settings.db_ssl_ca.strip():
    connect_args["ssl"] = ssl.create_default_context(cafile=settings.db_ssl_ca.strip())

engine = create_engine(
    database_url,
    pool_pre_ping=True,
    connect_args=connect_args,
)
