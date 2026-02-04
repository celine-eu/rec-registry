from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@db:5432/celine_rec_registry"
    )
    base_url: str = "http://localhost:8000"
    jsonld_context_url: str = "https://celine-eu.github.io/ontologies/celine.jsonld"


settings = Settings()
