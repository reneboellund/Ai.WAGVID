# Analysis job API

The analysis API schedules durable work; it never runs pose or video inference inside the web
request. Requests use the authenticated user's active organisation. Multi-organisation clients can
select a membership with `X-WAGVID-Organization: <slug>`.

## Create or recover a job

`POST /api/analyses/` with JSON:

```json
{
  "media_id": "uuid",
  "client_request_id": "stable-client-generated-key",
  "scope": "routine",
  "rulepack_id": "wag-2025-2028@revision",
  "model_profile": "competition-research"
}
```

The media must be checksum-verified and stored in the selected organisation. A new request returns
HTTP 201. Repeating the identical request/key returns the existing job with HTTP 200. Reusing a key
with different inputs is rejected. Each genuinely new analysis receives the next media revision.

## Read status

`GET /api/analyses/{analysis_id}/` returns job state, progress, pinned rule/model profile and the
result summary when available. Result media and full versioned exports will use authenticated links;
large payloads are not embedded in polling responses.

## Worker boundary

Workers lease queued jobs through the durable lease service. Expired leases can be recovered, and
only the owning worker can extend an active lease. Future pose/action adapters write the canonical
model export defined by `schemas/model-analysis-export-v1.schema.json`; official scores remain a
separate comparison channel.
