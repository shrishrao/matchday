"""Application settings, validated when the app starts."""

from pathlib import Path

from psycopg.conninfo import make_conninfo
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ===== Settings =====
class Settings(BaseSettings):
    """Settings read from environment variables and the project's .env file."""

    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    postgres_user: str = Field(min_length=1)
    postgres_password: SecretStr
    postgres_db: str = Field(min_length=1)
    postgres_host: str = Field(min_length=1)
    postgres_port: int = Field(ge=1, le=65535)

    pool_min_size: int = Field(default=2, ge=1)
    pool_max_size: int = Field(default=10, ge=1)
    pool_timeout_seconds: float = Field(default=5.0, gt=0)

    def conninfo(self) -> str:
        """Build the Postgres connection string."""
        return make_conninfo(
            host=self.postgres_host,
            port=self.postgres_port,
            user=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            dbname=self.postgres_db,
            connect_timeout=3,
        )
