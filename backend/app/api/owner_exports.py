"""Owner console CSV exports (phase 1): the visible list filter, as a file.

* GET /api/v1/owner/exports/organizations.csv   same filters and sort as GET /owner/organizations
* GET /api/v1/owner/exports/users.csv           same filters and sort as GET /owner/users
* GET /api/v1/owner/exports/subscriptions.csv   same filters and sort as GET /owner/subscriptions

Each export is capped at EXPORT_MAX (10,000) rows. One extra row is read to tell a full export from a cut one; a
cut export says so in the X-Export-Truncated header and in its audit row. The rows are read under the 5 s statement
timeout, the connection is released, and only then is the CSV written (core/owner_reads.py). The owner audit row
(`owner.export.<list>`: filters, row count, truncated) is written before the file is returned; if it cannot be
written, no file is returned. Cells a spreadsheet would run as a formula are prefixed with a quote. The response is
never cached. Email addresses appear only here and in the console itself.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Sequence, Tuple

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from backend.app.core import owner as owner_mod
from backend.app.core import owner_lists as lists
from backend.app.core import owner_reads as reads

router = APIRouter(prefix="/api/v1/owner/exports", tags=["Owner console exports"])


def _send(request: Request, owner: Dict[str, Any], kind: str, filters: Dict[str, Any],
          rows: List[Dict[str, Any]], columns: Sequence[Tuple[str, str]]) -> Response:
    truncated = len(rows) > reads.EXPORT_MAX
    rows = rows[:reads.EXPORT_MAX]
    meta = {k: (v[:100] if isinstance(v, str) else v) for k, v in filters.items() if v not in ("", None)}
    owner_mod.audit(request, f"owner.export.{kind}", "success", user_id=owner["user_id"], email=owner["email"],
                    session_id=owner["session_id"],
                    metadata={"filters": meta, "rows": len(rows), "truncated": truncated})
    body = reads.to_csv(columns, rows)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="cyphward-{kind}-{stamp}.csv"',
            "Cache-Control": "no-store",
            "X-Export-Rows": str(len(rows)),
            "X-Export-Truncated": "true" if truncated else "false",
        },
    )


@router.get("/organizations.csv")
def export_organizations(request: Request, q: str = Query("", max_length=100), billing: lists.OrgBilling = "",
                         plan: lists.PlanFilter = "", suspended: lists.YesNo = "", deleted: lists.OrgDeleted = "",
                         sort: lists.OrgSort = "created", dir: lists.Dir = "desc",
                         owner: Dict[str, Any] = Depends(owner_mod.require_owner)) -> Response:
    rows_q, _ = lists.organizations(q, billing, plan, suspended, sort, dir, reads.EXPORT_MAX + 1, 0, deleted)
    rows, = reads.bounded_read([rows_q])
    filters = {"q": q, "billing": billing, "plan": plan, "suspended": suspended, "deleted": deleted, "sort": sort,
               "dir": dir}
    return _send(request, owner, "organizations", filters, rows, lists.ORG_CSV)


@router.get("/users.csv")
def export_users(request: Request, q: str = Query("", max_length=100), mfa: lists.UserMfa = "",
                 verified: lists.YesNo = "", sort: lists.UserSort = "created", dir: lists.Dir = "desc",
                 owner: Dict[str, Any] = Depends(owner_mod.require_owner)) -> Response:
    rows_q, _ = lists.users(q, mfa, verified, sort, dir, reads.EXPORT_MAX + 1, 0)
    rows, = reads.bounded_read([rows_q])
    rows = [{**r, "roles": lists.user_roles(r)} for r in rows]
    filters = {"q": q, "mfa": mfa, "verified": verified, "sort": sort, "dir": dir}
    return _send(request, owner, "users", filters, rows, lists.USER_CSV)


@router.get("/subscriptions.csv")
def export_subscriptions(request: Request, q: str = Query("", max_length=100), status: lists.SubStatus = "",
                         plan: lists.PlanFilter = "", deleted: lists.OrgDeleted = "",
                         sort: lists.SubSort = "period_end", dir: lists.Dir = "asc",
                         owner: Dict[str, Any] = Depends(owner_mod.require_owner)) -> Response:
    rows_q, _ = lists.subscriptions(q, status, plan, sort, dir, reads.EXPORT_MAX + 1, 0, deleted)
    rows, = reads.bounded_read([rows_q])
    filters = {"q": q, "status": status, "plan": plan, "deleted": deleted, "sort": sort, "dir": dir}
    return _send(request, owner, "subscriptions", filters, rows, lists.SUB_CSV)
