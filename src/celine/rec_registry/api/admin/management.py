"""
Admin API routes for registry import/export operations.
"""

from fastapi import APIRouter, Depends, Query, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from celine.rec_registry.core.errors import RegistryError, error_responses
from celine.rec_registry.db.session import get_session
from celine.rec_registry.db.models import Community
from celine.rec_registry.schemas.bundle import (
    ImportRefusal,
    ImportRequest,
    ImportReport,
    MultiImportReport,
    RegistryBundleIn,
)
from celine.rec_registry.services.importer import (
    ImportRefused,
    ImportWouldOverwrite,
    import_refusals,
    replacement_import_bundle,
)
from celine.rec_registry.services.exporter import export_community_bundle
from celine.rec_registry.core.yaml_io import load_yaml_all, dump_yaml, dump_yaml_all

router = APIRouter()


def _refused(exc: ImportRefused) -> RegistryError:
    # 422, not 409: the bundle is what is wrong, whatever the registry holds
    # (REQ-0074). The code is the broken invariant's.
    return RegistryError(422, str(exc), exc.code)


async def _dry_run_refusals(session: AsyncSession, bundle: RegistryBundleIn):
    return [
        ImportRefusal(code=code, detail=detail)
        for code, detail in await import_refusals(session, bundle)
    ]


@router.post("/import", response_model=ImportReport, responses=error_responses(422))
async def admin_import(
    payload: ImportRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    Replacement import of a REC registry bundle.

    - Deletes existing community (by community.id/key) with all related data
    - Creates new community with members and assets atomically
    - Returns counts of deleted and inserted entities

    **This is destructive.** Members now arrive at runtime through the member
    API, so re-importing a stale export is the most likely way to lose them.
    Overwriting an existing community therefore requires `force=true`, and
    answers `409` without it, naming what would have been deleted.

    Use `dry_run=true` to see the effect first — that is the intended way to
    decide whether `force` is warranted.

    **A bundle that breaks an invariant is refused whole**, before anything is
    deleted: `422` with the invariant's `code` — `sensor_held`, one sensor held
    by two active members of the bundle, or by one of them and an active member
    of another community (REQ-0069); `asset_key_too_long`, an asset key over
    128 characters (REQ-0028). A dry run lists every such refusal in
    `refusals` instead. A body that fails validation is a `422` too, with
    FastAPI's list `detail`; the OpenAPI document declares both bodies.
    """
    refusals: list[ImportRefusal] = []
    try:
        async with session.begin():
            if payload.dry_run:
                refusals = await _dry_run_refusals(session, payload.bundle)
            community_key, deleted, inserted, warnings = await replacement_import_bundle(
                session=session,
                bundle=payload.bundle,
                dry_run=payload.dry_run,
                force=payload.force,
            )
    except ImportWouldOverwrite as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ImportRefused as exc:
        raise _refused(exc) from exc

    return ImportReport(
        community_key=community_key,
        deleted=deleted,
        inserted=inserted,
        warnings=warnings,
        refusals=refusals,
    )


@router.post(
    "/import/yaml", response_model=MultiImportReport, responses=error_responses(422)
)
async def admin_import_yaml(
    request: Request,
    dry_run: bool = Query(False, description="Validate without making changes"),
    force: bool = Query(
        False,
        description=(
            "Overwrite communities that already exist. Without it an existing "
            "community answers 409 rather than being deleted and recreated."
        ),
    ),
    session: AsyncSession = Depends(get_session),
):
    """
    Replacement import of one or more REC registry bundles from YAML.

    Accepts a multidocument YAML body (documents separated by `---`).
    Each document must be a valid registry bundle.

    **Destructive**: see `POST /admin/import`. `force=true` is required to
    overwrite an existing community, and a bundle breaking an invariant refuses
    the whole request with `422` and its `code`; a dry run reports it instead.

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
    try:
        async with session.begin():
            for bundle in bundles:
                refusals = (
                    await _dry_run_refusals(session, bundle) if dry_run else []
                )
                community_key, deleted, inserted, warnings = await replacement_import_bundle(
                    session=session,
                    bundle=bundle,
                    dry_run=dry_run,
                    force=force,
                )
                reports.append(ImportReport(
                    community_key=community_key,
                    deleted=deleted,
                    inserted=inserted,
                    warnings=warnings,
                    refusals=refusals,
                ))
    except ImportWouldOverwrite as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ImportRefused as exc:
        raise _refused(exc) from exc

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
