"""Owner console: the Academy course builder and course analytics (admin.cyphward.com, owner only).

Reads take `require_owner` and write an owner audit row before any data leaves (as owner_views.py does). Writes take
`require_owner_mutation` (owner session cookie plus the exact console Origin) and run in one transaction with their
owner_audit row, so a change can never commit without its record; a refusal is audited as rejected (`_run`).

Publishing needs the course title typed exactly as stored (`confirm_title`); so does deleting a draft course.
"""
import json
from typing import Annotated, Any, Callable, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, StringConstraints

from backend.app.academy import authoring
from backend.app.core import database
from backend.app.core import owner as owner_mod

router = APIRouter(prefix="/api/v1/owner/academy", tags=["Owner console: Academy"])

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]


def _uuid(value: str) -> str:
    import uuid
    try:
        return str(uuid.UUID(value))
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Not found.")


def _view(request: Request, owner: Dict[str, Any], section: str, target_id: Optional[str] = None) -> None:
    owner_mod.audit(request, f"owner.view.academy_{section}", "success", user_id=owner["user_id"],
                    email=owner["email"], session_id=owner["session_id"],
                    target_type="academy_course" if target_id else None, target_id=target_id)


def _run(request: Request, owner: Dict[str, Any], action: str, target_id: Optional[str],
         work: Callable[[Any], Dict[str, Any]]) -> Dict[str, Any]:
    try:
        with database.get_db() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    done = work(cur)
                    cur.execute(
                        "INSERT INTO owner_audit (actor_user_id, actor_email, session_id, action, outcome, "
                        "target_type, target_id, ip, user_agent, metadata) "
                        "VALUES (%s, %s, %s, %s, 'success', 'academy', %s, %s, %s, %s::jsonb) RETURNING id",
                        (owner["user_id"], owner["email"], owner["session_id"], action,
                         target_id or done["result"].get("id"), owner_mod.client_ip(request),
                         (request.headers.get("user-agent") or "")[:200] or None,
                         json.dumps(done["audit"], default=str)))
                    if cur.fetchone() is None:
                        raise RuntimeError("owner audit insert returned no row")
    except HTTPException as refused:
        if refused.status_code < 500:
            owner_mod.audit(request, action, "rejected", user_id=owner["user_id"], email=owner["email"],
                            session_id=owner["session_id"], target_type="academy", target_id=target_id,
                            metadata={"detail": refused.detail})
        raise
    except Exception:
        owner_mod.logger.exception("owner academy action %s failed", action)
        raise HTTPException(status_code=503, detail="The change could not be saved. Nothing was changed.")
    return done["result"]


# ── Bodies ─────────────────────────────────────────────────────────────────
Level = Literal["beginner", "intermediate", "advanced"]


class CourseBody(BaseModel):
    title: Title
    summary: str = Field(default="", max_length=600)
    level: Level = "beginner"
    duration_minutes: int = Field(default=30, ge=1, le=6000)
    cover_url: Optional[str] = Field(default=None, max_length=500, pattern=r"^https://\S+$")
    cover_alt: str = Field(default="", max_length=200)


class CourseEdit(BaseModel):
    title: Optional[Title] = None
    summary: Optional[str] = Field(default=None, max_length=600)
    level: Optional[Level] = None
    duration_minutes: Optional[int] = Field(default=None, ge=1, le=6000)
    cover_url: Optional[str] = Field(default=None, max_length=500, pattern=r"^https://\S+$")
    cover_alt: Optional[str] = Field(default=None, max_length=200)


class ConfirmTitle(BaseModel):
    confirm_title: str = Field(min_length=1, max_length=200)


class ModuleBody(BaseModel):
    title: Title


class LessonBody(BaseModel):
    title: Title
    body_md: str = Field(default="", max_length=40000)
    video_url: Optional[str] = Field(default=None, max_length=500)
    minutes: int = Field(default=5, ge=1, le=600)


class LessonEdit(BaseModel):
    title: Optional[Title] = None
    body_md: Optional[str] = Field(default=None, max_length=40000)
    video_url: Optional[str] = Field(default=None, max_length=500)
    minutes: Optional[int] = Field(default=None, ge=1, le=600)


class QuizBody(BaseModel):
    title: Title
    pass_mark: int = Field(default=70, ge=1, le=100)


class OptionIn(BaseModel):
    id: Optional[str] = None
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    is_correct: bool = False


class QuestionIn(BaseModel):
    id: Optional[str] = None
    prompt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
    kind: Literal["single", "multiple"] = "single"
    explanation: str = Field(default="", max_length=1000)
    options: List[OptionIn] = Field(min_length=0, max_length=12)


class QuizSave(BaseModel):
    title: Title
    pass_mark: int = Field(ge=1, le=100)
    questions: List[QuestionIn] = Field(max_length=100)


class ItemRef(BaseModel):
    kind: Literal["lesson", "quiz"]
    id: str


class ModuleOrder(BaseModel):
    id: str
    items: List[ItemRef] = Field(max_length=500)


class ReorderBody(BaseModel):
    modules: List[ModuleOrder] = Field(max_length=200)


def _ids(values: List[Optional[str]]) -> None:
    for v in values:
        if v is not None:
            _uuid(v)


# ── Reads ──────────────────────────────────────────────────────────────────
@router.get("/courses")
def list_courses(request: Request, owner: Dict[str, Any] = Depends(owner_mod.require_owner)) -> Dict[str, Any]:
    _view(request, owner, "courses")
    return {"courses": authoring.course_list()}


@router.get("/courses/{course_id}")
def course_detail(course_id: str, request: Request,
                  owner: Dict[str, Any] = Depends(owner_mod.require_owner)) -> Dict[str, Any]:
    cid = _uuid(course_id)
    _view(request, owner, "course", cid)
    tree = authoring.course_tree(cid)
    if not tree:
        raise HTTPException(status_code=404, detail="Not found.")
    return {**tree, "analytics": authoring.analytics(cid)}


@router.get("/courses/{course_id}/learners")
def course_learners(course_id: str, request: Request, limit: int = Query(100, ge=1, le=200),
                    offset: int = Query(0, ge=0, le=100000),
                    owner: Dict[str, Any] = Depends(owner_mod.require_owner)) -> Dict[str, Any]:
    cid = _uuid(course_id)
    _view(request, owner, "learners", cid)
    if not authoring.store.course_by_id(cid):
        raise HTTPException(status_code=404, detail="Not found.")
    return {**authoring.learners(cid, limit, offset), "analytics": authoring.analytics(cid)}


# ── Course writes ──────────────────────────────────────────────────────────
@router.post("/courses")
def create_course(body: CourseBody, request: Request,
                  owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    return _run(request, owner, "owner.academy.course_create", None,
                lambda cur: authoring.create_course(cur, body.model_dump()))


@router.patch("/courses/{course_id}")
def edit_course(course_id: str, body: CourseEdit, request: Request,
                owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    cid = _uuid(course_id)
    return _run(request, owner, "owner.academy.course_edit", cid,
                lambda cur: authoring.update_course(cur, cid, body.model_dump(exclude_unset=True)))


@router.post("/courses/{course_id}/publish")
def publish_course(course_id: str, body: ConfirmTitle, request: Request,
                   owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    cid = _uuid(course_id)
    return _run(request, owner, "owner.academy.course_publish", cid,
                lambda cur: authoring.publish(cur, cid, body.confirm_title))


@router.post("/courses/{course_id}/unpublish")
def unpublish_course(course_id: str, request: Request,
                     owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    cid = _uuid(course_id)
    return _run(request, owner, "owner.academy.course_unpublish", cid, lambda cur: authoring.unpublish(cur, cid))


@router.post("/courses/{course_id}/delete")
def delete_course(course_id: str, body: ConfirmTitle, request: Request,
                  owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    cid = _uuid(course_id)
    return _run(request, owner, "owner.academy.course_delete", cid,
                lambda cur: authoring.delete_course(cur, cid, body.confirm_title))


@router.post("/courses/{course_id}/reorder")
def reorder_course(course_id: str, body: ReorderBody, request: Request,
                   owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    cid = _uuid(course_id)
    _ids([m.id for m in body.modules] + [it.id for m in body.modules for it in m.items])
    return _run(request, owner, "owner.academy.course_reorder", cid,
                lambda cur: authoring.reorder(cur, cid, [m.model_dump() for m in body.modules]))


# ── Modules ────────────────────────────────────────────────────────────────
@router.post("/courses/{course_id}/modules")
def add_module(course_id: str, body: ModuleBody, request: Request,
               owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    cid = _uuid(course_id)
    return _run(request, owner, "owner.academy.module_create", cid, lambda cur: authoring.create_module(cur, cid, body.title))


@router.patch("/modules/{module_id}")
def edit_module(module_id: str, body: ModuleBody, request: Request,
                owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    mid = _uuid(module_id)
    return _run(request, owner, "owner.academy.module_edit", mid, lambda cur: authoring.update_module(cur, mid, body.title))


@router.post("/modules/{module_id}/remove")
def remove_module(module_id: str, request: Request,
                  owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    mid = _uuid(module_id)
    return _run(request, owner, "owner.academy.module_remove", mid, lambda cur: authoring.remove_module(cur, mid))


# ── Lessons ────────────────────────────────────────────────────────────────
@router.post("/modules/{module_id}/lessons")
def add_lesson(module_id: str, body: LessonBody, request: Request,
               owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    mid = _uuid(module_id)
    return _run(request, owner, "owner.academy.lesson_create", mid,
                lambda cur: authoring.create_lesson(cur, mid, body.model_dump()))


@router.patch("/lessons/{lesson_id}")
def edit_lesson(lesson_id: str, body: LessonEdit, request: Request,
                owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    lid = _uuid(lesson_id)
    return _run(request, owner, "owner.academy.lesson_edit", lid,
                lambda cur: authoring.update_lesson(cur, lid, body.model_dump(exclude_unset=True)))


@router.post("/lessons/{lesson_id}/remove")
def remove_lesson(lesson_id: str, request: Request,
                  owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    lid = _uuid(lesson_id)
    return _run(request, owner, "owner.academy.lesson_remove", lid, lambda cur: authoring.remove_lesson(cur, lid))


# ── Quizzes ────────────────────────────────────────────────────────────────
@router.post("/modules/{module_id}/quizzes")
def add_quiz(module_id: str, body: QuizBody, request: Request,
             owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    mid = _uuid(module_id)
    return _run(request, owner, "owner.academy.quiz_create", mid,
                lambda cur: authoring.create_quiz(cur, mid, body.title, body.pass_mark))


@router.put("/quizzes/{quiz_id}")
def save_quiz(quiz_id: str, body: QuizSave, request: Request,
              owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    qid = _uuid(quiz_id)
    _ids([q.id for q in body.questions] + [o.id for q in body.questions for o in q.options])
    return _run(request, owner, "owner.academy.quiz_save", qid,
                lambda cur: authoring.save_quiz(cur, qid, body.title, body.pass_mark,
                                                [q.model_dump() for q in body.questions]))


@router.post("/quizzes/{quiz_id}/remove")
def remove_quiz(quiz_id: str, request: Request,
                owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    qid = _uuid(quiz_id)
    return _run(request, owner, "owner.academy.quiz_remove", qid, lambda cur: authoring.remove_quiz(cur, qid))
