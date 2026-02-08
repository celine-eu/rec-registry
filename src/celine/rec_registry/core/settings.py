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

    # ==========================================================================
    # Authentication
    # ==========================================================================
    # When enabled, JWT tokens are validated and user info is extracted

    auth_enabled: bool = False

    # JWT verification settings
    # If verify_jwt is False, tokens are decoded without signature verification
    # (assumes upstream proxy like oauth2-proxy already verified)
    auth_verify_jwt: bool = False

    # JWKS URI for JWT signature verification (required if auth_verify_jwt=True)
    # Example: "https://auth.example.com/.well-known/jwks.json"
    auth_jwks_uri: str | None = None

    # Expected JWT issuer (optional, for validation)
    auth_issuer: str | None = None

    # Expected JWT audience (optional, for validation)
    auth_audience: str | None = None

    # Header name containing the JWT token
    auth_header_name: str = "authorization"

    # ==========================================================================
    # Policies Service
    # ==========================================================================
    # When enabled, authorization decisions are delegated to the policies service

    policies_enabled: bool = False

    # Policies service base URL
    policies_url: str = "http://api.celine.localhost/policies"

    # Policies service timeout in seconds
    policies_timeout: float = 5.0

    # Resource type to use when calling policies service
    # This identifies what kind of resource rec-registry manages
    policies_resource_type: str = "rec_registry"

    # Source service identifier sent to policies service
    policies_source_service: str = "rec-registry"


settings = Settings()
