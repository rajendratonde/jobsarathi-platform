"""Tables owned by engagement_db.

Foundation contains the two v5 platform tables present in every service database.
The approved email data model (2026-10-02) adds email_settings, email_templates and
email_delivery_logs here; see docs/decisions.md for why Engagement owns them.
Data model only: no Engagement business APIs and no email provider yet.
Nothing here may reference another service's tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CHAR, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from js_audit import AuditLogMixin
from js_core.db import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin, VersionMixin, make_base, soft_delete_check
from js_outbox import OutboxEventMixin

Base = make_base()


class EmailSettings(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, Base):
    """Outbound email configuration. The SMTP password is never stored: only a secret
    reference (env:NAME / file:/path), enforced by a CHECK constraint."""

    __tablename__ = "email_settings"
    __table_args__ = (
        CheckConstraint("delivery_mode IN ('DISABLED','DEV_LOG','SMTP')", name="delivery_mode"),
        CheckConstraint("smtp_security IN ('STARTTLS','SSL','NONE')", name="smtp_security"),
        CheckConstraint("smtp_port IS NULL OR smtp_port BETWEEN 1 AND 65535", name="smtp_port"),
        CheckConstraint("timeout_seconds BETWEEN 1 AND 120", name="timeout_seconds"),
        CheckConstraint(r"smtp_password_ref IS NULL OR smtp_password_ref ~ '^(env:[A-Za-z_][A-Za-z0-9_]*|file:/.+)$'",
                        name="password_is_reference"),
        CheckConstraint("delivery_mode <> 'SMTP' OR (smtp_host IS NOT NULL AND smtp_port IS NOT NULL "
                        "AND from_email IS NOT NULL)", name="smtp_complete"),
        CheckConstraint("NOT is_enabled OR delivery_mode <> 'DISABLED'", name="enabled_has_mode"),
    )
    setting_code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, server_default=text("'DEFAULT'"),
                                              default="DEFAULT")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    delivery_mode: Mapped[str] = mapped_column(String(15), nullable=False, server_default=text("'DISABLED'"),
                                               default="DISABLED")
    smtp_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    smtp_security: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'STARTTLS'"),
                                               default="STARTTLS")
    smtp_username: Mapped[str | None] = mapped_column(String(254), nullable=True)
    smtp_password_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    from_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    from_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reply_to_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("10"), default=10)

    def public_view(self) -> dict[str, Any]:
        """The only shape an API may return: whether credentials are configured, never their values."""
        return {"setting_code": self.setting_code, "is_enabled": self.is_enabled, "delivery_mode": self.delivery_mode,
                "smtp_host": self.smtp_host, "smtp_port": self.smtp_port, "smtp_security": self.smtp_security,
                "smtp_username_set": bool(self.smtp_username), "smtp_password_set": bool(self.smtp_password_ref),
                "from_email": self.from_email, "from_name": self.from_name, "reply_to_email": self.reply_to_email,
                "timeout_seconds": self.timeout_seconds, "version": self.version}


class EmailTemplate(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "email_templates"
    __table_args__ = (
        CheckConstraint("status IN ('DRAFT','ACTIVE','INACTIVE')", name="status"),
        CheckConstraint("template_code ~ '^[A-Z][A-Z0-9_]*$'", name="template_code"),
        soft_delete_check(),
        Index("uq_email_templates_code_language", "template_code", "language_code", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
        Index("ix_email_templates_status", "status", postgresql_where=text("deleted_at IS NULL")),
    )
    template_code: Mapped[str] = mapped_column(String(60), nullable=False)
    language_code: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'en'"), default="en")
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    allowed_variables: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(15), nullable=False, server_default=text("'DRAFT'"), default="DRAFT")


class EmailDeliveryLog(UUIDPrimaryKeyMixin, Base):
    """One row per send. Holds no message body, no subject and no secret; the recipient
    is stored masked plus a hash for lookups."""

    __tablename__ = "email_delivery_logs"
    __table_args__ = (
        CheckConstraint("status IN ('QUEUED','SENT','FAILED','SKIPPED')", name="status"),
        CheckConstraint("delivery_mode IN ('DISABLED','DEV_LOG','SMTP')", name="delivery_mode"),
        CheckConstraint("status <> 'SENT' OR sent_at IS NOT NULL", name="sent_at"),
        CheckConstraint("status <> 'FAILED' OR error_code IS NOT NULL", name="failure_code"),
        CheckConstraint("attempts >= 0", name="attempts"),
        Index("uq_email_delivery_logs_source", "source_service", "source_reference", unique=True,
              postgresql_where=text("source_reference IS NOT NULL")),
        Index("ix_email_delivery_logs_recipient", "recipient_hash", text("created_at DESC")),
        Index("ix_email_delivery_logs_status", "status", "created_at"),
        Index("ix_email_delivery_logs_template", "template_id"),
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_templates.id", ondelete="RESTRICT"), nullable=True)
    template_code: Mapped[str] = mapped_column(String(60), nullable=False)
    recipient_masked: Mapped[str] = mapped_column(String(254), nullable=False)
    recipient_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_service: Mapped[str] = mapped_column(String(30), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    delivery_mode: Mapped[str] = mapped_column(String(15), nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, server_default=text("'QUEUED'"), default="QUEUED")
    provider_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(AuditLogMixin, Base):
    __tablename__ = "audit_logs"


class OutboxEvent(OutboxEventMixin, Base):
    __tablename__ = "outbox_events"
