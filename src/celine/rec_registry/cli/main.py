"""
CELINE REC Registry CLI.

Commands:
- import: Import a v0.4 YAML bundle (idempotent)
- export: Export a community to v0.4 YAML
- list: List communities
- tree: Show community structure
- lookup: Lookup by user_id or sensor_id

Authentication:
- Client credentials: --client-id + --client-secret (admin operations)
- User credentials: --user + --password (user operations)
- Token: --token (pre-obtained JWT)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import typer
import yaml

from celine.sdk.auth import OidcClientCredentialsProvider
from celine.rec_registry.cli.config import settings

app = typer.Typer(name="celine-rec-registry", no_args_is_help=True)


# =============================================================================
# Authentication Helpers
# =============================================================================


async def _get_token_from_client_credentials(
    auth_url: str,
    client_id: str,
    client_secret: str,
    scope: str | None = None,
) -> str:
    """Get access token using client credentials flow."""
    provider = OidcClientCredentialsProvider(
        base_url=auth_url,
        client_id=client_id,
        client_secret=client_secret,
        scope=scope,
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


def _resolve_auth(
    token: str | None,
    client_id: str | None,
    client_secret: str | None,
    user: str | None,
    password: str | None,
    auth_url: str,
    scope: str | None = None,
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
        # Client credentials flow
        return asyncio.run(
            _get_token_from_client_credentials(
                auth_url=auth_url,
                client_id=client_id,
                client_secret=client_secret,
                scope=scope,
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
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate without writing to database",
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
    )

    yaml_text = file.read_text(encoding="utf-8")

    try:
        bundle = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as e:
        typer.secho(f"Invalid YAML: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if not isinstance(bundle, dict):
        typer.secho(
            "Top-level YAML must be a mapping/object", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(1)

    url = _api_url(api, "/admin/import")
    payload = {"bundle": bundle, "dry_run": dry_run}
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        r = httpx.post(url, json=payload, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        typer.secho(f"HTTP error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if r.status_code >= 400:
        typer.secho(
            f"Import failed [{r.status_code}]:\n{r.text}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)

    report = r.json()

    if dry_run:
        typer.secho("Dry run completed (no changes made)", fg=typer.colors.YELLOW)
    else:
        typer.secho("Import completed successfully", fg=typer.colors.GREEN)

    typer.echo(f"Community: {report.get('community_key')}")
    typer.echo(f"Deleted: {report.get('deleted')}")
    typer.echo(f"Inserted: {report.get('inserted')}")

    warnings = report.get("warnings", [])
    if warnings:
        typer.secho(f"\nWarnings ({len(warnings)}):", fg=typer.colors.YELLOW)
        for w in warnings:
            typer.echo(f"  - {w}")


# =============================================================================
# Export Command
# =============================================================================


@app.command("export")
def export_bundle(
    community: str = typer.Option(
        ...,
        "--community",
        "-c",
        help="Community key to export",
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
    Export a community to v0.4 YAML format.

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
    )

    url = _api_url(api, "/admin/export")
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        r = httpx.get(
            url, params={"community": community}, headers=headers, timeout=timeout
        )
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
