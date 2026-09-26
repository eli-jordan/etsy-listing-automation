"""`workspace/video.py`'s probe, against every clip the generator commits.

`scripts/generate_test_assets.py` writes each fixture to differ from the valid
one in exactly one fact, so each test here pins the one fact its clip exists
for. Whether that fact then *blocks* is `check_videos`'s question, not this
file's: the probe only reports what is there, and never raises.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.workspace.video import ProbeFailure, VideoFacts, probe_video

VIDEOS = Path(__file__).parent.parent / "fixtures" / "video"


def _facts(name: str) -> VideoFacts:
    facts = probe_video(VIDEOS / name)
    assert isinstance(facts, VideoFacts), facts
    return facts


def test_the_valid_clip_reports_its_size_duration_and_dimensions() -> None:
    facts = _facts("valid-3s-512.mp4")
    assert facts.size_bytes == (VIDEOS / "valid-3s-512.mp4").stat().st_size
    assert facts.duration_seconds == pytest.approx(3.2, abs=0.05)
    assert (facts.width, facts.height) == (512, 512)
    assert facts.has_audio is False


def test_the_short_clip_reports_two_seconds() -> None:
    assert _facts("short-2s-512.mp4").duration_seconds == pytest.approx(2.0, abs=0.05)


def test_the_small_clip_reports_400_pixels() -> None:
    facts = _facts("small-3s-400.mp4")
    assert (facts.width, facts.height) == (400, 400)


def test_a_clip_with_an_audio_track_says_so() -> None:
    assert _facts("with-audio-3s-512.mp4").has_audio is True


def test_audio_with_no_picture_is_a_failure_naming_the_missing_video_stream() -> None:
    failure = probe_video(VIDEOS / "audio-only-3s.mp4")
    assert isinstance(failure, ProbeFailure)
    assert "no video stream" in failure.reason


def test_a_png_renamed_mp4_is_a_failure_not_an_exception() -> None:
    """FFmpeg will happily open a PNG and decode its one frame, so this is
    refused by what the container *is*, whatever its name says."""
    failure = probe_video(VIDEOS / "png-renamed.mp4")
    assert isinstance(failure, ProbeFailure)
    assert "not an MP4 or MOV" in failure.reason


def test_a_missing_file_is_a_failure_not_an_exception(tmp_path: Path) -> None:
    failure = probe_video(tmp_path / "gone.mp4")
    assert isinstance(failure, ProbeFailure)
    assert "not found" in failure.reason


def test_an_empty_file_is_a_failure_not_an_exception(tmp_path: Path) -> None:
    empty = tmp_path / "empty.mov"
    empty.write_bytes(b"")
    failure = probe_video(empty)
    assert isinstance(failure, ProbeFailure)
    assert "not a readable video" in failure.reason
