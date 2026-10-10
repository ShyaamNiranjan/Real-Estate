from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from app import (ai, analytics, auth, billing, enquiries, errors, exports, google, hq, listings, media, public,
                 staff, team, trials, waitlist, workspace)
from app.config import get_settings
from app.db import public_session
from app.deps import SAFE_METHODS

app = FastAPI(title="Scrollwalk API", version="0.1.0", openapi_url="/api/v1/openapi.json")
errors.install(app)
app.include_router(auth.router)
app.include_router(google.router)
app.include_router(workspace.router)
app.include_router(team.router)
app.include_router(team.invite_router)
app.include_router(listings.router)
app.include_router(ai.router)
app.include_router(media.local_router)
app.include_router(media.router)
app.include_router(public.router)
app.include_router(enquiries.public_router)
app.include_router(enquiries.router)
app.include_router(analytics.public_router)
app.include_router(analytics.router)
app.include_router(waitlist.router)
app.include_router(billing.router)
app.include_router(billing.public_router)
app.include_router(exports.router)
app.include_router(trials.router)
app.include_router(staff.router)
app.include_router(hq.router)


@app.middleware("http")
async def guard(request: Request, call_next):
    settings = get_settings()
    # Browsers always send Origin on cross-site writes; refusing unknown origins stops
    # cross-site form posts even on endpoints that don't need a session yet.
    origin = request.headers.get("origin")
    if request.method not in SAFE_METHODS and origin and origin not in settings.allowed_origins:
        return JSONResponse(
            errors._body("origin_not_allowed", "This request came from a site that isn't allowed."), status_code=403
        )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers.setdefault("Cache-Control", "no-store")
    if not request.url.path.startswith(("/docs", "/redoc")):
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if settings.cookie_secure:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


class Health(BaseModel):
    status: str
    database: bool


@app.get("/api/v1/health", response_model=Health, tags=["system"])
def health() -> Health:
    try:
        with public_session() as session:
            session.execute(text("SELECT 1"))
        return Health(status="ok", database=True)
    except Exception:
        return Health(status="degraded", database=False)
