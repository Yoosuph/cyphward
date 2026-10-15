from fastapi import APIRouter
from backend.app.core.database import execute_one
from backend.app.core.runtime_guard import background_status

router = APIRouter(tags=["Health"])

@router.get("/health")
def health_check():
    db_ok = False
    try:
        res = execute_one("SELECT 1 as ok;")
        db_ok = bool(res and res.get("ok") == 1)
    except Exception:
        db_ok = False

    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "service": "cyphward-api",
        "version": "1.0.0",
        # Scheduler / scan-recovery loop state; never includes URLs or secrets.
        "background": background_status(),
    }
