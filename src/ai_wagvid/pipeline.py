"""Model-neutral orchestration for the analysis layers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from .actions import ActionSegment, TemporalActionModel
from .domain import Apparatus, TimeRange
from .interpretation import ElementInterpretation, GymnasticsInterpreter
from .perception import MotionPerceptionModel, PerceptionBundle
from .quality import ActionQualityModel, QualityAssessment


class PipelineState(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"
    FAILED = "FAILED"


@dataclass(frozen=True)
class PipelineResult:
    state: PipelineState
    perception: PerceptionBundle | None = None
    actions: tuple[ActionSegment, ...] = ()
    interpretations: tuple[ElementInterpretation, ...] = ()
    quality: QualityAssessment | None = None
    warnings: tuple[str, ...] = ()


class AnalysisPipeline:
    """Coordinates inference while keeping deterministic scoring outside the model stack."""

    def __init__(
        self,
        *,
        perception_model: MotionPerceptionModel,
        action_model: TemporalActionModel,
        interpreter: GymnasticsInterpreter,
        quality_model: ActionQualityModel | None = None,
    ) -> None:
        self.perception_model = perception_model
        self.action_model = action_model
        self.interpreter = interpreter
        self.quality_model = quality_model

    def run(
        self,
        *,
        media_id: str,
        apparatus: Apparatus,
        interval: TimeRange,
        camera_ids: Sequence[str],
        rulepack_id: str,
    ) -> PipelineResult:
        if not media_id or not camera_ids or not rulepack_id:
            raise ValueError("media_id, camera_ids and rulepack_id are required")

        perception = self.perception_model.perceive(
            media_id=media_id,
            apparatus=apparatus,
            interval=interval,
            camera_ids=camera_ids,
        )
        if perception.media_id != media_id or perception.apparatus != apparatus:
            raise ValueError("perception output does not match the requested media/apparatus")
        if not perception.has_usable_evidence:
            return PipelineResult(
                state=PipelineState.INCOMPLETE_EVIDENCE,
                perception=perception,
                warnings=perception.limitations or ("no usable motion evidence",),
            )

        actions = self.action_model.detect(perception=perception, apparatus=apparatus)
        interpretations = self.interpreter.interpret(
            perception=perception, rulepack_id=rulepack_id
        )
        quality = (
            self.quality_model.assess(media_id=media_id, apparatus=apparatus)
            if self.quality_model
            else None
        )
        warnings = list(perception.limitations)
        if not actions:
            warnings.append("no action segments detected")
        if not interpretations:
            warnings.append("no gymnastics elements interpreted")
        return PipelineResult(
            state=PipelineState.COMPLETE,
            perception=perception,
            actions=actions,
            interpretations=interpretations,
            quality=quality,
            warnings=tuple(warnings),
        )
