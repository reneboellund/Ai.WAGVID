# Media inspection and normalization

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
