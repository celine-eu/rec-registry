"""
Admin API routes for registry import/export operations.
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from celine.rec_registry.db.session import get_session
from celine.rec_registry.schemas.bundle import ImportRequest, ImportReport
from celine.rec_registry.services.importer import replacement_import_bundle
from celine.rec_registry.services.exporter import export_community_bundle_yaml

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/import", response_model=ImportReport)
async def admin_import(
    payload: ImportRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    Idempotent replacement import of a REC registry bundle.

    - Deletes existing community (by community.id/key) with all related data
    - Creates new community with members and assets atomically
    - Returns counts of deleted and inserted entities

    Use `dry_run=true` to validate without making changes.
    """
    async with session.begin():
        community_key, deleted, inserted, warnings = await replacement_import_bundle(
            session=session,
            bundle=payload.bundle,
            dry_run=payload.dry_run,
        )

    return ImportReport(
        community_key=community_key,
        deleted=deleted,
        inserted=inserted,
        warnings=warnings,
    )


@router.get("/export", response_class=PlainTextResponse)
async def admin_export(
    community: str = Query(..., description="Community key to export"),
    session: AsyncSession = Depends(get_session),
):
    """
    Export a community to v0.4 YAML format.

    Returns the complete registry bundle as YAML text.
    """
    try:
        text = await export_community_bundle_yaml(session, community_key=community)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return text
