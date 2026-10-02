"""Approved email data model: email_settings, email_templates, email_delivery_logs

Owner: Engagement (docs/decisions.md). Data model only; SMTP passwords are stored as
secret references, delivery logs keep no body and a masked recipient.

Revision ID: 0002_email_tables
Revises: 0001_platform_tables
Create Date: 2026-10-15
"""
from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from js_core.migrations import runtime_role_grants_sql

revision = '0002_email_tables'
down_revision = '0001_platform_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('email_settings',
    sa.Column('setting_code', sa.String(length=30), server_default=sa.text("'DEFAULT'"), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('delivery_mode', sa.String(length=15), server_default=sa.text("'DISABLED'"), nullable=False),
    sa.Column('smtp_host', sa.String(length=255), nullable=True),
    sa.Column('smtp_port', sa.Integer(), nullable=True),
    sa.Column('smtp_security', sa.String(length=10), server_default=sa.text("'STARTTLS'"), nullable=False),
    sa.Column('smtp_username', sa.String(length=254), nullable=True),
    sa.Column('smtp_password_ref', sa.String(length=300), nullable=True),
    sa.Column('from_email', sa.String(length=254), nullable=True),
    sa.Column('from_name', sa.String(length=120), nullable=True),
    sa.Column('reply_to_email', sa.String(length=254), nullable=True),
    sa.Column('timeout_seconds', sa.SmallInteger(), server_default=sa.text('10'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("NOT is_enabled OR delivery_mode <> 'DISABLED'", name=op.f('ck_email_settings_enabled_has_mode')),
    sa.CheckConstraint("delivery_mode <> 'SMTP' OR (smtp_host IS NOT NULL AND smtp_port IS NOT NULL AND from_email IS NOT NULL)", name=op.f('ck_email_settings_smtp_complete')),
    sa.CheckConstraint("delivery_mode IN ('DISABLED','DEV_LOG','SMTP')", name=op.f('ck_email_settings_delivery_mode')),
    sa.CheckConstraint("smtp_password_ref IS NULL OR smtp_password_ref ~ '^(env:[A-Za-z_][A-Za-z0-9_]*|file:/.+)$'", name=op.f('ck_email_settings_password_is_reference')),
    sa.CheckConstraint("smtp_security IN ('STARTTLS','SSL','NONE')", name=op.f('ck_email_settings_smtp_security')),
    sa.CheckConstraint('smtp_port IS NULL OR smtp_port BETWEEN 1 AND 65535', name=op.f('ck_email_settings_smtp_port')),
    sa.CheckConstraint('timeout_seconds BETWEEN 1 AND 120', name=op.f('ck_email_settings_timeout_seconds')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_email_settings')),
    sa.UniqueConstraint('setting_code', name=op.f('uq_email_settings_setting_code'))
    )
    op.create_table('email_templates',
    sa.Column('template_code', sa.String(length=60), nullable=False),
    sa.Column('language_code', sa.String(length=10), server_default=sa.text("'en'"), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('subject', sa.String(length=200), nullable=False),
    sa.Column('body_text', sa.Text(), nullable=False),
    sa.Column('body_html', sa.Text(), nullable=True),
    sa.Column('allowed_variables', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('status', sa.String(length=15), server_default=sa.text("'DRAFT'"), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.UUID(), nullable=True),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("status IN ('DRAFT','ACTIVE','INACTIVE')", name=op.f('ck_email_templates_status')),
    sa.CheckConstraint("template_code ~ '^[A-Z][A-Z0-9_]*$'", name=op.f('ck_email_templates_template_code')),
    sa.CheckConstraint('deleted_at IS NULL OR deleted_by IS NOT NULL', name=op.f('ck_email_templates_deleted_by_required')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_email_templates'))
    )
    op.create_index('ix_email_templates_status', 'email_templates', ['status'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('uq_email_templates_code_language', 'email_templates', ['template_code', 'language_code'], unique=True, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_table('email_delivery_logs',
    sa.Column('template_id', sa.UUID(), nullable=True),
    sa.Column('template_code', sa.String(length=60), nullable=False),
    sa.Column('recipient_masked', sa.String(length=254), nullable=False),
    sa.Column('recipient_hash', sa.CHAR(length=64), nullable=False),
    sa.Column('recipient_user_id', sa.UUID(), nullable=True),
    sa.Column('organization_id', sa.UUID(), nullable=True),
    sa.Column('source_service', sa.String(length=30), nullable=False),
    sa.Column('source_reference', sa.String(length=100), nullable=True),
    sa.Column('delivery_mode', sa.String(length=15), nullable=False),
    sa.Column('status', sa.String(length=15), server_default=sa.text("'QUEUED'"), nullable=False),
    sa.Column('provider_reference', sa.String(length=200), nullable=True),
    sa.Column('error_code', sa.String(length=60), nullable=True),
    sa.Column('attempts', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.CheckConstraint("delivery_mode IN ('DISABLED','DEV_LOG','SMTP')", name=op.f('ck_email_delivery_logs_delivery_mode')),
    sa.CheckConstraint("status <> 'FAILED' OR error_code IS NOT NULL", name=op.f('ck_email_delivery_logs_failure_code')),
    sa.CheckConstraint("status <> 'SENT' OR sent_at IS NOT NULL", name=op.f('ck_email_delivery_logs_sent_at')),
    sa.CheckConstraint("status IN ('QUEUED','SENT','FAILED','SKIPPED')", name=op.f('ck_email_delivery_logs_status')),
    sa.CheckConstraint('attempts >= 0', name=op.f('ck_email_delivery_logs_attempts')),
    sa.ForeignKeyConstraint(['template_id'], ['email_templates.id'], name=op.f('fk_email_delivery_logs_template_id_email_templates'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_email_delivery_logs'))
    )
    op.create_index('ix_email_delivery_logs_recipient', 'email_delivery_logs', ['recipient_hash', sa.literal_column('created_at DESC')], unique=False)
    op.create_index('ix_email_delivery_logs_status', 'email_delivery_logs', ['status', 'created_at'], unique=False)
    op.create_index('ix_email_delivery_logs_template', 'email_delivery_logs', ['template_id'], unique=False)
    op.create_index('uq_email_delivery_logs_source', 'email_delivery_logs', ['source_service', 'source_reference'], unique=True, postgresql_where=sa.text('source_reference IS NOT NULL'))

    role = context.config.attributes.get("runtime_role")
    if role:
        for statement in runtime_role_grants_sql(role):
            op.execute(statement)


def downgrade() -> None:
    op.drop_index('uq_email_delivery_logs_source', table_name='email_delivery_logs', postgresql_where=sa.text('source_reference IS NOT NULL'))
    op.drop_index('ix_email_delivery_logs_template', table_name='email_delivery_logs')
    op.drop_index('ix_email_delivery_logs_status', table_name='email_delivery_logs')
    op.drop_index('ix_email_delivery_logs_recipient', table_name='email_delivery_logs')
    op.drop_table('email_delivery_logs')
    op.drop_index('uq_email_templates_code_language', table_name='email_templates', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index('ix_email_templates_status', table_name='email_templates', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_table('email_templates')
    op.drop_table('email_settings')
