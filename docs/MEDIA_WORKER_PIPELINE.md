# Media worker pipeline

Ai.WAGVID media preparation is content-addressed, VFR-safe and fail-closed. Ordinary CI uses fake command runners; it does not run FFprobe/FFmpeg against real video.

## Processing identity

The worker first hashes the exact staged source file. `processing_id` is derived from source SHA-256, source size and proxy-profile digest, so changing source bytes or normalization policy creates a different processing directory. A verified matching set is reused idempotently; a corrupt verified output is rejected rather than silently regenerated under the same identity.

## Canonical frame timeline

FFprobe is executed as argv without a shell and selects the first video stream. The worker requests `best_effort_timestamp_time`, `pts_time`, packet duration and key-frame state for every frame. A frame artifact is accepted only when it is non-empty and presentation timestamps are monotonic.

The timeline artifact records exact source SHA-256/size, FFprobe version, command digest, raw FFprobe payload digest, frame count and whether varying presentation deltas were observed. `media_timeline_handoff.py` verifies both source identity and optional artifact SHA before producing the FFprobe-compatible payload used by the existing canonical-timeline import path. No constant frame rate, DTS value or missing timestamp is invented.

## Review proxy

FFmpeg writes `review-proxy.partial.mp4`. The command uses `-copyts`, `-start_at_zero` and `-fps_mode passthrough`; it intentionally contains no fixed `-r` or FPS filter. The proxy is SHA-256 hashed, required to be non-empty, and atomically renamed only after FFmpeg reports success. The verified manifest binds proxy hash/size, source hash, profile digest, FFmpeg version and command digest.

The review proxy is derived media. The immutable source remains the evidence/provenance authority.

## Journal and failure semantics

Every processing set has a JSONL append-only hash chain with legal transitions:

`planned -> probing -> timeline-written -> normalizing -> proxy-written -> verified`

Any nonterminal stage may transition to `failed`. The worker refuses to overwrite an incomplete work directory on a later run. Terminally failed directories can be atomically moved to a quarantine root with journal/timeline/partial files preserved, after which the same content-addressed source/profile may be retried in a clean directory. Verified sets cannot enter the failed-set recovery path.

## Publication boundary

Local processing success does not itself publish canonical application state. A later publisher must:

1. re-verify `manifest.json`, timeline SHA and proxy SHA/size;
2. write derived artifacts to provider-neutral object storage under immutable/content-addressed keys;
3. verify remote metadata/hash semantics;
4. persist the canonical timeline only against the exact source MediaAsset SHA;
5. persist proxy provenance separately from the original;
6. make publication idempotent by processing ID and artifact SHA.

Publication/provider failures must leave the local verified set intact and retryable. They must never downgrade or overwrite the original source object.

## Validation boundary

The branch is implementation groundwork, not a claim of codec/platform acceptance. Milestone validation still needs representative MP4/MOV, VFR, missing-audio, long-GOP and damaged-media samples on the intended worker images, plus actual object-store publication and Django persistence integration. Those tests should be batched once the worker integration boundary is ready rather than repeatedly transcoding during intermediate development.
