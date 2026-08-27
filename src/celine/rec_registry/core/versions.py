"""Which version of what, in one place.

Four places used to hold three opinions about the schema version — `/version`
said `0.4`, the documents and the example bundle said `0.5`, and both the bundle
model's default and the exporter said `1.0`. They drifted freely *because*
nothing read the field: a value nobody reads has nothing holding it to any other
copy of itself.

So the fix is not "correct the four literals", which would drift again. It is
that there is one copy and everything reads it.

## The two fields are different questions

`schemas/community/v0.5/README.md` defines them separately, and conflating them
is how `1.0` ended up in the `schema_version` slot:

* ``version`` — the format of the *envelope*: that a manifest is a mapping with
  `community` and `members` in it. Currently `1.0`, and it has never moved.
* ``schema_version`` — which schema under ``schemas/community/`` the *content*
  conforms to. Currently `0.5`, and it has moved once, with real removals:
  `area.location` and `topology[].dso` are gone, `community.operators` arrived.

## Why these are constants and not derived

``api_version`` is derived, from the installed distribution — that is the whole
point of it, and it is why `/version` can now answer "what is deployed?".

``CURRENT_SCHEMA_VERSION`` cannot be. The obvious derivation is to read
``schemas/community/`` and take the highest, but the `Dockerfile` copies `src`,
`policies`, `alembic` and `alembic.ini` — **`schemas/` does not ship in the
image**, so at runtime there is no directory to read. It is written down here
instead, and `tests/test_versions.py` holds it to the directory in the
repository, which is where a divergence would begin.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _distribution_version

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "DISTRIBUTION",
    "KNOWN_SCHEMA_VERSIONS",
    "MANIFEST_VERSION",
    "api_version",
]

DISTRIBUTION = "celine-rec-registry"

# The envelope format. Distinct from the schema version — see the module docstring.
MANIFEST_VERSION = "1.0"

# The schema under `schemas/community/` this service reads and writes.
CURRENT_SCHEMA_VERSION = "0.5"

# Every schema version published under `schemas/community/`. A bundle declaring
# one of these is understood; anything else is imported anyway and warned about,
# because refusing is what breaks restoring a backup, and a backup is restored
# when something has already gone wrong.
KNOWN_SCHEMA_VERSIONS = ("0.4", "0.5")


def api_version() -> str:
    """The version of the installed package, not a literal typed into a route.

    Answers `0.0.0+unknown` rather than raising when the distribution cannot be
    found — running from a source tree that was never installed, mostly.
    `/version` is reached for when something is already wrong, and a version
    route that raises is worse than one that says it does not know.
    """
    try:
        return _distribution_version(DISTRIBUTION)
    except PackageNotFoundError:  # pragma: no cover - depends on how it was installed
        return "0.0.0+unknown"
