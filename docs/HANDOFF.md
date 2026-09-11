# Handoff — connecting to the real LinkedIn account

Everything below is the remaining work. The rest of the system is done, tested
and pushed.

## State

- Repo: https://github.com/Arjun-Chandra-7/Linkdin-Bot (main, clean, 78 tests green)
- Jarvis agent: https://github.com/Arjun-Chandra-7/JARVIS (commit 4f69d67)
- Account being connected: https://www.linkedin.com/in/arjun-chandra-0b0b5826a/
  (already stored in the `settings` table as `linkedin_profile_url`)

## Done in this area

`scripts/linkedin_connect.py` — official OAuth 2.0 authorization-code flow.
Opens the browser, user approves on LinkedIn, a local callback server on
`http://localhost:8765/callback` receives the code, exchanges it for a token,
reads the person URN from `/v2/userinfo`, and writes `.env`
(`LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_AUTHOR_URN`, `LINKEDIN_PUBLISH_MODE=api`).
Fails with clear instructions when no app credentials exist.

Publishing itself (`backend/app/linkedin/publisher.py::LinkedInApiPublisher`)
was written earlier and posts to `POST https://api.linkedin.com/rest/posts`.

## Not done

1. **The flow has never been run against a real LinkedIn app.** Needs a
   developer app (Client ID/Secret) that only the account owner can create, so
   the token exchange, URN lookup and first real publish are all unverified.
2. **Self-exclusion from networking** — the user's own profile should never be
   recommended in the connection queue. `linkedin_profile_url` is stored but
   not yet checked in `backend/app/networking/service.py::add_candidate`.
3. **Identity is not surfaced** — `linkedin_display_name` / `linkedin_headline`
   are stored but unused by `backend/app/api/v1/profile.py` (which still
   produces generic headline suggestions) and unused by the desktop console.
4. **No Jarvis tool for the profile** — e.g. "open my LinkedIn profile".
5. **Token expiry is unhandled.** LinkedIn member tokens last ~60 days. The
   publisher raises `PublishingAuthExpiredError` on 401, but nothing warns
   ahead of time or prompts a reconnect.

## How to finish item 1

```
1. https://www.linkedin.com/developers/apps  ->  Create app
2. Products tab -> request "Share on LinkedIn" and
   "Sign In with LinkedIn using OpenID Connect"  (both self-serve, instant)
3. Auth tab -> Authorized redirect URLs -> add exactly:
       http://localhost:8765/callback
4. Copy Client ID + Client Secret into .env:
       LINKEDIN_CLIENT_ID=...
       LINKEDIN_CLIENT_SECRET=...
5. python scripts/linkedin_connect.py
6. Restart the backend.
```

Then verify: approve a post in the console and confirm it appears on the real
profile, and that `published_posts.external_url` is populated.

## Hard constraints — do not remove

These are enforced by `tests/test_safety_boundaries.py`; a change that breaks
them should be treated as a bug, not a failing test to update.

- Nothing publishes without a valid approval bound to a SHA-256 hash of the
  exact text the user saw. Editing after approval invalidates it.
- No browser automation anywhere, and no handling of LinkedIn cookies or
  session tokens.
- No endpoint sends or accepts connection invitations, sends DMs, comments or
  likes, and nothing operates in bulk. LinkedIn has no API for invitations, so
  the only implementation would be driving the user's logged-in browser, which
  breaches LinkedIn's User Agreement and risks the account. The product answer
  is the existing keyboard-driven queue (open profile + note on clipboard) and
  a link to LinkedIn's own invitation manager.
- Metrics that were never collected stay NULL and render as an em dash, never 0.
- The learning engine states sample size and confidence, and says
  INSUFFICIENT_DATA below four data points.
