"""Owner console course builder: the writes behind /api/v1/owner/academy (api/owner_academy.py).

Every function runs inside the caller's transaction (`cur`), which also writes the owner_audit row, and returns
{"result": ..., "audit": {...}} or raises HTTPException to refuse.

Rules:
  * Publishing needs the course title typed exactly (as stored) and a complete course: at least one lesson, and every
    quiz has questions, each with two or more options and the right number of correct ones.
  * Unpublishing keeps every learner record. Learners cannot open its lessons until it is published again.
  * Removing a module, lesson or quiz that has learner records archives it (hidden from the outline, history kept);
    otherwise it is deleted. A course can be deleted only while it is a draft with no enrolment and no assignment.
  * Lesson bodies are stored as written (Markdown) and rendered as sanitised blocks on read; a video link must be from
    an allow-listed provider and is stored as the embed URL built from its id (academy/video.py).
"""
import re
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from backend.app.academy import markdown, quiz as quizmod, store, video

TITLE_MISMATCH = "The title you typed does not match this course. Nothing was changed."
NOT_FOUND = "Not found."


def _one(cur, sql: str, params) -> Optional[Dict[str, Any]]:
    cur.execute(sql, params)
    return cur.fetchone()


def _all(cur, sql: str, params) -> List[Dict[str, Any]]:
    cur.execute(sql, params)
    return list(cur.fetchall() or [])


def lock_course(cur, course_id: str) -> Dict[str, Any]:
    row = _one(cur, "SELECT id, slug, title, status, published_at FROM academy_courses WHERE id = %s FOR UPDATE",
               (course_id,))
    if not row:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return row


def slug_for(cur, title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60].strip("-") or "course"
    slug, n = base, 2
    while _one(cur, "SELECT 1 AS taken FROM academy_courses WHERE slug = %s", (slug,)):
        slug, n = f"{base}-{n}", n + 1
    return slug


def _next_position(cur, sql: str, params) -> int:
    row = _one(cur, sql, params) or {}
    return int(row.get("n") if row.get("n") is not None else -1) + 1


# ── Courses ────────────────────────────────────────────────────────────────
COURSE_FIELDS = ("title", "summary", "level", "duration_minutes", "cover_url", "cover_alt")


def create_course(cur, fields: Dict[str, Any]) -> Dict[str, Any]:
    slug = slug_for(cur, fields["title"])
    row = _one(cur, "INSERT INTO academy_courses (slug, title, summary, level, duration_minutes, cover_url, cover_alt) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id, slug",
               (slug, fields["title"], fields.get("summary") or "", fields.get("level") or "beginner",
                fields.get("duration_minutes") or 30, fields.get("cover_url"), fields.get("cover_alt") or ""))
    return {"result": {"id": str(row["id"]), "slug": row["slug"]}, "audit": {"title": fields["title"], "slug": slug}}


def update_course(cur, course_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    lock_course(cur, course_id)
    changes = {k: v for k, v in fields.items() if k in COURSE_FIELDS}
    if not changes:
        raise HTTPException(status_code=422, detail="Nothing to change.")
    sets = ", ".join(f"{k} = %s" for k in changes) + ", updated_at = now()"
    cur.execute(f"UPDATE academy_courses SET {sets} WHERE id = %s RETURNING id", (*changes.values(), course_id))
    return {"result": {"id": course_id}, "audit": {"changed": sorted(changes)}}


def publish_problems(cur, course_id: str) -> List[str]:
    modules = store.outline(course_id, cur)
    items = store.flat_items(modules)
    problems = []
    if not any(it["kind"] == "lesson" for it in items):
        problems.append("Add at least one lesson before publishing.")
    for it in items:
        if it["kind"] == "quiz":
            q, questions, options = store.quiz_rows(course_id, it["id"], cur=cur)
            problems += quizmod.publish_problems(quizmod.owner_quiz(q, questions, options))
    for m in modules:
        if not m["items"]:
            problems.append(f"The module “{m['title']}” is empty. Add a lesson or remove the module.")
    return problems


def publish(cur, course_id: str, typed_title: str) -> Dict[str, Any]:
    course = lock_course(cur, course_id)
    if typed_title != course["title"]:
        raise HTTPException(status_code=409, detail=TITLE_MISMATCH)
    if course["status"] == "published":
        raise HTTPException(status_code=409, detail="This course is already published.")
    problems = publish_problems(cur, course_id)
    if problems:
        raise HTTPException(status_code=409, detail={"code": "not_ready", "message": "This course is not ready to publish.",
                                                     "problems": problems[:20]})
    cur.execute("UPDATE academy_courses SET status = 'published', published_at = now(), updated_at = now() "
                "WHERE id = %s RETURNING published_at", (course_id,))
    when = cur.fetchone()["published_at"]
    return {"result": {"id": course_id, "status": "published", "published_at": when.isoformat()},
            "audit": {"from": course["status"], "to": "published", "title": course["title"]}}


def unpublish(cur, course_id: str) -> Dict[str, Any]:
    course = lock_course(cur, course_id)
    if course["status"] != "published":
        raise HTTPException(status_code=409, detail="This course is not published.")
    cur.execute("UPDATE academy_courses SET status = 'draft', published_at = NULL, updated_at = now() WHERE id = %s "
                "RETURNING id", (course_id,))
    kept = _one(cur, "SELECT count(*) AS n FROM academy_enrolments WHERE course_id = %s", (course_id,))["n"]
    return {"result": {"id": course_id, "status": "draft", "enrolments_kept": int(kept)},
            "audit": {"from": "published", "to": "draft", "enrolments_kept": int(kept)}}


def delete_course(cur, course_id: str, typed_title: str) -> Dict[str, Any]:
    course = lock_course(cur, course_id)
    if typed_title != course["title"]:
        raise HTTPException(status_code=409, detail=TITLE_MISMATCH)
    if course["status"] != "draft":
        raise HTTPException(status_code=409, detail="Unpublish the course before deleting it.")
    used = _one(cur, "SELECT (SELECT count(*) FROM academy_enrolments WHERE course_id = %s) "
                     "+ (SELECT count(*) FROM academy_assignments WHERE course_id = %s) AS n", (course_id, course_id))
    if int(used["n"]):
        raise HTTPException(status_code=409, detail="People have started or been assigned this course, so it cannot "
                                                    "be deleted. Keep it as a draft instead.")
    cur.execute("DELETE FROM academy_courses WHERE id = %s RETURNING id", (course_id,))
    return {"result": {"id": course_id, "deleted": True}, "audit": {"title": course["title"]}}


# ── Modules ────────────────────────────────────────────────────────────────
def _module(cur, module_id: str) -> Dict[str, Any]:
    row = _one(cur, "SELECT id, course_id, title FROM academy_modules WHERE id = %s AND archived_at IS NULL", (module_id,))
    if not row:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    lock_course(cur, str(row["course_id"]))
    return row


def create_module(cur, course_id: str, title: str) -> Dict[str, Any]:
    lock_course(cur, course_id)
    pos = _next_position(cur, "SELECT max(position) AS n FROM academy_modules WHERE course_id = %s", (course_id,))
    row = _one(cur, "INSERT INTO academy_modules (course_id, position, title) VALUES (%s, %s, %s) RETURNING id",
               (course_id, pos, title))
    return {"result": {"id": str(row["id"])}, "audit": {"course_id": course_id, "title": title}}


def update_module(cur, module_id: str, title: str) -> Dict[str, Any]:
    m = _module(cur, module_id)
    cur.execute("UPDATE academy_modules SET title = %s, updated_at = now() WHERE id = %s RETURNING id", (title, module_id))
    return {"result": {"id": module_id}, "audit": {"course_id": str(m["course_id"]), "from": m["title"], "to": title}}


def _history(cur, course_id: str, lesson_ids: List[str], quiz_ids: List[str]) -> int:
    row = _one(cur, "SELECT (SELECT count(*) FROM academy_lesson_completions WHERE course_id = %s AND lesson_id = ANY(%s::uuid[])) "
                    "+ (SELECT count(*) FROM academy_quiz_attempts WHERE course_id = %s AND quiz_id = ANY(%s::uuid[])) AS n",
               (course_id, lesson_ids, course_id, quiz_ids))
    return int(row["n"])


def remove_module(cur, module_id: str) -> Dict[str, Any]:
    m = _module(cur, module_id)
    cid = str(m["course_id"])
    lessons = [str(r["id"]) for r in _all(cur, "SELECT id FROM academy_lessons WHERE course_id = %s AND module_id = %s", (cid, module_id))]
    quizzes = [str(r["id"]) for r in _all(cur, "SELECT id FROM academy_quizzes WHERE course_id = %s AND module_id = %s", (cid, module_id))]
    if _history(cur, cid, lessons, quizzes):
        cur.execute("UPDATE academy_modules SET archived_at = now(), updated_at = now() WHERE id = %s RETURNING id", (module_id,))
        outcome = "archived"
    else:
        cur.execute("DELETE FROM academy_modules WHERE id = %s RETURNING id", (module_id,))
        outcome = "deleted"
    return {"result": {"id": module_id, "outcome": outcome}, "audit": {"course_id": cid, "title": m["title"], "outcome": outcome}}


# ── Lessons ────────────────────────────────────────────────────────────────
def clean_lesson(fields: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    if "title" in fields:
        out["title"] = fields["title"]
    if "body_md" in fields:
        out["body_md"] = markdown.clean(fields["body_md"])
    if "minutes" in fields:
        out["minutes"] = fields["minutes"]
    if "video_url" in fields:
        try:
            out["video_url"] = video.embed_url(fields["video_url"])
        except ValueError as refused:
            raise HTTPException(status_code=422, detail=str(refused))
    return out


def _lesson(cur, lesson_id: str) -> Dict[str, Any]:
    row = _one(cur, "SELECT id, course_id, module_id, title FROM academy_lessons WHERE id = %s AND archived_at IS NULL",
               (lesson_id,))
    if not row:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    lock_course(cur, str(row["course_id"]))
    return row


def create_lesson(cur, module_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    m = _module(cur, module_id)
    data = clean_lesson(fields)
    pos = _next_position(cur, "SELECT max(position) AS n FROM (SELECT position FROM academy_lessons WHERE module_id = %s "
                              "UNION ALL SELECT position FROM academy_quizzes WHERE module_id = %s) x", (module_id, module_id))
    row = _one(cur, "INSERT INTO academy_lessons (course_id, module_id, position, title, body_md, video_url, minutes) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
               (m["course_id"], module_id, pos, data["title"], data.get("body_md", ""), data.get("video_url"),
                data.get("minutes") or 5))
    return {"result": {"id": str(row["id"]), "video_url": data.get("video_url")},
            "audit": {"course_id": str(m["course_id"]), "title": data["title"]}}


def update_lesson(cur, lesson_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    lesson = _lesson(cur, lesson_id)
    data = clean_lesson(fields)
    if not data:
        raise HTTPException(status_code=422, detail="Nothing to change.")
    sets = ", ".join(f"{k} = %s" for k in data) + ", updated_at = now()"
    cur.execute(f"UPDATE academy_lessons SET {sets} WHERE id = %s RETURNING id, body_md, video_url",
                (*data.values(), lesson_id))
    row = cur.fetchone()
    return {"result": {"id": lesson_id, "blocks": markdown.to_blocks(row["body_md"]), "video_url": row["video_url"]},
            "audit": {"course_id": str(lesson["course_id"]), "changed": sorted(data)}}


def remove_lesson(cur, lesson_id: str) -> Dict[str, Any]:
    lesson = _lesson(cur, lesson_id)
    cid = str(lesson["course_id"])
    if _history(cur, cid, [lesson_id], []):
        cur.execute("UPDATE academy_lessons SET archived_at = now(), updated_at = now() WHERE id = %s RETURNING id", (lesson_id,))
        outcome = "archived"
    else:
        cur.execute("DELETE FROM academy_lessons WHERE id = %s RETURNING id", (lesson_id,))
        outcome = "deleted"
    return {"result": {"id": lesson_id, "outcome": outcome}, "audit": {"course_id": cid, "title": lesson["title"], "outcome": outcome}}


# ── Quizzes ────────────────────────────────────────────────────────────────
def _quiz(cur, quiz_id: str) -> Dict[str, Any]:
    row = _one(cur, "SELECT id, course_id, module_id, title FROM academy_quizzes WHERE id = %s AND archived_at IS NULL",
               (quiz_id,))
    if not row:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    lock_course(cur, str(row["course_id"]))
    return row


def create_quiz(cur, module_id: str, title: str, pass_mark: int) -> Dict[str, Any]:
    m = _module(cur, module_id)
    pos = _next_position(cur, "SELECT max(position) AS n FROM (SELECT position FROM academy_lessons WHERE module_id = %s "
                              "UNION ALL SELECT position FROM academy_quizzes WHERE module_id = %s) x", (module_id, module_id))
    row = _one(cur, "INSERT INTO academy_quizzes (course_id, module_id, position, title, pass_mark) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING id", (m["course_id"], module_id, pos, title, pass_mark))
    return {"result": {"id": str(row["id"])}, "audit": {"course_id": str(m["course_id"]), "title": title}}


def save_quiz(cur, quiz_id: str, title: str, pass_mark: int, questions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Replace the quiz's questions with `questions` (ids kept where given, so attempts keep pointing at them)."""
    q = _quiz(cur, quiz_id)
    cid = str(q["course_id"])
    cur.execute("UPDATE academy_quizzes SET title = %s, pass_mark = %s, updated_at = now() WHERE id = %s RETURNING id",
                (title, pass_mark, quiz_id))
    existing_q = {str(r["id"]) for r in _all(cur, "SELECT id FROM academy_quiz_questions WHERE course_id = %s AND quiz_id = %s", (cid, quiz_id))}
    kept_q = set()
    for qpos, question in enumerate(questions):
        qid = question.get("id")
        if qid and qid in existing_q:
            cur.execute("UPDATE academy_quiz_questions SET position = %s, prompt = %s, kind = %s, explanation = %s "
                        "WHERE id = %s RETURNING id", (qpos, question["prompt"], question["kind"],
                                                        question.get("explanation") or "", qid))
        else:
            qid = str(_one(cur, "INSERT INTO academy_quiz_questions (course_id, quiz_id, position, prompt, kind, explanation) "
                                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                           (cid, quiz_id, qpos, question["prompt"], question["kind"], question.get("explanation") or ""))["id"])
        kept_q.add(qid)
        existing_o = {str(r["id"]) for r in _all(cur, "SELECT id FROM academy_quiz_options WHERE course_id = %s AND question_id = %s", (cid, qid))}
        kept_o = set()
        for opos, option in enumerate(question["options"]):
            oid = option.get("id")
            if oid and oid in existing_o:
                cur.execute("UPDATE academy_quiz_options SET position = %s, label = %s, is_correct = %s WHERE id = %s RETURNING id",
                            (opos, option["label"], bool(option["is_correct"]), oid))
            else:
                oid = str(_one(cur, "INSERT INTO academy_quiz_options (course_id, question_id, position, label, is_correct) "
                                    "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                               (cid, qid, opos, option["label"], bool(option["is_correct"])))["id"])
            kept_o.add(oid)
        gone = sorted(existing_o - kept_o)
        if gone:
            cur.execute("DELETE FROM academy_quiz_options WHERE course_id = %s AND id = ANY(%s::uuid[])", (cid, gone))
    gone_q = sorted(existing_q - kept_q)
    if gone_q:
        cur.execute("DELETE FROM academy_quiz_questions WHERE course_id = %s AND id = ANY(%s::uuid[])", (cid, gone_q))
    found, qs, opts = store.quiz_rows(cid, quiz_id, cur=cur)
    return {"result": quizmod.owner_quiz(found, qs, opts),
            "audit": {"course_id": cid, "questions": len(questions), "removed_questions": len(gone_q)}}


def remove_quiz(cur, quiz_id: str) -> Dict[str, Any]:
    q = _quiz(cur, quiz_id)
    cid = str(q["course_id"])
    if _history(cur, cid, [], [quiz_id]):
        cur.execute("UPDATE academy_quizzes SET archived_at = now(), updated_at = now() WHERE id = %s RETURNING id", (quiz_id,))
        outcome = "archived"
    else:
        cur.execute("DELETE FROM academy_quizzes WHERE id = %s RETURNING id", (quiz_id,))
        outcome = "deleted"
    return {"result": {"id": quiz_id, "outcome": outcome}, "audit": {"course_id": cid, "title": q["title"], "outcome": outcome}}


# ── Reorder ────────────────────────────────────────────────────────────────
def reorder(cur, course_id: str, modules: List[Dict[str, Any]]) -> Dict[str, Any]:
    """`modules` lists every current module of the course in the new order, each with every one of its items
    ({kind, id}) in the new order. Items stay in their own module. Anything missing, extra or moved is refused."""
    lock_course(cur, course_id)
    current = store.outline(course_id, cur)
    want_modules = [str(m["id"]) for m in modules]
    have_modules = [m["id"] for m in current]
    want_items = sorted((it["kind"], str(it["id"])) for m in modules for it in m["items"])
    have_items = sorted((it["kind"], it["id"]) for it in store.flat_items(current))
    if sorted(want_modules) != sorted(have_modules) or len(set(want_modules)) != len(want_modules) or want_items != have_items:
        raise HTTPException(status_code=409, detail="The course changed while you were reordering. Reload and try again.")
    for mpos, m in enumerate(modules):
        cur.execute("UPDATE academy_modules SET position = %s, updated_at = now() WHERE course_id = %s AND id = %s RETURNING id",
                    (mpos, course_id, str(m["id"])))
        for ipos, it in enumerate(m["items"]):
            table = "academy_lessons" if it["kind"] == "lesson" else "academy_quizzes"
            cur.execute(f"UPDATE {table} SET position = %s, updated_at = now() WHERE course_id = %s AND id = %s "
                        "AND module_id = %s RETURNING id", (ipos, course_id, str(it["id"]), str(m["id"])))
            if cur.fetchone() is None:
                raise HTTPException(status_code=409, detail="Items can be reordered within their own module only.")
    return {"result": {"id": course_id, "outline": store.outline(course_id, cur)},
            "audit": {"modules": len(modules), "items": len(want_items)}}


# ── Reads ──────────────────────────────────────────────────────────────────
def course_list() -> List[Dict[str, Any]]:
    rows = store.execute_query(
        f"SELECT {store.COURSE_COLUMNS}, {store._COUNTS}, "
        "(SELECT count(*) FROM academy_enrolments e WHERE e.course_id = c.id) AS enrolled, "
        "(SELECT count(*) FROM academy_certificates ce WHERE ce.course_id = c.id) AS completed, "
        "(SELECT count(*) FROM academy_assignments a WHERE a.course_id = c.id AND a.removed_at IS NULL) AS assigned "
        "FROM academy_courses c ORDER BY c.updated_at DESC, c.title") or []
    return [{**store.course_public(r), "status": r["status"], "updated_at": store._iso(r["updated_at"]),
             "enrolled": int(r["enrolled"]), "completed": int(r["completed"]), "assigned": int(r["assigned"])}
            for r in rows]


def course_tree(course_id: str) -> Optional[Dict[str, Any]]:
    course = store.course_by_id(course_id)
    if not course:
        return None
    modules = store.execute_query("SELECT id, title, position FROM academy_modules WHERE course_id = %s AND archived_at IS NULL "
                                  "ORDER BY position, created_at, id", (course_id,)) or []
    lessons = store.execute_query("SELECT id, module_id, title, body_md, video_url, minutes, position FROM academy_lessons "
                                  "WHERE course_id = %s AND archived_at IS NULL ORDER BY position, created_at, id", (course_id,)) or []
    quizzes = store.execute_query("SELECT id, module_id FROM academy_quizzes WHERE course_id = %s AND archived_at IS NULL "
                                  "ORDER BY position, created_at, id", (course_id,)) or []
    order = {it["id"]: n for n, it in enumerate(store.flat_items(store.outline(course_id)))}
    out_modules = []
    for m in modules:
        items = []
        for l in lessons:
            if l["module_id"] == m["id"]:
                items.append({"kind": "lesson", "id": str(l["id"]), "title": l["title"], "body_md": l["body_md"],
                              "video_url": l["video_url"], "minutes": l["minutes"], "position": l["position"]})
        for q in quizzes:
            if q["module_id"] == m["id"]:
                found, qs, opts = store.quiz_rows(course_id, str(q["id"]))
                items.append({"kind": "quiz", **quizmod.owner_quiz(found, qs, opts)})
        items.sort(key=lambda it: order.get(it["id"], 10 ** 6))
        out_modules.append({"id": str(m["id"]), "title": m["title"], "items": items})
    return {"course": {**store.course_public(course), "status": course["status"],
                       "updated_at": store._iso(course["updated_at"])},
            "modules": out_modules, "video_providers": list(video.PROVIDERS)}


def analytics(course_id: str) -> Dict[str, Any]:
    row = store.execute_one(
        "SELECT (SELECT count(*) FROM academy_enrolments WHERE course_id = %(c)s) AS enrolled, "
        "(SELECT count(*) FROM academy_certificates WHERE course_id = %(c)s) AS completed, "
        "(SELECT count(*) FROM academy_assignments WHERE course_id = %(c)s AND removed_at IS NULL) AS assigned, "
        "(SELECT count(DISTINCT org_id) FROM academy_assignments WHERE course_id = %(c)s AND removed_at IS NULL) AS organisations, "
        "(SELECT count(*) FROM academy_quiz_attempts WHERE course_id = %(c)s) AS attempts, "
        "(SELECT count(*) FROM academy_quiz_attempts WHERE course_id = %(c)s AND passed) AS attempts_passed",
        {"c": course_id}) or {}
    enrolled, completed = int(row.get("enrolled") or 0), int(row.get("completed") or 0)
    return {"enrolled": enrolled, "completed": completed, "in_progress": enrolled - completed,
            "assigned": int(row.get("assigned") or 0), "organisations": int(row.get("organisations") or 0),
            "quiz_attempts": int(row.get("attempts") or 0), "quiz_attempts_passed": int(row.get("attempts_passed") or 0)}


def learners(course_id: str, limit: int = 200, offset: int = 0) -> Dict[str, Any]:
    rows = store.execute_query(
        "SELECT e.user_id, e.enrolled_at, p.full_name, p.email, ce.completed_at, "
        "(SELECT count(*) FROM academy_lesson_completions lc WHERE lc.user_id = e.user_id AND lc.course_id = e.course_id) AS lessons_done, "
        "(SELECT count(DISTINCT quiz_id) FROM academy_quiz_attempts qa WHERE qa.user_id = e.user_id AND qa.course_id = e.course_id AND qa.passed) AS quizzes_passed "
        "FROM academy_enrolments e JOIN profiles p ON p.id = e.user_id "
        "LEFT JOIN academy_certificates ce ON ce.user_id = e.user_id AND ce.course_id = e.course_id "
        "WHERE e.course_id = %s ORDER BY e.enrolled_at DESC LIMIT %s OFFSET %s", (course_id, limit, offset)) or []
    total = (store.execute_one("SELECT count(*) AS n FROM academy_enrolments WHERE course_id = %s", (course_id,)) or {}).get("n", 0)
    return {"total": int(total), "items": [{
        "user_id": str(r["user_id"]), "name": r["full_name"] or "", "email": r["email"],
        "enrolled_at": store._iso(r["enrolled_at"]), "completed_at": store._iso(r["completed_at"]),
        "lessons_done": int(r["lessons_done"]), "quizzes_passed": int(r["quizzes_passed"])} for r in rows]}
