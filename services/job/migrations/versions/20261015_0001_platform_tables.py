"""Platform tables: audit_logs and outbox_events (v5, identical in every service database)

Revision ID: 0001_platform_tables
Revises:
Create Date: 2026-10-15
"""
from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from js_core.migrations import runtime_role_grants_sql

revision = "0001_platform_tables"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_type", sa.String(10), server_default=sa.text("'USER'"), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("result", sa.String(10), server_default=sa.text("'SUCCESS'"), nullable=False),
        sa.Column("before_data", postgresql.JSONB(), nullable=True),
        sa.Column("after_data", postgresql.JSONB(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
        sa.CheckConstraint("actor_type IN ('USER','SERVICE','SYSTEM')", name="ck_audit_logs_actor_type"),
        sa.CheckConstraint("result IN ('SUCCESS','FAILURE','DENIED')", name="ck_audit_logs_result"),
    )
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id", sa.text("occurred_at DESC")])
    op.create_index("ix_audit_logs_actor", "audit_logs", ["actor_user_id", sa.text("occurred_at DESC")])
    op.create_index("ix_audit_logs_organization", "audit_logs", ["organization_id", sa.text("occurred_at DESC")])
    op.create_index("ix_audit_logs_occurred_brin", "audit_logs", ["occurred_at"], postgresql_using="brin")

    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("aggregate_type", sa.String(50), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("event_version", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_events"),
    )
    op.create_index("ix_outbox_events_unpublished", "outbox_events", ["occurred_at"],
                    postgresql_where=sa.text("published_at IS NULL"))

    # Runtime role: DML on this database, but audit_logs stays append-only.
    role = context.config.attributes.get("runtime_role")
    if role:
        for statement in runtime_role_grants_sql(role):
            op.execute(statement)


def downgrade() -> None:
    op.drop_index("ix_outbox_events_unpublished", table_name="outbox_events")
    op.drop_table("outbox_events")
    for name in ("ix_audit_logs_occurred_brin", "ix_audit_logs_organization", "ix_audit_logs_actor", "ix_audit_logs_entity"):
        op.drop_index(name, table_name="audit_logs")
    op.drop_table("audit_logs")
