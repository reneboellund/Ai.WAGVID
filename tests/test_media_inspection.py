from fractions import Fraction
from pathlib import Path

import pytest

from ai_wagvid.media_inspection import (
    analysis_proxy_command,
    ffprobe_command,
    frame_timeline_probe_command,
    parse_ffprobe,
)


def test_probe_parser_preserves_fps_rotation_audio_and_duration():
    probe = parse_ffprobe(
        {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "30000/1001",
                    "r_frame_rate": "60/1",
                    "duration": "12.5",
                    "pix_fmt": "yuv420p",
                    "side_data_list": [{"rotation": -90}],
                },
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {"format_name": "mov,mp4", "duration": "12.6", "size": "12345"},
        }
    )
    assert probe.video.average_fps == Fraction(30000, 1001)
    assert probe.video.rotation_degrees == 270
    assert probe.video.likely_variable_frame_rate is True
    assert probe.audio_streams == 1
    assert probe.duration_s == 12.6
    assert probe.size_bytes == 12345


def test_probe_rejects_missing_video_or_dimensions():
    with pytest.raises(ValueError, match="no video"):
        parse_ffprobe({"streams": [{"codec_type": "audio"}]})
    with pytest.raises(ValueError, match="dimensions"):
        parse_ffprobe({"streams": [{"codec_type": "video", "width": 0, "height": 1}]})


def test_commands_are_argument_vectors_and_proxy_never_overwrites_source(tmp_path):
    source = tmp_path / "source video.mp4"
    destination = tmp_path / "proxy video.mp4"
    probe = ffprobe_command(source)
    assert probe[0] == "ffprobe"
    assert probe[-1] == str(source)
    proxy = analysis_proxy_command(source, destination)
    assert proxy[0] == "ffmpeg"
    assert proxy[-1] == str(destination)
    assert proxy[proxy.index("-fps_mode") + 1] == "passthrough"
    with pytest.raises(ValueError, match="overwrite"):
        analysis_proxy_command(source, Path(source))
    frame_probe = frame_timeline_probe_command(source)
    assert "-show_frames" in frame_probe
    assert "pkt_dts" in frame_probe[frame_probe.index("-show_entries") + 1]
