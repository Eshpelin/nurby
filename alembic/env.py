import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from shared.database import Base
from shared.models import *  # noqa: F401,F403 - import all models for autogenerate

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url with runtime DATABASE_URL so containers
# resolve postgres via the docker network instead of the host-bound
# port baked into alembic.ini.
_env_db_url = os.environ.get("DATABASE_URL")
if _env_db_url:
    config.set_main_option("sqlalchemy.url", _env_db_url)

target_metadata = Base.metadata


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    # Extensions the schema depends on (pgvector's `vector` type shows up
    # mid-chain in the face_embeddings migration). The docker image
    # pre-installs the extension binaries but each DATABASE still needs
    # CREATE EXTENSION, so a fresh database on a stock pgvector/postgres
    # image fails migration without this. Idempotent; requires the
    # migration role to own the database (true for the default setup).
    from sqlalchemy import text

    for ext in ("vector", "btree_gist"):
        try:
            connection.execute(text(f"CREATE EXTENSION IF NOT EXISTS {ext}"))
        except Exception:
            # Non-superuser against a managed DB: fall through and let the
            # migration surface the real error if the extension is missing.
            pass

    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online():
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
