"""App factory: error model, correlation IDs, pagination, health without a database."""

from __future__ import annotations

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from pydantic import BaseModel

from js_core.app import create_app
from js_core.config import Environment, ServiceSettings
from js_core.errors import Conflict, NotFound, PermissionDenied, VersionConflict
from js_core.responses import Page, PageParams, page_params

router = APIRouter(prefix="/v1")


class Body(BaseModel):
    name: str
    age: int


@router.get("/missing")
def missing():
    raise NotFound("Job not found.")


@router.get("/denied")
def denied():
    raise PermissionDenied()


@router.get("/conflict")
def conflict():
    raise VersionConflict()


@router.get("/custom")
def custom():
    raise Conflict("Already applied.", code="ALREADY_APPLIED", details={"application_number": "APP-000001"})


@router.get("/boom")
def boom():
    raise RuntimeError("database password is hunter2")


@router.post("/items")
def create(body: Body):
    return body


@router.get("/items", response_model=Page[int])
def items(params: PageParams = Depends(page_params)):
    return Page(items=list(range(params.offset, params.offset + params.size)), page=params.page,
                size=params.size, total=500)


@pytest.fixture()
def client():
    app = create_app(settings=ServiceSettings(service_name="unit", app_env=Environment.TEST, log_format="text"),
                     version="0.0.1", database=None, routers=[router])
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _shape(body: dict) -> None:
    assert set(body) == {"type", "status", "code", "message", "errors", "details", "correlation_id", "timestamp"}


@pytest.mark.parametrize("path,status,code", [
    ("/v1/missing", 404, "NOT_FOUND"), ("/v1/denied", 403, "PERMISSION_DENIED"),
    ("/v1/conflict", 409, "VERSION_CONFLICT"), ("/v1/custom", 409, "ALREADY_APPLIED"),
    ("/v1/nope", 404, "NOT_FOUND"),
])
def test_error_model(client, path, status, code):
    response = client.get(path)
    body = response.json()
    _shape(body)
    assert response.status_code == status == body["status"] and body["code"] == code
    assert body["correlation_id"] == response.headers["x-correlation-id"]


def test_custom_details_are_returned(client):
    assert client.get("/v1/custom").json()["details"] == {"application_number": "APP-000001"}


def test_validation_errors_list_fields(client):
    body = client.post("/v1/items", json={"name": "x", "age": "old"}).json()
    assert body["status"] == 422 and body["code"] == "VALIDATION_FAILED"
    assert [e["field"] for e in body["errors"]] == ["age"]


def test_unexpected_error_hides_details(client, caplog):
    response = client.get("/v1/boom")
    assert response.status_code == 500
    assert "hunter2" not in response.text and response.json()["code"] == "INTERNAL_ERROR"


def test_correlation_id_is_kept_or_replaced(client):
    kept = client.get("/health/live", headers={"X-Correlation-Id": "caller-corr-001"})
    assert kept.headers["x-correlation-id"] == "caller-corr-001"
    replaced = client.get("/health/live", headers={"X-Correlation-Id": "bad id with spaces"})
    assert replaced.headers["x-correlation-id"] != "bad id with spaces"
    assert kept.headers["x-request-id"] != replaced.headers["x-request-id"]


def test_pagination_limits(client):
    assert client.get("/v1/items?page=2&size=3").json() == {"items": [3, 4, 5], "page": 2, "size": 3, "total": 500}
    assert client.get("/v1/items").json()["size"] == 20
    assert client.get("/v1/items?size=101").status_code == 422
    assert client.get("/v1/items?page=0").status_code == 422


def test_health_without_database(client):
    assert client.get("/health/live").json()["status"] == "ok"
    assert client.get("/health/ready").status_code == 200


def test_docs_off_in_production():
    app = create_app(settings=ServiceSettings(service_name="p", app_env=Environment.PRODUCTION), version="1",
                     database=None)
    with TestClient(app) as c:
        assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404
