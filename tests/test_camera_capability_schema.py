import json
from pathlib import Path

from jsonschema import Draft202012Validator
from test_dahua_camera import fixture

from ai_wagvid.camera_sources import camera_capabilities_payload


def test_dahua_capability_snapshot_validates_against_public_schema():
    root = Path(__file__).parents[1]
    schema = json.loads((root / "schemas/camera-capabilities-v1.schema.json").read_text())
    payload = camera_capabilities_payload(fixture()[0].discover())
    assert list(Draft202012Validator(schema).iter_errors(payload)) == []
