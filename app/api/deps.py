import uuid
from fastapi import HTTPException, Request
from app.core.models import Integration
from app.core.security import is_operator


def get_db(request: Request):
    with request.app.state.session_factory() as session:
        yield session


def demo_owner(request: Request):
    if "owner" not in request.session:
        request.session["owner"] = str(uuid.uuid4())
    return request.session["owner"]


def service_for_request(session, integration_id, request):
    integration = session.get(Integration, integration_id)
    if not integration:
        raise HTTPException(404, "Service not found")
    if not is_operator(request) and (
        not request.app.state.settings.demo_mode
        or integration.demo_owner != demo_owner(request)
    ):
        raise HTTPException(404, "Service not found")
    return integration


def same_origin(request: Request):
    from urllib.parse import urlsplit

    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "Demo actions must come from this site")
