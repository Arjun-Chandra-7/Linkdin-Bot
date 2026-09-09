#!/usr/bin/env bash
# Build the Android APK and report exactly where it landed.
#
#   ./scripts/build-mobile.sh          # debug APK (what you side-load)
#   ./scripts/build-mobile.sh release  # unsigned release build
set -euo pipefail

VARIANT="${1:-debug}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT/mobile"

# The Android Gradle Plugin supports JDK 17/21. If JAVA_HOME points at a newer
# JDK the build fails with an unhelpful error, so prefer a known-good one.
if [[ -z "${JAVA_HOME:-}" ]]; then
  for candidate in "$HOME"/jdks/jdk-21* /usr/lib/jvm/java-21-openjdk*; do
    [[ -d "$candidate" ]] && { export JAVA_HOME="$candidate"; break; }
  done
fi
: "${ANDROID_HOME:=$HOME/Android/Sdk}"
export ANDROID_HOME

if [[ ! -d "$ANDROID_HOME" ]]; then
  echo "Android SDK not found at $ANDROID_HOME" >&2
  echo "Install it, or set ANDROID_HOME to your SDK location." >&2
  exit 1
fi
echo "sdk.dir=$ANDROID_HOME" > local.properties

case "$VARIANT" in
  debug)   TASK=":app:assembleDebug";   APK="app/build/outputs/apk/debug/app-debug.apk" ;;
  release) TASK=":app:assembleRelease"; APK="app/build/outputs/apk/release/app-release-unsigned.apk" ;;
  *) echo "Unknown variant: $VARIANT (use debug or release)" >&2; exit 1 ;;
esac

echo "Building $VARIANT with JAVA_HOME=${JAVA_HOME:-system default}"
./gradlew "$TASK"

FULL_PATH="$REPO_ROOT/mobile/$APK"
if [[ ! -f "$FULL_PATH" ]]; then
  echo "Build finished but no APK at $FULL_PATH" >&2
  exit 1
fi

echo
echo "APK: $FULL_PATH"
echo "Size: $(du -h "$FULL_PATH" | cut -f1)"
echo
echo "Install over USB:   adb install -r \"$FULL_PATH\""
echo "Or copy it to the phone (KDE Connect, USB) and open it there."
