"""The version constants against what is actually published.

`core/versions.py` writes the schema version down rather than deriving it,
because `schemas/` does not ship in the Docker image and there is no directory
to read at runtime. Writing a number down is how the four copies drifted in the
first place, so the constant is held to the directory here, in the one place
that can see both: the repository.

This is the check that fails when somebody adds `schemas/community/v0.6/` and
stops there.
"""

from __future__ import annotations

import pathlib

from celine.rec_registry.core.versions import (
    CURRENT_SCHEMA_VERSION,
    KNOWN_SCHEMA_VERSIONS,
    api_version,
)

PUBLISHED = pathlib.Path(__file__).parent.parent / "schemas" / "community"


def _published_versions() -> list[str]:
    """The schema versions that exist as directories, `v0.5` → `0.5`."""
    return sorted(d.name[1:] for d in PUBLISHED.iterdir() if d.name.startswith("v"))


class TestTheVersionConstantsMatchWhatIsPublished:
    def test_every_known_version_has_a_schema_directory(self):
        assert sorted(KNOWN_SCHEMA_VERSIONS) == _published_versions()

    def test_the_current_version_is_one_of_them(self):
        assert CURRENT_SCHEMA_VERSION in KNOWN_SCHEMA_VERSIONS

    def test_the_current_version_is_the_newest_published(self):
        """Adding `v0.6/` and forgetting to move the constant is the whole
        failure this file exists for."""
        newest = max(_published_versions(), key=lambda v: tuple(int(p) for p in v.split(".")))

        assert CURRENT_SCHEMA_VERSION == newest

    def test_the_current_schema_directory_holds_a_schema(self):
        current = PUBLISHED / f"v{CURRENT_SCHEMA_VERSION}"

        assert (current / "community.schema.json").is_file()


class TestTheApiVersion:
    def test_it_is_the_installed_distribution_version(self):
        """Not a literal, which is what it was — `1.0.0`, five minor releases
        after that stopped being true."""
        from importlib.metadata import version as package_version

        assert api_version() == package_version("celine-rec-registry")
