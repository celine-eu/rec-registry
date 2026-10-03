"""Startup posture check: development defaults are refused outside ``CELINE_ENV=dev``.

The service ships zero-config development defaults — the local stack's database
password, the local Keycloak as issuer, and two switches (`AUTH_ENABLED`,
`POLICIES_ENABLED`) the test suite turns off. Each is safe only because
something refuses it when the environment does not say it is development; this
module is that something (REQ-0088).

The rule is `celine.sdk.posture`'s, shared by every service: only
`CELINE_ENV=dev` (or `ENVIRONMENT=dev`) relaxes, and unset is hardened. In dev
each violation is logged as one warning; anywhere else startup raises
`InsecureConfiguration` naming all of them at once.

`POLICIES_ENABLED=false` is the dangerous one: with the policy engine off,
`/admin*` only asks for a validly signed token, so any token the issuer signs —
any user, any service account — gets every admin read, write and purge.
"""

from __future__ import annotations

# `celine.sdk.posture` lands in the celine-sdk release after 1.24.0.
# TODO: raise the `celine-sdk` floor in pyproject.toml once that release is out.
from celine.sdk.posture import PostureGuard

from celine.rec_registry.core.settings import Settings

SERVICE = "rec-registry"


def posture_guard(settings: Settings, env: str | None = None) -> PostureGuard:
    """Register every development-only setting of the service on one guard.

    ``env`` overrides the environment signal, for tests; ``None`` reads
    ``CELINE_ENV`` then ``ENVIRONMENT``.
    """
    guard = PostureGuard(SERVICE, env=env)
    guard.forbid_dev_database_url("DATABASE_URL", settings.database_url)
    guard.forbid_false(
        "AUTH_ENABLED",
        settings.auth_enabled,
        "Remove AUTH_ENABLED or set it to true.",
    )
    guard.forbid_false(
        "POLICIES_ENABLED",
        settings.policies_enabled,
        "Remove POLICIES_ENABLED or set it to true: with policies off any validly "
        "signed token is a full administrator of /admin.",
    )
    guard.require_explicit_oidc(settings.oidc)
    guard.forbid_secret_equal_to_client_id(
        "CELINE_OIDC_CLIENT_SECRET",
        settings.oidc.client_id,
        settings.oidc.client_secret,
    )
    return guard


def enforce_posture(settings: Settings, env: str | None = None) -> None:
    """Warn in dev; raise `InsecureConfiguration` anywhere else."""
    posture_guard(settings, env=env).enforce()
