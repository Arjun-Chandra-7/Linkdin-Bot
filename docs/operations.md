# Running it day to day

## System status without reading logs

`Settings` in the app shows every component's real state, and
`GET /api/v1/system/status` returns the same thing:

| Component | `ok` means | Other states |
|---|---|---|
| backend | Serving requests | – |
| database | Reachable, migrations applied | `error` with the reason |
| scheduler | Worker running, next job time shown | `disabled` if `SCHEDULER_ENABLED=false` |
| ai_provider | Provider configured | `not_configured` — no API key |
| linkedin | Publisher ready | `not_configured` — API mode without credentials |

It also reports failed job count, the next queued job, and the last successful
discovery. If something is wrong, that page says what.

## Structured logs

Every domain action is a named event, greppable:

```
POST_GENERATED       DRAFT_REJECTED_QUALITY   APPROVAL_INVALIDATED
POST_APPROVED        DRAFT_REJECTED_DUPLICATE PUBLISH_BLOCKED
POST_REJECTED        POST_SCHEDULED           PUBLISH_FAILED
POST_PUBLISHED       DEVICE_PAIRED            JOB_RETRY_SCHEDULED
DISCOVERY_COMPLETED  CONNECTION_RECOMMENDED   JOB_DEAD
```

```bash
grep POST_PUBLISHED backend.log
LOG_JSON=true ./scripts/dev.sh          # JSON output for machine parsing
```

Token, key, cookie and password fields are redacted automatically before a log
line is written.

## Cost

```bash
curl -H "Authorization: Bearer $TOKEN" localhost:8000/api/v1/system/costs
```

Every model call records provider, model, task, tokens and estimated cost.
`llm_daily_cost_limit_usd` and `llm_monthly_cost_limit_usd` are enforced
*before* a call is made — hitting the limit raises a clear error rather than
spending anyway.

## Jobs

The queue is a table. To see what is happening:

```sql
SELECT type, status, attempts, run_at, last_error FROM jobs ORDER BY id DESC LIMIT 20;
```

`DEAD` means a job exhausted its retries; the error is in `last_error`. Nothing
is lost silently. Jobs left `RUNNING` by a crash are requeued at startup.

## When something looks wrong

**A post did not go out.** Check `scheduled_posts.status` and the draft's
status. The likely causes, in order: the content was edited after approval (the
approval was invalidated and the post went back for review), the backend was
asleep at the scheduled time (the job runs as soon as it wakes), or publishing
failed (draft is `FAILED`, reason in `failure_reason`).

**Nothing is reaching the approval queue.** Usually the quality gate is doing
its job. Check for `DRAFT_REJECTED_QUALITY` in the logs — the rejection note
lists the specific issues. Lower `quality_threshold` if you disagree with it.

**Discovery finds nothing.** Check `sources.last_error`. A single failing feed
does not stop the run; it is recorded and skipped.

**The phone says "Backend offline".** The laptop is asleep, on another network,
or bound to localhost. Use `./scripts/dev.sh` (binds `0.0.0.0`).

## Backups

Everything is in one SQLite file (`data/copilot.db` by default). Copy it while
the backend is stopped, or use `sqlite3 data/copilot.db ".backup backup.db"`
while it runs. That file contains your approvals, published history and
learned style — the drafts are reproducible, that history is not.
