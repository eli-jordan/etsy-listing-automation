"""A video file's facts, through PyAV; never raises.

Etsy answers a file it cannot decode with a bare ``500``, so a clip passes only
once one frame decodes. Nothing read here is hashed, so ``av`` needs only a
floor pin.
"""

from __future__ import annotations

from pathlib import Path

import av

from etsy_listings.core.config.media import ProbeFailure, VideoFacts

__all__ = ["ProbeFailure", "VideoFacts", "probe_video"]

_QUICKTIME_FAMILY = frozenset({"mov", "mp4"})


def probe_video(path: Path) -> VideoFacts | ProbeFailure:
    try:
        size_bytes = path.stat().st_size
    except OSError:
        return ProbeFailure("was not found")
    try:
        return _read(path, size_bytes)
    except (av.FFmpegError, OSError, ValueError) as exc:
        return ProbeFailure(f"is not a readable video ({exc})")


def _read(path: Path, size_bytes: int) -> VideoFacts | ProbeFailure:
    with av.open(str(path)) as container:
        # FFmpeg opens a PNG as a one-frame video. Etsy takes MP4 and MOV, both
        # FFmpeg's QuickTime-family demuxer.
        if not _QUICKTIME_FAMILY.intersection(container.format.name.split(",")):
            return ProbeFailure(
                f"is not an MP4 or MOV file, whatever its name says "
                f"(it reads as {container.format.long_name})"
            )
        if not container.streams.video:
            return ProbeFailure("has no video stream")
        stream = container.streams.video[0]
        if next(container.decode(stream), None) is None:
            return ProbeFailure("has a video stream with no frame that decodes")
        if stream.duration is not None and stream.time_base is not None:
            duration = float(stream.duration * stream.time_base)
        elif container.duration is not None:
            duration = container.duration / av.time_base
        else:
            return ProbeFailure("does not say how long it is")
        return VideoFacts(
            size_bytes=size_bytes,
            duration_seconds=duration,
            width=stream.codec_context.width,
            height=stream.codec_context.height,
            has_audio=bool(container.streams.audio),
        )
