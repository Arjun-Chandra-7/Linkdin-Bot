# First run

Nine steps, about ten minutes.

## 1. Start the backend

```bash
cp .env.example .env
./scripts/dev.sh
```

The defaults are deliberately safe: the LLM provider is an offline mock (no API
key, no cost) and publishing is manual (nothing is posted for you). You can
work through this entire guide before deciding to spend anything.

## 2. Seed sources

```bash
python scripts/seed.py --github your-name/your-repo
```

Adds a few public feeds plus your own repository, and queues the daily loop.

## 3. Build and install the app

```bash
./scripts/build-mobile.sh
adb install -r mobile/app/build/outputs/apk/debug/app-debug.apk
```

Or copy the APK to the phone and tap it. See `docs/mobile.md`.

## 4. Pair

```bash
python scripts/pair.py
```

Enter the address and code in the app. The code lasts ten minutes and works
once.

## 5. Configure your interests

Settings in the app, or the `settings` table. The ones that matter early:

| Setting | Default | What it does |
|---|---|---|
| `posting_slots` | Mon 10:00, Wed 14:00, Fri 11:30 | When approved posts go out |
| `timezone` | `Asia/Kolkata` | Interpretation of those times |
| `category_mix` | 40/25/20/15 | Build logs vs lessons vs AI news vs milestones |
| `quality_threshold` | 70 | How good a draft must be to reach your phone |
| `llm_daily_cost_limit_usd` | 2.00 | Hard stop on spend |

## 6. Choose an AI provider

The mock provider writes real, topic-shaped posts from your notes and costs
nothing, which is enough to learn the workflow. For genuinely good writing:

```bash
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-opus-5
```

Spending is capped by `llm_daily_cost_limit_usd` and visible at
`/api/v1/system/costs`.

## 7. Set up publishing

Leave `LINKEDIN_PUBLISH_MODE=manual` unless you have a reason not to. You will
get a reminder with copy-ready text at the scheduled time and post it yourself.
For direct publishing via the official API, see `docs/linkedin.md`.

## 8. Generate your first draft

Do not wait for discovery. Open the app and add a note about something you
actually did this week — what broke, what you changed, what surprised you. Your
own notes are first-hand evidence and produce the best posts.

## 9. Approve it

Read it. Edit anything that does not sound like you — those edits are the
training signal the writer learns from. Approve.

The post is scheduled into your next free slot. At that time you get a
notification, you post it, and you tap "Mark as published". Add the metrics a
day or two later and the learning engine starts building a picture of what
works for your account specifically.

---

## What to expect early

**The approval queue will often be empty.** Drafts below the quality threshold
are rejected server-side and never shown. That is the system working. If you
want to see more, lower `quality_threshold`.

**Analytics will say it does not know anything.** It needs at least four
published posts with metrics before it will claim a pattern, and it labels
everything with its confidence and sample size. It will not tell you that
Wednesdays are better on the strength of two posts.
