# LinkedIn publishing

Two supported modes. Browser automation is not one of them, and will not be
added — it violates LinkedIn's terms and risks the user's account.

## Manual mode (default)

At the scheduled time the backend:

1. Verifies the approval is still valid for the current content.
2. Sends a high-priority notification to the phone.
3. Provides the copy-ready text and a link to LinkedIn's composer.

You paste, post, and tap **Mark as published** in the app. The system records
the publication and starts tracking it.

This mode requires no API access, cannot get your account restricted, and is
what the system uses unless you configure otherwise.

## API mode (official LinkedIn REST API)

Publishes directly using the official Posts API. It requires a member access
token with the `w_member_social` scope, which means:

1. Create an app at <https://www.linkedin.com/developers/apps>.
2. Request the **Share on LinkedIn** product.
3. Complete the OAuth 2.0 authorisation-code flow as yourself to obtain a
   member access token. (LinkedIn member tokens are typically valid for 60
   days and must be refreshed.)
4. Find your person URN — the `sub` claim from the userinfo endpoint, formatted
   as `urn:li:person:XXXX`.

Then set:

```bash
LINKEDIN_PUBLISH_MODE=api
LINKEDIN_ACCESS_TOKEN=<member access token>
LINKEDIN_AUTHOR_URN=urn:li:person:XXXX
```

The request the backend makes:

```
POST https://api.linkedin.com/rest/posts
Authorization: Bearer <token>
LinkedIn-Version: 202405
X-Restli-Protocol-Version: 2.0.0

{"author": "<urn>", "commentary": "<post text>", "visibility": "PUBLIC",
 "distribution": {"feedDistribution": "MAIN_FEED", ...},
 "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": false}
```

The post URN comes back in the `x-restli-id` response header.

**Failure behaviour is explicit.** A 401/403 raises
`PublishingAuthExpiredError` and the app tells you to reconnect. Any other
error marks the post `FAILED` with the reason. It never silently falls back to
manual, and never retries into something riskier — you decide what happens
next.

**Status in this repo:** implemented, **not configured**. `LinkedInApiPublisher`
reports `not_configured` until you supply credentials, and refuses to publish
rather than pretending. It has not been exercised against the live LinkedIn
API here, because that requires your account and an approved app.

## Analytics

LinkedIn does not expose member post analytics (impressions, unique views) to
an ordinary integration — those endpoints require partner-level access. So the
system asks you to enter the numbers from the post's own analytics view, and
leaves anything you do not enter as `NULL`.

This is why every analytics column is nullable and why the learning engine
excludes posts without data rather than treating them as zeros.
