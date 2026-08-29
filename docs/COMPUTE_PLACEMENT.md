# Compute placement and accelerator policy

Ai.WAGVID separates capability discovery, placement and execution. Core web code does not import CUDA, ROCm, OpenVINO or hyperscaler SDKs.

## Local first

Workers advertise immutable capability snapshots: provider/location, devices, backend, VRAM, supported precisions/capabilities, installed model bundles, queue/load, storage-locality tokens and optional known cost. NVIDIA, AMD, Intel and CPU discovery adapters translate observations into the same record.

`plan_analysis_placement()` receives already-discovered local workers. Only `provider=local` workers are accepted in this phase. The common scheduler applies model-bundle availability, backend/precision/capability constraints, VRAM, worker health and storage-locality policy. A compatible local worker wins before cloud spillover, even when a cloud offer happens to be cheaper.

## Cloud spillover

Cloud placement is considered only when no compatible local target exists and the request explicitly permits cloud execution. A `CloudComputePolicy` is mandatory. AWS, Azure and GCP offers are filtered by enabled provider, region, SKU prefix, current capacity/quota, backend/VRAM/precision/capabilities, storage locality and effective hourly-cost ceiling.

Unknown price fails closed when a cost ceiling is active. Spot/preemptible pricing is selected only when both policy and request permit it. Provider preference remains a user/policy input; it is not hard-coded as AWS-first.

## Storage locality

Placement may require a locality token produced by object or shared-file providers. `require_storage_locality=true` makes a mismatch a blocker; otherwise it is a ranking penalty. This prevents accidentally moving large gymnastics video across regions/clouds when a suitable worker is already close to the data.

## Execution leases

A runnable placement can produce an `ExecutionLease`. The lease identifier/idempotency key is deterministic from job ID, attempt and target identity. Repeating the same placement attempt therefore cannot create a second logical lease merely because an API response was lost. Retry attempts receive a new identity. Lease TTL is bounded to one hour.

The lease is still only a control-plane plan. Provider adapters/worker agents must perform compare-and-set/claim semantics when persistence is wired into the analysis queue.

## Validation boundary

Ordinary tests use synthetic capability records only. They do not execute GPU kernels, download model checkpoints, provision cloud instances or benchmark storage. Hardware/model compatibility and cloud quota/capacity acceptance remain explicit milestone tests.
