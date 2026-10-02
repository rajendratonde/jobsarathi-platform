"""Public read API. Other services and the React app read lists here; nobody reads reference_db."""

from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from js_core.errors import NotFound
from reference_service import service
from reference_service.lists import LISTS, get_list
from reference_service.runtime import Runtime, db_session, runtime

router = APIRouter(prefix="/reference", tags=["reference (public)"])
Db = Annotated[Session, Depends(db_session)]
Rt = Annotated[Runtime, Depends(runtime)]


def _cached(request: Request, rt: Runtime, fingerprint: str, build) -> Response:
    etag = 'W/"' + hashlib.sha256(f"{request.url.path}?{request.url.query}|{fingerprint}".encode()).hexdigest()[:32] + '"'
    headers = {"ETag": etag, "Cache-Control": f"public, max-age={rt.settings.read_max_age_seconds}",
               "Vary": "Accept-Encoding"}
    if etag in [t.strip() for t in request.headers.get("if-none-match", "").split(",")]:
        return Response(status_code=304, headers=headers)
    return JSONResponse(build(), headers=headers)


@router.get("")
def index() -> dict:
    return {"lists": [{"list": d.key, "label": d.label,
                       "parent": {"list": d.parent.list_key, "field": d.parent.field} if d.parent else None,
                       "fields": [e.name for e in d.extras], "searchable": d.searchable}
                      for d in LISTS.values() if d.public]}


@router.get("/lookups/{list_code}")
def lookup_values(list_code: str, request: Request, rt: Rt, session: Db) -> Response:
    d = LISTS["lookup_values"]
    code = list_code.upper()
    return _cached(request, rt, service.list_fingerprint(session, d, code),
                   lambda: {"list": f"lookups/{code}", "items": service.public_values(session, d, list_code=code)})


@router.get("/{list_key}")
def read_list(list_key: str, request: Request, rt: Rt, session: Db,
              q: str | None = Query(default=None, min_length=1, max_length=50),
              state: str | None = Query(default=None, max_length=50),
              category: str | None = Query(default=None, max_length=50)) -> Response:
    d = get_list(list_key)
    if not d.public:
        raise NotFound("Unknown reference list.", code="UNKNOWN_LIST")
    parent_code = state if d.key == "cities" else category if d.key == "job_roles" else None
    return _cached(request, rt, service.list_fingerprint(session, d),
                   lambda: {"list": d.key, "items": service.public_values(session, d, q=q, parent_code=parent_code)})
