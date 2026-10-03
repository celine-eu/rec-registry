"""
The startup posture check (REQ-0088) and the CLI's client-credential check (REQ-0089).

Only `CELINE_ENV=dev` relaxes either; unset and every other value are hardened.
The suite itself runs with `CELINE_ENV=dev` (conftest), so each test here sets
the signal it is about explicitly.
"""

from unittest.mock import AsyncMock, patch

import pytest
import typer
from celine.sdk.posture import InsecureConfiguration
from celine.sdk.settings.models import OidcSettings
from typer.testing import CliRunner

from celine.rec_registry.cli import main as cli
from celine.rec_registry.core.posture import enforce_posture, posture_guard
from celine.rec_registry.core.settings import Settings

DEV_DATABASE_URL = "postgresql+asyncpg://postgres:securepassword123@db:5432/rec_registry"
REAL_DATABASE_URL = "postgresql+asyncpg://rec_registry:Xk3-generated-9fQ@db:5432/rec_registry"

HARDENED = ["", "staging", "prod", "Dev-typo"]


def explicit_oidc(**overrides) -> OidcSettings:
    values = {
        "base_url": "https://auth.example.org/realms/example",
        "jwks_uri": "https://auth.example.org/realms/example/protocol/openid-connect/certs",
        "audience": "svc-rec-registry",
    }
    values.update(overrides)
    return OidcSettings(**values)


def hardened_settings(**overrides) -> Settings:
    """A configuration a deployment would pass: nothing left at a dev default."""
    values = {
        "_env_file": None,
        "database_url": REAL_DATABASE_URL,
        "auth_enabled": True,
        "policies_enabled": True,
        "oidc": explicit_oidc(),
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture(autouse=True)
def no_oidc_environment(monkeypatch):
    """An exported CELINE_OIDC_* would count as stated and hide the default."""
    for name in ("BASE_URL", "JWKS_URI", "CLIENT_ID", "CLIENT_SECRET", "AUDIENCE"):
        monkeypatch.delenv(f"CELINE_OIDC_{name}", raising=False)


@pytest.fixture
def no_env_signal(monkeypatch):
    monkeypatch.delenv("CELINE_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)


# =============================================================================
# Service startup
# =============================================================================


@pytest.mark.parametrize("env", HARDENED)
def test_a_hardened_environment_starts_with_real_values(env):
    """@verifies REQ-0088"""
    assert posture_guard(hardened_settings(), env=env).violations == []
    enforce_posture(hardened_settings(), env=env)


@pytest.mark.parametrize("env", HARDENED)
@pytest.mark.parametrize(
    "overrides, setting",
    [
        ({"database_url": DEV_DATABASE_URL}, "DATABASE_URL"),
        ({"auth_enabled": False}, "AUTH_ENABLED"),
        ({"policies_enabled": False}, "POLICIES_ENABLED"),
        ({"oidc": OidcSettings(audience="svc-rec-registry")}, "CELINE_OIDC_BASE_URL"),
        (
            {"oidc": explicit_oidc(client_id="svc-rec-registry", client_secret="svc-rec-registry")},
            "CELINE_OIDC_CLIENT_SECRET",
        ),
    ],
)
def test_a_hardened_environment_refuses_each_development_setting(env, overrides, setting):
    """@verifies REQ-0088"""
    with pytest.raises(InsecureConfiguration) as exc:
        enforce_posture(hardened_settings(**overrides), env=env)
    assert setting in str(exc.value)


def test_an_unset_signal_is_hardened(no_env_signal):
    """@verifies REQ-0088"""
    with pytest.raises(InsecureConfiguration):
        enforce_posture(hardened_settings(policies_enabled=False))


def test_environment_is_read_when_celine_env_is_unset(no_env_signal, monkeypatch):
    """@verifies REQ-0088"""
    monkeypatch.setenv("ENVIRONMENT", "dev")
    enforce_posture(hardened_settings(policies_enabled=False))


def test_every_violation_is_named_at_once():
    """@verifies REQ-0088"""
    dev_defaults = Settings(
        _env_file=None,
        database_url=DEV_DATABASE_URL,
        auth_enabled=False,
        policies_enabled=False,
        oidc=OidcSettings(client_id="svc-rec-registry", client_secret="svc-rec-registry"),
    )
    with pytest.raises(InsecureConfiguration) as exc:
        enforce_posture(dev_defaults, env="staging")
    message = str(exc.value)
    for setting in (
        "DATABASE_URL",
        "AUTH_ENABLED",
        "POLICIES_ENABLED",
        "CELINE_OIDC_BASE_URL",
        "CELINE_OIDC_JWKS_URI",
        "CELINE_OIDC_CLIENT_SECRET",
    ):
        assert setting in message


def test_dev_starts_with_every_development_default():
    """@verifies REQ-0088"""
    dev_defaults = Settings(
        _env_file=None,
        database_url=DEV_DATABASE_URL,
        auth_enabled=False,
        policies_enabled=False,
        oidc=OidcSettings(client_id="svc-rec-registry", client_secret="svc-rec-registry"),
    )
    # The posture logger is patched rather than read through caplog: other tests
    # reconfigure logging, and a warning that did not propagate would read as none.
    with patch("celine.sdk.posture.log") as log:
        enforce_posture(dev_defaults, env="dev")
    rendered = log.warning.call_args.args[-1]
    assert "POLICIES_ENABLED" in rendered and "AUTH_ENABLED" in rendered


def test_create_app_refuses_the_suites_own_switches_when_the_signal_is_unset(no_env_signal):
    """@verifies REQ-0088

    The suite runs with AUTH_ENABLED=false and POLICIES_ENABLED=false; the app
    factory itself refuses them before the policy middleware is installed.
    """
    from celine.rec_registry.main import create_app

    with pytest.raises(InsecureConfiguration) as exc:
        create_app()
    assert "POLICIES_ENABLED" in str(exc.value)


def test_create_app_refuses_them_under_staging(monkeypatch):
    """@verifies REQ-0088"""
    from celine.rec_registry.main import create_app

    monkeypatch.setenv("CELINE_ENV", "staging")
    with pytest.raises(InsecureConfiguration):
        create_app()


def test_create_app_starts_in_dev(monkeypatch):
    """@verifies REQ-0088"""
    from celine.rec_registry.main import create_app

    monkeypatch.setenv("CELINE_ENV", "dev")
    assert create_app().title == "CELINE REC Registry API"


# =============================================================================
# CLI client credentials
# =============================================================================

TOKEN_FN = "celine.rec_registry.cli.main._get_token_from_client_credentials"


def resolve(client_id: str, client_secret: str) -> str:
    return cli._resolve_auth(
        token=None,
        client_id=client_id,
        client_secret=client_secret,
        user=None,
        password=None,
        auth_url="https://auth.example.org/realms/example",
    )


@pytest.mark.parametrize("env", ["", "staging"])
def test_the_cli_refuses_a_secret_equal_to_its_client_id_outside_dev(env, monkeypatch):
    """@verifies REQ-0089"""
    monkeypatch.setenv("CELINE_ENV", env)
    fetch = AsyncMock(return_value="token")
    with patch(TOKEN_FN, fetch), pytest.raises(typer.BadParameter) as exc:
        resolve("celine-cli", "celine-cli")
    assert "client id" in str(exc.value)
    fetch.assert_not_called()


def test_the_cli_refuses_it_with_no_signal_at_all(no_env_signal):
    """@verifies REQ-0089"""
    result = CliRunner().invoke(
        cli.app,
        ["list", "--client-id", "celine-cli", "--client-secret", "celine-cli"],
    )
    assert result.exit_code != 0
    assert "refusing" in result.output


def test_the_cli_uses_a_real_secret_outside_dev(monkeypatch):
    """@verifies REQ-0089"""
    monkeypatch.setenv("CELINE_ENV", "staging")
    with patch(TOKEN_FN, AsyncMock(return_value="token")):
        assert resolve("svc-operator", "Xk3-generated-9fQ") == "token"


def test_the_cli_uses_the_development_secret_in_dev(monkeypatch):
    """@verifies REQ-0089"""
    monkeypatch.setenv("CELINE_ENV", "dev")
    with patch(TOKEN_FN, AsyncMock(return_value="token")):
        assert resolve("celine-cli", "celine-cli") == "token"


def test_a_token_needs_no_client_credentials_check(no_env_signal):
    """@verifies REQ-0089"""
    assert (
        cli._resolve_auth(
            token="jwt",
            client_id="celine-cli",
            client_secret="celine-cli",
            user=None,
            password=None,
            auth_url="https://auth.example.org/realms/example",
        )
        == "jwt"
    )
