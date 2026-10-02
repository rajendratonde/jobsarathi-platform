"""HTTP routes of the Application service.

Foundation: no business endpoints. Routes are added from the approved OpenAPI
contract in contracts/ when the service's phase starts.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/v1", tags=["application"])
