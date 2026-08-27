"""
Alembic environment configuration.

Supports automatic database creation if it doesn't exist.
"""

from __future__ import annotations

import logging
from logging.config import fileConfig
from urllib.parse import urlparse, urlunparse

from alembic import context
from sqlalchemy import MetaData, engine_from_config, pool, text
from sqlalchemy import create_engine

from celine.rec_registry.db.models import *  # noqa
from celine.rec_registry.db.session import Base
from celine.rec_registry.core.settings import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata: MetaData = Base.metadata

logger = logging.getLogger("alembic.env")


def _sync_db_url(async_url: str) -> str:
    """Convert async DB URL to sync for Alembic migrations."""
    if async_url.startswith("postgresql+asyncpg://"):
        return async_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    return async_url


def _get_maintenance_url(db_url: str) -> tuple[str, str]:
    """
    Parse DB URL and return (maintenance_url, db_name).

    Maintenance URL connects to 'postgres' database for admin operations.
    """
    parsed = urlparse(db_url)
    db_name = parsed.path.lstrip("/")

    # Connect to 'postgres' database for maintenance operations
    maintenance_parsed = parsed._replace(path="/postgres")
    maintenance_url = urlunparse(maintenance_parsed)

    return maintenance_url, db_name


def _ensure_database_exists(db_url: str) -> None:
    """
    Create the database if it doesn't exist.

    Connects to the 'postgres' maintenance database to check/create.
    """
    maintenance_url, db_name = _get_maintenance_url(db_url)

    if not db_name:
        logger.warning("Could not parse database name from URL, skipping auto-create")
        return

    engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")

    try:
        with engine.connect() as conn:
            # Check if database exists
            result = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :dbname"),
                {"dbname": db_name},
            )
            exists = result.scalar() is not None

            if not exists:
                logger.info(f"Creating database '{db_name}'...")
                # Sanitize db_name to prevent SQL injection (only allow safe chars)
                if not db_name.replace("_", "").isalnum():
                    raise ValueError(f"Invalid database name: {db_name}")
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
                logger.info(f"Database '{db_name}' created successfully")
            else:
                logger.debug(f"Database '{db_name}' already exists")
    except Exception as e:
        logger.warning(f"Could not auto-create database: {e}")
    finally:
        engine.dispose()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = _sync_db_url(settings.database_url)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    A caller may supply its own connection through ``config.attributes`` — the
    suite does, so that migrations can be run against a throwaway schema and
    compared to ``Base.metadata`` without a subprocess and without pointing
    ``settings.database_url`` at a test database. Deployment supplies nothing and
    takes the branch below.
    """
    supplied = config.attributes.get("connection")
    if supplied is not None:
        context.configure(
            connection=supplied, target_metadata=target_metadata, compare_type=True
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    sync_url = _sync_db_url(settings.database_url)

    # Ensure database exists before running migrations
    _ensure_database_exists(sync_url)

    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = sync_url
    connectable = engine_from_config(
        configuration, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, compare_type=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
