from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import typer
import yaml

app = typer.Typer(name="celine-registry", no_args_is_help=True)


def _api_url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _get_json(
    client: httpx.Client, url: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    r = client.get(url, params=params)
    if r.status_code >= 400:
        raise typer.BadParameter(f"GET {url} failed [{r.status_code}]: {r.text}")
    data = r.json()
    if not isinstance(data, dict):
        raise typer.BadParameter(f"GET {url} returned non-object JSON")
    return data


@app.command("import")
def import_bundle(
    file: Path = typer.Option(
        ...,
        "--file",
        "-f",
        exists=True,
        readable=True,
        help="Greenland YAML bundle file",
    ),
    api: str = typer.Option(
        "http://localhost:8000", "--api", help="Registry API base URL"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate without writing"),
    timeout: float = typer.Option(60.0, "--timeout", help="HTTP timeout seconds"),
):
    """
    Import a Greenland-style YAML bundle via /admin/import (JSON payload: bundle + dry_run).
    """
    yaml_text = file.read_text(encoding="utf-8")
    bundle = yaml.safe_load(yaml_text) or {}
    if not isinstance(bundle, dict):
        typer.secho(
            "Top-level YAML must be a mapping/object", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(1)

    url = _api_url(api, "/admin/import")
    payload = {"bundle": bundle, "dry_run": dry_run}

    try:
        r = httpx.post(url, json=payload, timeout=timeout)
    except httpx.HTTPError as exc:
        typer.secho(f"HTTP error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if r.status_code >= 400:
        typer.secho(
            f"Import failed [{r.status_code}]:\n{r.text}", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(1)

    report = r.json()
    typer.secho("Import completed", fg=typer.colors.GREEN)
    typer.echo(report)


@app.command("list")
def list_communities(
    api: str = typer.Option(
        "http://localhost:8000", "--api", help="Registry API base URL"
    ),
    key: str | None = typer.Option(
        None, "--key", help="Filter by community key (exact match)"
    ),
    limit: int = typer.Option(200, "--limit", min=1, max=500, help="Page size"),
    timeout: float = typer.Option(30.0, "--timeout", help="HTTP timeout seconds"),
):
    """
    List communities from GET /communities.
    """
    url = _api_url(api, "/communities")
    params: dict[str, Any] = {"limit": limit}
    if key:
        params["key"] = key

    with httpx.Client(timeout=timeout) as client:
        data = _get_json(client, url, params=params)

    items = data.get("items", [])
    if not items:
        typer.echo("No communities found.")
        raise typer.Exit(0)

    # Simple, stable output
    for c in sorted(items, key=lambda x: x.get("key", "")):
        typer.echo(f"- {c.get('key')}  {c.get('name') or ''}".rstrip())


def _group_assets_by_owner(
    assets: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for a in assets:
        owner = a.get("owner") or "UNKNOWN_OWNER"
        out.setdefault(owner, []).append(a)
    return out


def _group_meters_by_owner(
    meters: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for m in meters:
        owner = m.get("owner") or "UNKNOWN_OWNER"
        out.setdefault(owner, []).append(m)
    return out


@app.command("tree")
def community_tree(
    community: str = typer.Option(..., "--community", "-c", help="Community key"),
    api: str = typer.Option(
        "http://localhost:8000", "--api", help="Registry API base URL"
    ),
    timeout: float = typer.Option(30.0, "--timeout", help="HTTP timeout seconds"),
    max_items: int = typer.Option(
        500, "--max-items", min=1, max=5000, help="Max items per subleaf fetch"
    ),
):
    """
    Show a simplified community tree (community -> participants -> meters/assets).
    Pulls subleafs using minimal queries (no ?include).
    """
    with httpx.Client(timeout=timeout) as client:
        c = _get_json(client, _api_url(api, f"/communities/{community}"))
        participants = _get_json(
            client,
            _api_url(api, f"/communities/{community}/participants"),
            params={"limit": max_items},
        ).get("items", [])
        memberships = _get_json(
            client,
            _api_url(api, f"/communities/{community}/memberships"),
            params={"limit": max_items},
        ).get("items", [])
        sites = _get_json(
            client,
            _api_url(api, f"/communities/{community}/sites"),
            params={"limit": max_items},
        ).get("items", [])
        assets = _get_json(
            client,
            _api_url(api, f"/communities/{community}/assets"),
            params={"limit": max_items},
        ).get("items", [])
        meters = _get_json(
            client,
            _api_url(api, f"/communities/{community}/meters"),
            params={"limit": max_items},
        ).get("items", [])

    # Indexes
    participant_by_iri = {p.get("iri"): p for p in participants if p.get("iri")}
    participant_by_key = {p.get("key"): p for p in participants if p.get("key")}
    site_by_iri = {s.get("iri"): s for s in sites if s.get("iri")}
    site_by_key = {s.get("key"): s for s in sites if s.get("key")}

    assets_by_owner = _group_assets_by_owner(assets)
    meters_by_owner = _group_meters_by_owner(meters)

    # Community header
    typer.echo(f"{c.get('key')}  {c.get('name') or ''}".rstrip())
    typer.echo(f"  iri: {c.get('iri')}")

    typer.echo(f"  participants: {len(participants)}")
    typer.echo(f"  memberships: {len(memberships)}")
    typer.echo(f"  sites: {len(sites)}")
    typer.echo(f"  assets: {len(assets)}")
    typer.echo(f"  meters: {len(meters)}")

    # Sites (compact)
    if sites:
        typer.echo("  sites:")
        for s in sorted(sites, key=lambda x: x.get("key", "")):
            label = s.get("name") or s.get("area") or ""
            typer.echo(f"    - {s.get('key')} {label}".rstrip())

    # Participants with their memberships + meters/assets counts
    if participants:
        typer.echo("  participants:")
        # membership map by participant iri
        roles_by_participant: dict[str, list[str]] = {}
        for m in memberships:
            p_iri = m.get("participant")
            role = m.get("role_iri") or ""
            if p_iri:
                roles_by_participant.setdefault(p_iri, []).append(role)

        for p in sorted(participants, key=lambda x: x.get("key", "")):
            p_key = p.get("key")
            p_iri = p.get("iri")
            p_name = p.get("name") or ""
            p_kind = p.get("kind") or ""

            # Owner field in assets/meters is expected to be an IRI in API output.
            a_list = assets_by_owner.get(p_iri, [])
            m_list = meters_by_owner.get(p_iri, [])

            roles = roles_by_participant.get(p_iri, [])
            roles_s = ", ".join(sorted(set([r for r in roles if r]))) if roles else ""

            header = f"    - {p_key}"
            if p_name:
                header += f" {p_name}"
            if p_kind:
                header += f" [{p_kind}]"
            if roles_s:
                header += f" roles: {roles_s}"
            header += f"  assets={len(a_list)} meters={len(m_list)}"
            typer.echo(header)

            # Meters (simplified)
            for mm in sorted(m_list, key=lambda x: x.get("key", "")):
                site_label = ""
                site_ref = mm.get("site")
                if site_ref:
                    s = site_by_iri.get(site_ref) or site_by_key.get(site_ref)
                    site_label = f" @ {s.get('key')}" if s and s.get("key") else ""
                sensor = mm.get("sensor_id") or ""
                typer.echo(
                    f"        meter {mm.get('key')}{site_label} sensor={sensor}".rstrip()
                )

            # Assets (simplified)
            for aa in sorted(a_list, key=lambda x: x.get("key", "")):
                site_label = ""
                site_ref = aa.get("site")
                if site_ref:
                    s = site_by_iri.get(site_ref) or site_by_key.get(site_ref)
                    site_label = f" @ {s.get('key')}" if s and s.get("key") else ""
                cat = aa.get("category_iri") or ""
                typer.echo(
                    f"        asset {aa.get('key')}{site_label} category={cat}".rstrip()
                )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
