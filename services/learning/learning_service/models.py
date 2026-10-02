"""Tables owned by learning_db.

Foundation contains only the two v5 platform tables present in every service
database. Business tables are added exactly as defined in the v5 ERD when the
Learning phase starts; nothing here may reference another service's tables.
"""

from __future__ import annotations

from js_audit import AuditLogMixin
from js_core.db import make_base
from js_outbox import OutboxEventMixin

Base = make_base()


class AuditLog(AuditLogMixin, Base):
    __tablename__ = "audit_logs"


class OutboxEvent(OutboxEventMixin, Base):
    __tablename__ = "outbox_events"
