"""HTTP routes of the Reference Data service.

Public (no sign-in, cacheable with ETag):
    GET /v1/reference                       which lists exist
    GET /v1/reference/{list}                active values (cities?state=, job_roles?category=, skills?q=)
    GET /v1/reference/lookups/{list_code}   active lookup_values of one small list
Administration (REFERENCE.EDIT, platform-wide):
    GET/POST /v1/admin/reference/{list}, PUT /v1/admin/reference/{list}/{id},
    PATCH /v1/admin/reference/{list}/{id}/status       (no delete: deactivate)
Maker-Checker and audit:
    /v1/approvals*, /v1/audit-logs
"""

from fastapi import APIRouter

from reference_service.api import admin, approvals, public


def build_router() -> APIRouter:
    router = APIRouter(prefix="/v1")
    router.include_router(public.router)
    router.include_router(admin.router)
    router.include_router(approvals.router)
    return router
