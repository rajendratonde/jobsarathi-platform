"""Reference Data tables (v5 section 19): eleven reference lists, lookup_values, Maker-Checker tables

Extension pg_trgm (v5: reference_db) backs the skills type-ahead index.

Revision ID: 0002_reference_lists
Revises: 0001_platform_tables
Create Date: 2026-10-15
"""
from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from js_core.migrations import runtime_role_grants_sql

revision = '0002_reference_lists'
down_revision = '0001_platform_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE SEQUENCE approval_request_number_seq START 1")
    op.create_table('approval_policies',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('entity_type', sa.String(length=50), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=True),
    sa.Column('is_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('maker_permission_code', sa.String(length=120), nullable=False),
    sa.Column('checker_permission_code', sa.String(length=120), nullable=False),
    sa.Column('required_approvals', sa.SmallInteger(), server_default=sa.text('1'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint('required_approvals BETWEEN 1 AND 3', name=op.f('ck_approval_policies_required_approvals')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approval_policies'))
    )
    op.create_index('uq_approval_policies_entity_org', 'approval_policies', ['entity_type', sa.literal_column("COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'::uuid)")], unique=True)
    op.create_table('education_levels',
    sa.Column('level_rank', sa.SmallInteger(), nullable=False),
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('name_hi', sa.String(length=150), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_education_levels')),
    sa.UniqueConstraint('code', name=op.f('uq_education_levels_code'))
    )
    op.create_index('ix_education_levels_active_sort', 'education_levels', ['is_active', 'sort_order'], unique=False)
    op.create_table('experience_bands',
    sa.Column('min_months', sa.Integer(), nullable=False),
    sa.Column('max_months', sa.Integer(), nullable=True),
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('name_hi', sa.String(length=150), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.CheckConstraint('max_months IS NULL OR max_months > min_months', name=op.f('ck_experience_bands_month_range')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_experience_bands')),
    sa.UniqueConstraint('code', name=op.f('uq_experience_bands_code'))
    )
    op.create_index('ix_experience_bands_active_sort', 'experience_bands', ['is_active', 'sort_order'], unique=False)
    op.create_table('industries',
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('name_hi', sa.String(length=150), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_industries')),
    sa.UniqueConstraint('code', name=op.f('uq_industries_code'))
    )
    op.create_index('ix_industries_active_sort', 'industries', ['is_active', 'sort_order'], unique=False)
    op.create_table('job_categories',
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('name_hi', sa.String(length=150), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_job_categories')),
    sa.UniqueConstraint('code', name=op.f('uq_job_categories_code'))
    )
    op.create_index('ix_job_categories_active_sort', 'job_categories', ['is_active', 'sort_order'], unique=False)
    op.create_table('job_types',
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('name_hi', sa.String(length=150), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_job_types')),
    sa.UniqueConstraint('code', name=op.f('uq_job_types_code'))
    )
    op.create_index('ix_job_types_active_sort', 'job_types', ['is_active', 'sort_order'], unique=False)
    op.create_table('lookup_values',
    sa.Column('list_code', sa.String(length=50), nullable=False),
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('name_hi', sa.String(length=150), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_lookup_values'))
    )
    op.create_index('uq_lookup_values_list_code', 'lookup_values', ['list_code', 'code'], unique=True)
    op.create_table('pay_types',
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('name_hi', sa.String(length=150), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pay_types')),
    sa.UniqueConstraint('code', name=op.f('uq_pay_types_code'))
    )
    op.create_index('ix_pay_types_active_sort', 'pay_types', ['is_active', 'sort_order'], unique=False)
    op.create_table('skills',
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('name_hi', sa.String(length=150), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_skills')),
    sa.UniqueConstraint('code', name=op.f('uq_skills_code'))
    )
    op.create_index('ix_skills_active_sort', 'skills', ['is_active', 'sort_order'], unique=False)
    op.create_index('ix_skills_name_trgm', 'skills', ['name'], unique=False, postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'})
    op.create_table('states',
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('name_hi', sa.String(length=150), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_states')),
    sa.UniqueConstraint('code', name=op.f('uq_states_code'))
    )
    op.create_index('ix_states_active_sort', 'states', ['is_active', 'sort_order'], unique=False)
    op.create_table('work_modes',
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('name_hi', sa.String(length=150), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_work_modes')),
    sa.UniqueConstraint('code', name=op.f('uq_work_modes_code'))
    )
    op.create_index('ix_work_modes_active_sort', 'work_modes', ['is_active', 'sort_order'], unique=False)
    op.create_table('approval_requests',
    sa.Column('policy_id', sa.UUID(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('request_number', sa.String(length=20), nullable=False),
    sa.Column('entity_type', sa.String(length=50), nullable=False),
    sa.Column('entity_id', sa.UUID(), nullable=False),
    sa.Column('entity_version', sa.Integer(), nullable=False),
    sa.Column('action_type', sa.String(length=20), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=True),
    sa.Column('subject_user_id', sa.UUID(), nullable=True),
    sa.Column('proposed_changes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('change_summary', sa.String(length=500), nullable=True),
    sa.Column('maker_user_id', sa.UUID(), nullable=False),
    sa.Column('maker_comment', sa.Text(), nullable=True),
    sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('status', sa.String(length=15), server_default=sa.text("'PENDING'"), nullable=False),
    sa.Column('decided_by', sa.UUID(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision_reason', sa.Text(), nullable=True),
    sa.CheckConstraint("(status IN ('APPROVED','REJECTED')) = (decided_by IS NOT NULL AND decided_at IS NOT NULL)", name=op.f('ck_approval_requests_decision_recorded')),
    sa.CheckConstraint("status <> 'REJECTED' OR length(trim(decision_reason)) >= 5", name=op.f('ck_approval_requests_rejection_reason')),
    sa.CheckConstraint("status IN ('PENDING','APPROVED','REJECTED','WITHDRAWN','SUPERSEDED')", name=op.f('ck_approval_requests_status')),
    sa.CheckConstraint('decided_by IS NULL OR decided_by <> maker_user_id', name=op.f('ck_approval_requests_four_eyes')),
    sa.CheckConstraint('decided_by IS NULL OR subject_user_id IS NULL OR decided_by <> subject_user_id', name=op.f('ck_approval_requests_not_own_access')),
    sa.ForeignKeyConstraint(['policy_id'], ['approval_policies.id'], name=op.f('fk_approval_requests_policy_id_approval_policies'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approval_requests')),
    sa.UniqueConstraint('request_number', name=op.f('uq_approval_requests_request_number'))
    )
    op.create_index('ix_approval_requests_entity', 'approval_requests', ['entity_type', 'entity_id', sa.literal_column('submitted_at DESC')], unique=False)
    op.create_index('ix_approval_requests_inbox', 'approval_requests', ['organization_id', 'submitted_at'], unique=False, postgresql_where=sa.text("status = 'PENDING'"))
    op.create_index('ix_approval_requests_maker', 'approval_requests', ['maker_user_id', sa.literal_column('submitted_at DESC')], unique=False)
    op.create_index('uq_approval_requests_one_pending', 'approval_requests', ['entity_type', 'entity_id'], unique=True, postgresql_where=sa.text("status = 'PENDING'"))
    op.create_table('cities',
    sa.Column('state_id', sa.UUID(), nullable=False),
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('name_hi', sa.String(length=150), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['state_id'], ['states.id'], name=op.f('fk_cities_state_id_states'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cities')),
    sa.UniqueConstraint('code', name=op.f('uq_cities_code'))
    )
    op.create_index('ix_cities_state_active', 'cities', ['state_id', 'is_active'], unique=False)
    op.create_index('uq_cities_state_name', 'cities', ['state_id', sa.literal_column('lower(name)')], unique=True)
    op.create_table('job_roles',
    sa.Column('job_category_id', sa.UUID(), nullable=True),
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('name_hi', sa.String(length=150), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['job_category_id'], ['job_categories.id'], name=op.f('fk_job_roles_job_category_id_job_categories'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_job_roles')),
    sa.UniqueConstraint('code', name=op.f('uq_job_roles_code'))
    )
    op.create_index('ix_job_roles_category', 'job_roles', ['job_category_id'], unique=False)
    op.create_table('approval_actions',
    sa.Column('approval_request_id', sa.UUID(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('action', sa.String(length=15), nullable=False),
    sa.Column('actor_user_id', sa.UUID(), nullable=False),
    sa.Column('acting_organization_id', sa.UUID(), nullable=True),
    sa.Column('reviewed_version', sa.Integer(), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('acted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("action IN ('SUBMITTED','APPROVED','REJECTED','WITHDRAWN','SUPERSEDED','COMMENTED')", name=op.f('ck_approval_actions_action')),
    sa.ForeignKeyConstraint(['approval_request_id'], ['approval_requests.id'], name=op.f('fk_approval_actions_approval_request_id_approval_requests'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approval_actions'))
    )
    op.create_index('ix_approval_actions_request', 'approval_actions', ['approval_request_id', 'acted_at'], unique=False)

    role = context.config.attributes.get("runtime_role")
    if role:
        for statement in runtime_role_grants_sql(role):
            op.execute(statement)


def downgrade() -> None:
    op.drop_index('ix_approval_actions_request', table_name='approval_actions')
    op.drop_table('approval_actions')
    op.drop_index('ix_job_roles_category', table_name='job_roles')
    op.drop_table('job_roles')
    op.drop_index('uq_cities_state_name', table_name='cities')
    op.drop_index('ix_cities_state_active', table_name='cities')
    op.drop_table('cities')
    op.drop_index('uq_approval_requests_one_pending', table_name='approval_requests', postgresql_where=sa.text("status = 'PENDING'"))
    op.drop_index('ix_approval_requests_maker', table_name='approval_requests')
    op.drop_index('ix_approval_requests_inbox', table_name='approval_requests', postgresql_where=sa.text("status = 'PENDING'"))
    op.drop_index('ix_approval_requests_entity', table_name='approval_requests')
    op.drop_table('approval_requests')
    op.drop_index('ix_work_modes_active_sort', table_name='work_modes')
    op.drop_table('work_modes')
    op.drop_index('ix_states_active_sort', table_name='states')
    op.drop_table('states')
    op.drop_index('ix_skills_name_trgm', table_name='skills', postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'})
    op.drop_index('ix_skills_active_sort', table_name='skills')
    op.drop_table('skills')
    op.drop_index('ix_pay_types_active_sort', table_name='pay_types')
    op.drop_table('pay_types')
    op.drop_index('uq_lookup_values_list_code', table_name='lookup_values')
    op.drop_table('lookup_values')
    op.drop_index('ix_job_types_active_sort', table_name='job_types')
    op.drop_table('job_types')
    op.drop_index('ix_job_categories_active_sort', table_name='job_categories')
    op.drop_table('job_categories')
    op.drop_index('ix_industries_active_sort', table_name='industries')
    op.drop_table('industries')
    op.drop_index('ix_experience_bands_active_sort', table_name='experience_bands')
    op.drop_table('experience_bands')
    op.drop_index('ix_education_levels_active_sort', table_name='education_levels')
    op.drop_table('education_levels')
    op.drop_index('uq_approval_policies_entity_org', table_name='approval_policies')
    op.drop_table('approval_policies')
    op.execute("DROP SEQUENCE approval_request_number_seq")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
