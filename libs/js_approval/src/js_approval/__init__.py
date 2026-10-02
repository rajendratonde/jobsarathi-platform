"""Reusable Maker-Checker (v5 §10).

The same three tables live in each service that approves things (Identity,
Employer, Job; Reference Data optional). A service registers one handler per
entity type; this package enforces the rules every service must share:

* one PENDING request per record (also a partial unique index)
* the checker is never the maker, nor the user whose access is changing
  (service check here + CHECK constraints in the database)
* the checker holds the policy's checker permission in scope for the request's organization
* the record version must equal the submitted and the reviewed version, else SUPERSEDED (409)
* a rejection needs a reason of at least 5 characters
"""

from js_approval.models import ApprovalActionMixin, ApprovalPolicyMixin, ApprovalRequestMixin
from js_approval.service import ApprovalEngine, ApprovalHandler, ApprovalModels

__all__ = ["ApprovalPolicyMixin", "ApprovalRequestMixin", "ApprovalActionMixin",
           "ApprovalEngine", "ApprovalHandler", "ApprovalModels"]
