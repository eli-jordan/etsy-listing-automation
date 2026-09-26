"""Reading a video file's facts, through PyAV (PRD 71).

The video gate (`config/listing_validation.check_videos`) is pure, so
something has to open the file first; this is that something, and the only
module that imports ``av``. It answers a :class:`VideoFacts` or a
:class:`ProbeFailure` and never raises: a clip is a file the seller dropped
in a directory, and one that will not open is a thing to tell them about in
the issues banner, not a traceback that takes the editor or a ``--all`` batch
down with it.

Metadata plus one decoded frame. The frame is what "decodable" means -- a
container can announce an H.264 stream whose packets are garbage, and Etsy
answers a file it cannot decode with a bare ``500`` (decision 9), so the
header alone is not proof enough. Nothing read here is hashed: the stage that
uploads a clip hashes its bytes, never these facts, which is why ``av`` needs
only a floor pin where OpenCV and Pillow are pinned exactly.
"""

from __future__ import annotations

from pathlib import Path

import av

from etsy_listings.config.media import ProbeFailure, VideoFacts

__all__ = ["ProbeFailure", "VideoFacts", "probe_video"]

_QUICKTIME_FAMILY = frozenset({"mov", "mp4"})


def probe_video(path: Path) -> VideoFacts | ProbeFailure:
    """The file's size, duration, pixel size and whether it carries audio."""
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
        # FFmpeg opens a PNG as a one-frame "video", so the extension is
        # checked against what the file actually is: Etsy takes MP4 and MOV,
        # and both are FFmpeg's one QuickTime-family demuxer.
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
