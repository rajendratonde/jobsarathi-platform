"""Data only: permissions the Reference Data service enforces (v5 Maker-Checker table:
Reference list values -> maker REFERENCE.EDIT, checker REFERENCE.APPROVE)

* module REFERENCE_DATA with resource REFERENCE; actions EDIT and APPROVE already exist
* both permissions granted to the protected system role (a system role may gain permissions)
* holders of that role get a new authz_version so their tokens pick up the change

No schema change.

Revision ID: 0004_reference_permissions
Revises: 0003_identity_seed
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa

from js_core.ids import uuid7

revision = "0004_reference_permissions"
down_revision = "0003_identity_seed"
branch_labels = None
depends_on = None

CODES = [("EDIT", "Create, edit and deactivate reference list values"),
         ("APPROVE", "Approve or reject reference data changes")]


def upgrade() -> None:
    conn = op.get_bind()
    module_id, resource_id = uuid7(), uuid7()
    conn.execute(sa.text("INSERT INTO modules (id, module_code, name, description, sort_order) "
                         "VALUES (:id, 'REFERENCE_DATA', 'Reference Data', 'Shared master lists', 20)"), {"id": module_id})
    conn.execute(sa.text("INSERT INTO resources (id, module_id, resource_code, name) "
                         "VALUES (:id, :m, 'REFERENCE', 'Reference lists')"), {"id": resource_id, "m": module_id})
    for action, description in CODES:
        permission_id = uuid7()
        conn.execute(sa.text(
            "INSERT INTO permissions (id, resource_id, action_id, permission_code, description, is_enforced, "
            "declared_by_service) SELECT :id, :r, a.id, :code, :d, true, 'reference' FROM actions a "
            "WHERE a.action_code = :action"),
            {"id": permission_id, "r": resource_id, "code": f"REFERENCE.{action}", "d": description, "action": action})
        conn.execute(sa.text("INSERT INTO role_permissions (role_id, permission_id) "
                             "SELECT id, :p FROM roles WHERE is_system"), {"p": permission_id})
    conn.execute(sa.text("UPDATE users SET authz_version = authz_version + 1 WHERE id IN ("
                         "SELECT a.user_id FROM user_role_assignments a JOIN roles r ON r.id = a.role_id "
                         "WHERE r.is_system AND a.status <> 'REVOKED')"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM role_permissions WHERE permission_id IN "
                         "(SELECT id FROM permissions WHERE permission_code LIKE 'REFERENCE.%')"))
    conn.execute(sa.text("DELETE FROM permissions WHERE permission_code LIKE 'REFERENCE.%'"))
    conn.execute(sa.text("DELETE FROM resources WHERE resource_code = 'REFERENCE'"))
    conn.execute(sa.text("DELETE FROM modules WHERE module_code = 'REFERENCE_DATA'"))
