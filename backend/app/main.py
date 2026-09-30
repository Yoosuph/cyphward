from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html

from backend.app.core.config import CORS_ORIGINS
from backend.app.api import (
    overview,
    domains,
    assets,
    findings,
    scans,
    ai,
    settings,
    health,
    reports,
    organizations,
    members,
    remediation,
    dashboard,
    notifications,
)
from backend.app.workflows.inngest_workflow import (
    inngest_client,
    inngest_scan_pipeline_fn,
    inngest_daily_scan_cron,
)
import inngest.fast_api

app = FastAPI(
    title="Cyphward API",
    description="Sovereign Attack Surface Management & Risk Engine API per MVP Architecture",
    version="2.0.0",
    openapi_url="/api/v1/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inngest endpoint registration: /api/inngest
inngest.fast_api.serve(
    app,
    inngest_client,
    [inngest_scan_pipeline_fn, inngest_daily_scan_cron],
    serve_path="/api/inngest"
)

# Alias /api/v1/docs to Swagger UI
@app.get("/api/v1/docs", include_in_schema=False)
def api_v1_docs():
    return get_swagger_ui_html(
        openapi_url="/api/v1/openapi.json",
        title="Cyphward API — Documentation",
    )

# RFC 9457 Global Exception Handler — never leak internals to clients
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import logging

    logging.getLogger("cyphward").exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "type": "https://errors.cyphward.com/v1/internal-server-error",
            "title": "Internal Server Error",
            "status": 500,
            "detail": "An unexpected error occurred. Please try again later.",
            "instance": request.url.path,
        },
    )

# MVP Routers
app.include_router(organizations.router)
app.include_router(members.router)
app.include_router(overview.router)
app.include_router(dashboard.router)
app.include_router(domains.router)
app.include_router(assets.router)
app.include_router(findings.router)
app.include_router(scans.router)
app.include_router(remediation.router)
app.include_router(ai.router)
app.include_router(settings.router)
app.include_router(reports.router)
app.include_router(notifications.router)
app.include_router(health.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=True)
