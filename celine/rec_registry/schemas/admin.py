from typing import Dict, List
from pydantic import BaseModel, Field
from celine.rec_registry.schemas.bundle import RegistryBundleIn


class ImportRequest(BaseModel):
    """
    Import request where the client already parsed YAML into a JSON object.
    """

    bundle: RegistryBundleIn = Field(..., description="Greenland bundle as JSON object")
    dry_run: bool = Field(default=False, description="Validate without writing to DB")


class ImportReport(BaseModel):
    """
    Result of a replacement import operation.
    Returned by /admin/import and used by CLI.
    """

    community_key: str

    # Counts of deleted entities (previous state)
    deleted: Dict[str, int] = Field(default_factory=dict)

    # Counts of inserted entities (new state)
    inserted: Dict[str, int] = Field(default_factory=dict)

    # Non-fatal issues (skipped placeholders, missing refs, etc.)
    warnings: List[str] = Field(default_factory=list)
