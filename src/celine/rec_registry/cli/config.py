"""
CLI-specific settings for REC Registry.

Separate from service settings to avoid dependency bloat in CLI.
Shares .env file with service but uses CLI_ prefix for CLI-specific overrides.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CLISettings(BaseSettings):
    """Settings for REC Registry CLI.

    Environment variable resolution:
    1. CLI_* prefixed vars (highest priority)
    2. Unprefixed vars (shared with service)
    3. Default values

    Example .env:
        # Shared settings
        BASE_URL=http://api.celine.localhost/rec-registry
        AUTH_ENABLED=true

        # CLI-specific overrides
        CLI_BASE_URL=http://localhost:8002  # CLI uses different URL
        CLI_DEFAULT_TIMEOUT=60.0             # CLI has longer timeout
    """

    model_config = SettingsConfigDict(
        env_prefix="CLI_",  # Try CLI_* first
        env_file=".env",  # Load from .env
        env_file_encoding="utf-8",
        extra="ignore",  # Ignore service-specific settings
    )

    # =========================================================================
    # API Connection
    # =========================================================================

    base_url: str = Field(
        default="http://api.celine.localhost/rec-registry",
        description="Registry API base URL",
    )

    default_timeout: float = Field(
        default=30.0,
        description="Default HTTP timeout in seconds",
    )

    # =========================================================================
    # Authentication (OIDC)
    # =========================================================================

    oidc_base_url: str | None = Field(
        default="http://keycloak.celine.localhost/realms/celine",
        description="OIDC/Keycloak realm URL for token acquisition",
    )

    oidc_verify_ssl: bool = Field(
        default=True,
        description="Verify TLS on OIDC/Keycloak requests",
    )

    # Default client credentials (can be overridden per-command)
    client_id: str | None = Field(
        default="celine-cli",
        description="Default OAuth2 client ID",
    )

    client_secret: str | None = Field(
        default="celine-cli",
        description="Default OAuth2 client secret",
    )

    # Default user credentials (can be overridden per-command)
    username: str | None = Field(
        default=None,
        description="Default username for password grant",
    )

    password: str | None = Field(
        default=None,
        description="Default password for password grant",
    )

    # Default token (can be overridden per-command)
    token: str | None = Field(
        default=None,
        description="Pre-obtained JWT token",
    )

    scope: str | None = Field(
        default=None,
        description="OAuth2 scope to request",
    )

    # =========================================================================
    # CLI Behavior
    # =========================================================================

    output_format: str = Field(
        default="text",
        description="Default output format (text, json, yaml)",
    )

    color_output: bool = Field(
        default=True,
        description="Enable colored output",
    )

    verbose: bool = Field(
        default=False,
        description="Enable verbose logging",
    )


# Global settings instance
settings = CLISettings()
