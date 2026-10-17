"""Breach incident log: the 72-hour deadline, time zones and copy (packet C3b). No database needed."""
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.compliance import incidents as inc
from backend.app.compliance import reminders

UTC = timezone.utc
AWARE = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
DEADLINE = AWARE + timedelta(hours=72)
BANNED = ("compliant", "certified", "satisfies", "satisfied", "passes audit", "pass the audit",
          "compliance score", "fully meets", "meets the requirement", "is met", "guarantee")


def state(now, notified=None, aware=AWARE):
    return inc.deadline_state({"became_aware_at": aware, "notified_commission_at": notified}, now)


# ── The 72-hour edges ────────────────────────────────────────────────────


def test_deadline_is_exactly_72_hours_after_awareness():
    assert inc.deadline_for(AWARE) == DEADLINE
    assert state(AWARE)["hours_remaining"] == 72.0


def test_exactly_72_hours_is_not_yet_overdue():
    s = state(DEADLINE)
    assert s["overdue"] is False and s["hours_remaining"] == 0.0 and s["commission_state"] == "pending"


def test_one_minute_before_is_pending_and_one_minute_after_is_overdue():
    before, after = state(DEADLINE - timedelta(minutes=1)), state(DEADLINE + timedelta(minutes=1))
    assert before["overdue"] is False and before["hours_remaining"] == pytest.approx(1 / 60, abs=0.01)
    assert after["overdue"] is True and after["hours_remaining"] == 0.0 and after["commission_state"] == "overdue"


def test_notified_before_the_deadline_is_never_overdue_whenever_read():
    notified = DEADLINE - timedelta(minutes=1)
    for now in (notified, DEADLINE, DEADLINE + timedelta(days=400)):
        s = state(now, notified)
        assert s["overdue"] is False and s["notified_late"] is False
        assert s["commission_state"] == "notified_on_time" and s["hours_remaining"] is None


def test_notified_exactly_at_the_deadline_is_on_time():
    assert state(DEADLINE + timedelta(days=1), DEADLINE)["commission_state"] == "notified_on_time"


def test_notified_after_the_deadline_is_shown_as_notified_late_not_overdue():
    s = state(DEADLINE + timedelta(days=5), DEADLINE + timedelta(minutes=1))
    assert s["notified_late"] is True and s["overdue"] is False and s["commission_state"] == "notified_late"
    assert s["notified_after_hours"] == pytest.approx(72 + 1 / 60, abs=0.01)


def test_the_deadline_is_hours_not_wall_clock_across_a_clock_change():
    # New York clocks went forward on 8 March 2026: 72 real hours is 13:00 local, not 12:00.
    aware = inc.to_utc(datetime(2026, 3, 7, 12, 0), "America/New_York")
    local = inc.public({"id": "x", "title": "t", "severity": "low", "status": "open", "created_at": aware,
                        "updated_at": aware, "detected_at": aware, "became_aware_at": aware,
                        "notified_commission_at": None, "notified_subjects_at": None},
                       "America/New_York", aware)
    assert local["deadline_at"] == "2026-03-10T17:00:00+00:00"
    assert local["local"]["deadline_at"] == "2026-03-10T13:00:00-04:00"


# ── Time zones ───────────────────────────────────────────────────────────


def test_a_time_without_an_offset_near_midnight_in_lagos_is_stored_as_utc():
    late = inc.to_utc(datetime(2026, 10, 17, 23, 30), "Africa/Lagos")
    early = inc.to_utc(datetime(2026, 10, 18, 0, 30), "Africa/Lagos")
    assert late == datetime(2026, 10, 17, 22, 30, tzinfo=UTC)
    assert early == datetime(2026, 10, 17, 23, 30, tzinfo=UTC)  # a different UTC date than the Lagos date
    assert late.tzinfo is UTC or late.utcoffset() == timedelta(0)


def test_an_explicit_offset_wins_over_the_display_zone():
    assert inc.to_utc(datetime(2026, 10, 17, 23, 30, tzinfo=timezone(timedelta(hours=-5))), "Africa/Lagos") == \
        datetime(2026, 10, 18, 4, 30, tzinfo=UTC)


def test_display_shows_the_organisation_zone_while_the_deadline_stays_utc():
    aware = inc.to_utc(datetime(2026, 10, 17, 23, 30), "Africa/Lagos")
    row = {"id": "x", "title": "t", "severity": "low", "status": "open", "created_at": aware, "updated_at": aware,
           "detected_at": aware, "became_aware_at": aware, "notified_commission_at": None,
           "notified_subjects_at": None}
    out = inc.public(row, "Africa/Lagos", aware)
    assert out["became_aware_at"] == "2026-10-17T22:30:00+00:00"
    assert out["local"]["became_aware_at"] == "2026-10-17T23:30:00+01:00"
    assert out["deadline_at"] == "2026-10-20T22:30:00+00:00"
    assert out["local"]["deadline_at"] == "2026-10-20T23:30:00+01:00"
    assert out["display_timezone"] == "Africa/Lagos"


def test_a_wall_clock_time_that_a_clock_change_skips_is_refused():
    with pytest.raises(inc.IncidentError, match="does not exist"):
        inc.to_utc(datetime(2026, 3, 8, 2, 30), "America/New_York")  # 02:00 jumped to 03:00


def test_a_wall_clock_time_that_a_clock_change_repeats_is_refused():
    with pytest.raises(inc.IncidentError, match="two ways"):
        inc.to_utc(datetime(2026, 11, 1, 1, 30), "America/New_York")  # 01:00-02:00 happened twice


def test_times_either_side_of_a_clock_change_convert_correctly():
    assert inc.to_utc(datetime(2026, 3, 8, 1, 59), "America/New_York") == datetime(2026, 3, 8, 6, 59, tzinfo=UTC)
    assert inc.to_utc(datetime(2026, 3, 8, 3, 0), "America/New_York") == datetime(2026, 3, 8, 7, 0, tzinfo=UTC)
    # With an offset, the repeated hour is unambiguous.
    first = inc.to_utc(datetime(2026, 11, 1, 1, 30, tzinfo=timezone(timedelta(hours=-4))), "America/New_York")
    second = inc.to_utc(datetime(2026, 11, 1, 1, 30, tzinfo=timezone(timedelta(hours=-5))), "America/New_York")
    assert second - first == timedelta(hours=1)


def test_an_unknown_zone_falls_back_to_lagos():
    assert inc.zone_for("Mars/Olympus").key == "Africa/Lagos" and inc.zone_for(None).key == "Africa/Lagos"


# ── Validation ───────────────────────────────────────────────────────────


def test_times_in_the_future_and_notifications_before_awareness_are_refused():
    now = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
    with pytest.raises(inc.IncidentError, match="future"):
        inc._validate_times(now, now + timedelta(hours=1), None, None, now)
    with pytest.raises(inc.IncidentError, match="before you became aware"):
        inc._validate_times(now - timedelta(days=1), now - timedelta(hours=2), now - timedelta(hours=3), None, now)
    with pytest.raises(inc.IncidentError, match="30 days"):
        inc._validate_times(now, now - timedelta(days=31) - timedelta(minutes=1) , None, None, now)


# ── Copy ─────────────────────────────────────────────────────────────────


def test_checklist_and_incident_copy_avoid_verdict_language():
    texts = [inc.DISCLAIMER] + [part for step in inc.CHECKLIST for part in (step["title"], step["text"])]
    for text in texts:
        for phrase in BANNED:
            assert phrase not in text.lower(), (phrase, text)
    assert "not legal advice" in inc.DISCLAIMER.lower()
    assert [s["key"] for s in inc.CHECKLIST] == ["contain", "assess", "record", "notify_commission",
                                                  "notify_people", "review"]


def test_reminder_copy_avoids_verdict_language_and_carries_no_answer_content():
    expiry = reminders.expiry_date_text(datetime(2026, 11, 17, 23, 30, tzinfo=UTC), "Africa/Lagos")
    assert expiry == "18 November 2026"  # 00:30 on the 18th in Lagos
    from backend.app.compliance import questionnaire as qn
    for question in qn.QUESTIONS:
        item = reminders.what_expires(question["key"])
        email = reminders.email_copy("Acme Ltd", item, expiry, 7, "https://app.example/comply")
        note = reminders.notification_copy(item, expiry, 7)
        for text in (email["subject"], email["text"], email["html"], note["title"], note["body"]):
            for phrase in BANNED:
                assert phrase not in text.lower(), (phrase, text)
        assert expiry in email["text"] and item in email["text"] and "https://app.example/comply" in email["html"]


def test_email_html_escapes_the_organisation_name():
    email = reminders.email_copy("<b>Evil</b> & Co", "Item", "1 January 2027", 30, "https://x.test/comply")
    assert "<b>Evil</b>" not in email["html"] and "&lt;b&gt;Evil&lt;/b&gt;" in email["html"]


def test_reminders_wake_at_0700_utc_with_catch_up():
    from backend.app.scheduler import reminders_wake_at
    day = datetime(2026, 10, 17, tzinfo=UTC)
    assert reminders_wake_at(day.replace(hour=5), False) == day.replace(hour=7)
    assert reminders_wake_at(day.replace(hour=9), False) == day.replace(hour=9)  # missed: catch up now
    assert reminders_wake_at(day.replace(hour=9), True) == day.replace(day=18, hour=7)
