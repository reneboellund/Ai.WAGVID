# Media inspection and normalization

## Canonical timeline and immutable evidence

`ai_wagvid.media_timeline` hashes original media as a stream and builds a canonical
frame index from FFprobe `pts`, `pkt_dts`, `best_effort_timestamp`, duration and the
source stream time base. It never synthesizes a timestamp for a frame that lacks
one. Diagnostics preserve duplicate timestamps, backwards timestamps, suspected
gaps, effective FPS and likely variable frame rate.

The source remains immutable. Analysis proxies retain passthrough timing but are
derived objects and may not replace the original. Use
`frame_timeline_probe_command()` to plan the exact frame-level FFprobe operation.

`ai_wagvid.calibration` versions normalized-image apparatus geometry for vault,
bars, beam and floor. Multi-camera clock mappings apply measured offset plus drift
and return uncertainty that grows away from synchronization observations.

`ai_wagvid.evidence` binds an evidence interval to source SHA-256, timeline digest,
camera, exact start/end frames and optional calibration revision digest. Resolution
fails closed when any source, timeline, frame timestamp or calibration revision has
changed. This contract is the base for review playback, annotation and overlays.

Original uploads are immutable evidence. Ai.WAGVID first records the checksum and runs FFprobe to
capture codecs, dimensions, duration, rational average/nominal frame rates, rotation metadata,
pixel format and audio presence. Nominal FPS is never assumed to equal source timing.

`ai_wagvid.media_inspection` parses FFprobe JSON and builds shell-independent argument vectors. It
does not execute external programs. The initial proxy plan creates an H.264/AAC browser-compatible
derivative, preserves input frame timing with `-fps_mode passthrough`, and rejects source/destination
identity. Production execution must additionally use an isolated worker, time/resource limits,
captured tool versions, output checksum and atomic object-store promotion.

FFmpeg/FFprobe are deployment dependencies rather than Python package dependencies. They are not
installed or invoked during the current low-cost implementation milestone.
