import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).parents[1]


def load_routes() -> dict:
    return yaml.safe_load(
        (ROOT / "product" / "ui-routes.yaml").read_text(encoding="utf-8")
    )


def test_ui_route_registry_is_valid() -> None:
    schema = json.loads(
        (ROOT / "schemas" / "ui-route-registry-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert list(Draft202012Validator(schema).iter_errors(load_routes())) == []


def test_operational_product_has_no_missing_core_area() -> None:
    areas = {screen["area"] for screen in load_routes()["screens"]}
    assert {
        "overview",
        "operations",
        "master-data",
        "media",
        "training",
        "competition",
        "analysis",
        "review",
        "devices",
        "exchange",
        "research",
        "system",
        "administration",
    } <= areas


def test_critical_recovery_and_manual_control_actions_exist() -> None:
    screens = {screen["id"]: screen for screen in load_routes()["screens"]}
    assert "stop" in screens["operate"]["actions"]
    assert "stop" in screens["device-detail"]["actions"]
    assert "download-errors" in screens["imports"]["actions"]
    assert "retry-safe-failure" in screens["system-status"]["actions"]
    assert "start-restore-rehearsal" in screens["backups"]["actions"]


def test_admin_is_not_available_to_viewer() -> None:
    for screen in load_routes()["screens"]:
        if screen["area"] == "administration":
            assert "viewer" not in screen["roles"]
