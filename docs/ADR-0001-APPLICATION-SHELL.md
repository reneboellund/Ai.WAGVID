# ADR-0001: Operational application shell

Status: accepted for first usable product  
Date: 2026-08-16

## Decision

Build Ai.WAGVID as a modular Django web application with a native Android capture client.

- Django owns authentication, permissions, relational models, forms, admin, HTML views and APIs.
- Django templates plus HTMX provide the process-oriented WebUI/PWA.
- Django admin is reserved for trusted maintenance and exceptional data correction; it is not the
  operator interface.
- PostgreSQL stores operational records, provenance and audit events.
- S3-compatible object storage stores original, proxy and evidence media.
- A durable worker queue executes normalization, analysis, export and maintenance jobs.
- ASGI WebSockets are limited to Android device control and acknowledgements. SSE or polling updates
  dashboards and job progress where bidirectional messaging is unnecessary.
- Android remains native Kotlin with CameraX, Room and WorkManager.

## Why this is the easiest useful implementation

The current repository and analysis stack are Python. Django supplies the unglamorous product
functions that otherwise consume most delivery time: users, sessions, password flows, permissions,
forms, validation, database migrations and a maintenance admin. Server-rendered process views avoid
duplicating every validation rule in a TypeScript SPA. HTMX adds targeted live updates without
turning the first release into two independently versioned applications.

A desktop thick client is rejected for the first product. It complicates installation, updates,
database ownership, GPU/worker coordination and multi-user operation. The browser UI works on
desktop and tablet, can run fully on-premises, and still talks to local services when internet is
unavailable.

## Boundaries

Use custom process views for capture, analysis, review and operations. Django's own documentation
describes its admin as an internal model-centric management tool, not the complete front end.

Do not put ML inference inside web request handlers. Web requests create idempotent jobs; workers
write append-only results and progress events. Do not store video blobs in PostgreSQL.

## Reconsider when

Split services only after measured pressure requires it: independent scaling, separate release
cadence, security isolation or a proven team boundary. A future rich timeline may use a focused
TypeScript component inside the Django shell without replacing the whole UI.
