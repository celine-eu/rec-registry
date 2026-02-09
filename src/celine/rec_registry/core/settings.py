"""
Application settings using pydantic-settings.
"""

from pathlib import Path
from pydantic import Field
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

    auth_enabled: bool = True

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

    # =============================================================================
    # Policy Settings - UPDATED for in-process evaluation
    # =============================================================================

    policies_enabled: bool = Field(
        default=True, description="Enable policy-based authorization"
    )

    # Policy engine settings (replaces policies_url)
    policies_dir: Path = Field(
        default=Path("./policies"),
        description="Directory containing .rego policy files",
    )
    policies_data_dir: Path | None = Field(
        default=None, description="Optional directory containing policy data JSON files"
    )

    # Policy package to evaluate (service-specific)
    policies_package: str = Field(
        default="celine.rec_registry.access",
        description="Policy package to evaluate for authorization",
    )

    # Resource type for this service
    policies_resource_type: str = Field(
        default="rec_registry", description="Resource type for policy evaluation"
    )

    # Source service identifier (for audit logging)
    policies_source_service: str = Field(
        default="rec-registry", description="Service identifier for audit logs"
    )

    # Cache settings
    policies_cache_enabled: bool = Field(
        default=True, description="Enable in-memory decision caching"
    )
    policies_cache_ttl: int = Field(default=300, description="Cache TTL in seconds")
    policies_cache_maxsize: int = Field(
        default=10000, description="Maximum cache entries"
    )


settings = Settings()
