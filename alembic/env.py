from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from celine.rec_registry.core.settings import settings
from celine.rec_registry.models import Base

# this is the Alembic Config object, which provides access to the values within
# the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    from logging.config import fileConfig

    fileConfig(config.config_file_name)

# Provide metadata for autogeneration.
target_metadata = Base.metadata


def _sync_url(async_url: str) -> str:
    # Convert async SQLAlchemy URL to a sync URL for Alembic.
    # postgresql+asyncpg:// -> postgresql+psycopg://
    if "+asyncpg" in async_url:
        return async_url.replace("+asyncpg", "+psycopg")
    return async_url


def run_migrations_offline() -> None:
    url = _sync_url(os.getenv("DATABASE_URL", settings.database_url))
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _sync_url(os.getenv("DATABASE_URL", settings.database_url))

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
