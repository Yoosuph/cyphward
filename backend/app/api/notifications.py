"""
Cyphward Notifications API Router (spec §31, §34)
GET    /notifications
PATCH  /notifications/{id}/read
POST   /notifications/read-all
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from backend.app.core.auth import get_current_org
from backend.app.core.database import execute_one, execute_query

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])


@router.get("")
def list_notifications(
    unread_only: bool = False,
    limit: int = 50,
    org: Dict[str, Any] = Depends(get_current_org),
) -> Dict[str, Any]:
    query = "SELECT * FROM notifications WHERE org_id = %s"
    params: List[Any] = [org["id"]]
    if unread_only:
        query += " AND read_at IS NULL"
    query += " ORDER BY created_at DESC LIMIT %s"
    params.append(min(max(limit, 1), 200))

    rows = execute_query(query, tuple(params)) or []
    unread = execute_one(
        "SELECT COUNT(*) AS count FROM notifications WHERE org_id = %s AND read_at IS NULL",
        (org["id"],),
    ) or {"count": 0}
    return {"notifications": rows, "unread_count": unread.get("count", 0)}


@router.patch("/{notification_id}/read")
def mark_read(
    notification_id: str,
    org: Dict[str, Any] = Depends(get_current_org),
) -> Dict[str, Any]:
    row = execute_one(
        """
        UPDATE notifications SET read_at = now()
        WHERE id = %s AND org_id = %s AND read_at IS NULL
        RETURNING *
        """,
        (notification_id, org["id"]),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Notification not found or already read.")
    return {"notification": row}


@router.post("/read-all")
def mark_all_read(org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    execute_one(
        "UPDATE notifications SET read_at = now() WHERE org_id = %s AND read_at IS NULL",
        (org["id"],),
    )
    return {"message": "All notifications marked as read."}
