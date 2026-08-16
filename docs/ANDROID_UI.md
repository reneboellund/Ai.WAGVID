# Android capture UI and identity

The Android application is a focused camera/archive thin client. It shares the Ai.WAGVID visual
language with admin WebUI without copying the information density of the analysis workspace.

## Identity

The canonical app icon is `assets/ui/app-icon.svg`. It combines a camera frame, a W-shaped motion
trace and a red recording indicator. Android uses the adaptive foreground, dark background and
monochrome resources under `android/app/src/main/res`. Do not substitute FIG or apparatus marks.

App name: **Ai.WAGVID Capture**  
Short launcher label: **WAGVID**  
Package placeholder: `com.boellund.wagvid.capture`

## Primary camera screen

The camera preview remains visible behind a high-contrast status overlay:

- top: backend/device connection, battery, free storage and upload-queue count;
- below top: selected gymnast name, level/trin, license number and apparatus;
- center: framing guide and motion/athlete-presence indicator;
- bottom: 80 dp record/stop control, Manual/Auto selector and local archive shortcut;
- persistent recording state: red indicator, elapsed time and explicit `OPTAGER` text.

Manual stop is always enabled while recording, including when recording started automatically or the
backend connection was lost. Color is never the only state indicator.

## Required screens

1. First launch: camera/storage permission explanation and privacy boundary.
2. Connecting: automatic discovery progress with found backend identity.
3. Pairing: short code/QR confirmation and certificate fingerprint.
4. Manual connection: HTTPS URL or IP/port, validation result and retry.
5. Camera: manual/automatic recording and gymnast context.
6. Local archive: thumbnails, gymnast, date, activity, duration and upload state.
7. Upload queue: progress, waiting order, retry/error and remote URI when complete.
8. Settings: camera/resolution, discovery, backend identity and diagnostics.

There is no delete action in M1. Uploaded videos display `Uploadet · gemt lokalt`.

## Admin WebUI parity

Admin WebUI and Android must use the same state names, colors and command outcomes from
`assets/ui/mobile-tokens.json`. The WebUI device card shows:

- live preview and device identity;
- online/offline, battery, storage and network;
- active gymnast and activity;
- Manual/Auto, Arm/Disarm, Start/Stop;
- recording elapsed time;
- archive count and upload queue with progress.

A remote command must show pending, accepted or rejected acknowledgement. Android remains the final
authority for local camera and storage errors.

## Accessibility and responsive behavior

- minimum touch target: 48 dp; primary record control: 80 dp;
- portrait and landscape camera layouts;
- WCAG AA contrast for text and controls;
- text labels with icons; do not rely on red/green alone;
- TalkBack labels for record, stop, mode, connection and queue status;
- dynamic type without hiding Stop;
- haptic and optional audio feedback for start/stop;
- keep the screen awake while armed or recording, with a visible privacy indicator.
