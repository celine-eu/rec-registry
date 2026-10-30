"""
CELINE REC Registry CLI.

Commands:
- import: Import a v0.4 YAML bundle (idempotent)
- export: Export a community to v0.4 YAML
- list: List communities
- tree: Show community structure
- lookup: Lookup by user_id or sensor_id
- duplicate-sensors: Report sensor ids held by more than one active member (read-only)
- duplicate-delivery-points: Report delivery points held by more than one active member (read-only)
- out-of-set-values: Report members whose role, status or area is out of set (read-only)
- invalid-area-boundaries: Report stored areas breaking the one-substation rule (read-only)
- backfill-subjects: Fill in members' account subjects from Keycloak, by username (dry run by default)

Authentication:
- Client credentials: --client-id + --client-secret (admin operations)
- User credentials: --user + --password (user operations)
- Token: --token (pre-obtained JWT)
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import typer
import yaml

from celine.sdk.auth import OidcClientCredentialsProvider
from celine.sdk.posture import InsecureConfiguration, PostureGuard
from celine.rec_registry.cli.config import settings
from celine.rec_registry.core.area_boundary import (
    area_boundary_refusals,
    area_key_refusals,
)
# `find_duplicate_delivery_points` lives with the compared form, so the CLI and
# the per-community read (REQ-0087) share one definition of a duplicate.
from celine.rec_registry.core.delivery_point_id import find_duplicate_delivery_points
from celine.rec_registry.core.member_values import member_value_refusals
from celine.rec_registry.core.sensor_id import normalise_sensor_id

app = typer.Typer(name="celine-rec-registry", no_args_is_help=True)


# =============================================================================
# Authentication Helpers
# =============================================================================


async def _get_token_from_client_credentials(
    auth_url: str,
    client_id: str,
    client_secret: str,
    scope: str | None = None,
    verify_ssl: bool = True,
) -> str:
    """Get access token using client credentials flow."""
    provider = OidcClientCredentialsProvider(
        base_url=auth_url,
        client_id=client_id,
        client_secret=client_secret,
        scope=scope,
        verify_ssl=verify_ssl,
    )

    access_token = await provider.get_token()
    return access_token.access_token


async def _get_token_from_password(
    auth_url: str,
    username: str,
    password: str,
    client_id: str = "cli",
    scope: str | None = None,
) -> str:
    """Get access token using resource owner password flow."""
    # OIDC token endpoint
    token_url = f"{auth_url.rstrip('/')}/protocol/openid-connect/token"

    data = {
        "grant_type": "password",
        "username": username,
        "password": password,
        "client_id": client_id,
    }

    if scope:
        data["scope"] = scope

    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, data=data)

        if response.status_code != 200:
            raise typer.BadParameter(
                f"Authentication failed [{response.status_code}]: {response.text}"
            )

        token_data = response.json()
        return token_data["access_token"]


def _enforce_client_credentials_posture(client_id: str, client_secret: str) -> None:
    """Refuse a development client secret outside ``CELINE_ENV=dev``.

    Locally every client's secret equals its id (``celine-cli``/``celine-cli``
    is the CLI's own), so outside dev a secret equal to the id can only be a
    default nobody replaced. In dev the guard warns and the CLI proceeds.
    """
    guard = PostureGuard("celine-rec-registry CLI")
    guard.forbid_secret_equal_to_client_id(
        "--client-secret / REGISTRY_CLIENT_SECRET",
        client_id,
        client_secret,
        remediation="Pass the client's real secret, or a --token.",
    )
    try:
        guard.enforce()
    except InsecureConfiguration as exc:
        raise typer.BadParameter(str(exc)) from exc


def _resolve_auth(
    token: str | None,
    client_id: str | None,
    client_secret: str | None,
    user: str | None,
    password: str | None,
    auth_url: str,
    scope: str | None = None,
    verify_ssl: bool = True,
) -> str:
    """Resolve authentication and return access token.

    Priority:
    1. Explicit token
    2. Client credentials
    3. User credentials
    4. Error
    """
    if token:
        return token

    if client_id and client_secret:
        # Client credentials flow. A secret equal to its client id is the local
        # realm's convention, and refused before it is sent anywhere unless
        # CELINE_ENV=dev (REQ-0089).
        _enforce_client_credentials_posture(client_id, client_secret)
        return asyncio.run(
            _get_token_from_client_credentials(
                auth_url=auth_url,
                client_id=client_id,
                client_secret=client_secret,
                scope=scope,
                verify_ssl=verify_ssl,
            )
        )

    if user and password:
        # Resource owner password flow
        return asyncio.run(
            _get_token_from_password(
                auth_url=auth_url,
                username=user,
                password=password,
                scope=scope,
            )
        )

    raise typer.BadParameter(
        "Authentication required. Provide one of:\n"
        "  --token <jwt>\n"
        "  --client-id <id> --client-secret <secret>\n"
        "  --user <username> --password <password>"
    )


# =============================================================================
# Common Options
# =============================================================================


def _common_auth_options():
    """Common authentication options."""
    return [
        typer.Option(
            None,
            "--token",
            help="Pre-obtained JWT access token",
            envvar="REGISTRY_TOKEN",
        ),
        typer.Option(
            None,
            "--client-id",
            help="OAuth2 client ID (for admin operations)",
            envvar="REGISTRY_CLIENT_ID",
        ),
        typer.Option(
            None,
            "--client-secret",
            help="OAuth2 client secret",
            envvar="REGISTRY_CLIENT_SECRET",
        ),
        typer.Option(
            None,
            "--user",
            help="Username (for user operations)",
            envvar="REGISTRY_USER",
        ),
        typer.Option(
            None,
            "--password",
            help="User password",
            envvar="REGISTRY_PASSWORD",
        ),
        typer.Option(
            settings.oidc_base_url or "http://localhost:8080/realms/celine",
            "--auth-url",
            help="OIDC/Keycloak realm URL",
            envvar="REGISTRY_AUTH_URL",
        ),
        typer.Option(
            None,
            "--scope",
            help="OAuth2 scope (optional)",
            envvar="REGISTRY_SCOPE",
        ),
    ]


def _api_url(base: str, path: str) -> str:
    """Construct API URL."""
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _get_json(
    client: httpx.Client,
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """GET request returning JSON."""
    r = client.get(url, params=params, headers=headers or {})
    if r.status_code >= 400:
        raise typer.BadParameter(f"GET {url} failed [{r.status_code}]: {r.text}")
    data = r.json()
    if not isinstance(data, dict):
        raise typer.BadParameter(f"GET {url} returned non-object JSON")
    return data


# =============================================================================
# Import Command
# =============================================================================


@app.command("import")
def import_bundle(
    file: Path = typer.Option(
        ...,
        "--file",
        "-f",
        exists=True,
        readable=True,
        help="YAML bundle file",
    ),
    api: str = typer.Option(
        settings.base_url,
        "--api",
        help="Registry API base URL",
        envvar="REGISTRY_API_URL",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate without writing to database",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help=(
            "Overwrite a community that already exists. Import is destructive: "
            "it deletes the community with every member and asset, then "
            "recreates it from the file. Without this an existing community is "
            "refused. Try --dry-run first to see what would go."
        ),
    ),
    timeout: float = typer.Option(
        60.0,
        "--timeout",
        help="HTTP timeout in seconds",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        help="Pre-obtained JWT access token",
        envvar="REGISTRY_TOKEN",
    ),
    client_id: str | None = typer.Option(
        None,
        "--client-id",
        help="OAuth2 client ID (for admin operations)",
        envvar="REGISTRY_CLIENT_ID",
    ),
    client_secret: str | None = typer.Option(
        None,
        "--client-secret",
        help="OAuth2 client secret",
        envvar="REGISTRY_CLIENT_SECRET",
    ),
    user: str | None = typer.Option(
        None,
        "--user",
        help="Username (for user operations)",
        envvar="REGISTRY_USER",
    ),
    password: str | None = typer.Option(
        None,
        "--password",
        help="User password",
        envvar="REGISTRY_PASSWORD",
    ),
    auth_url: str = typer.Option(
        settings.oidc_base_url or "http://keycloak.celine.localhost/realms/celine",
        "--auth-url",
        help="OIDC/Keycloak realm URL",
        envvar="REGISTRY_AUTH_URL",
    ),
    scope: str | None = typer.Option(
        None,
        "--scope",
        help="OAuth2 scope (optional)",
        envvar="REGISTRY_SCOPE",
    ),
):
    """
    Import a YAML bundle (idempotent replacement import).

    Requires admin authentication (client credentials).
    
    Examples:
        # With client credentials
        celine-rec-registry import -f bundle.yaml \\
            --client-id admin --client-secret secret
        
        # With pre-obtained token
        celine-rec-registry import -f bundle.yaml --token $TOKEN
        
        # Using environment variables
        export REGISTRY_CLIENT_ID=admin
        export REGISTRY_CLIENT_SECRET=secret
        celine-rec-registry import -f bundle.yaml
    """
    # Resolve authentication
    access_token = _resolve_auth(
        token=token,
        client_id=client_id,
        client_secret=client_secret,
        user=user,
        password=password,
        auth_url=auth_url,
        scope=scope,
        verify_ssl=settings.oidc_verify_ssl,
    )

    yaml_text = file.read_text(encoding="utf-8")

    # Validate YAML locally before sending
    try:
        docs = list(yaml.safe_load_all(yaml_text))
        docs = [d for d in docs if d is not None]
    except yaml.YAMLError as e:
        typer.secho(f"Invalid YAML: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if not docs:
        typer.secho("No YAML documents found in file", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    url = _api_url(api, "/admin/import/yaml")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/yaml",
    }

    try:
        r = httpx.post(
            url,
            content=yaml_text.encode("utf-8"),
            params={
                "dry_run": str(dry_run).lower(),
                "force": str(force).lower(),
            },
            headers=headers,
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        typer.secho(f"HTTP error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if r.status_code == 409:
        typer.secho(f"Refused: {r.text}", fg=typer.colors.YELLOW, err=True)
        typer.secho(
            "Re-run with --dry-run to see the effect, or --force to accept it.",
            err=True,
        )
        raise typer.Exit(1)

    if r.status_code >= 400:
        typer.secho(
            f"Import failed [{r.status_code}]:\n{r.text}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)

    result = r.json()
    reports = result.get("reports", [])

    if dry_run:
        typer.secho("Dry run completed (no changes made)", fg=typer.colors.YELLOW)
    else:
        typer.secho("Import completed successfully", fg=typer.colors.GREEN)

    for report in reports:
        typer.echo(f"Community: {report.get('community_key')}")
        typer.echo(f"  Deleted: {report.get('deleted')}")
        typer.echo(f"  Inserted: {report.get('inserted')}")
        warnings = report.get("warnings", [])
        if warnings:
            typer.secho(f"  Warnings ({len(warnings)}):", fg=typer.colors.YELLOW)
            for w in warnings:
                typer.echo(f"    - {w}")


# =============================================================================
# Export Command
# =============================================================================


@app.command("export")
def export_bundle(
    community: list[str] | None = typer.Option(
        None,
        "--community",
        "-c",
        help="Community key to export (repeat for multiple; omit to export all)",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file (default: stdout)",
    ),
    api: str = typer.Option(
        settings.base_url,
        "--api",
        help="Registry API base URL",
    ),
    timeout: float = typer.Option(
        30.0,
        "--timeout",
        help="HTTP timeout in seconds",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        help="Pre-obtained JWT access token",
        envvar="REGISTRY_TOKEN",
    ),
    client_id: str | None = typer.Option(
        None,
        "--client-id",
        help="OAuth2 client ID",
        envvar="REGISTRY_CLIENT_ID",
    ),
    client_secret: str | None = typer.Option(
        None,
        "--client-secret",
        help="OAuth2 client secret",
        envvar="REGISTRY_CLIENT_SECRET",
    ),
    user: str | None = typer.Option(
        None,
        "--user",
        help="Username",
        envvar="REGISTRY_USER",
    ),
    password: str | None = typer.Option(
        None,
        "--password",
        help="User password",
        envvar="REGISTRY_PASSWORD",
    ),
    auth_url: str = typer.Option(
        settings.oidc_base_url or "http://localhost:8080/realms/celine",
        "--auth-url",
        help="OIDC/Keycloak realm URL",
        envvar="REGISTRY_AUTH_URL",
    ),
    scope: str | None = typer.Option(
        None,
        "--scope",
        help="OAuth2 scope",
        envvar="REGISTRY_SCOPE",
    ),
):
    """
    Export one or more communities to YAML format.

    Pass --community once per key to export specific communities.
    Omit --community entirely to export all communities.
    Multiple communities are returned as a multidocument YAML (--- separated).

    Requires admin authentication.
    """
    access_token = _resolve_auth(
        token=token,
        client_id=client_id,
        client_secret=client_secret,
        user=user,
        password=password,
        auth_url=auth_url,
        scope=scope,
        verify_ssl=settings.oidc_verify_ssl,
    )

    url = _api_url(api, "/admin/export")
    headers = {"Authorization": f"Bearer {access_token}"}
    params = [("community", key) for key in community] if community else []

    try:
        r = httpx.get(url, params=params, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        typer.secho(f"HTTP error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if r.status_code >= 400:
        typer.secho(
            f"Export failed [{r.status_code}]: {r.text}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)

    yaml_text = r.text

    if output:
        output.write_text(yaml_text, encoding="utf-8")
        typer.secho(f"Exported to {output}", fg=typer.colors.GREEN)
    else:
        typer.echo(yaml_text)


# =============================================================================
# List Command
# =============================================================================


@app.command("list")
def list_communities(
    api: str = typer.Option(
        settings.base_url,
        "--api",
        help="Registry API base URL",
    ),
    key: str | None = typer.Option(
        None,
        "--key",
        help="Filter by community key",
    ),
    limit: int = typer.Option(
        200,
        "--limit",
        min=1,
        max=500,
        help="Maximum number of results",
    ),
    timeout: float = typer.Option(
        30.0,
        "--timeout",
        help="HTTP timeout in seconds",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        help="Pre-obtained JWT access token",
        envvar="REGISTRY_TOKEN",
    ),
    client_id: str | None = typer.Option(
        None,
        "--client-id",
        help="OAuth2 client ID",
        envvar="REGISTRY_CLIENT_ID",
    ),
    client_secret: str | None = typer.Option(
        None,
        "--client-secret",
        help="OAuth2 client secret",
        envvar="REGISTRY_CLIENT_SECRET",
    ),
    user: str | None = typer.Option(
        None,
        "--user",
        help="Username",
        envvar="REGISTRY_USER",
    ),
    password: str | None = typer.Option(
        None,
        "--password",
        help="User password",
        envvar="REGISTRY_PASSWORD",
    ),
    auth_url: str = typer.Option(
        settings.oidc_base_url or "http://localhost:8080/realms/celine",
        "--auth-url",
        help="OIDC/Keycloak realm URL",
        envvar="REGISTRY_AUTH_URL",
    ),
    scope: str | None = typer.Option(
        None,
        "--scope",
        help="OAuth2 scope",
        envvar="REGISTRY_SCOPE",
    ),
):
    """
    List communities.

    Can use admin or user authentication.
    """
    access_token = _resolve_auth(
        token=token,
        client_id=client_id,
        client_secret=client_secret,
        user=user,
        password=password,
        auth_url=auth_url,
        scope=scope,
        verify_ssl=settings.oidc_verify_ssl,
    )

    url = _api_url(api, "/admin/communities")  # Use admin endpoint for listing
    params: dict[str, Any] = {"limit": limit}
    if key:
        params["key"] = key

    headers = {"Authorization": f"Bearer {access_token}"}

    with httpx.Client(timeout=timeout) as client:
        data = _get_json(client, url, params=params, headers=headers)

    items = data.get("items", [])
    if not items:
        typer.echo("No communities found.")
        raise typer.Exit(0)

    for c in sorted(items, key=lambda x: x.get("key", "")):
        typer.echo(f"- {c.get('key')}  {c.get('name') or ''}".rstrip())


# =============================================================================
# Tree Command
# =============================================================================


@app.command("tree")
def community_tree(
    community: str = typer.Option(
        ...,
        "--community",
        "-c",
        help="Community key",
    ),
    api: str = typer.Option(
        settings.base_url,
        "--api",
        help="Registry API base URL",
    ),
    timeout: float = typer.Option(
        30.0,
        "--timeout",
        help="HTTP timeout in seconds",
    ),
    max_items: int = typer.Option(
        500,
        "--max-items",
        min=1,
        max=5000,
        help="Maximum items per fetch",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        help="Pre-obtained JWT access token",
        envvar="REGISTRY_TOKEN",
    ),
    client_id: str | None = typer.Option(
        None,
        "--client-id",
        help="OAuth2 client ID",
        envvar="REGISTRY_CLIENT_ID",
    ),
    client_secret: str | None = typer.Option(
        None,
        "--client-secret",
        help="OAuth2 client secret",
        envvar="REGISTRY_CLIENT_SECRET",
    ),
    user: str | None = typer.Option(
        None,
        "--user",
        help="Username",
        envvar="REGISTRY_USER",
    ),
    password: str | None = typer.Option(
        None,
        "--password",
        help="User password",
        envvar="REGISTRY_PASSWORD",
    ),
    auth_url: str = typer.Option(
        settings.oidc_base_url or "http://localhost:8080/realms/celine",
        "--auth-url",
        help="OIDC/Keycloak realm URL",
        envvar="REGISTRY_AUTH_URL",
    ),
    scope: str | None = typer.Option(
        None,
        "--scope",
        help="OAuth2 scope",
        envvar="REGISTRY_SCOPE",
    ),
):
    """
    Show community structure tree.
    """
    access_token = _resolve_auth(
        token=token,
        client_id=client_id,
        client_secret=client_secret,
        user=user,
        password=password,
        auth_url=auth_url,
        scope=scope,
        verify_ssl=settings.oidc_verify_ssl,
    )

    headers = {"Authorization": f"Bearer {access_token}"}

    with httpx.Client(timeout=timeout) as client:
        # Fetch community
        c = _get_json(
            client, _api_url(api, f"/admin/communities/{community}"), headers=headers
        )

        # Fetch members
        members = _get_json(
            client,
            _api_url(api, f"/admin/communities/{community}/members"),
            params={"limit": max_items},
            headers=headers,
        ).get("items", [])

        # Fetch assets
        assets = _get_json(
            client,
            _api_url(api, f"/admin/communities/{community}/assets"),
            params={"limit": max_items},
            headers=headers,
        ).get("items", [])

    # Index assets by owner
    assets_by_owner: dict[str, list[dict]] = {}
    for a in assets:
        owner_key = a.get("owner_key", "UNKNOWN")
        assets_by_owner.setdefault(owner_key, []).append(a)

    # Print tree
    typer.echo(f"{c.get('key')}  {c.get('name') or ''}".rstrip())
    typer.echo(f"  description: {c.get('description') or '-'}")

    # Areas
    areas = c.get("areas", {})
    if areas:
        typer.echo(f"  areas ({len(areas)}):")
        for area_key, area_data in sorted(areas.items()):
            area_name = (
                area_data.get("name", area_key)
                if isinstance(area_data, dict)
                else area_key
            )
            typer.echo(f"    - {area_key}: {area_name}")

    # Summary
    typer.echo(f"  members: {len(members)}")
    typer.echo(f"  assets: {len(assets)}")

    # Members with their assets
    typer.echo("  members:")
    for m in sorted(members, key=lambda x: x.get("key", "")):
        m_key = m.get("key")
        m_name = m.get("name", "")
        m_role = m.get("role", "")
        m_user_id = m.get("user_id", "")

        member_assets = assets_by_owner.get(m_key, [])

        header = f"    - {m_key}"
        if m_name:
            header += f" ({m_name})"
        header += f" [{m_role}]"
        header += f"  user_id={m_user_id}"
        header += f"  assets={len(member_assets)}"
        typer.echo(header)

        # Group assets by type
        by_type: dict[str, list[dict]] = {}
        for a in member_assets:
            by_type.setdefault(a.get("asset_type", "unknown"), []).append(a)

        for asset_type, type_assets in sorted(by_type.items()):
            for a in sorted(type_assets, key=lambda x: x.get("key", "")):
                sensor = f" sensor={a.get('sensor_id')}" if a.get("sensor_id") else ""
                typer.echo(
                    f"        {asset_type}: {a.get('key')} {a.get('name', '')}{sensor}".rstrip()
                )


# =============================================================================
# Lookup Commands
# =============================================================================


@app.command("lookup-user")
def lookup_user(
    user_id: str = typer.Argument(..., help="User ID to lookup"),
    api: str = typer.Option(
        settings.base_url,
        "--api",
        help="Registry API base URL",
    ),
    timeout: float = typer.Option(
        30.0,
        "--timeout",
        help="HTTP timeout in seconds",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        help="Pre-obtained JWT access token",
        envvar="REGISTRY_TOKEN",
    ),
    client_id: str | None = typer.Option(
        None,
        "--client-id",
        help="OAuth2 client ID",
        envvar="REGISTRY_CLIENT_ID",
    ),
    client_secret: str | None = typer.Option(
        None,
        "--client-secret",
        help="OAuth2 client secret",
        envvar="REGISTRY_CLIENT_SECRET",
    ),
    user: str | None = typer.Option(
        None,
        "--user",
        help="Username",
        envvar="REGISTRY_USER",
    ),
    password: str | None = typer.Option(
        None,
        "--password",
        help="User password",
        envvar="REGISTRY_PASSWORD",
    ),
    auth_url: str = typer.Option(
        settings.oidc_base_url or "http://localhost:8080/realms/celine",
        "--auth-url",
        help="OIDC/Keycloak realm URL",
        envvar="REGISTRY_AUTH_URL",
    ),
    scope: str | None = typer.Option(
        None,
        "--scope",
        help="OAuth2 scope",
        envvar="REGISTRY_SCOPE",
    ),
):
    """
    Lookup a member by user_id across all communities.
    """
    access_token = _resolve_auth(
        token=token,
        client_id=client_id,
        client_secret=client_secret,
        user=user,
        password=password,
        auth_url=auth_url,
        scope=scope,
        verify_ssl=settings.oidc_verify_ssl,
    )

    url = _api_url(api, f"/admin/lookup/member-by-user-id/{user_id}")
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        r = httpx.get(url, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        typer.secho(f"HTTP error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if r.status_code == 404:
        typer.secho("User not found", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    if r.status_code >= 400:
        typer.secho(
            f"Lookup failed [{r.status_code}]: {r.text}", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(1)

    data = r.json()
    typer.echo(f"Community: {data.get('community_key')} ({data.get('community_name')})")
    typer.echo(f"Member: {data.get('key')} ({data.get('name')})")
    typer.echo(f"User ID: {data.get('user_id')}")
    typer.echo(f"Role: {data.get('role')}")
    typer.echo(f"Status: {data.get('status')}")


@app.command("lookup-sensor")
def lookup_sensor(
    sensor_id: str = typer.Argument(..., help="Sensor ID to lookup"),
    api: str = typer.Option(
        settings.base_url,
        "--api",
        help="Registry API base URL",
    ),
    timeout: float = typer.Option(
        30.0,
        "--timeout",
        help="HTTP timeout in seconds",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        help="Pre-obtained JWT access token",
        envvar="REGISTRY_TOKEN",
    ),
    client_id: str | None = typer.Option(
        None,
        "--client-id",
        help="OAuth2 client ID",
        envvar="REGISTRY_CLIENT_ID",
    ),
    client_secret: str | None = typer.Option(
        None,
        "--client-secret",
        help="OAuth2 client secret",
        envvar="REGISTRY_CLIENT_SECRET",
    ),
    user: str | None = typer.Option(
        None,
        "--user",
        help="Username",
        envvar="REGISTRY_USER",
    ),
    password: str | None = typer.Option(
        None,
        "--password",
        help="User password",
        envvar="REGISTRY_PASSWORD",
    ),
    auth_url: str = typer.Option(
        settings.oidc_base_url or "http://localhost:8080/realms/celine",
        "--auth-url",
        help="OIDC/Keycloak realm URL",
        envvar="REGISTRY_AUTH_URL",
    ),
    scope: str | None = typer.Option(
        None,
        "--scope",
        help="OAuth2 scope",
        envvar="REGISTRY_SCOPE",
    ),
):
    """
    Lookup a meter by sensor_id across all communities.
    """
    access_token = _resolve_auth(
        token=token,
        client_id=client_id,
        client_secret=client_secret,
        user=user,
        password=password,
        auth_url=auth_url,
        scope=scope,
        verify_ssl=settings.oidc_verify_ssl,
    )

    url = _api_url(api, f"/admin/lookup/asset-by-sensor-id/{sensor_id}")
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        r = httpx.get(url, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        typer.secho(f"HTTP error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if r.status_code == 404:
        typer.secho("Sensor not found", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    if r.status_code >= 400:
        typer.secho(
            f"Lookup failed [{r.status_code}]: {r.text}", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(1)

    data = r.json()
    typer.echo(f"Community: {data.get('community_key')} ({data.get('community_name')})")
    typer.echo(f"Owner: {data.get('owner_key')} (user_id: {data.get('owner_user_id')})")
    typer.echo(f"Asset: {data.get('key')} ({data.get('name')})")
    typer.echo(f"Type: {data.get('asset_type')}")
    typer.echo(f"Sensor ID: {data.get('sensor_id')}")


# =============================================================================
# Read-only reports over one export
# =============================================================================


def _read_export(api: str, access_token: str, timeout: float) -> list[dict[str, Any]]:
    """Every community, from one ``GET /admin/export``; exit ``2`` if unreadable.

    The reports below write nothing and issue no other request, and an
    unreadable registry is never reported as clean.
    """
    url = _api_url(api, "/admin/export")
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        r = httpx.get(url, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        typer.secho(f"HTTP error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)

    if r.status_code >= 400:
        typer.secho(
            f"Export failed [{r.status_code}]: {r.text}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)

    try:
        return [d for d in yaml.safe_load_all(r.text) if d is not None]
    except yaml.YAMLError as exc:
        typer.secho(f"Unreadable export: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)


# =============================================================================
# Duplicate Sensors Report
# =============================================================================


def find_duplicate_sensors(
    bundles: list[dict[str, Any]],
) -> list[tuple[str, list[tuple[str, str]]]]:
    """Every trimmed sensor id held by more than one active member.

    Reads exported bundles, as `GET /admin/export` answers them, and returns
    ``(sensor id, [(community key, member key), …])`` sorted by id. Only an
    ``active`` member holds a sensor (REQ-0069), and ids are compared trimmed
    — by ``normalise_sensor_id``, the registry's own definition, so ` SEN-1`,
    `\tSEN-1\n` and `SEN-1` are one. A member holding one id under two asset
    keys is one holder, not two.
    """
    holders: dict[str, set[tuple[str, str]]] = {}
    for bundle in bundles:
        if not isinstance(bundle, dict):
            continue
        community_key = str((bundle.get("community") or {}).get("id", ""))
        for member_key, member in (bundle.get("members") or {}).items():
            if not isinstance(member, dict) or member.get("status") != "active":
                continue
            meters = ((member.get("assets") or {}).get("meter")) or {}
            for meter in meters.values():
                sensor_id = normalise_sensor_id(
                    str((meter or {}).get("sensor_id") or "")
                )
                if sensor_id:
                    holders.setdefault(sensor_id, set()).add(
                        (community_key, str(member_key))
                    )
    return [
        (sensor_id, sorted(held_by))
        for sensor_id, held_by in sorted(holders.items())
        if len(held_by) > 1
    ]


@app.command("duplicate-sensors")
def duplicate_sensors(
    api: str = typer.Option(
        settings.base_url,
        "--api",
        help="Registry API base URL",
        envvar="REGISTRY_API_URL",
    ),
    timeout: float = typer.Option(
        60.0,
        "--timeout",
        help="HTTP timeout in seconds",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        help="Pre-obtained JWT access token",
        envvar="REGISTRY_TOKEN",
    ),
    client_id: str | None = typer.Option(
        None,
        "--client-id",
        help="OAuth2 client ID",
        envvar="REGISTRY_CLIENT_ID",
    ),
    client_secret: str | None = typer.Option(
        None,
        "--client-secret",
        help="OAuth2 client secret",
        envvar="REGISTRY_CLIENT_SECRET",
    ),
    user: str | None = typer.Option(
        None,
        "--user",
        help="Username",
        envvar="REGISTRY_USER",
    ),
    password: str | None = typer.Option(
        None,
        "--password",
        help="User password",
        envvar="REGISTRY_PASSWORD",
    ),
    auth_url: str = typer.Option(
        settings.oidc_base_url or "http://localhost:8080/realms/celine",
        "--auth-url",
        help="OIDC/Keycloak realm URL",
        envvar="REGISTRY_AUTH_URL",
    ),
    scope: str | None = typer.Option(
        None,
        "--scope",
        help="OAuth2 scope",
        envvar="REGISTRY_SCOPE",
    ),
):
    """
    Report every sensor id held by more than one active member (read-only).

    The registry refuses the next write that would make a second active holder
    of a sensor, but it does not repair holders that already exist. This lists
    them — one line per holder: sensor id, community key, member key, and how
    many active members hold that id — so they can be resolved by hand before
    anyone relies on the check.

    Reads every community through GET /admin/export (the export grant) and
    writes nothing. Exits 0 when there are none, 1 when there are, and 2 when
    the registry cannot be read.
    """
    access_token = _resolve_auth(
        token=token,
        client_id=client_id,
        client_secret=client_secret,
        user=user,
        password=password,
        auth_url=auth_url,
        scope=scope,
        verify_ssl=settings.oidc_verify_ssl,
    )

    bundles = _read_export(api, access_token, timeout)

    duplicates = find_duplicate_sensors(bundles)
    if not duplicates:
        typer.secho(
            "No sensor id is held by more than one active member.",
            fg=typer.colors.GREEN,
        )
        return

    typer.echo("sensor_id\tcommunity\tmember\tactive_holders")
    for sensor_id, held_by in duplicates:
        for community_key, member_key in held_by:
            typer.echo(f"{sensor_id}\t{community_key}\t{member_key}\t{len(held_by)}")
    typer.secho(
        f"{len(duplicates)} sensor id(s) held by more than one active member.",
        fg=typer.colors.YELLOW,
        err=True,
    )
    raise typer.Exit(1)


# =============================================================================
# Duplicate Delivery Points Report
# =============================================================================


@app.command("duplicate-delivery-points")
def duplicate_delivery_points(
    api: str = typer.Option(
        settings.base_url,
        "--api",
        help="Registry API base URL",
        envvar="REGISTRY_API_URL",
    ),
    timeout: float = typer.Option(
        60.0,
        "--timeout",
        help="HTTP timeout in seconds",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        help="Pre-obtained JWT access token",
        envvar="REGISTRY_TOKEN",
    ),
    client_id: str | None = typer.Option(
        None,
        "--client-id",
        help="OAuth2 client ID",
        envvar="REGISTRY_CLIENT_ID",
    ),
    client_secret: str | None = typer.Option(
        None,
        "--client-secret",
        help="OAuth2 client secret",
        envvar="REGISTRY_CLIENT_SECRET",
    ),
    user: str | None = typer.Option(
        None,
        "--user",
        help="Username",
        envvar="REGISTRY_USER",
    ),
    password: str | None = typer.Option(
        None,
        "--password",
        help="User password",
        envvar="REGISTRY_PASSWORD",
    ),
    auth_url: str = typer.Option(
        settings.oidc_base_url or "http://localhost:8080/realms/celine",
        "--auth-url",
        help="OIDC/Keycloak realm URL",
        envvar="REGISTRY_AUTH_URL",
    ),
    scope: str | None = typer.Option(
        None,
        "--scope",
        help="OAuth2 scope",
        envvar="REGISTRY_SCOPE",
    ),
):
    """
    Report every delivery point (POD) held by more than one active member (read-only).

    The registry refuses the next write that would make a second active holder
    of a delivery point (REQ-0085) — including a re-send of either holder's
    point, a reactivation of either, and a re-import of either community — but
    it does not repair holders that already exist. This lists them — one line
    per holder: the delivery point (trimmed and lower-cased, the form the
    registry compares), community key, member key, and how many active members
    hold it — so an operator can resolve them before the check blocks either.

    Reads every community through GET /admin/export (the export grant) and
    writes nothing. Exits 0 when there are none, 1 when there are, and 2 when
    the registry cannot be read.
    """
    access_token = _resolve_auth(
        token=token,
        client_id=client_id,
        client_secret=client_secret,
        user=user,
        password=password,
        auth_url=auth_url,
        scope=scope,
        verify_ssl=settings.oidc_verify_ssl,
    )

    bundles = _read_export(api, access_token, timeout)

    duplicates = find_duplicate_delivery_points(bundles)
    if not duplicates:
        typer.secho(
            "No delivery point is held by more than one active member.",
            fg=typer.colors.GREEN,
        )
        return

    typer.echo("delivery_point\tcommunity\tmember\tactive_holders")
    for point_id, held_by in duplicates:
        for community_key, member_key in held_by:
            typer.echo(f"{point_id}\t{community_key}\t{member_key}\t{len(held_by)}")
    typer.secho(
        f"{len(duplicates)} delivery point(s) held by more than one active member.",
        fg=typer.colors.YELLOW,
        err=True,
    )
    raise typer.Exit(1)


# =============================================================================
# Out-of-set Values Report
# =============================================================================


_MISSING = "<missing>"


def find_out_of_set_values(
    bundles: list[dict[str, Any]],
) -> list[tuple[str, str, str, str]]:
    """Every member field the registry's write paths would now refuse.

    Reads exported bundles, as ``GET /admin/export`` answers them, and returns
    ``(community key, member key, field, value)`` sorted, for each member
    whose ``role`` or ``status`` is outside its set, or whose ``area`` is not
    a key of its community's ``areas`` (REQ-0066) — judged by
    ``member_value_refusals``, the check the writes themselves run, so the
    report and the check cannot disagree. A field the export does not carry is
    reported with the value ``<missing>``.
    """
    found: list[tuple[str, str, str, str]] = []
    for bundle in bundles:
        if not isinstance(bundle, dict):
            continue
        community = bundle.get("community") or {}
        community_key = str(community.get("id", ""))
        areas = list((community.get("areas") or {}).keys())
        for member_key, member in (bundle.get("members") or {}).items():
            if not isinstance(member, dict):
                continue
            for out in member_value_refusals(
                role=member.get("role"),
                status=member.get("status"),
                area=member.get("area"),
                areas=areas,
            ):
                value = _MISSING if out.value is None else str(out.value)
                found.append((community_key, str(member_key), out.field, value))
    return sorted(found)


@app.command("out-of-set-values")
def out_of_set_values(
    api: str = typer.Option(
        settings.base_url,
        "--api",
        help="Registry API base URL",
        envvar="REGISTRY_API_URL",
    ),
    timeout: float = typer.Option(
        60.0,
        "--timeout",
        help="HTTP timeout in seconds",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        help="Pre-obtained JWT access token",
        envvar="REGISTRY_TOKEN",
    ),
    client_id: str | None = typer.Option(
        None,
        "--client-id",
        help="OAuth2 client ID",
        envvar="REGISTRY_CLIENT_ID",
    ),
    client_secret: str | None = typer.Option(
        None,
        "--client-secret",
        help="OAuth2 client secret",
        envvar="REGISTRY_CLIENT_SECRET",
    ),
    user: str | None = typer.Option(
        None,
        "--user",
        help="Username",
        envvar="REGISTRY_USER",
    ),
    password: str | None = typer.Option(
        None,
        "--password",
        help="User password",
        envvar="REGISTRY_PASSWORD",
    ),
    auth_url: str = typer.Option(
        settings.oidc_base_url or "http://localhost:8080/realms/celine",
        "--auth-url",
        help="OIDC/Keycloak realm URL",
        envvar="REGISTRY_AUTH_URL",
    ),
    scope: str | None = typer.Option(
        None,
        "--scope",
        help="OAuth2 scope",
        envvar="REGISTRY_SCOPE",
    ),
):
    """
    Report every member whose role, status or area is out of set (read-only).

    The registry refuses a role or status outside its set, and an area that is
    not one of the member's community's areas, on every write path — but it
    does not repair rows written before it did, and a re-import of such a
    community is refused. This lists them — one line per field: community key,
    member key, field, value — so they can be corrected before the check is
    relied on.

    Reads every community through GET /admin/export (the export grant) and
    writes nothing. Exits 0 when there are none, 1 when there are, and 2 when
    the registry cannot be read.
    """
    access_token = _resolve_auth(
        token=token,
        client_id=client_id,
        client_secret=client_secret,
        user=user,
        password=password,
        auth_url=auth_url,
        scope=scope,
        verify_ssl=settings.oidc_verify_ssl,
    )

    found = find_out_of_set_values(_read_export(api, access_token, timeout))
    if not found:
        typer.secho(
            "Every member's role, status and area is in set.",
            fg=typer.colors.GREEN,
        )
        return

    typer.echo("community\tmember\tfield\tvalue")
    for community_key, member_key, field, value in found:
        typer.echo(f"{community_key}\t{member_key}\t{field}\t{value}")
    typer.secho(
        f"{len(found)} out-of-set value(s) in "
        f"{len({(c, m) for c, m, _, _ in found})} member(s).",
        fg=typer.colors.YELLOW,
        err=True,
    )
    raise typer.Exit(1)


# =============================================================================
# Area Boundary Report
# =============================================================================


def find_invalid_area_boundaries(
    bundles: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    """Every stored area the one-substation rule would now refuse (REQ-0078).

    Reads exported bundles, as ``GET /admin/export`` answers them, and returns
    ``(community key, refusal)`` sorted, one per rule an area breaks — judged
    by ``area_boundary_refusals`` over **every** area of the community against
    its own ``topology``, the check the import runs (REQ-0067), so the report
    and the check cannot disagree. A key that is not an area key is reported
    too, by ``area_key_refusals``, which the import also runs. A refusal names
    area keys and the rule, never a boundary or node id.
    """
    found: list[tuple[str, str]] = []
    for bundle in bundles:
        if not isinstance(bundle, dict):
            continue
        community = bundle.get("community") or {}
        community_key = str(community.get("id", ""))
        areas = community.get("areas") or {}
        topology = community.get("topology") or []
        if not isinstance(areas, dict) or not isinstance(topology, list):
            continue
        for detail in area_key_refusals(areas):
            found.append((community_key, detail))
        for detail in area_boundary_refusals(areas, topology):
            found.append((community_key, detail))
    return sorted(found)


@app.command("invalid-area-boundaries")
def invalid_area_boundaries(
    api: str = typer.Option(
        settings.base_url,
        "--api",
        help="Registry API base URL",
        envvar="REGISTRY_API_URL",
    ),
    timeout: float = typer.Option(
        60.0,
        "--timeout",
        help="HTTP timeout in seconds",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        help="Pre-obtained JWT access token",
        envvar="REGISTRY_TOKEN",
    ),
    client_id: str | None = typer.Option(
        None,
        "--client-id",
        help="OAuth2 client ID",
        envvar="REGISTRY_CLIENT_ID",
    ),
    client_secret: str | None = typer.Option(
        None,
        "--client-secret",
        help="OAuth2 client secret",
        envvar="REGISTRY_CLIENT_SECRET",
    ),
    user: str | None = typer.Option(
        None,
        "--user",
        help="Username",
        envvar="REGISTRY_USER",
    ),
    password: str | None = typer.Option(
        None,
        "--password",
        help="User password",
        envvar="REGISTRY_PASSWORD",
    ),
    auth_url: str = typer.Option(
        settings.oidc_base_url or "http://localhost:8080/realms/celine",
        "--auth-url",
        help="OIDC/Keycloak realm URL",
        envvar="REGISTRY_AUTH_URL",
    ),
    scope: str | None = typer.Option(
        None,
        "--scope",
        help="OAuth2 scope",
        envvar="REGISTRY_SCOPE",
    ),
):
    """
    Report every stored area that breaks the one-substation rule (read-only).

    The registry refuses an area that is not one GSE primary substation — one
    boundary, one primary_substation topology node with its id, no two areas
    on one boundary id — on the area PUT, the topology node routes and the
    import, and an area key that is not letters, digits, '-' and '_' (at most
    128, starting with a letter or digit) on the area PUT and the import. It
    does not re-judge areas stored before the rules, and a re-import of their
    community is refused. This lists them — one line per broken rule:
    community key, and the refusal naming the area keys — so they can be
    corrected (an onboarding registry-sync, an area rename, or a reshaped
    bundle) before
    anything relies on the rule.

    Reads every community through GET /admin/export (the export grant) and
    writes nothing. Exits 0 when there are none, 1 when there are, and 2 when
    the registry cannot be read.
    """
    access_token = _resolve_auth(
        token=token,
        client_id=client_id,
        client_secret=client_secret,
        user=user,
        password=password,
        auth_url=auth_url,
        scope=scope,
        verify_ssl=settings.oidc_verify_ssl,
    )

    found = find_invalid_area_boundaries(_read_export(api, access_token, timeout))
    if not found:
        typer.secho(
            "Every stored area keeps the one-substation rule and has an area key.",
            fg=typer.colors.GREEN,
        )
        return

    typer.echo("community\trefusal")
    for community_key, detail in found:
        typer.echo(f"{community_key}\t{detail}")
    typer.secho(
        f"{len(found)} area rule(s) broken in "
        f"{len({c for c, _ in found})} community(ies).",
        fg=typer.colors.YELLOW,
        err=True,
    )
    raise typer.Exit(1)


# =============================================================================
# Subject Backfill
# =============================================================================


@dataclass
class SubjectBackfill:
    """What a ``backfill-subjects`` run found, before anything is written.

    ``to_set`` is ``(community key, member key, subject)`` for each member that
    holds no subject and whose username names exactly one Keycloak account. The
    counts cover every member examined; they are what the command prints.
    """

    examined: int = 0
    to_set: list[tuple[str, str, str]] = dataclass_field(default_factory=list)
    already_set: int = 0
    no_account: int = 0
    ambiguous: int = 0
    differs: int = 0


def plan_subject_backfill(
    bundles: list[dict[str, Any]],
    find_subjects: Callable[[str], list[str]],
) -> SubjectBackfill:
    """Decide, for every exported member, whether its subject can be filled in.

    ``find_subjects(username)`` answers the ids of the Keycloak accounts whose
    username is exactly ``username``, and is asked once per distinct username.
    Members of every status are covered: an inactive member's account still
    exists, and the mirrors carry inactive members too.

    A member already holding a subject is never planned for a write. When
    Keycloak names another account it is counted in ``differs``, for somebody
    to look at — replacing it would re-link a member to an account nobody chose.
    No account leaves the member as it is (a member can exist before its
    account), and so do two (no answer is better than a guessed one).
    """
    plan = SubjectBackfill()
    answers: dict[str, list[str]] = {}

    for bundle in bundles:
        if not isinstance(bundle, dict):
            continue
        community_key = str((bundle.get("community") or {}).get("id", ""))
        for member_key, member in (bundle.get("members") or {}).items():
            if not isinstance(member, dict):
                continue
            username = str(member.get("user_id") or "").strip()
            if not username:
                continue
            plan.examined += 1

            if username not in answers:
                answers[username] = list(dict.fromkeys(find_subjects(username)))
            found = answers[username]

            held = str(member.get("subject") or "").strip().lower()
            if not found:
                plan.no_account += 1
            elif len(found) > 1:
                plan.ambiguous += 1
            elif held:
                if held == found[0].lower():
                    plan.already_set += 1
                else:
                    plan.differs += 1
            else:
                plan.to_set.append((community_key, str(member_key), found[0].lower()))

    return plan


def keycloak_admin_url(auth_url: str) -> str:
    """The realm's Admin API root, from its OIDC realm URL.

    ``https://kc.example/realms/celine`` →
    ``https://kc.example/admin/realms/celine``; a ``/auth`` context path before
    ``/realms`` is kept.
    """
    base, sep, realm = auth_url.rstrip("/").rpartition("/realms/")
    if not sep or not realm:
        raise typer.BadParameter(
            f"--auth-url {auth_url!r} names no realm; pass --keycloak-url"
        )
    return f"{base}/admin/realms/{realm}"


class _KeycloakUnreadable(Exception):
    """Keycloak's user search could not be read. Carries a status, never a name."""


def _keycloak_subjects(admin_url: str, token: str, timeout: float) -> Callable[[str], list[str]]:
    """``find_subjects`` over Keycloak's user search, ``exact`` on the username.

    The search is asked for the exact name and its answer is filtered again:
    an account counts only when its username *is* the member's ``user_id``
    (compared case-insensitively — Keycloak holds usernames lower-case).

    A failure raises :class:`_KeycloakUnreadable` with the status alone: the
    request's URL carries the username, so neither it nor the exception text is
    ever printed.
    """
    url = f"{admin_url.rstrip('/')}/users"
    headers = {"Authorization": f"Bearer {token}"}

    def find(username: str) -> list[str]:
        try:
            r = httpx.get(
                url,
                params={"username": username, "exact": "true", "briefRepresentation": "true"},
                headers=headers,
                timeout=timeout,
            )
        except httpx.HTTPError as exc:
            raise _KeycloakUnreadable(type(exc).__name__) from None
        if r.status_code >= 400:
            raise _KeycloakUnreadable(str(r.status_code))
        try:
            users = r.json()
        except ValueError:
            raise _KeycloakUnreadable("unreadable answer") from None
        if not isinstance(users, list):
            raise _KeycloakUnreadable("unreadable answer")
        wanted = username.lower()
        return [
            str(u["id"])
            for u in users
            if isinstance(u, dict)
            and u.get("id")
            and str(u.get("username") or "").lower() == wanted
        ]

    return find


@app.command("backfill-subjects")
def backfill_subjects(
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Write the subjects found. Without it nothing is written (dry run).",
    ),
    api: str = typer.Option(
        settings.base_url,
        "--api",
        help="Registry API base URL",
        envvar="REGISTRY_API_URL",
    ),
    timeout: float = typer.Option(
        60.0,
        "--timeout",
        help="HTTP timeout in seconds",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        help="Pre-obtained JWT access token for the registry",
        envvar="REGISTRY_TOKEN",
    ),
    client_id: str | None = typer.Option(
        None,
        "--client-id",
        help="OAuth2 client ID for the registry",
        envvar="REGISTRY_CLIENT_ID",
    ),
    client_secret: str | None = typer.Option(
        None,
        "--client-secret",
        help="OAuth2 client secret for the registry",
        envvar="REGISTRY_CLIENT_SECRET",
    ),
    user: str | None = typer.Option(
        None,
        "--user",
        help="Username",
        envvar="REGISTRY_USER",
    ),
    password: str | None = typer.Option(
        None,
        "--password",
        help="User password",
        envvar="REGISTRY_PASSWORD",
    ),
    auth_url: str = typer.Option(
        settings.oidc_base_url or "http://localhost:8080/realms/celine",
        "--auth-url",
        help="OIDC/Keycloak realm URL",
        envvar="REGISTRY_AUTH_URL",
    ),
    scope: str | None = typer.Option(
        None,
        "--scope",
        help="OAuth2 scope",
        envvar="REGISTRY_SCOPE",
    ),
    keycloak_url: str | None = typer.Option(
        None,
        "--keycloak-url",
        help="Keycloak Admin API realm URL (default: derived from --auth-url)",
        envvar="KEYCLOAK_ADMIN_URL",
    ),
    keycloak_token: str | None = typer.Option(
        None,
        "--keycloak-token",
        help="Pre-obtained JWT for Keycloak's Admin API (needs view-users)",
        envvar="KEYCLOAK_TOKEN",
    ),
    keycloak_client_id: str | None = typer.Option(
        None,
        "--keycloak-client-id",
        help="OAuth2 client ID holding view-users in the realm",
        envvar="KEYCLOAK_CLIENT_ID",
    ),
    keycloak_client_secret: str | None = typer.Option(
        None,
        "--keycloak-client-secret",
        help="OAuth2 client secret for --keycloak-client-id",
        envvar="KEYCLOAK_CLIENT_SECRET",
    ),
):
    """
    Fill in each member's account subject from Keycloak, by username (REQ-0102).

    For every member in GET /admin/export (the export grant) the Keycloak
    account whose username is the member's user_id is looked up, through the
    realm's Admin API (a client holding view-users: --keycloak-token, or
    --keycloak-client-id/--keycloak-client-secret; without either, the
    registry's own token is presented). A member holding no subject and naming
    exactly one account is given that account's id through
    PATCH /admin/communities/{community}/members/{member} (members.write).

    Dry run unless --apply. Every lookup runs before the first write, so a
    Keycloak failure leaves the registry as it was. A subject already held is
    never replaced: one that differs from Keycloak's is counted under
    "differs". Re-running is safe; written members count as already_set.

    Prints counts only — no member key, username, e-mail or subject. Exits 0,
    1 when any member differs, is ambiguous or failed to write, and 2 when the
    registry or Keycloak cannot be read.
    """
    access_token = _resolve_auth(
        token=token,
        client_id=client_id,
        client_secret=client_secret,
        user=user,
        password=password,
        auth_url=auth_url,
        scope=scope,
        verify_ssl=settings.oidc_verify_ssl,
    )

    if keycloak_token:
        admin_token = keycloak_token
    elif keycloak_client_id and keycloak_client_secret:
        _enforce_client_credentials_posture(keycloak_client_id, keycloak_client_secret)
        admin_token = asyncio.run(
            _get_token_from_client_credentials(
                auth_url=auth_url,
                client_id=keycloak_client_id,
                client_secret=keycloak_client_secret,
                verify_ssl=settings.oidc_verify_ssl,
            )
        )
    else:
        admin_token = access_token

    admin_url = keycloak_url or keycloak_admin_url(auth_url)

    bundles = _read_export(api, access_token, timeout)

    try:
        plan = plan_subject_backfill(
            bundles, _keycloak_subjects(admin_url, admin_token, timeout)
        )
    except _KeycloakUnreadable as exc:
        typer.secho(
            f"Keycloak user search failed ({exc}); nothing was written. A 401 or 403 "
            "is a token without view-users in the realm.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)

    written = 0
    failed = 0
    if apply:
        headers = {"Authorization": f"Bearer {access_token}"}
        for community_key, member_key, subject in plan.to_set:
            url = _api_url(
                api,
                f"/admin/communities/{quote(community_key, safe='')}"
                f"/members/{quote(member_key, safe='')}",
            )
            try:
                r = httpx.patch(url, json={"subject": subject}, headers=headers, timeout=timeout)
            except httpx.HTTPError:
                failed += 1
                continue
            if r.status_code >= 400:
                failed += 1
            else:
                written += 1

    typer.echo(f"examined\t{plan.examined}")
    if apply:
        typer.echo(f"set\t{written}")
    else:
        typer.echo(f"would_set\t{len(plan.to_set)}")
    typer.echo(f"already_set\t{plan.already_set}")
    typer.echo(f"no_account\t{plan.no_account}")
    typer.echo(f"ambiguous\t{plan.ambiguous}")
    typer.echo(f"differs\t{plan.differs}")
    typer.echo(f"failed\t{failed}")

    if not apply:
        typer.secho("Dry run: nothing was written. Pass --apply to write.", err=True)

    if plan.differs or plan.ambiguous or failed:
        raise typer.Exit(1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
