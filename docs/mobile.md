# The Android app

Kotlin + Jetpack Compose, single activity, Material 3, dark-first.

## Building

```bash
./scripts/build-mobile.sh          # debug APK
./scripts/build-mobile.sh release  # unsigned release build
```

Output: `mobile/app/build/outputs/apk/debug/app-debug.apk`

Requirements: **JDK 17 or 21** (the Android Gradle Plugin does not support
newer JDKs — the script tries to find a suitable one) and the Android SDK with
platform 35 and build-tools 35.0.0. Point `ANDROID_HOME` at your SDK if it is
not in `~/Android/Sdk`.

CI also builds this APK on every push and uploads it as an artifact, so you can
download a build without a local toolchain.

## Installing

Over USB:

```bash
adb devices                 # confirm the phone is listed
adb install -r mobile/app/build/outputs/apk/debug/app-debug.apk
```

Or copy the `.apk` to the phone (KDE Connect, USB, anything) and tap it in a
file manager. Android will ask you to allow installs from that source once.

No Play Store account or developer account is required. The debug APK is signed
with the standard Android debug key, which is fine for side-loading.

## Pairing

1. `python scripts/pair.py` on the laptop — prints the LAN address, a one-time
   code and a QR code.
2. Enter both in the app.

The token returned is stored in `EncryptedSharedPreferences` (AES-256 with the
key in the Android Keystore). Settings shows honestly whether the Keystore was
available.

Cleartext HTTP is permitted only to private LAN ranges
(`res/xml/network_security_config.xml`), so a mistyped address cannot send your
token to a public host in the clear.

## Screens

| Screen | Purpose |
|---|---|
| **Home** | What needs you right now, next scheduled post, backend reachability. No vanity metrics. |
| **Approvals** | The review queue. Cards show format, hook, preview, quality score and age. |
| **Approval detail** | The main screen: full text, variants, why it was written, quality issues, sources, unverified claims, rewrite tools, and approve/edit/reject/save. |
| **Calendar** | Everything with a place in time, from draft to published. |
| **People** | Connection suggestions with reasons and a draft note. Open profile / copy note / skip. You send the invitation. |
| **Analytics** | Published posts, manually entered metrics, and learned insights with sample sizes and confidence. |
| **Settings** | Connection details, live system status per component, safety statement, unpair. |

## Offline behaviour

The approval queue is cached in Room, so it is readable when the laptop is
asleep. Decisions made offline are queued and flushed on reconnect.

The safety property that makes this sound: each queued decision carries the
`client_action_id` generated **when you tapped** and the content hash of the
text **you actually read**. So:

- Replaying the queue twice records one decision.
- If the draft changed while you were offline, the server returns 409 and the
  queued action is dropped rather than applied — the post comes back for
  review instead of being approved on the strength of text you never saw.

The server is always authoritative for publication state.

## Notifications

There is no cloud push here by design — the backend is a laptop on your LAN,
not a service. A WorkManager job polls every 15 minutes while the backend is
reachable, and the app also syncs on open. Notifications are raised locally.

The trade-off is that a notification can arrive up to ~15 minutes late rather
than instantly. That is a consequence of not requiring a cloud account, and it
is stated here rather than hidden.

Notification actions deliberately stop at "open": you cannot approve a post
from the notification shade, because you would be approving text you had not
read. That is the one thing this system exists to prevent.
