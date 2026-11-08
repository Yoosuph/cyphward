"""Quiz serialisers and the server-side grader.

Two serialisers, never one with a flag: `learner_quiz` builds the learner's payload from a fixed key list and has no
way to include `is_correct` or the explanations; `owner_quiz` is used only by the owner console.

Grading (`grade`): a question is correct only when the chosen option ids equal the set of correct option ids exactly.
An unanswered question counts as wrong. Ids that do not belong to the question, or more than one choice on a
single-choice question, are refused (ValueError -> 422) and nothing is recorded. score = floor(correct * 100 / total),
so a score never rounds up past the pass mark.

What a learner sees after submitting: the score, pass or not, and which questions were right. The correct options are
never sent. Explanations are sent only once the attempt passed, so a failed attempt plus a retry does not reveal the
answers.
"""
from typing import Any, Dict, Iterable, List, Mapping, Optional

LEARNER_QUESTION_KEYS = ("id", "prompt", "kind", "options")
LEARNER_OPTION_KEYS = ("id", "label")
LEARNER_QUIZ_KEYS = ("id", "title", "pass_mark", "question_count", "questions")


def learner_quiz(quiz: Mapping[str, Any], questions: Iterable[Mapping[str, Any]],
                 options: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    by_question: Dict[str, List[Dict[str, Any]]] = {}
    for o in options:
        by_question.setdefault(str(o["question_id"]), []).append({"id": str(o["id"]), "label": o["label"]})
    qs = [{"id": str(q["id"]), "prompt": q["prompt"], "kind": q["kind"], "options": by_question.get(str(q["id"]), [])}
          for q in questions]
    return {"id": str(quiz["id"]), "title": quiz["title"], "pass_mark": int(quiz["pass_mark"]),
            "question_count": len(qs), "questions": qs}


def owner_quiz(quiz: Mapping[str, Any], questions: Iterable[Mapping[str, Any]],
               options: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    by_question: Dict[str, List[Dict[str, Any]]] = {}
    for o in options:
        by_question.setdefault(str(o["question_id"]), []).append(
            {"id": str(o["id"]), "label": o["label"], "is_correct": bool(o["is_correct"]), "position": o["position"]})
    return {"id": str(quiz["id"]), "title": quiz["title"], "pass_mark": int(quiz["pass_mark"]),
            "position": quiz["position"], "archived": quiz.get("archived_at") is not None,
            "questions": [{"id": str(q["id"]), "prompt": q["prompt"], "kind": q["kind"],
                           "explanation": q.get("explanation") or "", "position": q["position"],
                           "options": by_question.get(str(q["id"]), [])} for q in questions]}


def normalise_answers(raw: Any) -> Dict[str, List[str]]:
    """{question_id: [option_id, ...]} with string ids, de-duplicated. Anything else is refused."""
    if not isinstance(raw, dict) or len(raw) > 200:
        raise ValueError("Answers must map each question to the options you chose.")
    out: Dict[str, List[str]] = {}
    for key, value in raw.items():
        chosen = value if isinstance(value, list) else [value] if isinstance(value, str) else None
        if chosen is None or len(chosen) > 50 or not all(isinstance(c, str) and 0 < len(c) <= 64 for c in chosen):
            raise ValueError("Answers must map each question to the options you chose.")
        out[str(key)] = sorted(set(chosen))
    return out


def grade(questions: Iterable[Mapping[str, Any]], options: Iterable[Mapping[str, Any]], answers: Mapping[str, List[str]],
          pass_mark: int) -> Dict[str, Any]:
    qs = list(questions)
    option_question: Dict[str, str] = {}
    correct: Dict[str, set] = {str(q["id"]): set() for q in qs}
    for o in options:
        option_question[str(o["id"])] = str(o["question_id"])
        if o["is_correct"]:
            correct.setdefault(str(o["question_id"]), set()).add(str(o["id"]))
    known = {str(q["id"]): q for q in qs}
    for qid, chosen in answers.items():
        if qid not in known:
            raise ValueError("One of the answers is for a question that is not in this quiz.")
        if any(option_question.get(c) != qid for c in chosen):
            raise ValueError("One of the answers is not an option of its question.")
        if known[qid]["kind"] == "single" and len(chosen) > 1:
            raise ValueError("Choose one option for a single-choice question.")
    results = []
    right = 0
    for q in qs:
        qid = str(q["id"])
        ok = bool(answers.get(qid)) and set(answers[qid]) == correct.get(qid, set())
        right += ok
        results.append({"question_id": qid, "correct": ok})
    total = len(qs)
    score = (right * 100) // total if total else 0
    return {"correct_count": right, "question_count": total, "score_percent": score, "pass_mark": int(pass_mark),
            "passed": total > 0 and score >= int(pass_mark), "results": results}


def learner_result(graded: Mapping[str, Any], questions: Iterable[Mapping[str, Any]],
                   attempt_id: Optional[str] = None) -> Dict[str, Any]:
    """What the learner gets back from a submission: never the correct options; explanations only when passed."""
    explanations = {str(q["id"]): q.get("explanation") or "" for q in questions}
    passed = bool(graded["passed"])
    return {
        "attempt_id": attempt_id, "score_percent": graded["score_percent"], "pass_mark": graded["pass_mark"],
        "passed": passed, "correct_count": graded["correct_count"], "question_count": graded["question_count"],
        "results": [{"question_id": r["question_id"], "correct": r["correct"],
                     **({"explanation": explanations.get(r["question_id"], "")} if passed else {})}
                    for r in graded["results"]],
    }


def publish_problems(quiz: Mapping[str, Any]) -> List[str]:
    """Why a quiz (owner_quiz shape) cannot be published yet, in plain words. Empty when it can."""
    problems = []
    if not quiz["questions"]:
        problems.append(f"The quiz “{quiz['title']}” has no questions.")
    for n, q in enumerate(quiz["questions"], 1):
        right = sum(1 for o in q["options"] if o["is_correct"])
        if len(q["options"]) < 2:
            problems.append(f"Question {n} of “{quiz['title']}” needs at least two options.")
        if right == 0:
            problems.append(f"Question {n} of “{quiz['title']}” has no correct option.")
        if q["kind"] == "single" and right > 1:
            problems.append(f"Question {n} of “{quiz['title']}” is single choice but has more than one correct option.")
    return problems
