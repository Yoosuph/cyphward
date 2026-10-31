"""
Cyphward Notifications API (notifications phase 1; services/notifications.py has the rules)

Customer app (the signed-in person, in the organisation named by X-Organization-Id):
GET    /notifications                       newest first, 50 at most per page, with the unread count
PATCH  /notifications/{id}/read             idempotent
POST   /notifications/read-all              idempotent
GET    /notifications/preferences           the person's mutes per category
PUT    /notifications/preferences/{category}

Owner console (owner session; reads and marks are written to owner_audit):
GET    /owner/notifications
GET    /owner/notifications/unread-count    the 60-second poll; returns a number only
POST   /owner/notifications/{id}/read
POST   /owner/notifications/read-all
"""
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from backend.app.core import owner as owner_mod
from backend.app.core.auth import get_current_org, get_current_user
from backend.app.services import notification_messages as msg
from backend.app.services import notifications as svc

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])
owner_router = APIRouter(prefix="/api/v1/owner/notifications", tags=["Owner console"])

NOT_FOUND = "Notification not found."


def _uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail=NOT_FOUND)


def _user_id(org: Dict[str, Any]) -> str:
    uid = org.get("current_user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="Sign in to see notifications.")
    return str(uid)


@router.get("")
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(svc.PAGE_CAP, ge=1, le=200),
    offset: int = Query(0, ge=0, le=100000),
    org: Dict[str, Any] = Depends(get_current_org),
) -> Dict[str, Any]:
    return svc.customer_list(str(org["id"]), _user_id(org), limit, offset, unread_only)


@router.patch("/{notification_id}/read")
def mark_read(notification_id: str, org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    row = svc.customer_mark_read(str(org["id"]), _user_id(org), _uuid(notification_id))
    if row is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return {"notification": row}


@router.post("/read-all")
def mark_all_read(org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    marked = svc.customer_mark_all_read(str(org["id"]), _user_id(org))
    return {"message": "All notifications marked as read.", "marked": marked}


class PreferenceBody(BaseModel):
    in_app: Optional[bool] = None
    email: Optional[bool] = None


@router.get("/preferences")
def get_preferences(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    return {"preferences": svc.get_preferences(str(user["id"])),
            "email_note": "Email is sent only for critical alerts. Everything else stays in the app."}


@router.put("/preferences/{category}")
def put_preference(category: str, body: PreferenceBody,
                   user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if category not in msg.CATEGORIES:
        raise HTTPException(status_code=404, detail="Unknown notification category.")
    return {"preference": svc.set_preference(str(user["id"]), category, body.in_app, body.email)}


# ── Owner console ──────────────────────────────────────────────────────────
def _audit(request: Request, owner: Dict[str, Any], action: str, target_id: Optional[str] = None,
           metadata: Optional[Dict[str, Any]] = None) -> None:
    owner_mod.audit(request, action, "success", user_id=owner["user_id"], email=owner["email"],
                    session_id=owner["session_id"], target_type="notification" if target_id else None,
                    target_id=target_id, metadata=metadata)


@owner_router.get("")
def owner_list(request: Request, limit: int = Query(svc.PAGE_CAP, ge=1, le=200), offset: int = Query(0, ge=0, le=100000),
               owner: Dict[str, Any] = Depends(owner_mod.require_owner)) -> Dict[str, Any]:
    _audit(request, owner, "owner.view.notifications", metadata={"limit": min(limit, svc.PAGE_CAP), "offset": offset})
    return svc.owner_list(owner["user_id"], limit, offset)


@owner_router.get("/unread-count")
def owner_unread(owner: Dict[str, Any] = Depends(owner_mod.require_owner)) -> Dict[str, Any]:
    return {"unread_count": svc.owner_unread(owner["user_id"])}


@owner_router.post("/read-all")
def owner_mark_all(request: Request, owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    marked = svc.owner_mark_all_read(owner["user_id"])
    _audit(request, owner, "owner.notifications.read_all", metadata={"marked": marked})
    return {"message": "All notifications marked as read.", "marked": marked}


@owner_router.post("/{notification_id}/read")
def owner_mark(notification_id: str, request: Request,
               owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    result = svc.owner_mark_read(owner["user_id"], _uuid(notification_id))
    if result is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    _audit(request, owner, "owner.notifications.read", target_id=result["notification"]["id"],
           metadata={"changed": result["changed"]})
    return {"notification": result["notification"]}
