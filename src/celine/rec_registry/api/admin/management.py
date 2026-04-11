"""
Admin API routes for registry import/export operations.
"""

from fastapi import APIRouter, Depends, Query, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from celine.rec_registry.db.session import get_session
from celine.rec_registry.db.models import Community
from celine.rec_registry.schemas.bundle import (
    ImportRequest,
    ImportReport,
    MultiImportReport,
    RegistryBundleIn,
)
from celine.rec_registry.services.importer import replacement_import_bundle
from celine.rec_registry.services.exporter import export_community_bundle
from celine.rec_registry.core.yaml_io import load_yaml_all, dump_yaml, dump_yaml_all

router = APIRouter()


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


@router.post("/import/yaml", response_model=MultiImportReport)
async def admin_import_yaml(
    request: Request,
    dry_run: bool = Query(False, description="Validate without making changes"),
    session: AsyncSession = Depends(get_session),
):
    """
    Idempotent replacement import of one or more REC registry bundles from YAML.

    Accepts a multidocument YAML body (documents separated by `---`).
    Each document must be a valid registry bundle.

    Returns a report for each imported bundle.
    """
    body = await request.body()
    try:
        raw_text = body.decode("utf-8")
    except UnicodeDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid UTF-8 body: {e}")

    try:
        docs = load_yaml_all(raw_text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not docs:
        raise HTTPException(status_code=400, detail="No YAML documents found in body")

    bundles: list[RegistryBundleIn] = []
    for i, doc in enumerate(docs):
        try:
            bundles.append(RegistryBundleIn.model_validate(doc))
        except ValidationError as e:
            raise HTTPException(
                status_code=422,
                detail=f"Document {i} validation error: {e}",
            )

    reports: list[ImportReport] = []
    async with session.begin():
        for bundle in bundles:
            community_key, deleted, inserted, warnings = await replacement_import_bundle(
                session=session,
                bundle=bundle,
                dry_run=dry_run,
            )
            reports.append(ImportReport(
                community_key=community_key,
                deleted=deleted,
                inserted=inserted,
                warnings=warnings,
            ))

    return MultiImportReport(reports=reports, dry_run=dry_run)


@router.get("/export", response_class=PlainTextResponse)
async def admin_export(
    community: list[str] | None = Query(None, description="Community key(s) to export; omit to export all"),
    session: AsyncSession = Depends(get_session),
):
    """
    Export one or more communities to YAML format.

    Pass `community` once per key to export specific communities.
    Omit `community` entirely to export all communities.
    Returns a multidocument YAML string (documents separated by `---`).
    """
    if not community:
        keys = list(await session.scalars(select(Community.key)))
    else:
        keys = community

    docs = []
    for key in keys:
        try:
            doc = await export_community_bundle(session, community_key=key)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))
        docs.append(doc)

    if len(docs) == 1:
        return PlainTextResponse(content=dump_yaml(docs[0]))

    return PlainTextResponse(content=dump_yaml_all(docs))
