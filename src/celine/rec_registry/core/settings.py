"""
Application settings using pydantic-settings.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = (
        "postgresql+asyncpg://postgres:securepassword123@172.17.0.1:15432/celine_rec_registry"
    )
    database_echo: bool = False

    # API
    base_url: str = "http://api.celine.localhost/rec-registry"

    # Pagination defaults
    default_page_size: int = 50
    max_page_size: int = 500


settings = Settings()
