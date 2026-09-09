"""Scheduling, durability and duplicate-publication protection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.approvals.service import submit_decision
from app.core.settings_store import set_setting
from app.database.enums import ApprovalAction, DraftStatus, JobStatus, ScheduleStatus
from app.database.models import Job, PublishedPost, ScheduledPost
from app.jobs.handlers import publish_post
from app.jobs.queue import claim_due_jobs, enqueue, fail_job, recover_orphaned_jobs
from app.scheduler.service import candidate_slots, schedule_approved_draft


def _approve_and_schedule(db, draft):
    result = submit_decision(
        db, draft_id=draft.id, device_id="dev-1", action=ApprovalAction.APPROVE
    )
    slot = schedule_approved_draft(db, result.draft, result.version, result.approval)
    db.commit()
    return slot


# ---------------------------------------------------------------- slots ----


def test_slots_follow_configured_days_and_times(db):
    set_setting(db, "timezone", "Asia/Kolkata")
    set_setting(db, "posting_slots", [{"weekday": "WED", "time": "14:00"}])
    db.commit()

    slots = candidate_slots(db, count=3)
    assert slots, "expected upcoming slots"
    for slot in slots:
        local = slot.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata"))
        assert local.weekday() == 2  # Wednesday
        assert (local.hour, local.minute) == (14, 0)


def test_slot_allocation_respects_minimum_gap(db, make_draft):
    set_setting(db, "min_hours_between_posts", 20)
    db.commit()

    first = _approve_and_schedule(db, make_draft("First post about the scheduler."))
    second_draft = make_draft("A completely different post about database indexes.")
    second = _approve_and_schedule(db, second_draft)

    assert abs(second.scheduled_at - first.scheduled_at) >= timedelta(hours=20)


def test_no_configured_slots_still_schedules(db, make_draft):
    """Removing every slot must not silently drop approved posts."""
    set_setting(db, "posting_slots", [])
    db.commit()
    slot = _approve_and_schedule(db, make_draft())
    assert slot.scheduled_at > datetime.now(UTC)


# ------------------------------------------------------- double publish ----


def test_same_job_running_twice_publishes_once(db, make_draft):
    """The spec's requirement: a job delivered twice must publish once."""
    draft = make_draft()
    slot = _approve_and_schedule(db, draft)
    slot.scheduled_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()

    first = publish_post(db, {"scheduled_post_id": slot.id})
    db.commit()
    second = publish_post(db, {"scheduled_post_id": slot.id})
    db.commit()

    # Manual mode parks awaiting the user, so neither run may publish twice.
    assert first.get("awaiting_user_action") is True
    assert "skipped" in second or second.get("awaiting_user_action") is True
    assert db.query(PublishedPost).count() == 0

    from app.jobs.handlers import record_publication

    record_publication(
        db,
        draft=draft,
        slot=slot,
        version=draft.current_version,
        approval_id=slot.approval_id,
        method=__import__("app.database.enums", fromlist=["PublishMethod"]).PublishMethod.MANUAL,
    )
    db.commit()
    assert db.query(PublishedPost).count() == 1

    # A late redelivery after publication must be a no-op.
    third = publish_post(db, {"scheduled_post_id": slot.id})
    db.commit()
    assert "skipped" in third
    assert db.query(PublishedPost).count() == 1


def test_publishing_blocked_when_content_changed_after_approval(db, make_draft):
    from app.approvals.service import add_version

    draft = make_draft()
    slot = _approve_and_schedule(db, draft)
    add_version(db, draft, "Rewritten after approval and never re-approved.")
    db.commit()

    # Editing already cancelled the slot, so the job finds nothing to do.
    # Either way the invariant is the same: nothing is published, and the post
    # is back in front of the user.
    result = publish_post(db, {"scheduled_post_id": slot.id})
    db.commit()

    assert result.get("blocked") or "skipped" in result
    assert db.query(PublishedPost).count() == 0
    assert draft.status == DraftStatus.READY_FOR_REVIEW

    # And if the slot were somehow still pending, the approval check blocks it.
    slot.status = ScheduleStatus.PENDING
    db.commit()
    forced = publish_post(db, {"scheduled_post_id": slot.id})
    db.commit()
    assert forced.get("blocked")
    assert db.query(PublishedPost).count() == 0


def test_rejected_draft_cannot_be_published_by_a_stale_job(db, make_draft):
    draft = make_draft()
    slot = _approve_and_schedule(db, draft)

    # The user changes their mind before the job fires.
    draft.status = DraftStatus.REJECTED
    db.commit()

    result = publish_post(db, {"scheduled_post_id": slot.id})
    db.commit()
    assert result.get("blocked")
    assert db.query(PublishedPost).count() == 0


def test_identical_content_is_never_scheduled_twice(db, make_draft):
    draft = make_draft()
    result = submit_decision(
        db, draft_id=draft.id, device_id="dev-1", action=ApprovalAction.APPROVE
    )
    first = schedule_approved_draft(db, result.draft, result.version, result.approval)
    second = schedule_approved_draft(db, result.draft, result.version, result.approval)
    db.commit()
    assert first.id == second.id
    assert db.query(ScheduledPost).count() == 1


# -------------------------------------------------------------- jobs ------


def test_queue_survives_restart(db, make_draft):
    """A scheduled post's job must still be there after the backend restarts."""
    draft = make_draft()
    slot = _approve_and_schedule(db, draft)

    jobs = db.query(Job).filter(Job.type == "publish_post").all()
    assert len(jobs) == 1
    assert jobs[0].run_at == slot.scheduled_at

    # Simulate a crash mid-execution, then a restart.
    jobs[0].status = JobStatus.RUNNING
    jobs[0].locked_by = "worker-that-died"
    db.commit()

    assert recover_orphaned_jobs(db) == 1
    db.refresh(jobs[0])
    assert jobs[0].status == JobStatus.QUEUED
    assert jobs[0].locked_by is None


def test_enqueue_is_idempotent(db):
    first = enqueue(db, "discover_topics", {}, idempotency_key="daily-1")
    second = enqueue(db, "discover_topics", {}, idempotency_key="daily-1")
    db.commit()
    assert first.id == second.id
    assert db.query(Job).count() == 1


def test_failed_jobs_retry_with_backoff_then_die(db):
    job = enqueue(db, "publish_post", {"scheduled_post_id": 1}, max_attempts=2)
    db.commit()

    job.attempts = 1
    fail_job(db, job, "boom")
    assert job.status == JobStatus.QUEUED
    assert job.run_at > datetime.now(UTC)

    job.attempts = 2
    fail_job(db, job, "boom again")
    assert job.status == JobStatus.DEAD
    assert "boom again" in job.last_error


def test_claiming_marks_jobs_running(db):
    enqueue(db, "generate_learning_report", {})
    db.commit()
    claimed = claim_due_jobs(db, "worker-1")
    assert len(claimed) == 1
    assert claimed[0].status == JobStatus.RUNNING
    # A second worker finds nothing left to take.
    assert claim_due_jobs(db, "worker-2") == []


def test_future_jobs_are_not_claimed(db):
    enqueue(db, "discover_topics", {}, run_at=datetime.now(UTC) + timedelta(hours=2))
    db.commit()
    assert claim_due_jobs(db, "worker-1") == []


def test_schedule_honors_explicit_requested_at(db, make_draft):
    draft = make_draft("Post with explicit schedule time.")
    result = submit_decision(
        db, draft_id=draft.id, device_id="dev-1", action=ApprovalAction.APPROVE
    )
    custom_time = datetime.now(UTC) + timedelta(days=3, hours=5)
    slot = schedule_approved_draft(
        db, result.draft, result.version, result.approval, requested_at=custom_time
    )
    db.commit()
    assert slot.scheduled_at == custom_time
    assert draft.proposed_publish_at == custom_time


def test_schedule_honors_draft_proposed_publish_at(db, make_draft):
    draft = make_draft("Post with pre-existing proposed time from custom idea.")
    custom_time = datetime.now(UTC) + timedelta(days=2, hours=3)
    draft.proposed_publish_at = custom_time
    db.commit()

    result = submit_decision(
        db, draft_id=draft.id, device_id="dev-1", action=ApprovalAction.APPROVE
    )
    # requested_at is None, so it falls back to draft.proposed_publish_at
    slot = schedule_approved_draft(
        db, result.draft, result.version, result.approval, requested_at=None
    )
    db.commit()
    assert slot.scheduled_at == custom_time


def test_reschedule_updates_slot_and_draft(db, make_draft):
    draft = make_draft("Post to be rescheduled.")
    slot = _approve_and_schedule(db, draft)
    new_time = datetime.now(UTC) + timedelta(days=5)

    from app.api.v1.schedule import reschedule

    reschedule(slot_id=slot.id, scheduled_at=new_time, db=db, _=None)
    db.refresh(slot)
    db.refresh(draft)
    assert slot.scheduled_at == new_time
    assert draft.proposed_publish_at == new_time
