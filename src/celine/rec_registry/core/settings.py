"""
Application settings using pydantic-settings.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from celine.sdk.settings.models import OidcSettings, PoliciesSettings


def _policies_settings() -> PoliciesSettings:
    # The same `.env` the rest of Settings reads: a nested settings model only
    # sees the process environment otherwise.
    return PoliciesSettings(_env_file=".env", _env_file_encoding="utf-8")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = (
        "postgresql+asyncpg://postgres:securepassword123@host.docker.internal:15432/celine_rec_registry"
    )
    database_echo: bool = False

    # API
    base_url: str = "http://api.celine.localhost/rec-registry"

    # Pagination defaults
    default_page_size: int = 50
    max_page_size: int = 500

    oidc: OidcSettings = OidcSettings(audience="svc-rec-registry")

    auth_enabled: bool = True
    auth_header_name: str = "authorization"

    # =============================================================================

    # Policy Settings - UPDATED for in-process evaluation
    # =============================================================================

    policies_enabled: bool = Field(
        default=True, description="Enable policy-based authorization"
    )

    # The bundle and its decision cache: the platform's CELINE_POLICIES_DIR,
    # _DATA_DIR and _CACHE_*, read by the SDK as every other service reads them.
    policies: PoliciesSettings = Field(default_factory=_policies_settings)

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


settings = Settings()
