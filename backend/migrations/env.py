"""Migrations always run as app_owner. Pass `-x url=...` to target another database (tests)."""

from alembic import context
from sqlalchemy import create_engine, pool

from app.config import get_settings

url = context.get_x_argument(as_dictionary=True).get("url") or get_settings().migrations_database_url


def run_migrations_offline() -> None:
    context.configure(url=url, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
