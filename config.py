from pydantic_settings import BaseSettings, SettingsConfigDict


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
        env_file=".env.test",
        extra="ignore",
    )


settings = Settings()