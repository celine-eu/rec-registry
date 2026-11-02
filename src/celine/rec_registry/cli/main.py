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
- mirror-members: Mirror another registry's members into this one, from its mirror export (dry run by default)

Authentication:
- Client credentials: --client-id + --client-secret (admin operations)
- User credentials: --user + --password (user operations)
- Token: --token (pre-obtained JWT)
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx
import typer
import yaml

from celine.sdk.auth import OidcClientCredentialsProvider
from celine.sdk.posture import InsecureConfiguration, PostureGuard, current_env
from celine.rec_registry.cli.config import settings
from celine.rec_registry.core.area_boundary import (
    area_boundary_refusals,
    area_key_refusals,
)
# `find_duplicate_delivery_points` lives with the compared form, so the CLI and
# the per-community read (REQ-0087) share one definition of a duplicate.
from celine.rec_registry.core.delivery_point_id import (
    find_duplicate_delivery_points,
    normalise_delivery_point_id,
)
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


# =============================================================================
# Member Mirror
# =============================================================================

#: The `extra` key that marks a member as written by `mirror-members` (REQ-0104).
#: Its value names the source (its host, or `file`); only its presence is read.
MIRROR_MARKER = "mirror_source"

#: A mirrored meter's type. The source exports sensor ids only, so the direction
#: is not known; `bidirectional` claims none.
MIRROR_METER_TYPE = "bidirectional"

#: The type of the delivery points a mirror holds: the source's POD hashes
#: (REQ-0105), never a POD. Only points of this type, on managed members, are written.
MIRROR_POINT_TYPE = "pod-hmac"

_INACTIVE = "inactive"
_ACTIVE = "active"


def _meter_key(sensor_id: str) -> str:
    """The asset key a mirrored meter is written under (REQ-0071's convention)."""
    return f"meter-{sensor_id}"


@dataclass
class MemberMirror:
    """What a ``mirror-members`` run would write, and what it skipped.

    Every list holds community keys and member keys, which the command never
    prints; the counts are what it prints. ``creates`` and ``updates`` carry the
    ``POST`` and ``PATCH`` bodies; ``attaches`` names a sensor id, ``detaches``
    an asset key.

    From a keyed source (REQ-0105): ``point_adds`` and ``point_removes`` name a
    ``pod-hmac`` delivery point; ``attach_pods`` gives the ``pod`` of a meter
    ``attaches`` names; ``meter_pods`` is ``(…, sensor id, old pod, new pod)`` for
    a meter already attached whose ``pod`` changes.
    """

    creates: list[tuple[str, str, dict[str, Any]]] = dataclass_field(default_factory=list)
    updates: list[tuple[str, str, dict[str, Any]]] = dataclass_field(default_factory=list)
    deactivations: list[tuple[str, str]] = dataclass_field(default_factory=list)
    attaches: list[tuple[str, str, str]] = dataclass_field(default_factory=list)
    detaches: list[tuple[str, str, str]] = dataclass_field(default_factory=list)
    source_members: int = 0
    unchanged: int = 0
    communities_missing: int = 0
    skipped_no_community: int = 0
    skipped_no_area: int = 0
    skipped_unmanaged_key: int = 0
    skipped_sensor_held: int = 0
    point_adds: list[tuple[str, str, str]] = dataclass_field(default_factory=list)
    point_removes: list[tuple[str, str, str]] = dataclass_field(default_factory=list)
    attach_pods: dict[tuple[str, str, str], str] = dataclass_field(default_factory=dict)
    meter_pods: list[tuple[str, str, str, str | None, str | None]] = dataclass_field(
        default_factory=list
    )
    skipped_pod_held: int = 0
    pod_hashes_absent: int = 0


def _held_meters(member: dict[str, Any]) -> dict[str, str]:
    """``{sensor id: asset key}`` for a bundle member's meters, ids trimmed."""
    meters = ((member.get("assets") or {}).get("meter")) or {}
    held: dict[str, str] = {}
    if not isinstance(meters, dict):
        return held
    for asset_key, meter in meters.items():
        if isinstance(meter, dict):
            sensor_id = normalise_sensor_id(meter.get("sensor_id"))
            if sensor_id:
                held[sensor_id] = str(asset_key)
    return held


def _meter_pods(member: dict[str, Any]) -> dict[str, str | None]:
    """``{sensor id: pod}`` for a bundle member's meters, both in compared form."""
    meters = ((member.get("assets") or {}).get("meter")) or {}
    pods: dict[str, str | None] = {}
    if not isinstance(meters, dict):
        return pods
    for meter in meters.values():
        if isinstance(meter, dict):
            sensor_id = normalise_sensor_id(meter.get("sensor_id"))
            if sensor_id:
                pods[sensor_id] = normalise_delivery_point_id(meter.get("pod"))
    return pods


def _point_ids(member: dict[str, Any]) -> set[str]:
    """Every delivery point a bundle member lists, any type, in compared form."""
    return {
        p
        for p in (
            normalise_delivery_point_id(dp.get("id"))
            for dp in member.get("delivery_points") or []
            if isinstance(dp, dict)
        )
        if p
    }


def _mirror_points(member: dict[str, Any]) -> dict[str, tuple[str, bool]]:
    """``{compared id: (stored id, active)}`` of a member's ``pod-hmac`` points."""
    points: dict[str, tuple[str, bool]] = {}
    for dp in member.get("delivery_points") or []:
        if not isinstance(dp, dict) or dp.get("type") != MIRROR_POINT_TYPE:
            continue
        point_id = normalise_delivery_point_id(dp.get("id"))
        if point_id:
            points[point_id] = (str(dp["id"]), dp.get("active", True) is not False)
    return points


def _mirror_meter_body(sensor_id: str, pod: str | None = None) -> dict[str, Any]:
    """The ``PUT …/assets/meter-<sensor id>`` body of a mirrored meter."""
    asset_key = _meter_key(sensor_id)
    properties: dict[str, Any] = {
        "name": asset_key,
        "sensor_id": sensor_id,
        "meter_type": MIRROR_METER_TYPE,
    }
    if pod is not None:
        properties["pod"] = pod
    return {"key": asset_key, "asset_type": "meter", "properties": properties}


def plan_member_mirror(
    source: dict[str, Any],
    target: list[dict[str, Any]],
    *,
    origin: str,
) -> MemberMirror:
    """Decide what makes the target registry mirror the source's members (REQ-0104).

    ``source`` is the source's mirror export (REQ-0103); ``target`` the target's
    full export, one bundle per community. ``origin`` is the marker's value on
    a member this run creates.

    A member is *managed* when its ``extra`` holds :data:`MIRROR_MARKER`; only
    managed members are written. For each source member of a community and an
    area the target has:

    - none in the target under its key: created, keyed, named and logged in by
      its member key, with the source's area, role, type, status and subject;
    - a managed one: patched on the fields that differ (a null type or subject
      in the source leaves the target's as it is: a patch cannot clear them);
    - an unmanaged one under its key, or holding its key as ``user_id``:
      ``skipped_unmanaged_key``, nothing written.

    Its meters follow the source's sensor ids, at ``meter-<sensor id>``; a
    sensor an active unmanaged member holds anywhere, or whose meter key an
    unmanaged member of the community holds, is ``skipped_sensor_held``.
    A managed member the source no longer lists is deactivated, never purged,
    and keeps its meters but those another member is about to take.
    Communities and areas are never created.

    A source member carrying ``pod_hashes`` (a keyed source, REQ-0105) makes its
    mirror's ``pod-hmac`` delivery points exactly those hashes — added, re-added
    when stored inactive, removed when gone (removed rather than set inactive:
    an active member holds every point it lists, whatever its flag, REQ-0085) —
    and each of its meters' ``pod`` the hash ``meter_pod_hashes`` gives, or none.
    A hash an active unmanaged member holds, as a delivery point or a meter's
    ``pod``, is ``skipped_pod_held`` (once per member) and neither added nor
    named by a meter. Points of other types are never touched. A source member
    without ``pod_hashes`` (a source without the key) is counted in
    ``pod_hashes_absent`` and its mirror's points and pods are left as they are.
    """
    plan = MemberMirror()

    communities: dict[str, dict[str, Any]] = {}
    for bundle in target:
        if not isinstance(bundle, dict):
            continue
        community = bundle.get("community") or {}
        key = str(community.get("id") or "")
        if key:
            communities[key] = {
                "areas": set((community.get("areas") or {}).keys()),
                "members": {
                    str(mk): m
                    for mk, m in (bundle.get("members") or {}).items()
                    if isinstance(m, dict)
                },
            }

    def managed(member: dict[str, Any]) -> bool:
        return MIRROR_MARKER in member

    # Sensors unmanaged members hold, by sensor id: (community, active, asset key).
    unmanaged_sensors: dict[str, list[tuple[str, bool, str]]] = {}
    for community_key, community in communities.items():
        for member in community["members"].values():
            if managed(member):
                continue
            active = member.get("status") == _ACTIVE
            for sensor_id, asset_key in _held_meters(member).items():
                unmanaged_sensors.setdefault(sensor_id, []).append(
                    (community_key, active, asset_key)
                )

    # Hashes active unmanaged members hold anywhere, as points or meters' pods.
    unmanaged_pods: set[str] = set()
    for community in communities.values():
        for member in community["members"].values():
            if managed(member) or member.get("status") != _ACTIVE:
                continue
            unmanaged_pods |= _point_ids(member)
            unmanaged_pods |= {p for p in _meter_pods(member).values() if p}

    def sensor_blocked(community_key: str, sensor_id: str) -> bool:
        for holder_community, active, asset_key in unmanaged_sensors.get(sensor_id, []):
            if active:
                return True
            if holder_community == community_key and asset_key == _meter_key(sensor_id):
                return True
        return False

    listed: set[tuple[str, str]] = set()
    # Sensors this run attaches, so a gone mirror holding one lets it go.
    claimed: set[str] = set()

    for entry in source.get("communities") or []:
        if not isinstance(entry, dict):
            continue
        community_key = str(entry.get("community") or "")
        members = [m for m in entry.get("members") or [] if isinstance(m, dict)]
        plan.source_members += len(members)
        plan.pod_hashes_absent += sum(1 for m in members if "pod_hashes" not in m)
        community = communities.get(community_key)
        if community is None:
            plan.communities_missing += 1
            plan.skipped_no_community += len(members)
            continue

        usernames = {
            str(m.get("user_id") or ""): mk
            for mk, m in community["members"].items()
            if not managed(m)
        }

        for member in members:
            member_key = str(member.get("key") or "")
            if not member_key:
                continue
            listed.add((community_key, member_key))

            if member.get("area") not in community["areas"]:
                plan.skipped_no_area += 1
                continue

            existing = community["members"].get(member_key)
            if (existing is not None and not managed(existing)) or (
                usernames.get(member_key) not in (None, member_key)
            ):
                plan.skipped_unmanaged_key += 1
                continue

            fields: dict[str, Any] = {
                "user_id": member_key,
                "area": member.get("area"),
                "role": member.get("role"),
                "status": member.get("status"),
            }
            if member.get("type") is not None:
                fields["type"] = member["type"]
            if member.get("subject"):
                fields["subject"] = str(member["subject"]).lower()

            wanted: list[str] = []
            for raw in member.get("sensor_ids") or []:
                sensor_id = normalise_sensor_id(raw)
                if not sensor_id or sensor_id in wanted:
                    continue
                if sensor_blocked(community_key, sensor_id):
                    plan.skipped_sensor_held += 1
                    continue
                wanted.append(sensor_id)

            if existing is None:
                plan.creates.append(
                    (
                        community_key,
                        member_key,
                        {
                            "key": member_key,
                            "user_id": member_key,
                            "name": member_key,
                            **({"type": fields["type"]} if "type" in fields else {}),
                            "role": fields["role"],
                            "area": fields["area"],
                            "status": fields["status"],
                            **({"subject": fields["subject"]} if "subject" in fields else {}),
                            "extra": {MIRROR_MARKER: origin},
                        },
                    )
                )
                held: dict[str, str] = {}
                changed = True
            else:
                changes = {}
                for name, value in fields.items():
                    current = existing.get(name)
                    if name == "subject" and current is not None:
                        current = str(current).lower()
                    if current != value:
                        changes[name] = value
                if changes:
                    plan.updates.append((community_key, member_key, changes))
                held = _held_meters(existing)
                changed = bool(changes)

            for sensor_id, asset_key in held.items():
                if sensor_id not in wanted:
                    plan.detaches.append((community_key, member_key, asset_key))
                    changed = True
            for sensor_id in wanted:
                claimed.add(sensor_id)
                if sensor_id not in held:
                    plan.attaches.append((community_key, member_key, sensor_id))
                    changed = True
            if "pod_hashes" in member:
                changed |= _plan_pods(
                    plan,
                    community_key,
                    member_key,
                    member,
                    existing or {},
                    wanted,
                    held,
                    unmanaged_pods,
                )
            if not changed:
                plan.unchanged += 1

    # Mirrors the source no longer lists: deactivated, never purged.
    for community_key, community in communities.items():
        for member_key, member in community["members"].items():
            if not managed(member) or (community_key, member_key) in listed:
                continue
            for sensor_id, asset_key in _held_meters(member).items():
                if sensor_id in claimed:
                    plan.detaches.append((community_key, member_key, asset_key))
            if member.get("status") != _INACTIVE:
                plan.deactivations.append((community_key, member_key))

    return plan


def _plan_pods(
    plan: MemberMirror,
    community_key: str,
    member_key: str,
    member: dict[str, Any],
    existing: dict[str, Any],
    wanted: list[str],
    held: dict[str, str],
    unmanaged_pods: set[str],
) -> bool:
    """Plan one keyed source member's points and meter pods; ``True`` if any change."""
    blocked: set[str] = set()

    def usable(raw: Any) -> str | None:
        point_id = normalise_delivery_point_id(raw)
        if point_id is None:
            return None
        if point_id in unmanaged_pods:
            blocked.add(point_id)
            return None
        return point_id

    wanted_points: list[str] = []
    for raw in member.get("pod_hashes") or []:
        point_id = usable(raw)
        if point_id and point_id not in wanted_points:
            wanted_points.append(point_id)

    raw_pods = member.get("meter_pod_hashes")
    source_pods = {
        normalise_sensor_id(sid): pod
        for sid, pod in (raw_pods.items() if isinstance(raw_pods, dict) else [])
    }
    desired = {sensor_id: usable(source_pods.get(sensor_id)) for sensor_id in wanted}
    plan.skipped_pod_held += len(blocked)

    changed = False
    current_points = _mirror_points(existing)
    for point_id in wanted_points:
        current = current_points.get(point_id)
        if current is None or not current[1]:
            plan.point_adds.append((community_key, member_key, point_id))
            changed = True
    for point_id, (stored_id, _) in sorted(current_points.items()):
        if point_id not in wanted_points:
            plan.point_removes.append((community_key, member_key, stored_id))
            changed = True

    current_pods = _meter_pods(existing)
    for sensor_id in wanted:
        pod = desired[sensor_id]
        if sensor_id not in held:
            if pod is not None:
                plan.attach_pods[(community_key, member_key, sensor_id)] = pod
        elif current_pods.get(sensor_id) != pod:
            plan.meter_pods.append(
                (community_key, member_key, sensor_id, current_pods.get(sensor_id), pod)
            )
            changed = True
    return changed


_PROD_ENVS = ("prod", "production")


def _refuse(message: str) -> None:
    """Print why nothing was done, and exit ``2``."""
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(2)


def _read_mirror_source(url: str, access_token: str, timeout: float) -> dict[str, Any]:
    """The source's ``GET /admin/export/mirror``; exit ``2`` if unreadable.

    A failure is reported by status alone: the answer comes from another
    environment, and nothing it says is echoed.
    """
    try:
        r = httpx.get(
            _api_url(url, "/admin/export/mirror"),
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        _refuse(f"Source unreachable ({type(exc).__name__}); nothing was written.")
    if r.status_code >= 400:
        _refuse(
            f"Source mirror export failed [{r.status_code}]; nothing was written. "
            "A 401 or 403 is a source token without rec-registry.mirror."
        )
    try:
        return r.json()
    except ValueError:
        _refuse("Source mirror export is not JSON; nothing was written.")
    raise AssertionError("unreachable")  # pragma: no cover


@app.command("mirror-members")
def mirror_members(
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Write the mirror. Without it nothing is written (dry run).",
    ),
    source_url: str | None = typer.Option(
        None,
        "--source-url",
        help="Source registry API base URL, read through GET /admin/export/mirror",
        envvar="SOURCE_REGISTRY_API_URL",
    ),
    source_file: str | None = typer.Option(
        None,
        "--source-file",
        help="A saved mirror export (JSON) instead of --source-url",
    ),
    source_token: str | None = typer.Option(
        None,
        "--source-token",
        help="Pre-obtained JWT for the source registry (needs rec-registry.mirror)",
        envvar="SOURCE_REGISTRY_TOKEN",
    ),
    source_client_id: str | None = typer.Option(
        None,
        "--source-client-id",
        help="OAuth2 client ID in the source's realm, holding rec-registry.mirror",
        envvar="SOURCE_REGISTRY_CLIENT_ID",
    ),
    source_client_secret: str | None = typer.Option(
        None,
        "--source-client-secret",
        help="OAuth2 client secret for --source-client-id",
        envvar="SOURCE_REGISTRY_CLIENT_SECRET",
    ),
    source_auth_url: str | None = typer.Option(
        None,
        "--source-auth-url",
        help="The source's OIDC/Keycloak realm URL",
        envvar="SOURCE_REGISTRY_AUTH_URL",
    ),
    source_scope: str | None = typer.Option(
        None,
        "--source-scope",
        help="OAuth2 scope to request from the source's realm",
        envvar="SOURCE_REGISTRY_SCOPE",
    ),
    api: str = typer.Option(
        settings.base_url,
        "--api",
        help="Target registry API base URL",
        envvar="REGISTRY_API_URL",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        help="Pre-obtained JWT for the target registry",
        envvar="REGISTRY_TOKEN",
    ),
    client_id: str | None = typer.Option(
        None,
        "--client-id",
        help="OAuth2 client ID for the target registry",
        envvar="REGISTRY_CLIENT_ID",
    ),
    client_secret: str | None = typer.Option(
        None,
        "--client-secret",
        help="OAuth2 client secret for the target registry",
        envvar="REGISTRY_CLIENT_SECRET",
    ),
    auth_url: str = typer.Option(
        settings.oidc_base_url or "http://localhost:8080/realms/celine",
        "--auth-url",
        help="The target's OIDC/Keycloak realm URL",
        envvar="REGISTRY_AUTH_URL",
    ),
    scope: str | None = typer.Option(
        None,
        "--scope",
        help="OAuth2 scope to request from the target's realm",
        envvar="REGISTRY_SCOPE",
    ),
    timeout: float = typer.Option(
        60.0,
        "--timeout",
        help="HTTP timeout in seconds",
    ),
):
    """
    Mirror the source registry's members into the target registry (REQ-0104).

    Reads the source's GET /admin/export/mirror (rec-registry.mirror, with the
    source's own client) or --source-file, and the target's GET /admin/export
    (rec-registry.export). Each source member of a community and area the
    target has is created or updated there as a mirror: key, user_id and name
    are the member key; area, role, type, status and subject are the
    source's; extra.mirror_source marks it; each sensor id becomes a meter at
    meter-<sensor id>. Mirrors the source no longer lists are deactivated,
    never purged. Communities and areas are never created, and a member
    without the marker is never written. From a source holding POD_HMAC_KEY,
    each mirror's pod-hmac delivery points and meter pods follow the source's
    POD hashes (REQ-0105); a source without it is counted, not refused. Writes
    go through the target's admin API: members.write for members and delivery
    points, assets.write for meters.

    Dry run unless --apply. Refuses to run with CELINE_ENV or ENVIRONMENT set
    to prod/production, and when source and target URLs name the same host.

    Prints counts only — no community, member key, sensor id or subject.
    Exits 0, 1 when any write failed, and 2 when it refused or could not read
    the source or the target (nothing written).
    """
    env = current_env()
    if env in _PROD_ENVS:
        _refuse(f"Refusing to run with the environment set to {env!r}: a mirror is never prod.")

    if (source_url is None) == (source_file is None):
        _refuse("Name exactly one source: --source-url or --source-file.")

    if source_url is not None:
        source_host = (urlparse(source_url).hostname or "").lower()
        target_host = (urlparse(api).hostname or "").lower()
        if not source_host or source_host == target_host:
            _refuse("Refusing to mirror a registry into itself: source and target name the same host.")

    access_token = _resolve_auth(
        token=token,
        client_id=client_id,
        client_secret=client_secret,
        user=None,
        password=None,
        auth_url=auth_url,
        scope=scope,
        verify_ssl=settings.oidc_verify_ssl,
    )

    if source_url is not None:
        if not source_token and not source_auth_url:
            _refuse("--source-auth-url is required with --source-client-id/--source-client-secret.")
        source_access = _resolve_auth(
            token=source_token,
            client_id=source_client_id,
            client_secret=source_client_secret,
            user=None,
            password=None,
            auth_url=source_auth_url or "",
            scope=source_scope,
            verify_ssl=settings.oidc_verify_ssl,
        )
        source = _read_mirror_source(source_url, source_access, timeout)
        origin = source_host
    else:
        try:
            source = json.loads(Path(source_file).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _refuse("--source-file is not a readable JSON mirror export.")
        origin = "file"

    if not isinstance(source, dict) or not isinstance(source.get("communities"), list):
        _refuse("The source is not a mirror export: no communities list; nothing was written.")
    if not source["communities"]:
        _refuse(
            "The source lists no community; nothing was written. Acting on it would "
            "deactivate every mirror."
        )

    bundles = _read_export(api, access_token, timeout)
    plan = plan_member_mirror(source, bundles, origin=origin)

    done = {
        "create": 0,
        "update": 0,
        "deactivate": 0,
        "attach_meter": 0,
        "detach_meter": 0,
        "add_delivery_point": 0,
        "remove_delivery_point": 0,
        "set_meter_pod": 0,
    }
    failed = 0
    if apply:
        headers = {"Authorization": f"Bearer {access_token}"}

        def member_url(community_key: str, member_key: str | None = None) -> str:
            path = f"/admin/communities/{quote(community_key, safe='')}/members"
            if member_key is not None:
                path += f"/{quote(member_key, safe='')}"
            return _api_url(api, path)

        def send(method: Callable[..., Any], url: str, body: dict | None) -> bool:
            try:
                kwargs: dict[str, Any] = {"headers": headers, "timeout": timeout}
                if body is not None:
                    kwargs["json"] = body
                r = method(url, **kwargs)
            except httpx.HTTPError:
                return False
            return r.status_code < 400

        def count(name: str, ok: bool) -> None:
            nonlocal failed
            if ok:
                done[name] += 1
            else:
                failed += 1

        def meter_url(ck: str, mk: str, sensor_id: str) -> str:
            return f"{member_url(ck, mk)}/assets/{quote(_meter_key(sensor_id), safe='')}"

        def point_url(ck: str, mk: str, point_id: str) -> str:
            return f"{member_url(ck, mk)}/delivery-points/{quote(point_id, safe='')}"

        # Meters leave before anyone takes them, a point no meter names before it
        # is removed, holders let a hash go before another takes it, and members
        # exist before their points and meters are written.
        for ck, mk, asset_key in plan.detaches:
            url = f"{member_url(ck, mk)}/assets/{quote(asset_key, safe='')}"
            count("detach_meter", send(httpx.delete, url, None))
        pod_writes_ok: list[bool] = []
        for ck, mk, sensor_id, old, _new in plan.meter_pods:
            ok = True
            if old is not None:
                ok = send(httpx.put, meter_url(ck, mk, sensor_id), _mirror_meter_body(sensor_id))
                if not ok:
                    failed += 1
            pod_writes_ok.append(ok)
        for ck, mk, point_id in plan.point_removes:
            count("remove_delivery_point", send(httpx.delete, point_url(ck, mk, point_id), None))
        for ck, mk in plan.deactivations:
            count("deactivate", send(httpx.patch, member_url(ck, mk), {"status": _INACTIVE}))
        for ck, mk, body in plan.updates:
            count("update", send(httpx.patch, member_url(ck, mk), body))
        not_created: set[tuple[str, str]] = set()
        for ck, mk, body in plan.creates:
            ok = send(httpx.post, member_url(ck), body)
            if not ok:
                not_created.add((ck, mk))
            count("create", ok)
        for ck, mk, point_id in plan.point_adds:
            if (ck, mk) in not_created:
                continue
            body = {"id": point_id, "type": MIRROR_POINT_TYPE, "active": True}
            count("add_delivery_point", send(httpx.put, point_url(ck, mk, point_id), body))
        for ck, mk, sensor_id in plan.attaches:
            if (ck, mk) in not_created:
                continue
            body = _mirror_meter_body(sensor_id, plan.attach_pods.get((ck, mk, sensor_id)))
            count("attach_meter", send(httpx.put, meter_url(ck, mk, sensor_id), body))
        for (ck, mk, sensor_id, _old, new), ok in zip(plan.meter_pods, pod_writes_ok):
            if new is not None:
                linked = send(
                    httpx.put, meter_url(ck, mk, sensor_id), _mirror_meter_body(sensor_id, new)
                )
                if not linked:
                    failed += 1
                ok = ok and linked
            if ok:
                done["set_meter_pod"] += 1

    planned = {
        "create": len(plan.creates),
        "update": len(plan.updates),
        "deactivate": len(plan.deactivations),
        "attach_meter": len(plan.attaches),
        "detach_meter": len(plan.detaches),
        "add_delivery_point": len(plan.point_adds),
        "remove_delivery_point": len(plan.point_removes),
        "set_meter_pod": len(plan.meter_pods),
    }
    past = {
        "create": "created",
        "update": "updated",
        "deactivate": "deactivated",
        "attach_meter": "attached_meter",
        "detach_meter": "detached_meter",
        "add_delivery_point": "added_delivery_point",
        "remove_delivery_point": "removed_delivery_point",
        "set_meter_pod": "set_meter_pod",
    }

    typer.echo(f"source_members\t{plan.source_members}")
    for name, n in planned.items():
        if apply:
            typer.echo(f"{past[name]}\t{done[name]}")
        else:
            typer.echo(f"would_{name}\t{n}")
    typer.echo(f"unchanged\t{plan.unchanged}")
    typer.echo(f"communities_missing\t{plan.communities_missing}")
    typer.echo(f"skipped_no_community\t{plan.skipped_no_community}")
    typer.echo(f"skipped_no_area\t{plan.skipped_no_area}")
    typer.echo(f"skipped_unmanaged_key\t{plan.skipped_unmanaged_key}")
    typer.echo(f"skipped_sensor_held\t{plan.skipped_sensor_held}")
    typer.echo(f"skipped_pod_held\t{plan.skipped_pod_held}")
    typer.echo(f"pod_hashes_absent\t{plan.pod_hashes_absent}")
    typer.echo(f"failed\t{failed}")

    if plan.pod_hashes_absent:
        typer.secho(
            "The source carries no POD hashes for some members (no POD_HMAC_KEY there): "
            "their delivery points and meter pods were left as they are.",
            err=True,
        )

    if not apply:
        typer.secho("Dry run: nothing was written. Pass --apply to write.", err=True)

    if failed:
        raise typer.Exit(1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
