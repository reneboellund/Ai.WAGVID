import json
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).parents[1]


def test_mobile_tokens_include_capture_and_upload_states() -> None:
    tokens = json.loads(
        (ROOT / "assets" / "ui" / "mobile-tokens.json").read_text(encoding="utf-8")
    )
    states = tokens["status_labels"]
    assert states["recording"] == "Optager"
    assert states["uploaded"] == "Uploadet · gemt lokalt"
    assert states["retry-wait"] == "Offline · prøver igen"
    assert tokens["minimum_touch_target_dp"] >= 48


def test_android_icon_resources_are_well_formed_xml() -> None:
    paths = [
        ROOT / "android" / "app" / "src" / "main" / "res" / "values" / "colors.xml",
        ROOT / "android" / "app" / "src" / "main" / "res" / "drawable" / "ic_launcher_foreground.xml",
        ROOT / "android" / "app" / "src" / "main" / "res" / "drawable" / "ic_launcher_monochrome.xml",
        ROOT / "android" / "app" / "src" / "main" / "res" / "mipmap-anydpi-v26" / "ic_launcher.xml",
    ]
    for path in paths:
        ElementTree.parse(path)


def test_canonical_app_icons_are_svg() -> None:
    for filename in ("app-icon.svg", "app-icon-monochrome.svg"):
        root = ElementTree.parse(ROOT / "assets" / "ui" / filename).getroot()
        assert root.tag.endswith("svg")
