"""
Application settings using pydantic-settings.
"""

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from celine.sdk.settings.models import OidcSettings, PoliciesSettings


def _policies_settings() -> PoliciesSettings:
    # The same `.env` the rest of Settings reads: a nested settings model only
    # sees the process environment otherwise.
    return PoliciesSettings(_env_file=".env", _env_file_encoding="utf-8")


#: The shortest `POD_HMAC_KEY` the service starts with (REQ-0105).
POD_HMAC_KEY_MIN_LENGTH = 32


class Settings(BaseSettings):
    # `hide_input_in_errors`: a refused value — the POD key among them — is never
    # echoed by the validation error that stops the service.
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", hide_input_in_errors=True
    )

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

    # =============================================================================
    # POD pseudonymisation (REQ-0105)
    # =============================================================================

    # `POD_HMAC_KEY`. Set only where PODs live (prod): both member exports then
    # carry each member's PODs as HMAC-SHA256 hashes under it. Unset (or empty),
    # they carry no hash field at all. Never logged, never exported, never shared:
    # PODs are a small space, so the key holder can rebuild the mapping. Changing
    # it orphans every hash computed before.
    pod_hmac_key: SecretStr | None = Field(
        default=None,
        description="HMAC key for POD hashes in the member exports; at least 32 characters",
    )

    @field_validator("pod_hmac_key", mode="before")
    @classmethod
    def _empty_pod_hmac_key_is_unset(cls, value):
        if value is None or (isinstance(value, str) and value == ""):
            return None
        return value

    @field_validator("pod_hmac_key")
    @classmethod
    def _pod_hmac_key_is_long_enough(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            secret = value.get_secret_value()
            if len(secret) < POD_HMAC_KEY_MIN_LENGTH or not secret.strip():
                raise ValueError(
                    f"POD_HMAC_KEY must be at least {POD_HMAC_KEY_MIN_LENGTH} characters"
                )
        return value


settings = Settings()
