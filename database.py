from pathlib import Path
from security import AuthConfig

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL, create_engine


class Settings(BaseSettings):
    db_host: str
    db_port: int = 3306
    db_user: str
    db_password: SecretStr
    db_name: str
    app_origin: str = "http://127.0.0.1:8000"
    auth_cookie_secure: bool = False
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

engine = create_engine(
    database_url,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 5},
)