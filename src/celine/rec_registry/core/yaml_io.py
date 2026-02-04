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
