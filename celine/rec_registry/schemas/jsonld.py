from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class JsonLdModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class JsonLdNode(JsonLdModel):
    context: Optional[str] = Field(default=None, alias="@context")
    id: str = Field(alias="@id")
    type: Any = Field(alias="@type")


class GraphDocument(JsonLdModel):
    context: str = Field(alias="@context")
    graph: List[Dict[str, Any]] = Field(alias="@graph")
