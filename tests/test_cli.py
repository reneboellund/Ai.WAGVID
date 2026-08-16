import json

import pytest
import yaml

from ai_wagvid.cli import run


def test_cli_reports_contract_profile_as_not_runnable(capsys):
    assert run(["model-profile", "coaching-contract@1"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["profile_id"] == "coaching-contract@1"
    assert output["runnable"] is False


def test_cli_parses_saved_ffprobe_without_running_external_process(tmp_path, capsys):
    probe = tmp_path / "probe.json"
    probe.write_text(
        json.dumps(
            {
                "streams": [
                    {
                        "codec_type": "video",
                        "width": 1920,
                        "height": 1080,
                        "avg_frame_rate": "25/1",
                        "r_frame_rate": "25/1",
                    }
                ],
                "format": {"duration": "10"},
            }
        ),
        encoding="utf-8",
    )
    run(["parse-ffprobe", str(probe)])
    assert json.loads(capsys.readouterr().out)["video"]["average_fps"] == "25/1"


def test_cli_validates_and_materialises_dataset_split(tmp_path, capsys):
    manifest = {
        "schema_version": "dataset-manifest-v1",
        "dataset": {
            "id": "cli-fixture",
            "version": "1",
            "title": "CLI fixture",
            "source_url": "https://example.invalid/data",
            "retrieved_at": "2026-08-16T10:00:00Z",
        },
        "governance": {
            "access_basis": "approval",
            "approved_by": "owner",
            "approved_at": "2026-08-16T10:00:00Z",
            "allowed_uses": ["internal research"],
            "personal_data": "pseudonymous",
        },
        "split_policy": {"salt": "v1", "train": 1, "validation": 0, "test": 0},
        "samples": [
            {
                "id": "sample-1",
                "athlete_group_id": "athlete-1",
                "event_group_id": "event-1",
                "routine_group_id": "routine-1",
                "source_sha256": "a" * 64,
                "media_uri": "local://sample.mp4",
            }
        ],
    }
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    run(["validate-dataset", str(path)])
    output = json.loads(capsys.readouterr().out)
    assert output["valid"] is True
    assert output["assignments"] == {"sample-1": "train"}


def test_cli_proxy_plan_refuses_source_overwrite(tmp_path):
    source = tmp_path / "source.mp4"
    with pytest.raises(ValueError, match="overwrite"):
        run(["plan-proxy", str(source), str(source)])
