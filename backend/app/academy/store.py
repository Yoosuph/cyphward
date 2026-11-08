"""Academy reads and writes. Every organisation query names org_id; every learner query names the user.

Rules kept here:
  * Learners see published courses only. A course that is unpublished keeps every enrolment, completion, attempt and
    certificate; its lessons and quizzes stop opening until it is published again, and My learning still lists it.
  * The course outline (and so what "complete" means) is the published structure without archived modules, lessons
    and quizzes.
  * A certificate is issued once per person and course, in the same transaction as the lesson completion or quiz pass
    that finished the course. A race between two finishing requests leaves one row (UNIQUE (user_id, course_id)).
  * Assignments: owners and admins of an organisation assign published courses to its members. Progress per member
    is read only through org_course_detail(org_id, ...), which joins on the organisation's own assignments.
"""
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.app.academy import certificate as cert
from backend.app.academy import markdown, quiz as quizmod, video
from backend.app.core import database
from backend.app.core.database import execute_one, execute_query

EVIDENCE_WINDOW_MONTHS = 12
DUE_SOON_DAYS = 3
COURSE_COLUMNS = ("c.id, c.slug, c.title, c.summary, c.level, c.duration_minutes, c.cover_url, c.cover_alt, "
                  "c.status, c.published_at, c.created_at, c.updated_at")
LEVEL_LABELS = {"beginner": "Beginner", "intermediate": "Intermediate", "advanced": "Advanced"}


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, (datetime, date)) else value


def course_public(row: Dict[str, Any]) -> Dict[str, Any]:
    """A course card. Never the price (phase 1)."""
    return {"id": str(row["id"]), "slug": row["slug"], "title": row["title"], "summary": row["summary"],
            "level": row["level"], "level_label": LEVEL_LABELS.get(row["level"], row["level"]),
            "duration_minutes": row["duration_minutes"], "cover_url": row.get("cover_url"),
            "cover_alt": row.get("cover_alt") or "", "published_at": _iso(row.get("published_at")),
            "lesson_count": int(row.get("lesson_count") or 0), "quiz_count": int(row.get("quiz_count") or 0)}


_COUNTS = ("(SELECT count(*) FROM academy_lessons l JOIN academy_modules m ON m.id = l.module_id AND m.course_id = l.course_id "
           " WHERE l.course_id = c.id AND l.archived_at IS NULL AND m.archived_at IS NULL) AS lesson_count, "
           "(SELECT count(*) FROM academy_quizzes q JOIN academy_modules m ON m.id = q.module_id AND m.course_id = q.course_id "
           " WHERE q.course_id = c.id AND q.archived_at IS NULL AND m.archived_at IS NULL) AS quiz_count")


# ── Catalogue and outline ──────────────────────────────────────────────────
def published_courses() -> List[Dict[str, Any]]:
    rows = execute_query(f"SELECT {COURSE_COLUMNS}, {_COUNTS} FROM academy_courses c WHERE c.status = 'published' "
                         "ORDER BY c.published_at DESC, c.title") or []
    return [course_public(r) for r in rows]


def course_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    if not re.fullmatch(r"[a-z0-9-]{1,80}", slug or ""):
        return None
    return execute_one(f"SELECT {COURSE_COLUMNS}, {_COUNTS} FROM academy_courses c WHERE c.slug = %s", (slug,))


def course_by_id(course_id: str) -> Optional[Dict[str, Any]]:
    return execute_one(f"SELECT {COURSE_COLUMNS}, {_COUNTS} FROM academy_courses c WHERE c.id = %s", (course_id,))


def outline(course_id: str, cur: Any = None) -> List[Dict[str, Any]]:
    """Modules in order, each with its lessons and quizzes in order (archived ones left out)."""
    def run(sql: str, params: Tuple) -> List[Dict[str, Any]]:
        if cur is not None:
            cur.execute(sql, params)
            return list(cur.fetchall() or [])
        return execute_query(sql, params) or []

    modules = run("SELECT id, title, position FROM academy_modules WHERE course_id = %s AND archived_at IS NULL "
                  "ORDER BY position, created_at, id", (course_id,))
    items = run(
        "SELECT 'lesson' AS kind, id, module_id, title, position, minutes, created_at FROM academy_lessons "
        "WHERE course_id = %s AND archived_at IS NULL "
        "UNION ALL SELECT 'quiz' AS kind, id, module_id, title, position, NULL::int AS minutes, created_at "
        "FROM academy_quizzes WHERE course_id = %s AND archived_at IS NULL "
        "ORDER BY position, kind, created_at, id", (course_id, course_id))
    by_module: Dict[str, List[Dict[str, Any]]] = {}
    for it in items:
        by_module.setdefault(str(it["module_id"]), []).append(
            {"kind": it["kind"], "id": str(it["id"]), "title": it["title"],
             **({"minutes": it["minutes"]} if it["kind"] == "lesson" else {})})
    return [{"id": str(m["id"]), "title": m["title"], "items": by_module.get(str(m["id"]), [])} for m in modules]


def flat_items(modules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [it for m in modules for it in m["items"]]


# ── Progress ───────────────────────────────────────────────────────────────
def _done_sets(user_id: str, course_id: str, cur: Any = None) -> Tuple[Dict[str, Any], set]:
    sql_l = "SELECT lesson_id, completed_at FROM academy_lesson_completions WHERE user_id = %s AND course_id = %s"
    sql_q = "SELECT DISTINCT quiz_id FROM academy_quiz_attempts WHERE user_id = %s AND course_id = %s AND passed"
    if cur is not None:
        cur.execute(sql_l, (user_id, course_id))
        lessons = {str(r["lesson_id"]): r["completed_at"] for r in cur.fetchall() or []}
        cur.execute(sql_q, (user_id, course_id))
        quizzes = {str(r["quiz_id"]) for r in cur.fetchall() or []}
        return lessons, quizzes
    lessons = {str(r["lesson_id"]): r["completed_at"] for r in execute_query(sql_l, (user_id, course_id)) or []}
    quizzes = {str(r["quiz_id"]) for r in execute_query(sql_q, (user_id, course_id)) or []}
    return lessons, quizzes


def progress_of(items: List[Dict[str, Any]], lessons_done: Dict[str, Any], quizzes_passed: set) -> Dict[str, Any]:
    done = [it for it in items if (it["id"] in lessons_done if it["kind"] == "lesson" else it["id"] in quizzes_passed)]
    total = len(items)
    nxt = next((it for it in items if it not in done), None)
    return {"done_count": len(done), "total": total,
            "percent": (len(done) * 100 // total) if total else 0,
            "complete": total > 0 and len(done) == total,
            "next": {"kind": nxt["kind"], "id": nxt["id"], "title": nxt["title"]} if nxt else None}


def enrolment(user_id: str, course_id: str) -> Optional[Dict[str, Any]]:
    return execute_one("SELECT enrolled_at FROM academy_enrolments WHERE user_id = %s AND course_id = %s",
                       (user_id, course_id))


def certificate_for(user_id: str, course_id: str) -> Optional[Dict[str, Any]]:
    return execute_one("SELECT code, learner_name, course_title, completed_at, issued_at FROM academy_certificates "
                       "WHERE user_id = %s AND course_id = %s", (user_id, course_id))


def learner_state(user_id: str, course_id: str, modules: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    enrolled = enrolment(user_id, course_id)
    if not enrolled:
        return None
    lessons, quizzes = _done_sets(user_id, course_id)
    items = flat_items(modules)
    state = progress_of(items, lessons, quizzes)
    issued = certificate_for(user_id, course_id)
    state.update(enrolled_at=_iso(enrolled["enrolled_at"]),
                 completed_at=_iso(issued["completed_at"]) if issued else None,
                 certificate_code=issued["code"] if issued else None,
                 done_ids=sorted(set(lessons) | quizzes))
    return state


def enrol(user_id: str, course_id: str) -> bool:
    row = execute_one("INSERT INTO academy_enrolments (user_id, course_id) VALUES (%s, %s) "
                      "ON CONFLICT (user_id, course_id) DO NOTHING RETURNING id", (user_id, course_id))
    return row is not None


def lesson_row(course_id: str, lesson_id: str) -> Optional[Dict[str, Any]]:
    return execute_one(
        "SELECT l.id, l.title, l.body_md, l.video_url, l.minutes FROM academy_lessons l "
        "JOIN academy_modules m ON m.id = l.module_id AND m.course_id = l.course_id "
        "WHERE l.course_id = %s AND l.id = %s AND l.archived_at IS NULL AND m.archived_at IS NULL",
        (course_id, lesson_id))


def lesson_view(row: Dict[str, Any]) -> Dict[str, Any]:
    url = row.get("video_url") if video.is_embed_url(row.get("video_url")) else None
    return {"id": str(row["id"]), "title": row["title"], "minutes": row["minutes"],
            "blocks": markdown.to_blocks(row["body_md"]),
            "video": {"embed_url": url} if url else None}


def _locked_user(cur: Any, user_id: str, course_id: str) -> None:
    """Serialise one person's finishing writes for one course (transaction-scoped)."""
    cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"academy:{user_id}:{course_id}",))


def maybe_issue_certificate(cur: Any, user_id: str, course: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Inside the caller's transaction: issue the certificate if every lesson is done and every quiz passed.
    Returns the new certificate row, or None (not finished, or already issued)."""
    course_id = str(course["id"])
    items = flat_items(outline(course_id, cur))
    lessons, quizzes = _done_sets(user_id, course_id, cur)
    if not progress_of(items, lessons, quizzes)["complete"]:
        return None
    cur.execute("SELECT full_name, email FROM profiles WHERE id = %s", (user_id,))
    person = cur.fetchone() or {}
    cur.execute(
        "INSERT INTO academy_certificates (code, user_id, course_id, learner_name, course_title, completed_at) "
        "VALUES (%s, %s, %s, %s, %s, now()) ON CONFLICT (user_id, course_id) DO NOTHING "
        "RETURNING code, learner_name, course_title, completed_at",
        (cert.new_code(), user_id, course_id, cert.display_name(person.get("full_name")), course["title"]))
    return cur.fetchone()


def complete_lesson(user_id: str, course: Dict[str, Any], lesson_id: str) -> Optional[Dict[str, Any]]:
    """Record the lesson as done (idempotent). Returns a new certificate when this finished the course."""
    with database.get_db() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                _locked_user(cur, user_id, str(course["id"]))
                cur.execute("INSERT INTO academy_lesson_completions (user_id, course_id, lesson_id) VALUES (%s, %s, %s) "
                            "ON CONFLICT (user_id, lesson_id) DO NOTHING", (user_id, str(course["id"]), lesson_id))
                return maybe_issue_certificate(cur, user_id, course)


def quiz_rows(course_id: str, quiz_id: str, *, include_archived: bool = False, cur: Any = None):
    def run(sql, params):
        if cur is not None:
            cur.execute(sql, params)
            return list(cur.fetchall() or [])
        return execute_query(sql, params) or []

    found = run("SELECT q.id, q.title, q.pass_mark, q.position, q.archived_at FROM academy_quizzes q "
                "JOIN academy_modules m ON m.id = q.module_id AND m.course_id = q.course_id "
                "WHERE q.course_id = %s AND q.id = %s" +
                ("" if include_archived else " AND q.archived_at IS NULL AND m.archived_at IS NULL"),
                (course_id, quiz_id))
    if not found:
        return None, [], []
    questions = run("SELECT id, prompt, kind, explanation, position FROM academy_quiz_questions "
                    "WHERE course_id = %s AND quiz_id = %s ORDER BY position, created_at, id", (course_id, quiz_id))
    options = run("SELECT o.id, o.question_id, o.label, o.is_correct, o.position FROM academy_quiz_options o "
                  "JOIN academy_quiz_questions qq ON qq.id = o.question_id AND qq.course_id = o.course_id "
                  "WHERE o.course_id = %s AND qq.quiz_id = %s ORDER BY o.position, o.created_at, o.id",
                  (course_id, quiz_id))
    return found[0], questions, options


def attempts_summary(user_id: str, quiz_id: str) -> Dict[str, Any]:
    row = execute_one("SELECT count(*) AS attempts, max(score_percent) AS best, bool_or(passed) AS passed "
                      "FROM academy_quiz_attempts WHERE user_id = %s AND quiz_id = %s", (user_id, quiz_id)) or {}
    return {"attempts": int(row.get("attempts") or 0), "best_score": row.get("best"), "passed": bool(row.get("passed"))}


def submit_attempt(user_id: str, course: Dict[str, Any], quiz_id: str, answers: Dict[str, List[str]]):
    """Grade on the server and record the attempt. Returns (learner_result, new certificate or None).
    Raises ValueError for answers that do not fit the quiz (nothing recorded)."""
    course_id = str(course["id"])
    with database.get_db() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                _locked_user(cur, user_id, course_id)
                quiz, questions, options = quiz_rows(course_id, quiz_id, cur=cur)
                if quiz is None:
                    raise LookupError("quiz")
                graded = quizmod.grade(questions, options, answers, quiz["pass_mark"])
                cur.execute(
                    "INSERT INTO academy_quiz_attempts (user_id, course_id, quiz_id, answers, correct_count, "
                    "question_count, score_percent, pass_mark, passed) VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s) "
                    "RETURNING id",
                    (user_id, course_id, quiz_id, json.dumps(answers), graded["correct_count"], graded["question_count"],
                     graded["score_percent"], graded["pass_mark"], graded["passed"]))
                attempt_id = str(cur.fetchone()["id"])
                issued = maybe_issue_certificate(cur, user_id, course) if graded["passed"] else None
    return quizmod.learner_result(graded, questions, attempt_id), issued


# ── My learning ────────────────────────────────────────────────────────────
def my_learning(user_id: str) -> Dict[str, Any]:
    """Enrolled courses (with progress), assigned courses from the person's non-deleted organisations, and
    certificates. Assignments of a deleted organisation are left out."""
    enrolled = execute_query(
        f"SELECT {COURSE_COLUMNS}, {_COUNTS}, e.enrolled_at FROM academy_enrolments e "
        "JOIN academy_courses c ON c.id = e.course_id WHERE e.user_id = %s ORDER BY e.enrolled_at DESC",
        (user_id,)) or []
    assigned = execute_query(
        f"SELECT {COURSE_COLUMNS}, {_COUNTS}, a.id AS assignment_id, a.due_on, a.assigned_at, o.id AS org_id, "
        "o.name AS org_name FROM academy_assignments a JOIN academy_courses c ON c.id = a.course_id "
        "JOIN organizations o ON o.id = a.org_id "
        "WHERE a.user_id = %s AND a.removed_at IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM organization_suspensions os WHERE os.org_id = a.org_id AND os.status = 'deleted') "
        "ORDER BY a.due_on NULLS LAST, a.assigned_at", (user_id,)) or []
    certs = execute_query(
        "SELECT ce.code, ce.course_title, ce.completed_at, c.slug FROM academy_certificates ce "
        "JOIN academy_courses c ON c.id = ce.course_id WHERE ce.user_id = %s ORDER BY ce.completed_at DESC",
        (user_id,)) or []
    states: Dict[str, Dict[str, Any]] = {}

    def state(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        cid = str(row["id"])
        if cid not in states:
            states[cid] = learner_state(user_id, cid, outline(cid)) or {}
        return states[cid] or None

    today = datetime.now(timezone.utc).date()
    courses = []
    for row in enrolled:
        st = state(row)
        courses.append({**course_public(row), "available": row["status"] == "published", "progress": st})
    assignments = []
    for row in assigned:
        st = state(row) if any(str(e["id"]) == str(row["id"]) for e in enrolled) else None
        due = row.get("due_on")
        assignments.append({
            "id": str(row["assignment_id"]), "course": course_public(row), "available": row["status"] == "published",
            "org_name": row["org_name"], "due_on": _iso(due), "assigned_at": _iso(row["assigned_at"]),
            "overdue": bool(due and due < today and not (st and st.get("completed_at"))),
            "progress": st})
    return {"courses": courses, "assignments": assignments,
            "certificates": [{"code": c["code"], "course_title": c["course_title"], "course_slug": c["slug"],
                              "completed_on": c["completed_at"].date().isoformat()} for c in certs]}


def certificate_by_code(code: str) -> Optional[Dict[str, Any]]:
    normal = cert.normalise_code(code)
    if not normal:
        return None
    return execute_one("SELECT code, user_id, course_id, learner_name, course_title, completed_at FROM academy_certificates "
                       "WHERE code = %s", (normal,))


# ── Organisation assignments ───────────────────────────────────────────────
def org_overview(org_id: str) -> List[Dict[str, Any]]:
    """Per course with any assignment in this organisation: counts only."""
    rows = execute_query(
        "SELECT c.id, c.slug, c.title, c.status, count(*) AS assigned, "
        "count(ce.user_id) AS completed, "
        "count(*) FILTER (WHERE a.due_on IS NOT NULL AND a.due_on < CURRENT_DATE AND ce.user_id IS NULL) AS overdue "
        "FROM academy_assignments a JOIN academy_courses c ON c.id = a.course_id "
        "LEFT JOIN academy_certificates ce ON ce.user_id = a.user_id AND ce.course_id = a.course_id "
        "WHERE a.org_id = %s AND a.removed_at IS NULL "
        "GROUP BY c.id, c.slug, c.title, c.status ORDER BY c.title", (org_id,)) or []
    return [{"course_id": str(r["id"]), "slug": r["slug"], "title": r["title"], "available": r["status"] == "published",
             "assigned": int(r["assigned"]), "completed": int(r["completed"]), "overdue": int(r["overdue"])}
            for r in rows]


def org_course_detail(org_id: str, course_id: str) -> List[Dict[str, Any]]:
    """This organisation's members assigned to the course, with their progress. Never another organisation's."""
    rows = execute_query(
        "SELECT a.id AS assignment_id, a.user_id, a.due_on, a.assigned_at, p.full_name, p.email, m.role, "
        "ce.completed_at FROM academy_assignments a "
        "JOIN organization_members m ON m.user_id = a.user_id AND m.org_id = a.org_id "
        "JOIN profiles p ON p.id = a.user_id "
        "LEFT JOIN academy_certificates ce ON ce.user_id = a.user_id AND ce.course_id = a.course_id "
        "WHERE a.org_id = %s AND a.course_id = %s AND a.removed_at IS NULL "
        "ORDER BY lower(coalesce(nullif(p.full_name, ''), p.email))", (org_id, course_id)) or []
    items = flat_items(outline(course_id))
    today = datetime.now(timezone.utc).date()
    out = []
    for r in rows:
        lessons, quizzes = _done_sets(str(r["user_id"]), course_id)
        st = progress_of(items, lessons, quizzes)
        out.append({"assignment_id": str(r["assignment_id"]), "user_id": str(r["user_id"]),
                    "name": cert.display_name(r["full_name"]), "email": r["email"], "role": r["role"],
                    "due_on": _iso(r["due_on"]), "assigned_at": _iso(r["assigned_at"]),
                    "percent": 100 if r["completed_at"] else st["percent"],
                    "completed_at": _iso(r["completed_at"]),
                    "overdue": bool(r["due_on"] and r["due_on"] < today and not r["completed_at"])})
    return out


def assign(cur: Any, org_id: str, course_id: str, user_ids: List[str], due_on: Optional[date], by: str) -> List[Dict[str, Any]]:
    """Inside the caller's transaction. Members only (checked here and by the composite foreign key).
    Returns the new assignments; people who already hold an active one are skipped."""
    cur.execute("SELECT user_id FROM organization_members WHERE org_id = %s AND user_id = ANY(%s::uuid[])",
                (org_id, user_ids))
    members = {str(r["user_id"]) for r in cur.fetchall() or []}
    if members != set(user_ids):
        raise ValueError("Every person must be a member of this organisation.")
    created = []
    for uid in user_ids:
        cur.execute("INSERT INTO academy_assignments (org_id, course_id, user_id, assigned_by, due_on) "
                    "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (org_id, course_id, user_id) WHERE removed_at IS NULL "
                    "DO NOTHING RETURNING id, user_id, due_on", (org_id, course_id, uid, by, due_on))
        row = cur.fetchone()
        if row:
            created.append({"id": str(row["id"]), "user_id": str(row["user_id"]), "due_on": _iso(row["due_on"])})
    return created


def assignment(org_id: str, assignment_id: str) -> Optional[Dict[str, Any]]:
    return execute_one("SELECT a.id, a.course_id, a.user_id, a.due_on, a.removed_at, c.title FROM academy_assignments a "
                       "JOIN academy_courses c ON c.id = a.course_id WHERE a.org_id = %s AND a.id = %s",
                       (org_id, assignment_id))


def set_due(org_id: str, assignment_id: str, due_on: Optional[date]) -> bool:
    return execute_one("UPDATE academy_assignments SET due_on = %s WHERE org_id = %s AND id = %s AND removed_at IS NULL "
                       "RETURNING id", (due_on, org_id, assignment_id)) is not None


def unassign(org_id: str, assignment_id: str, by: str) -> bool:
    return execute_one("UPDATE academy_assignments SET removed_at = now(), removed_by = %s "
                       "WHERE org_id = %s AND id = %s AND removed_at IS NULL RETURNING id",
                       (by, org_id, assignment_id)) is not None


def completion_orgs(cur: Any, user_id: str, course_id: str) -> List[Dict[str, Any]]:
    """Organisations to tell about a completion: an active assignment, and the organisation is neither suspended
    (no writes while suspended) nor deleted."""
    cur.execute("SELECT DISTINCT a.org_id FROM academy_assignments a WHERE a.user_id = %s AND a.course_id = %s "
                "AND a.removed_at IS NULL AND NOT EXISTS (SELECT 1 FROM organization_suspensions os "
                "WHERE os.org_id = a.org_id AND os.status IN ('suspended', 'deleted'))", (user_id, course_id))
    return list(cur.fetchall() or [])


DUE_SOON_SQL = """
SELECT a.id, a.org_id, a.user_id, a.due_on, c.title
FROM academy_assignments a JOIN academy_courses c ON c.id = a.course_id
WHERE a.removed_at IS NULL AND a.due_on IS NOT NULL
  AND a.due_on >= %s AND a.due_on <= %s
  AND c.status = 'published'
  AND NOT EXISTS (SELECT 1 FROM academy_certificates ce WHERE ce.user_id = a.user_id AND ce.course_id = a.course_id)
  AND NOT EXISTS (SELECT 1 FROM organization_suspensions os WHERE os.org_id = a.org_id
                  AND os.status IN ('suspended', 'deleted'))
ORDER BY a.due_on, a.id
"""


def due_soon(today: date) -> List[Dict[str, Any]]:
    return execute_query(DUE_SOON_SQL, (today, today + timedelta(days=DUE_SOON_DAYS))) or []


# ── Completion evidence for the Compliance page ────────────────────────────
TRAINING_REQUIREMENT = "gaid.training.in_place"
EVIDENCE_LABEL = "Cyphward Academy records"
EVIDENCE_SQL = """
SELECT c.id, c.title, count(*) AS assigned,
       count(ce.user_id) FILTER (WHERE ce.completed_at > %s - make_interval(months => %s)) AS completed
FROM academy_assignments a
JOIN organization_members m ON m.user_id = a.user_id AND m.org_id = a.org_id
JOIN academy_courses c ON c.id = a.course_id
LEFT JOIN academy_certificates ce ON ce.user_id = a.user_id AND ce.course_id = a.course_id
WHERE a.org_id = %s AND a.removed_at IS NULL
GROUP BY c.id, c.title
ORDER BY c.title
"""


def evidence_line(completed: int, assigned: int, title: str, months: int = EVIDENCE_WINDOW_MONTHS) -> str:
    who = "assigned member" if assigned == 1 else "assigned members"
    return f"{completed} of {assigned} {who} completed {title} in the last {months} months"


def training_records(org_id: str, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """What the training requirement shows from Academy records: one line per assigned course. Informational: it
    never changes the requirement's status or the readiness counts."""
    now = now or datetime.now(timezone.utc)
    rows = execute_query(EVIDENCE_SQL, (now, EVIDENCE_WINDOW_MONTHS, org_id)) or []
    return [{"source": "tool_observed", "source_label": "Tool observed", "label": EVIDENCE_LABEL,
             "course_id": str(r["id"]), "course_title": r["title"], "assigned": int(r["assigned"]),
             "completed": int(r["completed"]), "window_months": EVIDENCE_WINDOW_MONTHS, "as_of": _iso(now),
             "text": evidence_line(int(r["completed"]), int(r["assigned"]), r["title"])} for r in rows]

