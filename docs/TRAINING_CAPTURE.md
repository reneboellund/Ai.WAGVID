# Android training capture

Ai.WAGVID supports three non-competition recording intents:

- `routine`: a complete exercise performed in training;
- `training`: a longer coached training segment;
- `drill`: one skill or simple training moment.

Competition recordings continue to use the separate competition-video contract so official scores,
adjudication and immutable competition provenance are not mixed with coaching data.

## Operator flow

1. In the admin WebUI, select a gymnast by stable ID and verify name, level/trin and license number.
2. Select activity type, apparatus and optional target skill.
3. Connect an Android phone mounted on a tripod and show camera preview/device health.
4. Start manually, or arm motion detection.
5. While armed, motion may start a recording. Exercise-end detection finalizes it after a configured
   quiet period, including pre-roll and post-roll.
6. A local Android stop or remote admin stop always overrides an automatically started recording.
7. Upload resumes safely after network loss; only a stored video URI and SHA-256 enter the record.
8. Queue analysis as full routine, training session, single skill or simple moment.

## Connection discovery

The thin client attempts connection without keyboard input:

1. discover `_wagvid._tcp.local` through mDNS/DNS-SD;
2. listen briefly for an authenticated backend discovery datagram on the local network;
3. use a previously paired backend;
4. offer manual HTTPS URL or IP/port entry when discovery fails.

Discovery only locates a candidate backend. Pairing still requires a short code or QR confirmation,
and the client stores the approved server certificate fingerprint. Plain unauthenticated UDP packets
must never be accepted as control commands.

## Local archive and upload queue

After finalization, Android writes the video and metadata to its local archive and immediately adds a
persistent upload job. A foreground/background worker uploads the oldest eligible item, resumes from
the recorded byte offset after interruption, and retries with backoff when the backend or network is
unavailable. Additional recordings remain queued while upload capacity is busy.

A successful upload records the remote URI and checksum but does not delete or move the local video.
There is no automatic deletion path. Storage status and archive capacity must be visible in both the
Android app and admin WebUI; any future deletion feature must be a separate explicit user action.

## Control contract

The first implementation uses a deterministic state machine:

`offline -> ready -> armed -> recording -> finalizing -> armed`

Manual recording uses:

`offline -> ready -> recording -> finalizing -> ready`

Commands must be idempotent at the transport layer and carry a command ID, device ID, actor,
timestamp and expected prior state. Android remains able to stop locally when the WebUI connection
is lost. Remote control must use authenticated, short-lived device sessions and an audit log.

## Automatic boundary detection

Motion detection is only a recording trigger, not the final exercise classifier. A lightweight
on-device signal can create a candidate window. The server-side perception layer then refines
gymnast presence, apparatus region, active movement and end-of-exercise boundaries. Thresholds are
configurable per apparatus and must avoid clipping the approach, mount, landing and salute.

## Analysis output

Training analysis reuses the perception and interpretation layers but adapts feedback to its scope:

- routine: element sequence, recognized alternatives, execution observations and rule-based score;
- training: segmented attempts, consistency, progression and coach-review markers;
- drill/simple moment: target skill, phases, angles, timing and specific improvement observations.

The system must distinguish observed evidence from coaching suggestions and expose confidence.
Training feedback is not an official score and never overwrites competition results.
