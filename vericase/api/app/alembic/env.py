"""Alembic environment configuration for VeriCase.

This file wires Alembic to:
- the same DATABASE_URL used by the application (via app.config.Settings)
- the SQLAlchemy metadata defined on app.db.Base

It is designed to work in both:
- local development (running `alembic` from vericase/api)
- container environments (running inside /code with app/ on PYTHONPATH)
"""

from __future__ import annotations

from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import create_engine, pool

from app.config import settings
from app.db import Base

# Alembic Config object, provides access to values in alembic.ini.
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for 'autogenerate' support.
target_metadata = Base.metadata


def get_url() -> str:
    """Return the database URL used for migrations.

    We intentionally reuse the application's DATABASE_URL so that
    migrations always run against the same database as the app.
    """
    return settings.DATABASE_URL


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    In this mode, we configure the context with just a URL, and not an
    Engine. Calls to context.execute() here generate SQL strings.
    """
    url = get_url()

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario, we need an Engine and associate a connection with
    the context.
    """
    connectable = create_engine(
        get_url(),
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

