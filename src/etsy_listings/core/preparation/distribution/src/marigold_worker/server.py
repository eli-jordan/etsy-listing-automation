"""Protocol v1 server. The reader accepts controls while one model call runs."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import queue
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray
from PIL import Image

MAX_LINE = 65536
MAX_PIXELS = 4096 * 4096


class Backend(Protocol):
    def capabilities(self) -> dict[str, Any]: ...
    def infer(
        self, role: str, image: Image.Image, settings: dict[str, int]
    ) -> tuple[NDArray[np.float32], dict[str, Any]]: ...


def safe_path(root: Path, relative: object, suffix: str) -> Path:
    if not isinstance(relative, str) or ":" in relative or chr(92) in relative:
        raise ValueError("Expected a relative cache path")
    if any(part in ("", ".", "..") for part in relative.split("/")):
        raise ValueError("Unsafe relative cache path")
    path = root.joinpath(*relative.split("/")).resolve()
    if not path.is_relative_to(root) or path.suffix != suffix:
        raise ValueError("Cache path escape or unexpected file type")
    return path


def serve(backend: Backend, *, cache_root: str, idle_seconds: float = 300) -> None:
    root = Path(cache_root)
    if not root.is_absolute():
        raise ValueError("Worker cache root must be native absolute")
    root = root.resolve()
    capabilities = backend.capabilities()
    pending: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=1)
    lock = threading.Lock()
    output_lock = threading.Lock()
    active: dict[str, Any] = {"id": None, "cancelled": False, "shutdown": False, "hello": False}

    def emit(kind: str, request_id: str, **body: Any) -> None:
        with output_lock:
            print(
                json.dumps(dict(protocol=1, type=kind, request_id=request_id, **body)), flush=True
            )

    def read() -> None:
        try:
            while line := sys.stdin.readline(MAX_LINE + 1):
                request_id = "invalid"
                try:
                    if len(line) > MAX_LINE or not line.endswith(chr(10)):
                        raise ValueError("Oversized or incomplete request")
                    message = json.loads(line)
                    if not isinstance(message, dict) or message.get("protocol") != 1:
                        raise ValueError("Unsupported protocol")
                    candidate = message.get("request_id")
                    if not isinstance(candidate, str) or not candidate or len(candidate) > 128:
                        request_id = "invalid"
                        raise ValueError("Invalid request ID")
                    request_id = candidate
                    kind = message.get("type")
                    with lock:
                        if kind == "cancel":
                            if message.get("target") == active["id"]:
                                active["cancelled"] = True
                            emit("result", request_id, acknowledged=True)
                        elif kind == "shutdown":
                            active["shutdown"] = True
                            active["cancelled"] = True
                            emit("result", request_id, acknowledged=True)
                            if active["id"] is None:
                                pending.put_nowait(None)
                            return
                        elif kind == "hello":
                            if active["id"] is not None:
                                raise ValueError("Worker is busy")
                            active["hello"] = True
                            emit("hello", request_id, **capabilities)
                        elif kind == "infer":
                            if not active["hello"]:
                                raise ValueError("Handshake required before inference")
                            if active["id"] is not None:
                                raise ValueError(
                                    "Worker is busy; only one inference call is allowed"
                                )
                            active["id"] = request_id
                            active["cancelled"] = False
                            pending.put_nowait(message)
                        else:
                            raise ValueError("Unknown protocol request type")
                except (ValueError, TypeError, queue.Full) as exc:
                    emit("error", str(request_id), code="invalid_request", message=str(exc))
        finally:
            with lock:
                active["shutdown"] = True
                active["cancelled"] = True
                if active["id"] is None:
                    with contextlib.suppress(queue.Full):
                        pending.put_nowait(None)

    threading.Thread(target=read, daemon=True).start()
    while True:
        try:
            message = pending.get(timeout=idle_seconds)
        except queue.Empty:
            return
        if message is None:
            return
        request_id = message["request_id"]
        temporary: Path | None = None
        try:
            role = message.get("role")
            if role not in ("normals", "lighting", "depth"):
                raise ValueError("Unsupported prediction role")
            settings = message.get("settings")
            if not isinstance(settings, dict) or set(settings) != {
                "num_inference_steps",
                "ensemble_size",
            }:
                raise ValueError("Expected explicit inference steps and ensemble size")
            for key, limit in (("num_inference_steps", 10), ("ensemble_size", 3)):
                if type(settings[key]) is not int or not 1 <= settings[key] <= limit:
                    raise ValueError(f"{key} must be an integer in [1, {limit}] for this engine")
            source = safe_path(root, message.get("input"), ".png")
            destination = safe_path(root, message.get("output"), ".npz")
            if destination.exists():
                raise ValueError("Output already exists; choose a new evidence artifact")
            with Image.open(source) as opened:
                if max(opened.size) > 4096 or opened.width * opened.height > MAX_PIXELS:
                    raise ValueError("Inference image exceeds 4096 by 4096 pixel budget")
                image = opened.convert("RGB")
            emit("progress", request_id, step=role)
            prediction, metadata = backend.infer(role, image, settings)
            expected = (
                3 if role == "lighting" else 1,
                image.height,
                image.width,
                1 if role == "depth" else 3,
            )
            if (
                prediction.dtype != np.float32
                or prediction.shape != expected
                or not np.isfinite(prediction).all()
            ):
                raise ValueError("Model returned invalid prediction shape, dtype or finite values")
            if role == "normals":
                if not np.allclose(np.linalg.norm(prediction, axis=-1), 1, atol=0.02):
                    raise ValueError("Model normals are not unit vectors")
            elif prediction.min() < 0 or prediction.max() > 1:
                raise ValueError("Model prediction is outside [0, 1]")
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name("." + destination.name + "." + uuid.uuid4().hex)
            with temporary.open("wb") as stream:
                np.savez_compressed(stream, prediction=prediction)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            with destination.open("rb") as checksum_stream:
                checksum = hashlib.file_digest(checksum_stream, "sha256").hexdigest()
            with lock:
                cancelled = active["cancelled"]
                active["id"] = None
                emit(
                    "result",
                    request_id,
                    artifact=message["output"],
                    checksum=checksum,
                    cancelled=cancelled,
                    metadata=metadata,
                )
        except Exception as exc:
            if temporary:
                temporary.unlink(missing_ok=True)
            with lock:
                active["id"] = None
                emit(
                    "error",
                    request_id,
                    code="inference_failed",
                    message=f"{exc}. Earlier evidence is retained; retry with unchanged settings.",
                )
        with lock:
            if active["shutdown"]:
                return
