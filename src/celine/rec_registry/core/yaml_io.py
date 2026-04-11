"""
YAML parsing and serialization utilities.
"""

from __future__ import annotations

from typing import Any

import yaml


def load_yaml(text: str) -> dict[str, Any]:
    """
    Parse YAML text into a Python dict.

    Raises:
        ValueError: if the YAML is invalid or top-level is not a mapping/object.
    """
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("Top-level YAML must be a mapping/object")

    return data


def load_yaml_all(text: str) -> list[dict[str, Any]]:
    """
    Parse a multidocument YAML string into a list of Python dicts.

    Raises:
        ValueError: if the YAML is invalid or any document is not a mapping/object.
    """
    try:
        docs = list(yaml.safe_load_all(text))
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML: {e}") from e

    result = []
    for i, doc in enumerate(docs):
        if doc is None:
            continue
        if not isinstance(doc, dict):
            raise ValueError(f"Document {i} top-level must be a mapping/object")
        result.append(doc)

    return result


def dump_yaml(data: Any) -> str:
    """
    Dump a Python object to YAML text.

    Notes:
      - Uses block style by default (no flow style)
      - Preserves key insertion order (Python 3.7+ dict order)
      - Allows Unicode output
    """
    return yaml.safe_dump(
        data,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )


def dump_yaml_all(docs: list[Any]) -> str:
    """
    Dump a list of Python objects to a multidocument YAML string.

    Each document is separated by the YAML document marker (---).
    """
    return yaml.safe_dump_all(
        docs,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
