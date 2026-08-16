from ai_wagvid.domain import Apparatus, TimeRange
from ai_wagvid.perception import PerceptionBundle, PoseFrame, Visibility
from ai_wagvid.pipeline import AnalysisPipeline, PipelineState


class PerceptionStub:
    model_id = "pose-stub@1"

    def __init__(self, usable=True):
        self.usable = usable

    def perceive(self, *, media_id, apparatus, interval, camera_ids):
        frames = (PoseFrame(0, (), Visibility.VISIBLE, camera_ids[0]),) if self.usable else ()
        return PerceptionBundle(
            media_id=media_id,
            apparatus=apparatus,
            interval=interval,
            pose_frames=frames,
            limitations=() if self.usable else ("gymnast out of frame",),
        )


class ActionStub:
    model_id = "action-stub@1"

    def __init__(self):
        self.called = False

    def detect(self, *, perception, apparatus):
        self.called = True
        return ()


class InterpreterStub:
    interpreter_id = "interpreter-stub@1"

    def __init__(self):
        self.called = False

    def interpret(self, *, perception, rulepack_id):
        self.called = True
        return ()


def pipeline(usable=True):
    action = ActionStub()
    interpreter = InterpreterStub()
    return (
        AnalysisPipeline(
            perception_model=PerceptionStub(usable),
            action_model=action,
            interpreter=interpreter,
        ),
        action,
        interpreter,
    )


def test_pipeline_stops_before_interpretation_when_evidence_is_unusable():
    subject, action, interpreter = pipeline(usable=False)
    result = subject.run(
        media_id="media-1",
        apparatus=Apparatus.BB,
        interval=TimeRange(0, 10),
        camera_ids=("camera-1",),
        rulepack_id="fig-wag@2025",
    )
    assert result.state == PipelineState.INCOMPLETE_EVIDENCE
    assert result.warnings == ("gymnast out of frame",)
    assert not action.called and not interpreter.called


def test_pipeline_runs_layers_but_never_creates_a_score():
    subject, action, interpreter = pipeline()
    result = subject.run(
        media_id="media-1",
        apparatus=Apparatus.FX,
        interval=TimeRange(0, 10),
        camera_ids=("camera-1",),
        rulepack_id="fig-wag@2025",
    )
    assert result.state == PipelineState.COMPLETE
    assert action.called and interpreter.called
    assert result.warnings == ("no action segments detected", "no gymnastics elements interpreted")
    assert not hasattr(result, "score")
