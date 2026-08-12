from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    PGHOST: str = "localhost"
    PGPORT: int = 5432
    PGUSER: str
    PGPASSWORD: str
    PGDATABASE: str

    GEOCODE_API: str = ""

    ENV: str = "dev"
    DEBUG: bool = False

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env.dev",
        extra="ignore",
    )


settings = Settings()