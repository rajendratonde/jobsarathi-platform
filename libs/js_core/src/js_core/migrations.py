"""Alembic helpers shared by every service's migrations/env.py."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def alembic_config(service_root: Path, url: str | None = None) -> Config:
    cfg = Config(str(service_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(service_root / "migrations"))
    if url:
        cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def head_revision(service_root: Path) -> str | None:
    """The revision a ready database must be at."""
    script = ScriptDirectory.from_config(alembic_config(service_root))
    heads = script.get_heads()
    if len(heads) > 1:
        raise RuntimeError(f"Multiple Alembic heads in {service_root.name}: {heads}")
    return heads[0] if heads else None


def runtime_role_grants_sql(runtime_role: str, append_only_tables: tuple[str, ...] = ("audit_logs",)) -> list[str]:
    """Statements that give the runtime role DML on this database, with append-only audit tables.

    Wrapped in DO blocks so they are skipped (not failed) when the role does not
    exist, e.g. in a throwaway test database.
    """
    role = runtime_role.replace('"', "")
    stmts = [
        f"""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
            EXECUTE 'GRANT USAGE ON SCHEMA public TO "{role}"';
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{role}"';
            EXECUTE 'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"';
        END IF; END $$;""",
    ]
    for table in append_only_tables:
        stmts.append(
            f"""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}')
                AND to_regclass('public.{table}') IS NOT NULL THEN
                EXECUTE 'REVOKE UPDATE, DELETE, TRUNCATE ON public.{table} FROM "{role}"';
            END IF; END $$;""")
    return stmts
