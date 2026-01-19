from __future__ import annotations

import asyncio
from pathlib import Path

import typer
import yaml

from celine.rec_registry.db.session import AsyncSessionLocal
from celine.rec_registry.schemas.import_yaml import CommunityImportDoc
from celine.rec_registry.services.importer import replace_community_from_doc

app = typer.Typer(add_completion=False, help="CELINE REC Registry CLI")
import_app = typer.Typer(name="import", help="Import registry structures")
app.add_typer(import_app)


@import_app.command("community")
def import_community(
    file: Path = typer.Option(..., "--file", "-f", exists=True, dir_okay=False, readable=True),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate and print counts without writing"),
):
    """Replace a community registry definition from an ergonomic YAML file."""

    payload = yaml.safe_load(file.read_text(encoding="utf-8"))
    doc = CommunityImportDoc.model_validate(payload)

    async def _run():
        async with AsyncSessionLocal() as session:
            if dry_run:
                # Just map + basic validation; no DB writes
                from celine.rec_registry.services.yaml_mapping import map_yaml_to_orm

                mapped = map_yaml_to_orm(doc)
                return {
                    "community": mapped.community_key,
                    "participants": len(mapped.participants),
                    "memberships": len(mapped.memberships),
                    "sites": len(mapped.sites),
                    "meters": len(mapped.meters),
                    "assets": len(mapped.assets),
                    "tariffs": len(mapped.tariffs),
                    "timeseries": len(mapped.timeseries),
                    "topology_edges": len(mapped.topology_edges),
                    "mode": "REPLACE (dry-run)",
                }

            stats = await replace_community_from_doc(session, doc)
            await session.commit()
            stats["community"] = doc.community.key
            stats["mode"] = "REPLACE"
            return stats

    result = asyncio.run(_run())
    typer.echo(yaml.safe_dump(result, sort_keys=False))


if __name__ == "__main__":
    app()
