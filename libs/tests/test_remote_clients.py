"""The HTTP clients services use to reach Identity and Reference Data, against a local test server."""

from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from js_auth.context import Scope
from js_auth.keys import load_key_ring
from js_auth.remote import HttpAuthzProvider, JwksKeys
from js_core.config import Environment
from js_core.errors import DependencyUnavailable, ValidationFailed
from js_reference import ReferenceClient


class FakeServer:
    """Routes: path -> (status, body, headers); records request headers."""

    def __init__(self) -> None:
        self.routes: dict[str, tuple[int, object, dict]] = {}
        self.requests: list[tuple[str, dict]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                outer.requests.append((self.path, dict(self.headers)))
                status, body, headers = outer.routes.get(self.path.split("?")[0], (404, {"code": "NOT_FOUND"}, {}))
                if callable(body):
                    status, body, headers = body(self)
                payload = b"" if status == 304 else json.dumps(body).encode()
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.server: ThreadingHTTPServer | None = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None


@pytest.fixture()
def server():
    s = FakeServer()
    yield s
    s.close()


def test_jwks_keys_load_and_refresh_on_unknown_kid(server):
    first, second = load_key_ring(env=Environment.TEST), load_key_ring(env=Environment.TEST)
    server.routes["/.well-known/jwks.json"] = (200, first.jwks(), {})
    keys = JwksKeys(server.url + "/.well-known/jwks.json", min_refresh_seconds=0)
    assert keys.key_for(first.kid) is not None
    server.routes["/.well-known/jwks.json"] = (200, second.jwks(), {})  # Identity rotated its key
    assert keys.key_for(second.kid) is not None
    server.close()
    assert keys.key_for(second.kid) is not None  # last good keys survive an outage


def test_http_authz_provider_sends_service_token_and_maps_scopes(server):
    key = ec.generate_private_key(ec.SECP256R1())
    user = uuid.uuid4()
    server.routes[f"/v1/internal/authz/users/{user}"] = (
        200, {"organization_id": None, "authz_version": 7, "roles": ["X"], "permissions": {"REFERENCE.EDIT": "ALL"}}, {})
    provider = HttpAuthzProvider(server.url, service_name="reference", private_key=key)
    effective = provider.effective(user, None)
    assert effective.authz_version == 7 and effective.scopes == {"REFERENCE.EDIT": Scope.ALL}
    token = server.requests[-1][1]["X-Service-Token"]
    claims = jwt.decode(token, key.public_key(), algorithms=["ES256"], audience="identity")
    assert claims["iss"] == "reference" and claims["typ"] == "service"


def test_http_authz_provider_fails_closed(server):
    key = ec.generate_private_key(ec.SECP256R1())
    provider = HttpAuthzProvider(server.url, service_name="reference", private_key=key)
    assert provider.effective(uuid.uuid4(), None).authz_version == -1  # 404: unknown user, no access
    server.routes["/v1/internal/authz/users/x"] = (500, {}, {})
    unreachable = HttpAuthzProvider("http://127.0.0.1:9", service_name="reference", private_key=key, timeout=0.3)
    with pytest.raises(DependencyUnavailable):
        unreachable.effective(uuid.uuid4(), None)


def test_reference_client_caches_revalidates_and_validates(server):
    calls = {"n": 0}

    def job_types(handler):
        calls["n"] += 1
        if handler.headers.get("If-None-Match") == 'W/"v1"':
            return 304, None, {"ETag": 'W/"v1"'}
        return 200, {"list": "job_types", "items": [{"code": "FULL_TIME", "name": "Full-time", "name_hi": None,
                                                     "sort_order": 0}]}, {"ETag": 'W/"v1"'}

    server.routes["/v1/reference/job_types"] = (200, job_types, {})
    client = ReferenceClient(server.url, ttl_seconds=0)
    assert client.label("job_types", "FULL_TIME") == "Full-time"
    assert client.require("job_types", "FULL_TIME").code == "FULL_TIME"
    with pytest.raises(ValidationFailed):
        client.require("job_types", "NOPE", field_name="job_type_code")
    assert calls["n"] == 3 and server.requests[-1][1].get("If-None-Match") == 'W/"v1"'  # revalidated, not refetched
    server.close()
    assert client.is_valid("job_types", "FULL_TIME")  # last good copy while Reference Data is down
    with pytest.raises(DependencyUnavailable):
        ReferenceClient("http://127.0.0.1:9", timeout=0.3, retries=0).values("job_types")
