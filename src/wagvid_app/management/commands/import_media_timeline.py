"""Persist a validated canonical frame timeline from an existing FFprobe JSON payload."""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from wagvid_app.media_timeline_store import persist_media_timeline, timeline_object_key
from wagvid_app.models import MediaAsset


class Command(BaseCommand):
    help = "Persist canonical PTS/DTS frame metadata for a verified MediaAsset"

    def add_arguments(self, parser):
        parser.add_argument("media_id")
        parser.add_argument("ffprobe_json", type=Path)
        parser.add_argument("--stream-index", type=int, default=0)

    def handle(self, *args, **options):
        try:
            media = MediaAsset.objects.get(pk=options["media_id"])
        except (MediaAsset.DoesNotExist, ValueError) as error:
            raise CommandError("MediaAsset was not found") from error
        path = options["ffprobe_json"]
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CommandError(f"Cannot read FFprobe JSON: {error}") from error
        try:
            timeline = persist_media_timeline(
                media,
                payload,
                stream_index=options["stream_index"],
            )
        except (ValueError, OSError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            self.style.SUCCESS(
                f"Persisted {len(timeline.frames)} canonical frames "
                f"({timeline.digest[:12]}…) at {timeline_object_key(media)}"
            )
        )
