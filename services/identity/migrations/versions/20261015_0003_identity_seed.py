"""Identity seed data (Implementation Blueprint §SEEDS, identity_db)

* the single PLATFORM organization (ORG-000001)
* the Identity permission catalogue: module, resources, actions, permissions
* protected system role PLATFORM_ADMIN holding every Identity permission
* default CANDIDATE role (no permissions yet; candidate services declare theirs later)
* approval policies for ROLE, ROLE_PERMISSIONS and PERMISSION (enabled) and
  USER_ROLE_ASSIGNMENT (disabled until Q7 decides which roles are privileged)

The first admin user is NOT created here; see ``identity_service.bootstrap``.
Everything below is data - no code checks a role code or name.

Revision ID: 0003_identity_seed
Revises: 0002_identity_access
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa

from js_core.ids import uuid7

revision = "0003_identity_seed"
down_revision = "0002_identity_access"
branch_labels = None
depends_on = None

MODULE = ("ACCESS_CONTROL", "Identity & Access", "Organizations, users, roles, permissions and approvals")

RESOURCES = [
    ("ORGANIZATION", "Organizations"),
    ("USER", "Users"),
    ("ROLE", "Roles"),
    ("MAKER_CHECKER", "Approvals"),
    ("AUDIT", "Audit log"),
]

ACTIONS = [
    ("VIEW", "View"), ("CREATE", "Create"), ("EDIT", "Edit"), ("DISABLE", "Disable"),
    ("ASSIGN", "Assign"), ("APPROVE", "Approve"),
]

PERMISSIONS = [
    ("ORGANIZATION", "VIEW", "See organizations"),
    ("ORGANIZATION", "EDIT", "Suspend or reactivate organizations"),
    ("USER", "VIEW", "See users and memberships"),
    ("USER", "CREATE", "Create users and add members"),
    ("USER", "EDIT", "Edit users and memberships; issue temporary passwords"),
    ("USER", "DISABLE", "Disable users; remove members"),
    ("ROLE", "VIEW", "See roles, the permission catalogue and the matrix"),
    ("ROLE", "CREATE", "Propose new roles"),
    ("ROLE", "EDIT", "Propose role, permission and catalogue changes"),
    ("ROLE", "ASSIGN", "Assign and revoke user roles"),
    ("ROLE", "APPROVE", "Approve or reject access-control changes"),
    ("MAKER_CHECKER", "VIEW", "See the approval queue"),
    ("MAKER_CHECKER", "APPROVE", "Decide approval requests"),
    ("AUDIT", "VIEW", "Search the audit log"),
]

ROLES = [
    # (role_code, name, description, is_system, grants every seeded permission)
    ("PLATFORM_ADMIN", "Platform Administrator", "Protected system role with every Identity permission", True, True),
    ("CANDIDATE", "Candidate", "Default role for people who sign up with OTP", False, False),
]

POLICIES = [
    # (entity_type, enabled, maker permission, checker permission)
    ("ROLE", True, "ROLE.EDIT", "ROLE.APPROVE"),
    ("ROLE_PERMISSIONS", True, "ROLE.EDIT", "ROLE.APPROVE"),
    ("PERMISSION", True, "ROLE.EDIT", "ROLE.APPROVE"),
    ("USER_ROLE_ASSIGNMENT", False, "ROLE.ASSIGN", "ROLE.APPROVE"),
]


def upgrade() -> None:
    conn = op.get_bind()

    def insert(sql: str, **params) -> None:
        conn.execute(sa.text(sql), params)

    insert("""INSERT INTO organizations (id, organization_code, name, organization_type, is_platform, status)
              VALUES (:id, 'ORG-' || lpad(nextval('organization_code_seq')::text, 6, '0'), 'JobSarathi',
                      'PLATFORM', true, 'ACTIVE')""", id=uuid7())

    module_id = uuid7()
    insert("INSERT INTO modules (id, module_code, name, description, sort_order) VALUES (:id, :c, :n, :d, 10)",
           id=module_id, c=MODULE[0], n=MODULE[1], d=MODULE[2])

    resource_ids = {}
    for code, name in RESOURCES:
        resource_ids[code] = uuid7()
        insert("INSERT INTO resources (id, module_id, resource_code, name) VALUES (:id, :m, :c, :n)",
               id=resource_ids[code], m=module_id, c=code, n=name)

    action_ids = {}
    for code, name in ACTIONS:
        action_ids[code] = uuid7()
        insert("INSERT INTO actions (id, action_code, name) VALUES (:id, :c, :n)", id=action_ids[code], c=code, n=name)

    permission_ids = []
    for resource, action, description in PERMISSIONS:
        pid = uuid7()
        permission_ids.append(pid)
        insert("""INSERT INTO permissions (id, resource_id, action_id, permission_code, description, is_enforced,
                                           declared_by_service)
                  VALUES (:id, :r, :a, :code, :d, true, 'identity')""",
               id=pid, r=resource_ids[resource], a=action_ids[action], code=f"{resource}.{action}", d=description)

    for code, name, description, is_system, grant_all in ROLES:
        rid = uuid7()
        insert("""INSERT INTO roles (id, role_code, name, description, is_system, status)
                  VALUES (:id, :c, :n, :d, :s, 'ACTIVE')""", id=rid, c=code, n=name, d=description, s=is_system)
        if grant_all:
            for pid in permission_ids:
                insert("INSERT INTO role_permissions (role_id, permission_id) VALUES (:r, :p)", r=rid, p=pid)

    for entity_type, enabled, maker, checker in POLICIES:
        insert("""INSERT INTO approval_policies (id, entity_type, is_enabled, maker_permission_code,
                                                 checker_permission_code)
                  VALUES (:id, :e, :en, :m, :c)""", id=uuid7(), e=entity_type, en=enabled, m=maker, c=checker)


def downgrade() -> None:
    # Only reversible on a database with nothing but the seed (fresh environments).
    for statement in (
        "DELETE FROM approval_policies",
        "DELETE FROM role_permissions",
        "DELETE FROM roles",
        "DELETE FROM permissions",
        "DELETE FROM actions",
        "DELETE FROM resources",
        "DELETE FROM modules",
        "DELETE FROM organizations WHERE is_platform",
        "ALTER SEQUENCE organization_code_seq RESTART WITH 1",
    ):
        op.execute(statement)
