"""Reference Data client (Implementation Blueprint: "Every service -> Reference Data").

Services never read reference_db. They call ``GET /v1/reference/{list}`` and keep a local copy:

    client = ReferenceClient("http://reference:8000")
    client.require("job_types", "FULL_TIME")      # 422 if unknown or inactive
    label = client.label("cities", "PUNE")         # "Pune"

* each list is cached for ``ttl_seconds``; after that it is revalidated with If-None-Match
  (a 304 keeps the copy without downloading it again)
* if Reference Data is unreachable, the last good copy is used; with no copy at all the
  call fails with 503 so a write never accepts a code nobody has checked
* timeout 2 s, 2 retries (Blueprint service-call table)
"""

from js_reference.client import ReferenceClient, ReferenceList, ReferenceValue

__all__ = ["ReferenceClient", "ReferenceList", "ReferenceValue"]
