# Analysis operations and reviewed-learning loop

## Durable job lifecycle

An analysis request is idempotent per organization and locks its media while assigning the next
revision. Workers lease queued jobs; an expired lease can be recovered by another worker. Every
lease increments `attempts`. Progress events are append-only, worker-owned and monotonic, so the UI
can show both the current percentage and the exact processing history.

Retryable failures are requeued explicitly. When the configured attempt ceiling is reached, the
same failure becomes terminal. A stale or non-owning worker cannot report progress or complete the
job. The current implementation provides the persistence and state transitions; an external queue
transport and worker process remain deployment tasks.

## Score comparison and review

Official and proposed D, E, neutral and final scores are compared field by field. Missing values and
threshold-sized deviations require review. This comparison does not declare either source correct.

A reviewer, organization administrator or system administrator can conclude a pending analysis as:

- official result confirmed;
- AI-supported discrepancy requiring investigation;
- corrected learning labels;
- inconclusive evidence.

Corrected labels require all four score fields. The conclusion, accepted values, reviewer, time and
reason are append-only and audit logged. The review UI displays both official and proposed totals,
individual deduction evidence and the overall conclusion form.

## Controlled learning export

`/imports-exports/reviewed-labels.json` is available only to researchers and administrators. It
exports complete human-corrected labels and complete official labels explicitly confirmed by a
human. Inconclusive cases and unconfirmed AI-supported discrepancies are excluded from ground
truth. Every export creates an audit event. Reviewer identity remains provenance and must never be
used as a scoring feature.

## Offline commands

After installing the package locally:

```text
wagvid validate-dataset path/to/manifest.yaml
wagvid model-profile competition-research-contract@1
wagvid parse-ffprobe path/to/ffprobe.json
wagvid plan-proxy source.mp4 proxy.mp4
```

These commands validate or print plans. They do not download datasets, load checkpoints, invoke
FFmpeg or run GPU inference. Contract-only model profiles deliberately report `runnable: false`.
