"""Two runs of this suite can share one PostgreSQL without meeting.

The integration fixtures build and drop a throwaway schema. With a fixed name,
a second run started while the first is still going drops the first one's
tables under it, or collides with it on `pg_type` while both create the same
types — failures that belong to neither run and do not reproduce alone.
"""

import os
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).parent.parent


def _schemas_of_one_run() -> tuple[str, str]:
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            "import tests.conftest as c, tests.test_migrations as m;"
            "print(c.SCHEMA); print(m.SCHEMA)",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return out[0], out[1]


def test_each_run_builds_its_own_schemas():
    first = _schemas_of_one_run()
    second = _schemas_of_one_run()

    assert first[0] != second[0]
    assert first[1] != second[1]
    assert first[0].startswith("rec_registry_test_")
    assert first[1].startswith("rec_registry_migrations_")
    # A PostgreSQL identifier is at most 63 bytes; a longer one is truncated
    # silently, and two truncated names could meet again.
    assert all(len(name) <= 63 for name in first + second)
