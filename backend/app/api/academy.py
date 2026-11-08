"""Cyphward Academy API for learners (academy.cyphward.com) and for organisation assignments (the customer app).

Learner routes act on the signed-in person, never on an organisation: they take `get_current_user` (or the optional
variant for the public catalogue) and every query names the person. Their writes are the person's own learning
record, so they sit on the reviewed allow-list in test_suspension_gate.py.

Organisation routes (/api/v1/academy/org/...) are tenant-scoped: reads take `require_admin` (owners and admins see
their own organisation's members only; plain members never see colleagues' progress) and writes take
`require_active_admin` (refused while the organisation is suspended, 404 when deleted).

Public: GET /courses, GET /courses/{slug} (the outline without lesson bodies) and GET /verify/{code}
(learner name, course title and completion date only; rate limited per IP).
"""
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend.app.academy import certificate as cert
from backend.app.academy import quiz as quizmod, store
from backend.app.core import database
from backend.app.core.auth import get_current_user, log_audit, require_admin
from backend.app.core.owner import client_ip
from backend.app.core.rate_limit import check_rate_limit
from backend.app.core.suspension import require_active_admin
from backend.app.services import notifications

router = APIRouter(prefix="/api/v1/academy", tags=["Academy"])

QUIZ_LIMIT = (10, 600)      # submissions per person per quiz per 10 minutes
VERIFY_LIMIT = (30, 300)    # verification look-ups per IP per 5 minutes
NOT_FOUND = "Course not found."
NOT_AVAILABLE = "This course is not available right now. Your progress is kept."
NOT_ENROLLED = {"code": "not_enrolled", "message": "Start the course to open its lessons."}


def optional_user(authorization: Optional[str] = Header(None), request: Request = None) -> Optional[Dict[str, Any]]:
    """The signed-in person when a bearer token is sent (a bad token is still refused), else None."""
    if not authorization:
        return None
    return get_current_user(authorization, request)


def _uuid(value: str) -> str:
    import uuid
    try:
        return str(uuid.UUID(value))
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Not found.")


def _published(slug: str) -> Dict[str, Any]:
    course = store.course_by_slug(slug)
    if not course or course["status"] != "published":
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return course


def _enrolled_course(slug: str, user: Dict[str, Any]) -> Dict[str, Any]:
    course = store.course_by_slug(slug)
    if not course:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    enrolled = store.enrolment(str(user["id"]), str(course["id"]))
    if course["status"] != "published":
        raise HTTPException(status_code=404 if not enrolled else 409, detail=NOT_FOUND if not enrolled else NOT_AVAILABLE)
    if not enrolled:
        raise HTTPException(status_code=409, detail=NOT_ENROLLED)
    return course


def _neighbours(modules: List[Dict[str, Any]], item_id: str) -> Dict[str, Any]:
    items = store.flat_items(modules)
    idx = next((i for i, it in enumerate(items) if it["id"] == item_id), None)
    if idx is None:
        return {"prev": None, "next": None}
    pick = lambda it: {"kind": it["kind"], "id": it["id"], "title": it["title"]} if it else None  # noqa: E731
    return {"prev": pick(items[idx - 1] if idx > 0 else None), "next": pick(items[idx + 1] if idx + 1 < len(items) else None)}


def _notify_completion(user: Dict[str, Any], course: Dict[str, Any], issued: Optional[Dict[str, Any]]) -> None:
    """A new certificate: tell the owners and admins of each active organisation that assigned the course."""
    if not issued:
        return
    with database.get_db() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                orgs = store.completion_orgs(cur, str(user["id"]), str(course["id"]))
    for row in orgs:
        notifications.emit("academy_course_completed", row["org_id"],
                           key=f"academy_completed:{user['id']}:{course['id']}",
                           params={"name": cert.display_name(user.get("full_name")), "course": course["title"]},
                           actor_id=user["id"])


def _certificate_out(issued: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return cert.public_view(issued) if issued else None


# ── Catalogue (public) ─────────────────────────────────────────────────────
@router.get("/courses")
def catalogue() -> Dict[str, Any]:
    return {"courses": store.published_courses()}


@router.get("/courses/{slug}")
def course_page(slug: str, user: Optional[Dict[str, Any]] = Depends(optional_user)) -> Dict[str, Any]:
    course = store.course_by_slug(slug)
    enrolled = bool(user and course and store.enrolment(str(user["id"]), str(course["id"])))
    if not course or (course["status"] != "published" and not enrolled):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    modules = store.outline(str(course["id"]))
    state = store.learner_state(str(user["id"]), str(course["id"]), modules) if user else None
    done = set((state or {}).get("done_ids") or [])
    for m in modules:
        for it in m["items"]:
            it["done"] = it["id"] in done
    return {"course": store.course_public(course), "available": course["status"] == "published",
            "modules": modules, "signed_in": user is not None, "progress": state}


# ── Learning (signed in) ───────────────────────────────────────────────────
@router.post("/courses/{slug}/enrol")
def start_course(slug: str, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    course = _published(slug)
    started = store.enrol(str(user["id"]), str(course["id"]))
    modules = store.outline(str(course["id"]))
    return {"started": started, "progress": store.learner_state(str(user["id"]), str(course["id"]), modules)}


@router.get("/courses/{slug}/lessons/{lesson_id}")
def open_lesson(slug: str, lesson_id: str, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    course = _enrolled_course(slug, user)
    row = store.lesson_row(str(course["id"]), _uuid(lesson_id))
    if not row:
        raise HTTPException(status_code=404, detail="Lesson not found.")
    modules = store.outline(str(course["id"]))
    state = store.learner_state(str(user["id"]), str(course["id"]), modules) or {}
    lesson = store.lesson_view(row)
    lesson["done"] = lesson["id"] in set(state.get("done_ids") or [])
    return {"course": {"slug": course["slug"], "title": course["title"]}, "lesson": lesson,
            **_neighbours(modules, lesson["id"]), "progress": state}


@router.post("/courses/{slug}/lessons/{lesson_id}/complete")
def finish_lesson(slug: str, lesson_id: str, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    course = _enrolled_course(slug, user)
    lid = _uuid(lesson_id)
    if not store.lesson_row(str(course["id"]), lid):
        raise HTTPException(status_code=404, detail="Lesson not found.")
    issued = store.complete_lesson(str(user["id"]), course, lid)
    _notify_completion(user, course, issued)
    modules = store.outline(str(course["id"]))
    return {"progress": store.learner_state(str(user["id"]), str(course["id"]), modules),
            "certificate": _certificate_out(issued)}


@router.get("/courses/{slug}/quizzes/{quiz_id}")
def open_quiz(slug: str, quiz_id: str, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    course = _enrolled_course(slug, user)
    quiz, questions, options = store.quiz_rows(str(course["id"]), _uuid(quiz_id))
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found.")
    modules = store.outline(str(course["id"]))
    return {"course": {"slug": course["slug"], "title": course["title"]},
            "quiz": quizmod.learner_quiz(quiz, questions, options),
            "attempts": store.attempts_summary(str(user["id"]), str(quiz["id"])),
            **_neighbours(modules, str(quiz["id"])),
            "progress": store.learner_state(str(user["id"]), str(course["id"]), modules)}


class AttemptBody(BaseModel):
    answers: Dict[str, Any] = Field(default_factory=dict)


@router.post("/courses/{slug}/quizzes/{quiz_id}/attempts")
def submit_quiz(slug: str, quiz_id: str, body: AttemptBody,
                user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    course = _enrolled_course(slug, user)
    qid = _uuid(quiz_id)
    check_rate_limit(f"academy-quiz:{user['id']}:{qid}", *QUIZ_LIMIT)
    try:
        answers = quizmod.normalise_answers(body.answers)
        result, issued = store.submit_attempt(str(user["id"]), course, qid, answers)
    except LookupError:
        raise HTTPException(status_code=404, detail="Quiz not found.")
    except ValueError as refused:
        raise HTTPException(status_code=422, detail=str(refused))
    _notify_completion(user, course, issued)
    modules = store.outline(str(course["id"]))
    return {"result": result, "attempts": store.attempts_summary(str(user["id"]), qid),
            "progress": store.learner_state(str(user["id"]), str(course["id"]), modules),
            "certificate": _certificate_out(issued)}


@router.get("/me/learning")
def my_learning(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    return store.my_learning(str(user["id"]))


@router.get("/certificates/{code}/pdf")
def certificate_pdf(code: str, user: Dict[str, Any] = Depends(get_current_user)) -> Response:
    row = store.certificate_by_code(code)
    if not row or str(row["user_id"]) != str(user["id"]):
        raise HTTPException(status_code=404, detail="Certificate not found.")
    return Response(cert.to_pdf(row), media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="cyphward-academy-{row["code"]}.pdf"',
        "Cache-Control": "no-store"})


# ── Public verification ────────────────────────────────────────────────────
@router.get("/verify/{code}")
def verify(code: str, request: Request) -> Dict[str, Any]:
    check_rate_limit(f"academy-verify-ip:{client_ip(request) or 'unknown'}", *VERIFY_LIMIT)
    row = store.certificate_by_code(code)
    if not row:
        raise HTTPException(status_code=404, detail="No certificate has this ID. Check it and try again.")
    return {"certificate": cert.public_view(row)}


# ── Organisation assignments ───────────────────────────────────────────────
class AssignBody(BaseModel):
    course_id: str
    user_ids: List[str] = Field(min_length=1, max_length=500)
    due_on: Optional[date] = None


class DueBody(BaseModel):
    due_on: Optional[date] = None


def _check_due(due_on: Optional[date]) -> None:
    if due_on is not None and due_on < date.today():
        raise HTTPException(status_code=422, detail="Choose a due date that is today or later.")


@router.get("/org/overview")
def org_overview(org: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    return {"courses": store.org_overview(str(org["id"])), "available": store.published_courses()}


@router.get("/org/courses/{course_id}")
def org_course(course_id: str, org: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    course = store.course_by_id(_uuid(course_id))
    if not course:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return {"course": store.course_public(course), "available": course["status"] == "published",
            "members": store.org_course_detail(str(org["id"]), str(course["id"]))}


@router.post("/org/assignments")
def assign(body: AssignBody, org: Dict[str, Any] = Depends(require_active_admin)) -> Dict[str, Any]:
    course = store.course_by_id(_uuid(body.course_id))
    if not course or course["status"] != "published":
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    _check_due(body.due_on)
    user_ids = sorted({_uuid(u) for u in body.user_ids})
    org_id, by = str(org["id"]), str(org["current_user_id"])
    try:
        with database.get_db() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    created = store.assign(cur, org_id, str(course["id"]), user_ids, body.due_on, by)
    except ValueError as refused:
        raise HTTPException(status_code=422, detail=str(refused))
    due_text = cert.long_date(body.due_on) if body.due_on else None
    for row in created:
        notifications.emit("academy_course_assigned", org_id, key=f"academy_assigned:{row['id']}",
                           params={"course": course["title"], "due": due_text}, recipients=[row["user_id"]],
                           actor_id=by)
    log_audit(org_id, by, "academy.assigned", "academy_course", str(course["id"]),
              {"assigned": len(created), "skipped": len(user_ids) - len(created), "due_on": body.due_on})
    return {"assigned": len(created), "already_assigned": len(user_ids) - len(created), "assignments": created}


@router.patch("/org/assignments/{assignment_id}")
def change_due(assignment_id: str, body: DueBody, org: Dict[str, Any] = Depends(require_active_admin)) -> Dict[str, Any]:
    aid = _uuid(assignment_id)
    _check_due(body.due_on)
    if not store.set_due(str(org["id"]), aid, body.due_on):
        raise HTTPException(status_code=404, detail="Assignment not found.")
    log_audit(str(org["id"]), str(org["current_user_id"]), "academy.due_changed", "academy_assignment", aid,
              {"due_on": body.due_on})
    return {"id": aid, "due_on": body.due_on.isoformat() if body.due_on else None}


@router.delete("/org/assignments/{assignment_id}")
def remove_assignment(assignment_id: str, org: Dict[str, Any] = Depends(require_active_admin)) -> Dict[str, Any]:
    aid = _uuid(assignment_id)
    if not store.unassign(str(org["id"]), aid, str(org["current_user_id"])):
        raise HTTPException(status_code=404, detail="Assignment not found.")
    log_audit(str(org["id"]), str(org["current_user_id"]), "academy.unassigned", "academy_assignment", aid, {})
    return {"id": aid, "removed": True}
