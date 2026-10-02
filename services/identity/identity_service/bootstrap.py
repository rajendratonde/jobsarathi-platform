"""Create the first platform administrator (one-time, run by an operator).

    BOOTSTRAP_ADMIN_PASSWORD_REF=env:FIRST_ADMIN_PASSWORD \\
    python -m identity_service.bootstrap --email admin@example.com --name "Platform Admin" --role-code PLATFORM_ADMIN

* the password comes from a secret reference (env:/file:), never from argv or a migration
* the user must change it at first sign-in (E1 password_change_required)
* the role is named by its CODE (data from the roles table) and given with ALL scope on the
  platform-organization membership
* refuses to run if the email already exists
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime

from pydantic import SecretStr
from sqlalchemy import select

from identity_service.config import get_db_settings, get_settings
from identity_service.models import (
    AuditLog,
    AuthIdentity,
    Organization,
    OrganizationMembership,
    Role,
    User,
    UserRoleAssignment,
)
from identity_service.security import check_password_policy, hash_password
from identity_service.services.directory import normalize_email
from js_audit import ActorType, record_audit
from js_core import secrets
from js_core.db import Database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--role-code", required=True, help="Code of an ACTIVE role, e.g. PLATFORM_ADMIN from the seed")
    args = parser.parse_args(argv)

    ref = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD_REF")
    if not ref or not secrets.is_reference(ref):
        print("Set BOOTSTRAP_ADMIN_PASSWORD_REF to env:NAME or file:/path", file=sys.stderr)
        return 2
    password = secrets.resolve(SecretStr(ref)).get_secret_value()  # type: ignore[union-attr]
    settings = get_settings()
    check_password_policy(password, min_length=settings.password_min_length, field="password")
    email = normalize_email(args.email)

    db = Database(get_db_settings())
    try:
        with db.session() as session:
            if session.scalar(select(AuthIdentity.id).where(AuthIdentity.identity_type == "EMAIL_PASSWORD",
                                                            AuthIdentity.identifier == email)):
                print(f"A user with {email} already exists; nothing done.", file=sys.stderr)
                return 1
            platform = session.scalar(select(Organization).where(Organization.is_platform.is_(True)))
            role = session.scalar(select(Role).where(Role.role_code == args.role_code, Role.status == "ACTIVE"))
            if platform is None or role is None:
                print("Platform organization or active role not found. Run migrations first.", file=sys.stderr)
                return 1
            now = datetime.now(UTC)
            user = User(display_name=args.name.strip(), status="ACTIVE")
            session.add(user)
            session.flush()
            session.add(AuthIdentity(user_id=user.id, identity_type="EMAIL_PASSWORD", identifier=email,
                                     password_hash=hash_password(password), is_primary=True, verified_at=now,
                                     password_change_required=True))
            membership = OrganizationMembership(organization_id=platform.id, user_id=user.id, status="ACTIVE",
                                                joined_at=now)
            session.add(membership)
            session.flush()
            session.add(UserRoleAssignment(user_id=user.id, role_id=role.id, membership_id=membership.id,
                                           scope_type="ALL", status="ACTIVE"))
            record_audit(session, AuditLog, action="USER.BOOTSTRAPPED", entity_type="USER", entity_id=user.id,
                         actor_type=ActorType.SYSTEM, organization_id=platform.id,
                         after={"role_code": role.role_code, "scope": "ALL"})
            session.commit()
            print(f"Created {email} ({user.id}) with {role.role_code} / ALL. Password change required at first sign-in.")
            return 0
    finally:
        db.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
