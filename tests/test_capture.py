import pytest

from ai_wagvid.capture import (
    CaptureCommand,
    CaptureMode,
    CaptureSession,
    CaptureState,
    CaptureTransitionError,
)


def test_manual_recording_from_admin() -> None:
    session = CaptureSession().apply(CaptureCommand.CONNECT)
    session = session.apply(CaptureCommand.START, actor="admin:coach-1")
    assert session.state is CaptureState.RECORDING
    assert session.mode is CaptureMode.MANUAL
    assert session.recording_started_by == "admin:coach-1"

    session = session.apply(CaptureCommand.STOP, actor="admin:coach-1")
    assert session.state is CaptureState.FINALIZING
    assert session.stop_reason == "manual:admin:coach-1"


def test_motion_recording_rearms_after_exercise_end() -> None:
    session = CaptureSession().apply(CaptureCommand.CONNECT)
    session = session.apply(CaptureCommand.ARM, mode=CaptureMode.MOTION)
    session = session.apply(CaptureCommand.MOTION_STARTED)
    assert session.state is CaptureState.RECORDING
    assert session.recording_started_by == "motion-detector"

    session = session.apply(CaptureCommand.EXERCISE_ENDED)
    assert session.state is CaptureState.FINALIZING
    assert session.stop_reason == "automatic:exercise-ended"

    session = session.apply(CaptureCommand.FINALIZED)
    assert session.state is CaptureState.ARMED


def test_manual_stop_overrides_motion_recording() -> None:
    session = CaptureSession().apply(CaptureCommand.CONNECT)
    session = session.apply(CaptureCommand.ARM, mode=CaptureMode.MOTION)
    session = session.apply(CaptureCommand.MOTION_STARTED)
    session = session.apply(CaptureCommand.STOP, actor="android-local")
    assert session.state is CaptureState.FINALIZING
    assert session.stop_reason == "manual:android-local"


def test_motion_cannot_start_unarmed_device() -> None:
    session = CaptureSession().apply(CaptureCommand.CONNECT)
    with pytest.raises(CaptureTransitionError):
        session.apply(CaptureCommand.MOTION_STARTED)
