from datetime import UTC, datetime, timedelta

import pytest

from ai_wagvid.upload_queue import UploadItem, UploadState, next_upload


def item(name: str, age_minutes: int = 0) -> UploadItem:
    return UploadItem(
        capture_id=name,
        local_uri=f"content://wagvid/archive/{name}.mp4",
        sha256="a" * 64,
        created_at=datetime.now(UTC) - timedelta(minutes=age_minutes),
    )


def test_oldest_pending_video_uploads_first() -> None:
    older = item("older", age_minutes=10)
    newer = item("newer")
    assert next_upload([newer, older]) == older


def test_interrupted_upload_keeps_progress_and_retries() -> None:
    upload = item("capture").start().checkpoint(1_048_576)
    upload = upload.retry("network-offline")
    assert upload.state is UploadState.RETRY_WAIT
    assert upload.uploaded_bytes == 1_048_576
    assert upload.local_retained is True

    resumed = upload.start()
    assert resumed.attempts == 2
    assert resumed.uploaded_bytes == 1_048_576


def test_successful_upload_never_deletes_local_video() -> None:
    completed = item("capture").start().complete(
        "https://backend.example/videos/capture"
    )
    assert completed.state is UploadState.UPLOADED
    assert completed.local_retained is True
    assert next_upload([completed]) is None


def test_upload_progress_cannot_move_backwards() -> None:
    upload = item("capture").start().checkpoint(100)
    with pytest.raises(ValueError):
        upload.checkpoint(99)
