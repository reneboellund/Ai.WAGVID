"""Offline administrative CLI; validation commands do not download or run models."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from fractions import Fraction
from pathlib import Path
from typing import Any

from .dataset_manifest import load_dataset_manifest
from .media_inspection import analysis_proxy_command, parse_ffprobe
from .model_bundles import load_model_catalog, resolve_profile


def _json_safe(value: Any) -> Any:
    if isinstance(value, Fraction):
        return f"{value.numerator}/{value.denominator}"
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wagvid", description="Ai.WAGVID offline tooling")
    commands = parser.add_subparsers(dest="command", required=True)

    dataset = commands.add_parser("validate-dataset")
    dataset.add_argument("manifest", type=Path)
    dataset.add_argument(
        "--schema", type=Path, default=Path("schemas/dataset-manifest-v1.schema.json")
    )

    models = commands.add_parser("model-profile")
    models.add_argument("profile")
    models.add_argument("--catalog", type=Path, default=Path("config/model-bundles.yaml"))
    models.add_argument(
        "--schema", type=Path, default=Path("schemas/model-bundles-v1.schema.json")
    )

    probe = commands.add_parser("parse-ffprobe")
    probe.add_argument("input", type=Path, help="Previously captured ffprobe JSON")

    proxy = commands.add_parser("plan-proxy")
    proxy.add_argument("source", type=Path)
    proxy.add_argument("destination", type=Path)
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate-dataset":
        manifest = load_dataset_manifest(args.manifest, schema_path=args.schema)
        output = {
            "valid": True,
            "dataset": manifest["dataset"],
            "sample_count": len(manifest["samples"]),
            "assignments": manifest["assignments"],
        }
    elif args.command == "model-profile":
        profile = resolve_profile(
            load_model_catalog(args.catalog, schema_path=args.schema), args.profile
        )
        output = asdict(profile) | {"runnable": profile.runnable}
    elif args.command == "parse-ffprobe":
        output = asdict(parse_ffprobe(args.input.read_text(encoding="utf-8")))
    else:
        output = {"command": analysis_proxy_command(args.source, args.destination)}
    print(json.dumps(_json_safe(output), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
