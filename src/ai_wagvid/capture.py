"""Deterministic recording control shared by Android capture and admin WebUI."""

from dataclasses import dataclass, replace
from enum import StrEnum


class CaptureMode(StrEnum):
    MANUAL = "manual"
    MOTION = "motion-detection"


class CaptureState(StrEnum):
    OFFLINE = "offline"
    READY = "ready"
    ARMED = "armed"
    RECORDING = "recording"
    FINALIZING = "finalizing"


class CaptureCommand(StrEnum):
    CONNECT = "connect"
    ARM = "arm"
    DISARM = "disarm"
    START = "start"
    STOP = "stop"
    MOTION_STARTED = "motion-started"
    EXERCISE_ENDED = "exercise-ended"
    FINALIZED = "finalized"
    DISCONNECT = "disconnect"


class CaptureTransitionError(ValueError):
    """Raised when a device command is invalid for its current state."""


@dataclass(frozen=True)
class CaptureSession:
    state: CaptureState = CaptureState.OFFLINE
    mode: CaptureMode = CaptureMode.MANUAL
    recording_started_by: str | None = None
    stop_reason: str | None = None

    def apply(
        self,
        command: CaptureCommand,
        *,
        actor: str = "admin-webui",
        mode: CaptureMode | None = None,
    ) -> "CaptureSession":
        """Apply a command. Manual stop is valid for every active recording."""
        if command is CaptureCommand.CONNECT and self.state is CaptureState.OFFLINE:
            return replace(self, state=CaptureState.READY)
        if command is CaptureCommand.DISCONNECT:
            return replace(self, state=CaptureState.OFFLINE)
        if command is CaptureCommand.ARM and self.state is CaptureState.READY:
            return replace(
                self,
                state=CaptureState.ARMED,
                mode=mode or CaptureMode.MOTION,
                recording_started_by=None,
                stop_reason=None,
            )
        if command is CaptureCommand.DISARM and self.state is CaptureState.ARMED:
            return replace(self, state=CaptureState.READY)
        if command is CaptureCommand.START and self.state in {
            CaptureState.READY,
            CaptureState.ARMED,
        }:
            return replace(
                self,
                state=CaptureState.RECORDING,
                mode=mode or CaptureMode.MANUAL,
                recording_started_by=actor,
                stop_reason=None,
            )
        if (
            command is CaptureCommand.MOTION_STARTED
            and self.state is CaptureState.ARMED
            and self.mode is CaptureMode.MOTION
        ):
            return replace(
                self,
                state=CaptureState.RECORDING,
                recording_started_by="motion-detector",
                stop_reason=None,
            )
        if command is CaptureCommand.STOP and self.state is CaptureState.RECORDING:
            return replace(
                self,
                state=CaptureState.FINALIZING,
                stop_reason=f"manual:{actor}",
            )
        if (
            command is CaptureCommand.EXERCISE_ENDED
            and self.state is CaptureState.RECORDING
            and self.mode is CaptureMode.MOTION
        ):
            return replace(
                self,
                state=CaptureState.FINALIZING,
                stop_reason="automatic:exercise-ended",
            )
        if command is CaptureCommand.FINALIZED and self.state is CaptureState.FINALIZING:
            next_state = (
                CaptureState.ARMED
                if self.mode is CaptureMode.MOTION
                else CaptureState.READY
            )
            return replace(
                self,
                state=next_state,
                recording_started_by=None,
            )
        raise CaptureTransitionError(
            f"Cannot apply {command.value} while capture is {self.state.value}"
        )
