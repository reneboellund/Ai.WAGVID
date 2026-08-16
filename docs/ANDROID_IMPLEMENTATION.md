# Android capture implementation milestone

The repository now contains a native Kotlin application skeleton under `android/`. It targets a
thin, offline-first capture client and deliberately does not contain model inference or scoring.

## Implemented contracts

- CameraX preview and video recording with an always-available local stop action;
- app-private local archive with SHA-256 calculated after finalization;
- Room-backed immutable capture records and persistent resumable upload queue;
- WorkManager upload with backend offset resume, bounded chunks and retry backoff;
- local video retained after successful upload—there is no deletion call in the worker;
- encrypted backend URL, device identity and API token storage;
- HTTPS-only Android network security policy;
- mDNS discovery for `_wagvid._tcp` and validated manual HTTPS fallback;
- pairing repository for one-time six-digit code exchange;
- command coordinator for ARM, DISARM, START and STOP acknowledgements;
- motion-gate hysteresis with configurable start/quiet windows, pre-roll and post-roll metadata;
- adaptive and monochrome launcher assets from the established Ai.WAGVID identity.

## Backend flow

1. An organization administrator requests a five-minute pairing offer in the device UI or API.
2. Android claims the offer with its stable installation ID and receives a device token once.
3. Five incorrect code attempts permanently lock that offer.
4. Android sends heartbeat telemetry: state, battery, free storage, network, app version, active
   capture and upload-queue size.
5. Admin selects device, gymnast, activity and apparatus and sends an idempotent command.
6. Android polls pending/delivered commands, verifies the expected local state, executes locally and
   acknowledges accepted or rejected with a stable error code.
7. Finalized media is hashed, archived locally, queued, uploaded from the server offset and retained.

Every pairing and command transition is organization-scoped and audit logged. The phone remains
authoritative for camera permissions, storage failures and manual emergency stop.

## Deliberately not executed in this milestone

No Gradle wrapper distribution, Android SDK, Maven dependency, emulator, APK build, camera hardware
test or network upload was downloaded or run. Python contract tests inspect the Android manifest,
dependency declarations, retention invariant and JSON command schema. A real Android build and
instrumented device test are a later explicit release-gate operation.
