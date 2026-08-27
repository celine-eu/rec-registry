"""The migrations build the schema the models declare.

Two different things build this schema and only one of them was ever tested.
Deployment runs the migrations — `docker-compose.yaml` starts with
`alembic upgrade head`, `taskfile.yml` has `db:migrate`, and the `Dockerfile`
copies `alembic/` into the image. The suite does not: `conftest.py` calls
`Base.metadata.create_all`.

So a model that had drifted from `alembic/versions/` passed every test and would
have failed on the first real deploy — or, worse, succeeded against a database
built one way and not the other. This file closes that, by building the schema
the way deployment does and comparing it to the way the suite does.

The comparison is `alembic.autogenerate.compare_metadata`, which is what
`alembic revision --autogenerate` runs to decide what a new revision should
contain. An empty result is the statement that autogenerating right now would
produce an empty migration.

**Server defaults are deliberately not compared.** The models write
`server_default="{}"` where the migration writes `sa.text("'{}'::jsonb")`; they
build the same default and compare as different text. A check that reports drift
that is not drift is a check somebody eventually deletes.
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

from celine.rec_registry.db.session import Base

# Imported for the side effect of registering every table on `Base.metadata`;
# comparing against a half-populated metadata would report every absent model as
# a table to drop.
import celine.rec_registry.db.models  # noqa: F401

from tests.conftest import PG_URL

# Its own schema, not the one `pg_engine` builds: this test creates the schema
# with the migrations rather than with `create_all`, and the two must not meet.
SCHEMA = "rec_registry_migrations"

REPO_ROOT = __import__("pathlib").Path(__file__).parent.parent


def _sync_url(url: str) -> str:
    """Alembic runs on the sync driver; the suite's URL names the async one."""
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)


@pytest.fixture
def migrated_connection():
    """A connection to a throwaway schema built by `alembic upgrade head`.

    A schema rather than a database, like `pg_engine`, so the fixture needs no
    CREATE DATABASE rights and leaves nothing behind.

    The connection is handed to `env.py` through `config.attributes`, which is
    alembic's own hook for this: `env.py` otherwise reads
    `settings.database_url`, and pointing that at a test database from inside a
    running suite would mean an environment variable and a subprocess.
    """
    engine = create_engine(_sync_url(PG_URL), future=True)

    try:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
            conn.execute(text(f'CREATE SCHEMA "{SCHEMA}"'))
    except Exception as exc:  # pragma: no cover - environment dependent
        engine.dispose()
        pytest.skip(f"No database available at {PG_URL}: {exc}")

    with engine.connect() as conn:
        conn.execute(text(f'SET search_path TO "{SCHEMA}"'))

        config = Config(str(REPO_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
        config.attributes["connection"] = conn
        command.upgrade(config, "head")
        conn.commit()

        yield conn

    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
    engine.dispose()


@pytest.mark.integration
class TestTheMigrationsMatchTheModels:
    def test_upgrading_to_head_builds_what_the_models_declare(
        self, migrated_connection
    ):
        """No difference between the deployed schema and `Base.metadata`.

        A failure here names what diverged. Read it in the direction alembic
        means it: `add_*` is in the models and missing from the migrations,
        `remove_*` is in the migrations and gone from the models. Either is
        drift, and the fix is whichever of the two is wrong — not, reflexively,
        a new revision.
        """
        context = MigrationContext.configure(
            migrated_connection, opts={"compare_type": True}
        )

        differences = compare_metadata(context, Base.metadata)

        assert differences == [], (
            "alembic upgrade head and Base.metadata disagree; "
            "`alembic revision --autogenerate` would produce a non-empty "
            f"migration:\n  " + "\n  ".join(repr(d) for d in differences)
        )

    def test_the_three_tables_are_all_there(self, migrated_connection):
        """A guard on the check above rather than a check of its own.

        `compare_metadata` against an empty schema reports every table as
        missing, so an empty result can only mean agreement if the migrations
        actually ran. If this fails, the test above proves nothing.
        """
        present = set(
            migrated_connection.scalars(
                text(
                    "select tablename from pg_tables where schemaname = :schema"
                ),
                {"schema": SCHEMA},
            )
        )

        assert {"community", "member", "asset"} <= present
