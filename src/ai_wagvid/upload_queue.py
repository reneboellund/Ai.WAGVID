"""Persistent upload-queue domain rules for the Android thin client."""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum


class UploadState(StrEnum):
    QUEUED = "queued"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    RETRY_WAIT = "retry-wait"


@dataclass(frozen=True)
class UploadItem:
    capture_id: str
    local_uri: str
    sha256: str
    created_at: datetime
    state: UploadState = UploadState.QUEUED
    attempts: int = 0
    uploaded_bytes: int = 0
    remote_uri: str | None = None
    last_error: str | None = None
    local_retained: bool = True

    def start(self) -> "UploadItem":
        if self.state not in {UploadState.QUEUED, UploadState.RETRY_WAIT}:
            raise ValueError(f"Cannot start upload in state {self.state.value}")
        return replace(
            self,
            state=UploadState.UPLOADING,
            attempts=self.attempts + 1,
            last_error=None,
        )

    def checkpoint(self, uploaded_bytes: int) -> "UploadItem":
        if self.state is not UploadState.UPLOADING:
            raise ValueError("Only an active upload can be checkpointed")
        if uploaded_bytes < self.uploaded_bytes:
            raise ValueError("Upload progress cannot move backwards")
        return replace(self, uploaded_bytes=uploaded_bytes)

    def retry(self, error: str) -> "UploadItem":
        if self.state is not UploadState.UPLOADING:
            raise ValueError("Only an active upload can enter retry wait")
        return replace(self, state=UploadState.RETRY_WAIT, last_error=error)

    def complete(self, remote_uri: str) -> "UploadItem":
        if self.state is not UploadState.UPLOADING:
            raise ValueError("Only an active upload can complete")
        # Completion never removes the local archive. Deletion is a separate,
        # explicit user-owned operation and is intentionally absent here.
        return replace(
            self,
            state=UploadState.UPLOADED,
            remote_uri=remote_uri,
            last_error=None,
            local_retained=True,
        )


def next_upload(items: list[UploadItem]) -> UploadItem | None:
    """Return the oldest eligible item; one worker uploads sequentially."""
    eligible = [
        item
        for item in items
        if item.state in {UploadState.QUEUED, UploadState.RETRY_WAIT}
    ]
    return min(eligible, key=lambda item: item.created_at) if eligible else None
