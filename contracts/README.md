# API contracts

One OpenAPI 3.1 file per service (`<service>.openapi.yaml`), written and approved before
that service's endpoints are coded (Implementation Blueprint §8, §32).

Every operation states: path under `/v1`, permission (`x-permission`), scope, whether
Maker-Checker applies, request and response schemas, and the shared error model
(`js_core.errors.ErrorResponse`). React types and mock servers are generated from these files.

Empty in Foundation: no business endpoints exist yet.
