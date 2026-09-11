# Jarvis integration

The copilot is exposed to [Jarvis](https://github.com/Arjun-Chandra-7/JARVIS)
as an agent, alongside its other tools.

## Setup

In Jarvis's `.env`:

```bash
LINKEDIN_COPILOT_URL=http://127.0.0.1:8000
LINKEDIN_COPILOT_DIR=$HOME/Dev/Linkdin/repo
```

That is the whole setup. Jarvis authenticates over a loopback-only desktop
session, and starts this backend itself if it isn't already running.

## What you can say

| You say | What happens |
|---|---|
| "open LinkedIn stats" | Console opens, Jarvis reads the summary aloud |
| "open my LinkedIn approvals" | Console opens on the queue |
| "anything to approve?" | Lists what's waiting, with quality scores |
| "read the first one" | Reads the post aloud, in full |
| "approve it" | Approves and schedules it |
| "who should I connect with?" | Names them and why, opens the queue |
| "write a post about the bug I just fixed" | Captures it as a draft |

## Why voice approval is still safe

A post can be approved by voice **only after Jarvis has read it aloud**. The
approval carries the hash of the text that was read, so if the draft changed in
between, the backend refuses it and Jarvis says so. Asking to approve something
unheard gets a refusal:

> "I haven't read that one to you yet, and I won't approve a post you haven't
> heard. Say 'read it' first, or approve it in the console."

That keeps the guarantee the rest of the system is built on: what you consented
to is exactly what goes out.

## Networking, out loud

Jarvis will tell you who is worth connecting with and open the queue. It does
not send or accept invitations, and that is not a missing feature — LinkedIn
has no API for either, so the only implementation would be driving your
logged-in browser session, which breaches their User Agreement and risks the
account the whole system exists to build.

What you get instead: candidates discovered from the public GitHub API
(contributors to the AI and developer-tooling repos you follow), each with a
reason and a drafted note, and one keystroke that opens their profile with the
note already on your clipboard. Accepting incoming invitations is one click
through the link to LinkedIn's own invitation manager.
