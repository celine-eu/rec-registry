from fastapi import APIRouter, Depends, UploadFile, File, Body, Query, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from celine.rec_registry.db.session import get_session
from celine.rec_registry.core.yaml_io import load_yaml
from celine.rec_registry.schemas.bundle import RegistryBundleIn
from celine.rec_registry.services.importer import replacement_import_bundle
from celine.rec_registry.services.exporter import export_community_bundle_yaml
from celine.rec_registry.schemas.admin import ImportReport, ImportRequest
from celine.rec_registry.core.settings import settings

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/import", response_model=ImportReport)
async def admin_import(
    payload: ImportRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    Replacement import of a REC YAML bundle.

    - Deletes existing community graph (by community.key)
    - Recreates it atomically
    """
    async with session.begin():
        community_key, deleted, inserted, warnings = await replacement_import_bundle(
            session=session,
            bundle=payload.bundle,
            base_url=settings.base_url,
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
    community: str = Query(..., description="Community key"),
    session: AsyncSession = Depends(get_session),
):
    try:
        text = await export_community_bundle_yaml(session, community_key=community)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return text
