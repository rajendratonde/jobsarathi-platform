"""Database foundation against real PostgreSQL: soft delete, versioning, audit, outbox, readiness."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import String, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm.exc import StaleDataError

from js_audit import AuditLogMixin, record_audit
from js_core import context
from js_core.app import create_app
from js_core.config import Environment, ServiceSettings
from js_core.db import (
    Database,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionMixin,
    make_base,
    soft_delete_check,
    transaction,
)
from js_outbox import OutboxEventMixin, add_event

Base = make_base()


class Widget(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    """Test-only table exercising every mixin; not a JobSarathi entity."""

    __tablename__ = "test_widgets"
    __table_args__ = (soft_delete_check(),)
    name: Mapped[str] = mapped_column(String(50), nullable=False)


class AuditLog(AuditLogMixin, Base):
    __tablename__ = "audit_logs"


class OutboxEvent(OutboxEventMixin, Base):
    __tablename__ = "outbox_events"


@pytest.fixture(scope="module")
def db(db_settings):
    database = Database(db_settings)
    Base.metadata.create_all(database.engine)
    yield database
    Base.metadata.drop_all(database.engine)
    database.dispose()


ACTOR = uuid.uuid4()


def test_soft_deleted_rows_are_hidden_by_default(db):
    with db.session() as s, transaction(s):
        live, gone = Widget(name="live"), Widget(name="gone")
        s.add_all([live, gone])
    with db.session() as s, transaction(s):
        s.get(Widget, gone.id).soft_delete(ACTOR)
    with db.session() as s:
        names = set(s.scalars(select(Widget.name)).all())
        assert "live" in names and "gone" not in names
        assert s.scalars(select(Widget).where(Widget.id == gone.id)).first() is None
        everything = s.scalars(select(Widget).execution_options(include_deleted=True)).all()
        assert {"live", "gone"} <= {w.name for w in everything}


def test_soft_delete_requires_deleted_by(db):
    with db.session() as s:
        w = Widget(name="bad")
        s.add(w)
        s.flush()
        from datetime import UTC, datetime
        w.deleted_at = datetime.now(UTC)
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()


def test_version_increments_and_lost_update_is_refused(db):
    with db.session() as s, transaction(s):
        w = Widget(name="v1")
        s.add(w)
    assert w.version == 1
    with db.session() as a, db.session() as b:
        wa, wb = a.get(Widget, w.id), b.get(Widget, w.id)
        wa.name = "edit-a"
        a.commit()
        assert wa.version == 2
        wb.name = "edit-b"
        with pytest.raises(StaleDataError):
            b.commit()


def test_audit_and_outbox_commit_and_roll_back_with_the_change(db):
    token = context.correlation_id_var.set("corr-audit-0001")
    try:
        with db.session() as s, transaction(s):
            w = Widget(name="audited")
            s.add(w)
            s.flush()
            record_audit(s, AuditLog, action="ENTITY_CREATED", entity_type="TEST_WIDGET", entity_id=w.id,
                         actor_user_id=ACTOR, after={"name": "audited", "password": "never-stored"})
            add_event(s, OutboxEvent, aggregate_type="TEST_WIDGET", aggregate_id=w.id, event_type="WidgetCreated",
                      payload={"id": str(w.id)})
        with pytest.raises(RuntimeError):
            with db.session() as s, transaction(s):
                record_audit(s, AuditLog, action="ENTITY_UPDATED", entity_type="TEST_WIDGET", entity_id=w.id)
                add_event(s, OutboxEvent, aggregate_type="TEST_WIDGET", aggregate_id=w.id,
                          event_type="WidgetUpdated", payload={})
                raise RuntimeError("use case failed")
    finally:
        context.correlation_id_var.reset(token)
    with db.session() as s:
        audits = s.scalars(select(AuditLog).where(AuditLog.entity_id == w.id)).all()
        events = s.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == w.id)).all()
    assert [a.action for a in audits] == ["ENTITY_CREATED"]
    assert audits[0].after_data == {"name": "audited", "password": "***"}
    assert audits[0].correlation_id == "corr-audit-0001"
    assert [e.event_type for e in events] == ["WidgetCreated"] and events[0].published_at is None


def test_outbox_rejects_bad_event_names(db):
    with db.session() as s, pytest.raises(ValueError):
        add_event(s, OutboxEvent, aggregate_type="X", aggregate_id=uuid.uuid4(), event_type="job_published", payload={})


def test_version_conflict_maps_to_409(db):
    from fastapi import APIRouter

    router = APIRouter()

    @router.post("/stale")
    def stale():
        raise StaleDataError("lost update")

    app = create_app(settings=ServiceSettings(service_name="t", app_env=Environment.TEST, log_format="text"),
                     version="1", database=db, routers=[router])
    with TestClient(app) as c:
        body = c.post("/stale").json()
        assert body["status"] == 409 and body["code"] == "VERSION_CONFLICT"
        ready = c.get("/health/ready")
        assert ready.status_code == 200 and ready.json()["checks"]["database"]["status"] == "ok"


def test_ready_reports_unreachable_database_without_leaking(db_settings):
    bad = db_settings.model_copy(update={"port": 1, "connect_timeout_seconds": 1})
    database = Database(bad)
    app = create_app(settings=ServiceSettings(service_name="t", app_env=Environment.TEST, log_format="text"),
                     version="1", database=database)
    with TestClient(app) as c:
        response = c.get("/health/ready")
    assert response.status_code == 503
    assert "password" not in response.text and db_settings.password.get_secret_value() not in response.text
