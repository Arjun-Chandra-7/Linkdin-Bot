#!/usr/bin/env python3
"""End-to-end acceptance check against a running backend.

Walks the whole product flow the way the phone would, and asserts the safety
properties rather than just printing responses:

    pair -> generate -> stale-hash refused -> edit+approve -> replay is a no-op
    -> scheduled -> publish (manual reminder) -> confirm -> metrics -> learning

Usage:  python scripts/e2e_check.py [--base http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]

PASS, FAIL = "  PASS", "  FAIL"
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"{PASS if condition else FAIL}  {label}" + (f"  [{detail}]" if detail else ""))
    if not condition:
        failures.append(label)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--python", default=str(REPO_ROOT / ".venv/bin/python"))
    args = parser.parse_args()
    base = args.base.rstrip("/")
    client = httpx.Client(base_url=base, timeout=30.0)

    print("\n== 1. Backend reachable ==")
    health = client.get("/health")
    check("health endpoint responds", health.status_code == 200, health.text[:60])

    print("\n== 2. Authentication ==")
    check("unauthenticated request is rejected", client.get("/api/v1/drafts").status_code == 401)
    bad = client.post(
        "/api/v1/auth/pair", json={"code": "ZZZZ-ZZZZ", "device_name": "attacker"}
    )
    check("invalid pairing code is rejected", bad.status_code == 401)

    code_output = subprocess.run(
        [args.python, str(REPO_ROOT / "scripts/pair.py"), "--no-qr"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    ).stdout
    code = next(
        line.split()[-1] for line in code_output.splitlines() if "Pairing code" in line
    )
    paired = client.post(
        "/api/v1/auth/pair", json={"code": code, "device_name": "E2E device"}
    )
    check("device pairs with a valid code", paired.status_code == 200)
    token = paired.json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"

    replay_pair = client.post(
        "/api/v1/auth/pair", json={"code": code, "device_name": "second device"}
    )
    check("pairing code is single-use", replay_pair.status_code == 401)

    print("\n== 3. Draft generation and the quality gate ==")
    created = client.post(
        "/api/v1/drafts/from-idea",
        json={
            "topic": "making the job queue survive a laptop restart",
            "notes": (
                "Jobs left in RUNNING after a crash were never retried, so a scheduled "
                "post silently never went out. Turned on WAL so the writer stopped "
                "blocking readers. Added idempotency keys and exponential backoff "
                "capped at an hour."
            ),
            "category": "BUILD_LOG",
        },
    )
    check("draft is generated", created.status_code == 200, str(created.status_code))
    draft = created.json()
    draft_id, original_hash = draft["id"], draft["current_version"]["content_hash"]
    check(
        "draft cleared the quality gate",
        draft["status"] == "READY_FOR_REVIEW",
        f"status={draft['status']} quality={draft['quality_score']}",
    )
    check("multiple variants were produced", draft["version_count"] >= 2,
          f"{draft['version_count']} versions")

    print("\n== 4. Approval integrity ==")
    stale = client.post(
        "/api/v1/approvals",
        json={
            "draft_id": draft_id, "action": "APPROVE",
            "expected_content_hash": "0" * 64, "client_action_id": "stale-1",
        },
    )
    check("approval with a stale content hash is refused", stale.status_code == 409,
          stale.json().get("code", ""))

    no_hash = client.post(
        "/api/v1/approvals",
        json={"draft_id": draft_id, "action": "APPROVE", "client_action_id": "nohash-1"},
    )
    check("approval without a content hash is refused", no_hash.status_code == 422)

    edited = (
        "I spent this week making the job queue survive a laptop restart.\n\n"
        "What actually happened:\n"
        "- Jobs left in RUNNING after a crash were never retried, so a scheduled post "
        "silently never went out.\n"
        "- Turning on WAL stopped the writer blocking readers.\n"
        "- Idempotency keys plus exponential backoff capped at an hour.\n\n"
        "The part I got wrong: I keyed idempotency off the row id instead of the "
        "content hash, so identical content mapped to two different keys."
    )
    approved = client.post(
        "/api/v1/approvals",
        json={
            "draft_id": draft_id, "action": "APPROVE",
            "expected_content_hash": original_hash,
            "edited_content": edited, "client_action_id": "phone-act-1",
        },
    )
    check("edited draft is approved", approved.status_code == 200, approved.text[:80])
    result = approved.json()
    check("approval binds to the edited content, not the original",
          result["approved_content_hash"] != original_hash)
    check("approved draft is scheduled", result["status"] == "SCHEDULED",
          f"at {result['scheduled_at']}")

    replayed = client.post(
        "/api/v1/approvals",
        json={
            "draft_id": draft_id, "action": "APPROVE",
            "expected_content_hash": result["approved_content_hash"],
            "client_action_id": "phone-act-1",
        },
    )
    check("replayed offline approval is a no-op", replayed.json().get("replayed") is True)

    print("\n== 5. Publishing ==")
    slots = client.get("/api/v1/schedule").json()
    check("post appears on the schedule", len(slots) == 1, f"{len(slots)} slot(s)")
    slot_id = slots[0]["id"]

    due = (datetime.now(UTC) - timedelta(seconds=5)).isoformat().replace("+00:00", "Z")
    rescheduled = client.post(
        f"/api/v1/schedule/{slot_id}/reschedule", params={"scheduled_at": due}
    )
    check("post can be rescheduled", rescheduled.status_code == 200, rescheduled.text[:80])

    status = ""
    for _ in range(30):
        import time

        time.sleep(2)
        status = client.get(f"/api/v1/drafts/{draft_id}").json()["status"]
        if status == "PUBLISHING":
            break
    check("scheduler picked the post up", status == "PUBLISHING", f"status={status}")

    notifications = client.get("/api/v1/notifications/pending").json()
    kinds = {n["type"] for n in notifications}
    check("a publish reminder was queued for the phone", "PUBLISH_REMINDER" in kinds,
          ", ".join(sorted(kinds)))

    confirmed = client.post(f"/api/v1/schedule/{slot_id}/confirm-published")
    check("manual publication can be confirmed", confirmed.status_code == 200,
          confirmed.text[:80])
    final = client.get(f"/api/v1/drafts/{draft_id}").json()
    check("draft reaches PUBLISHED", final["status"] == "PUBLISHED", final["status"])

    print("\n== 6. Analytics and learning ==")
    overview = client.get("/api/v1/analytics/overview").json()
    check("published post is tracked", overview["published_count"] == 1)
    check("empty state is shown instead of fake numbers",
          bool(overview["empty_state"]) and overview["posts_with_metrics"] == 0,
          overview.get("empty_state", "")[:50])

    post_id = overview["posts"][0]["published_post_id"]
    metrics = client.post(
        f"/api/v1/analytics/posts/{post_id}/metrics",
        json={"impressions": 1400, "reactions": 32, "comments": 6},
    )
    check("metrics can be entered manually", metrics.status_code == 200)
    check("unreported metrics stay null rather than zero",
          metrics.json()["reposts"] is None)

    insights = client.post("/api/v1/analytics/recompute").json()
    check("learning engine reports insufficient data honestly",
          any(i["confidence"] == "INSUFFICIENT_DATA" for i in insights),
          insights[0]["statement"][:60] if insights else "none")

    print("\n== 7. Safety boundaries ==")
    spec = httpx.get(f"{base}/openapi.json", timeout=10).json()
    paths = " ".join(spec["paths"]).lower()
    forbidden = [p for p in ("send-invite", "send_connection", "auto-connect", "bulk") if p in paths]
    check("no endpoint sends connections or does bulk actions", not forbidden, str(forbidden))

    status_payload = client.get("/api/v1/system/status").json()
    check("system status reports real component states",
          status_payload["linkedin"]["status"] in {"ok", "not_configured"},
          f"linkedin={status_payload['linkedin']['status']}, ai={status_payload['ai_provider']['status']}")

    print("\n" + "=" * 56)
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All acceptance checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
