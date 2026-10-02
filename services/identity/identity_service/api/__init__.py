"""HTTP routes of the Identity & Access service (Implementation Blueprint identity API catalogue)."""

from fastapi import APIRouter

from identity_service.api import admin, approvals, auth, internal, rbac


def build_router(*, dev_sink: bool) -> APIRouter:
    router = APIRouter(prefix="/v1")
    router.include_router(auth.router)
    router.include_router(admin.router)
    router.include_router(rbac.router)
    router.include_router(approvals.router)
    router.include_router(internal.internal)
    if dev_sink:
        router.include_router(internal.dev)
    return router


well_known = internal.well_known
