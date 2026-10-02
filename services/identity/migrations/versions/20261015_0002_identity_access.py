"""Identity & Access tables (v5 sections 7-10) + approved E1 auth_identities.password_change_required

Revision ID: 0002_identity_access
Revises: 0001_platform_tables
Create Date: 2026-10-02
"""
from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from js_core.migrations import runtime_role_grants_sql

revision = '0002_identity_access'
down_revision = '0001_platform_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE organization_code_seq START 1")
    op.execute("CREATE SEQUENCE approval_request_number_seq START 1")
    op.create_table('actions',
    sa.Column('action_code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.UUID(), nullable=True),
    sa.CheckConstraint("action_code ~ '^[A-Z][A-Z_]*$'", name=op.f('ck_actions_action_code')),
    sa.CheckConstraint('deleted_at IS NULL OR deleted_by IS NOT NULL', name=op.f('ck_actions_deleted_by_required')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_actions'))
    )
    op.create_index('uq_actions_code', 'actions', ['action_code'], unique=True, postgresql_where=sa.text('deleted_at IS NULL'))
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
    op.create_table('modules',
    sa.Column('module_code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.UUID(), nullable=True),
    sa.CheckConstraint('deleted_at IS NULL OR deleted_by IS NOT NULL', name=op.f('ck_modules_deleted_by_required')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_modules'))
    )
    op.create_index('uq_modules_code', 'modules', ['module_code'], unique=True, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_table('organizations',
    sa.Column('organization_code', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('organization_type', sa.String(length=20), nullable=False),
    sa.Column('is_platform', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('status', sa.String(length=15), server_default=sa.text("'ACTIVE'"), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.UUID(), nullable=True),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("is_platform = (organization_type = 'PLATFORM')", name=op.f('ck_organizations_platform_type')),
    sa.CheckConstraint("organization_type IN ('PLATFORM','EMPLOYER','COLLEGE','PARTNER')", name=op.f('ck_organizations_organization_type')),
    sa.CheckConstraint("status IN ('ACTIVE','SUSPENDED')", name=op.f('ck_organizations_status')),
    sa.CheckConstraint('deleted_at IS NULL OR deleted_by IS NOT NULL', name=op.f('ck_organizations_deleted_by_required')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_organizations')),
    sa.UniqueConstraint('organization_code', name=op.f('uq_organizations_organization_code'))
    )
    op.create_index('ix_organizations_type_status', 'organizations', ['organization_type', 'status'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('uq_organizations_single_platform', 'organizations', ['is_platform'], unique=True, postgresql_where=sa.text('is_platform'))
    op.create_table('users',
    sa.Column('display_name', sa.String(length=150), nullable=False),
    sa.Column('status', sa.String(length=15), server_default=sa.text("'ACTIVE'"), nullable=False),
    sa.Column('authz_version', sa.BigInteger(), server_default=sa.text('1'), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.UUID(), nullable=True),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("status IN ('PENDING','ACTIVE','DISABLED','LOCKED')", name=op.f('ck_users_status')),
    sa.CheckConstraint('deleted_at IS NULL OR deleted_by IS NOT NULL', name=op.f('ck_users_deleted_by_required')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    op.create_index('ix_users_status', 'users', ['status'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
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
    op.create_table('auth_identities',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('identity_type', sa.String(length=20), nullable=False),
    sa.Column('identifier', sa.String(length=254), nullable=False),
    sa.Column('provider_code', sa.String(length=50), nullable=True),
    sa.Column('password_hash', sa.Text(), nullable=True),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_primary', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('failed_attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('password_change_required', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.UUID(), nullable=True),
    sa.CheckConstraint("(identity_type = 'EMAIL_PASSWORD') = (password_hash IS NOT NULL)", name=op.f('ck_auth_identities_password_only_for_email')),
    sa.CheckConstraint("identity_type <> 'SSO' OR provider_code IS NOT NULL", name=op.f('ck_auth_identities_sso_provider')),
    sa.CheckConstraint("identity_type IN ('MOBILE_OTP','EMAIL_PASSWORD','SSO')", name=op.f('ck_auth_identities_identity_type')),
    sa.CheckConstraint('deleted_at IS NULL OR deleted_by IS NOT NULL', name=op.f('ck_auth_identities_deleted_by_required')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_auth_identities_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auth_identities'))
    )
    op.create_index('ix_auth_identities_user', 'auth_identities', ['user_id'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('uq_auth_identities_identifier', 'auth_identities', ['identity_type', 'identifier', sa.literal_column("COALESCE(provider_code, '')")], unique=True, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_table('organization_memberships',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=15), server_default=sa.text("'ACTIVE'"), nullable=False),
    sa.Column('joined_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.UUID(), nullable=True),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("status IN ('INVITED','ACTIVE','SUSPENDED','ENDED')", name=op.f('ck_organization_memberships_status')),
    sa.CheckConstraint('deleted_at IS NULL OR deleted_by IS NOT NULL', name=op.f('ck_organization_memberships_deleted_by_required')),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_organization_memberships_organization_id_organizations'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_organization_memberships_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_organization_memberships'))
    )
    op.create_index('ix_organization_memberships_org_status', 'organization_memberships', ['organization_id', 'status'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_organization_memberships_user_active', 'organization_memberships', ['user_id'], unique=False, postgresql_where=sa.text("deleted_at IS NULL AND status = 'ACTIVE'"))
    op.create_index('uq_organization_memberships_org_user', 'organization_memberships', ['organization_id', 'user_id'], unique=True, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_table('resources',
    sa.Column('module_id', sa.UUID(), nullable=False),
    sa.Column('resource_code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.UUID(), nullable=True),
    sa.CheckConstraint("resource_code ~ '^[A-Z][A-Z_]*$'", name=op.f('ck_resources_resource_code')),
    sa.CheckConstraint('deleted_at IS NULL OR deleted_by IS NOT NULL', name=op.f('ck_resources_deleted_by_required')),
    sa.ForeignKeyConstraint(['module_id'], ['modules.id'], name=op.f('fk_resources_module_id_modules'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_resources'))
    )
    op.create_index('ix_resources_module', 'resources', ['module_id'], unique=False)
    op.create_index('uq_resources_code', 'resources', ['resource_code'], unique=True, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_table('roles',
    sa.Column('role_code', sa.String(length=60), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('owner_organization_id', sa.UUID(), nullable=True),
    sa.Column('is_system', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'DRAFT'"), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.UUID(), nullable=True),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("status IN ('DRAFT','PENDING_APPROVAL','ACTIVE','DISABLED')", name=op.f('ck_roles_status')),
    sa.CheckConstraint('NOT (is_system AND deleted_at IS NOT NULL)', name=op.f('ck_roles_system_not_deleted')),
    sa.CheckConstraint('deleted_at IS NULL OR deleted_by IS NOT NULL', name=op.f('ck_roles_deleted_by_required')),
    sa.ForeignKeyConstraint(['owner_organization_id'], ['organizations.id'], name=op.f('fk_roles_owner_organization_id_organizations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_roles'))
    )
    op.create_index('ix_roles_owner', 'roles', ['owner_organization_id'], unique=False)
    op.create_index('ix_roles_status', 'roles', ['status'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('uq_roles_code', 'roles', ['role_code'], unique=True, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('uq_roles_owner_name', 'roles', [sa.literal_column("COALESCE(owner_organization_id, '00000000-0000-0000-0000-000000000000'::uuid)"), sa.literal_column('lower(name)')], unique=True, postgresql_where=sa.text('deleted_at IS NULL'))
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
    op.create_table('otp_challenges',
    sa.Column('purpose', sa.String(length=20), nullable=False),
    sa.Column('mobile_hash', sa.CHAR(length=64), nullable=False),
    sa.Column('mobile_last4', sa.CHAR(length=4), nullable=False),
    sa.Column('auth_identity_id', sa.UUID(), nullable=True),
    sa.Column('code_hash', sa.CHAR(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('attempt_count', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('max_attempts', sa.SmallInteger(), server_default=sa.text('5'), nullable=False),
    sa.Column('status', sa.String(length=15), server_default=sa.text("'PENDING'"), nullable=False),
    sa.Column('delivery_status', sa.String(length=15), server_default=sa.text("'NOT_SENT'"), nullable=False),
    sa.Column('delivery_reference', sa.String(length=100), nullable=True),
    sa.Column('requested_ip', postgresql.INET(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.CheckConstraint("(status = 'VERIFIED') = (verified_at IS NOT NULL)", name=op.f('ck_otp_challenges_verified_at')),
    sa.CheckConstraint("delivery_status IN ('NOT_SENT','SENT','FAILED','DISABLED')", name=op.f('ck_otp_challenges_delivery_status')),
    sa.CheckConstraint("purpose IN ('LOGIN','SIGNUP','VERIFY_MOBILE')", name=op.f('ck_otp_challenges_purpose')),
    sa.CheckConstraint("status IN ('PENDING','VERIFIED','EXPIRED','LOCKED','CANCELLED')", name=op.f('ck_otp_challenges_status')),
    sa.CheckConstraint('attempt_count <= max_attempts', name=op.f('ck_otp_challenges_attempts')),
    sa.CheckConstraint('expires_at > created_at', name=op.f('ck_otp_challenges_expiry')),
    sa.ForeignKeyConstraint(['auth_identity_id'], ['auth_identities.id'], name=op.f('fk_otp_challenges_auth_identity_id_auth_identities'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_otp_challenges'))
    )
    op.create_index('ix_otp_challenges_mobile_recent', 'otp_challenges', ['mobile_hash', sa.literal_column('created_at DESC')], unique=False)
    op.create_index('ix_otp_challenges_pending', 'otp_challenges', ['status', 'expires_at'], unique=False, postgresql_where=sa.text("status = 'PENDING'"))
    op.create_table('permissions',
    sa.Column('resource_id', sa.UUID(), nullable=False),
    sa.Column('action_id', sa.UUID(), nullable=False),
    sa.Column('permission_code', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_enforced', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('declared_by_service', sa.String(length=50), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.UUID(), nullable=True),
    sa.CheckConstraint("permission_code ~ '^[A-Z][A-Z_]*\\.[A-Z][A-Z_]*$'", name=op.f('ck_permissions_permission_code')),
    sa.CheckConstraint('deleted_at IS NULL OR deleted_by IS NOT NULL', name=op.f('ck_permissions_deleted_by_required')),
    sa.ForeignKeyConstraint(['action_id'], ['actions.id'], name=op.f('fk_permissions_action_id_actions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['resource_id'], ['resources.id'], name=op.f('fk_permissions_resource_id_resources'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_permissions'))
    )
    op.create_index('ix_permissions_action', 'permissions', ['action_id'], unique=False)
    op.create_index('ix_permissions_resource', 'permissions', ['resource_id'], unique=False)
    op.create_index('uq_permissions_code', 'permissions', ['permission_code'], unique=True, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('uq_permissions_resource_action', 'permissions', ['resource_id', 'action_id'], unique=True, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_table('user_role_assignments',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('role_id', sa.UUID(), nullable=False),
    sa.Column('membership_id', sa.UUID(), nullable=True),
    sa.Column('scope_type', sa.String(length=15), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'ACTIVE'"), nullable=False),
    sa.Column('valid_from', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_by', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("(status = 'REVOKED') = (revoked_at IS NOT NULL)", name=op.f('ck_user_role_assignments_revoked_at')),
    sa.CheckConstraint("scope_type IN ('OWN','ORGANIZATION','CITY','REGION','ALL')", name=op.f('ck_user_role_assignments_scope_type')),
    sa.CheckConstraint("scope_type NOT IN ('ORGANIZATION','ALL') OR membership_id IS NOT NULL", name=op.f('ck_user_role_assignments_scope_needs_membership')),
    sa.CheckConstraint("status IN ('PENDING_APPROVAL','ACTIVE','REVOKED')", name=op.f('ck_user_role_assignments_status')),
    sa.CheckConstraint('valid_until IS NULL OR valid_until > valid_from', name=op.f('ck_user_role_assignments_validity')),
    sa.ForeignKeyConstraint(['membership_id'], ['organization_memberships.id'], name=op.f('fk_user_role_assignments_membership_id_organization_memberships'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], name=op.f('fk_user_role_assignments_role_id_roles'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_role_assignments_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_role_assignments'))
    )
    op.create_index('ix_user_role_assignments_membership', 'user_role_assignments', ['membership_id'], unique=False)
    op.create_index('ix_user_role_assignments_role', 'user_role_assignments', ['role_id'], unique=False)
    op.create_index('ix_user_role_assignments_user_active', 'user_role_assignments', ['user_id'], unique=False, postgresql_where=sa.text("status = 'ACTIVE'"))
    op.create_index('uq_user_role_assignments_live', 'user_role_assignments', ['user_id', 'role_id', sa.literal_column("COALESCE(membership_id, '00000000-0000-0000-0000-000000000000'::uuid)")], unique=True, postgresql_where=sa.text("status <> 'REVOKED'"))
    op.create_table('user_sessions',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('auth_identity_id', sa.UUID(), nullable=False),
    sa.Column('refresh_token_hash', sa.CHAR(length=64), nullable=False),
    sa.Column('active_organization_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_reason', sa.String(length=30), nullable=True),
    sa.Column('ip_address', postgresql.INET(), nullable=True),
    sa.Column('user_agent', sa.String(length=300), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.CheckConstraint('expires_at > created_at', name=op.f('ck_user_sessions_expiry')),
    sa.ForeignKeyConstraint(['active_organization_id'], ['organizations.id'], name=op.f('fk_user_sessions_active_organization_id_organizations'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['auth_identity_id'], ['auth_identities.id'], name=op.f('fk_user_sessions_auth_identity_id_auth_identities'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_sessions_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_sessions')),
    sa.UniqueConstraint('refresh_token_hash', name=op.f('uq_user_sessions_refresh_token_hash'))
    )
    op.create_index('ix_user_sessions_active', 'user_sessions', ['user_id'], unique=False, postgresql_where=sa.text('revoked_at IS NULL'))
    op.create_table('role_permissions',
    sa.Column('role_id', sa.UUID(), nullable=False),
    sa.Column('permission_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], name=op.f('fk_role_permissions_permission_id_permissions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], name=op.f('fk_role_permissions_role_id_roles'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('role_id', 'permission_id', name=op.f('pk_role_permissions'))
    )
    op.create_index('ix_role_permissions_permission', 'role_permissions', ['permission_id'], unique=False)

    # Runtime role: DML on the new tables and sequences; audit_logs stays append-only.
    role = context.config.attributes.get("runtime_role")
    if role:
        for statement in runtime_role_grants_sql(role):
            op.execute(statement)


def downgrade() -> None:
    op.drop_index('ix_role_permissions_permission', table_name='role_permissions')
    op.drop_table('role_permissions')
    op.drop_index('ix_user_sessions_active', table_name='user_sessions', postgresql_where=sa.text('revoked_at IS NULL'))
    op.drop_table('user_sessions')
    op.drop_index('uq_user_role_assignments_live', table_name='user_role_assignments', postgresql_where=sa.text("status <> 'REVOKED'"))
    op.drop_index('ix_user_role_assignments_user_active', table_name='user_role_assignments', postgresql_where=sa.text("status = 'ACTIVE'"))
    op.drop_index('ix_user_role_assignments_role', table_name='user_role_assignments')
    op.drop_index('ix_user_role_assignments_membership', table_name='user_role_assignments')
    op.drop_table('user_role_assignments')
    op.drop_index('uq_permissions_resource_action', table_name='permissions', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index('uq_permissions_code', table_name='permissions', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index('ix_permissions_resource', table_name='permissions')
    op.drop_index('ix_permissions_action', table_name='permissions')
    op.drop_table('permissions')
    op.drop_index('ix_otp_challenges_pending', table_name='otp_challenges', postgresql_where=sa.text("status = 'PENDING'"))
    op.drop_index('ix_otp_challenges_mobile_recent', table_name='otp_challenges')
    op.drop_table('otp_challenges')
    op.drop_index('ix_approval_actions_request', table_name='approval_actions')
    op.drop_table('approval_actions')
    op.drop_index('uq_roles_owner_name', table_name='roles', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index('uq_roles_code', table_name='roles', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index('ix_roles_status', table_name='roles', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index('ix_roles_owner', table_name='roles')
    op.drop_table('roles')
    op.drop_index('uq_resources_code', table_name='resources', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index('ix_resources_module', table_name='resources')
    op.drop_table('resources')
    op.drop_index('uq_organization_memberships_org_user', table_name='organization_memberships', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index('ix_organization_memberships_user_active', table_name='organization_memberships', postgresql_where=sa.text("deleted_at IS NULL AND status = 'ACTIVE'"))
    op.drop_index('ix_organization_memberships_org_status', table_name='organization_memberships', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_table('organization_memberships')
    op.drop_index('uq_auth_identities_identifier', table_name='auth_identities', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index('ix_auth_identities_user', table_name='auth_identities', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_table('auth_identities')
    op.drop_index('uq_approval_requests_one_pending', table_name='approval_requests', postgresql_where=sa.text("status = 'PENDING'"))
    op.drop_index('ix_approval_requests_maker', table_name='approval_requests')
    op.drop_index('ix_approval_requests_inbox', table_name='approval_requests', postgresql_where=sa.text("status = 'PENDING'"))
    op.drop_index('ix_approval_requests_entity', table_name='approval_requests')
    op.drop_table('approval_requests')
    op.drop_index('ix_users_status', table_name='users', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_table('users')
    op.drop_index('uq_organizations_single_platform', table_name='organizations', postgresql_where=sa.text('is_platform'))
    op.drop_index('ix_organizations_type_status', table_name='organizations', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_table('organizations')
    op.drop_index('uq_modules_code', table_name='modules', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_table('modules')
    op.drop_index('uq_approval_policies_entity_org', table_name='approval_policies')
    op.drop_table('approval_policies')
    op.drop_index('uq_actions_code', table_name='actions', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_table('actions')
    op.execute("DROP SEQUENCE approval_request_number_seq")
    op.execute("DROP SEQUENCE organization_code_seq")
