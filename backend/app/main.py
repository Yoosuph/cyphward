from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html

import asyncio
import logging

from backend.app.core.config import CORS_ORIGINS, SCHEDULER_ENABLED
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
    scanner_jobs,
    auth,
    auth_google,
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
app.include_router(auth.router)
app.include_router(auth_google.google_router)
app.include_router(health.router)
app.include_router(scanner_jobs.router)

# ---------------------------------------------------------------------------
# Startup recovery: scans orphaned by a previous process death (local mode
# pipelines are not lease-backed; see backend.app.core.scan_recovery).
# Runs before the scheduler so a stale queued/running row cannot suppress
# today's due-domain check.
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def recover_interrupted_scans_on_startup() -> None:
    try:
        from backend.app.core.scan_recovery import recover_interrupted_scans
        recover_interrupted_scans()
    except Exception:
        logging.getLogger("cyphward.scan_recovery").exception(
            "startup scan recovery failed"
        )


# ---------------------------------------------------------------------------
# In-process daily scan scheduler (06:00 UTC sweep) — backend.app.scheduler
# ---------------------------------------------------------------------------
_scheduler_task: asyncio.Task | None = None
_scheduler_stop: asyncio.Event | None = None


@app.on_event("startup")
async def start_daily_scan_scheduler() -> None:
    global _scheduler_task, _scheduler_stop
    if not SCHEDULER_ENABLED:
        logging.getLogger("cyphward.scheduler").info(
            "daily scan scheduler disabled (CYPHWARD_SCHEDULER_ENABLED=false)"
        )
        return
    from backend.app.scheduler import daily_scan_scheduler

    _scheduler_stop = asyncio.Event()
    _scheduler_task = asyncio.create_task(daily_scan_scheduler(_scheduler_stop))


@app.on_event("shutdown")
async def stop_daily_scan_scheduler() -> None:
    if _scheduler_stop is not None:
        _scheduler_stop.set()
    if _scheduler_task is None:
        return
    try:
        await asyncio.wait_for(_scheduler_task, timeout=5)
    except asyncio.TimeoutError:
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=True)
