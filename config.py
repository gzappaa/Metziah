from pathlib import Path
import os

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

    # -- Promo notifications --
    USER_LAT: float | None = None
    USER_LON: float | None = None
    MAX_STORE_DISTANCE_KM: float = 5

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    EMAIL_FROM: str = ""
    EMAIL_TO: str = ""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / f".env.{os.getenv('ENV', 'test')}",
        extra="ignore",
    )


settings = Settings()