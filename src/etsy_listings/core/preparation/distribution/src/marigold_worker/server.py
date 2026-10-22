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
from pydantic import ValidationError

from .protocol import (
    MAX_LINE,
    REQUEST,
    Acknowledged,
    CancelRequest,
    Capabilities,
    Envelope,
    Failure,
    HelloReply,
    HelloRequest,
    InferenceMetadata,
    InferenceResult,
    InferenceSettings,
    InferRequest,
    Progress,
    Role,
    ShutdownRequest,
    describe,
    encode,
)

MAX_PIXELS = 4096 * 4096


class Backend(Protocol):
    def capabilities(self) -> Capabilities: ...
    def infer(
        self, role: Role, image: Image.Image, settings: InferenceSettings
    ) -> tuple[NDArray[np.float32], InferenceMetadata]: ...


def safe_path(root: Path, relative: str) -> Path:
    """The request model has already refused unsafe path syntax."""
    path = root.joinpath(*relative.split("/")).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Cache path escapes the cache root")
    return path


def serve(backend: Backend, *, cache_root: str, idle_seconds: float = 300) -> None:
    root = Path(cache_root)
    if not root.is_absolute():
        raise ValueError("Worker cache root must be native absolute")
    root = root.resolve()
    capabilities = backend.capabilities()
    pending: queue.Queue[InferRequest | None] = queue.Queue(maxsize=1)
    lock = threading.Lock()
    output_lock = threading.Lock()
    active: dict[str, Any] = {"id": None, "cancelled": False, "shutdown": False, "hello": False}

    def emit(reply: HelloReply | Progress | InferenceResult | Acknowledged | Failure) -> None:
        with output_lock:
            sys.stdout.write(encode(reply))
            sys.stdout.flush()

    def read() -> None:
        try:
            while line := sys.stdin.readline(MAX_LINE + 1):
                request_id = "invalid"
                try:
                    if len(line) > MAX_LINE or not line.endswith(chr(10)):
                        raise ValueError("Oversized or incomplete request")
                    raw = json.loads(line)
                    request_id = Envelope.model_validate(raw).request_id
                    request = REQUEST.validate_python(raw)
                    with lock:
                        if isinstance(request, CancelRequest):
                            if request.target == active["id"]:
                                active["cancelled"] = True
                            emit(Acknowledged(request_id=request_id))
                        elif isinstance(request, ShutdownRequest):
                            active["shutdown"] = True
                            active["cancelled"] = True
                            emit(Acknowledged(request_id=request_id))
                            if active["id"] is None:
                                pending.put_nowait(None)
                            return
                        elif isinstance(request, HelloRequest):
                            if active["id"] is not None:
                                raise ValueError("Worker is busy")
                            active["hello"] = True
                            emit(HelloReply(request_id=request_id, **capabilities.model_dump()))
                        else:
                            if not active["hello"]:
                                raise ValueError("Handshake required before inference")
                            if active["id"] is not None:
                                raise ValueError(
                                    "Worker is busy; only one inference call is allowed"
                                )
                            active["id"] = request_id
                            active["cancelled"] = False
                            pending.put_nowait(request)
                except (ValueError, TypeError, queue.Full) as exc:
                    reason = describe(exc) if isinstance(exc, ValidationError) else str(exc)
                    emit(Failure(request_id=request_id, code="invalid_request", message=reason))
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
        request_id = message.request_id
        temporary: Path | None = None
        try:
            role = message.role
            source = safe_path(root, message.input)
            destination = safe_path(root, message.output)
            if destination.exists():
                raise ValueError("Output already exists; choose a new evidence artifact")
            with Image.open(source) as opened:
                if max(opened.size) > 4096 or opened.width * opened.height > MAX_PIXELS:
                    raise ValueError("Inference image exceeds 4096 by 4096 pixel budget")
                image = opened.convert("RGB")
            emit(Progress(request_id=request_id, step=role))
            prediction, metadata = backend.infer(role, image, message.settings)
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
                    InferenceResult(
                        request_id=request_id,
                        artifact=message.output,
                        checksum=checksum,
                        cancelled=cancelled,
                        metadata=metadata,
                    )
                )
        except Exception as exc:
            if temporary:
                temporary.unlink(missing_ok=True)
            with lock:
                active["id"] = None
                emit(
                    Failure(
                        request_id=request_id,
                        code="inference_failed",
                        message=f"{exc}. Earlier evidence is retained; "
                        "retry with unchanged settings.",
                    )
                )
        with lock:
            if active["shutdown"]:
                return
