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
from typing import Protocol

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

MAX_DIMENSION = 4096
MAX_PIXELS = MAX_DIMENSION * MAX_DIMENSION

Reply = HelloReply | Progress | InferenceResult | Acknowledged | Failure


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


def _invalid(message: str) -> None:
    # S01 TRY301: the request loop answers this; the raise stays out of its try.
    raise ValueError(message)


def _open_image(source: Path) -> Image.Image:
    with Image.open(source) as opened:
        if max(opened.size) > MAX_DIMENSION or opened.width * opened.height > MAX_PIXELS:
            _invalid("Inference image exceeds 4096 by 4096 pixel budget")
        image: Image.Image = opened.convert("RGB")
    return image


def _check_prediction(role: Role, image: Image.Image, prediction: NDArray[np.float32]) -> None:
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
        _invalid("Model returned invalid prediction shape, dtype or finite values")
    if role == "normals":
        if not np.allclose(np.linalg.norm(prediction, axis=-1), 1, atol=0.02):
            _invalid("Model normals are not unit vectors")
    elif prediction.min() < 0 or prediction.max() > 1:
        _invalid("Model prediction is outside [0, 1]")


def _publish(destination: Path, prediction: NDArray[np.float32]) -> str:
    """Write the prediction beside ``destination``, fsync it, move it into
    place and return its sha256. A failure removes the temporary file."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name("." + destination.name + "." + uuid.uuid4().hex)
    try:
        with temporary.open("wb") as stream:
            np.savez_compressed(stream, prediction=prediction)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    with destination.open("rb") as checksum_stream:
        return hashlib.file_digest(checksum_stream, "sha256").hexdigest()


class _Session:
    """One worker process's state, shared by the control reader thread and the
    model call loop. ``lock`` guards the active call's fields, and replies that
    change them are written under it; ``output_lock`` keeps each reply line
    whole."""

    def __init__(self, backend: Backend, root: Path) -> None:
        self.backend = backend
        self.root = root
        self.capabilities = backend.capabilities()
        self.pending: queue.Queue[InferRequest | None] = queue.Queue(maxsize=1)
        self.lock = threading.Lock()
        self.output_lock = threading.Lock()
        self.active: str | None = None
        self.cancelled = False
        self.shutdown = False
        self.hello = False

    def emit(self, reply: Reply) -> None:
        with self.output_lock:
            sys.stdout.write(encode(reply))
            sys.stdout.flush()

    # The control reader thread.

    def read(self) -> None:
        try:
            while line := sys.stdin.readline(MAX_LINE + 1):
                if self._read_line(line):
                    return
        finally:
            with self.lock:
                self.shutdown = True
                self.cancelled = True
                if self.active is None:
                    with contextlib.suppress(queue.Full):
                        self.pending.put_nowait(None)

    def _read_line(self, line: str) -> bool:
        """Answer one request line. True once the reader should stop."""
        request_id = "invalid"
        try:
            if len(line) > MAX_LINE or not line.endswith(chr(10)):
                _invalid("Oversized or incomplete request")
            raw = json.loads(line)
            request_id = Envelope.model_validate(raw).request_id
            request = REQUEST.validate_python(raw)
            with self.lock:
                return self._control(request, request_id)
        except (ValueError, TypeError, queue.Full) as exc:
            reason = describe(exc) if isinstance(exc, ValidationError) else str(exc)
            self.emit(Failure(request_id=request_id, code="invalid_request", message=reason))
            return False

    def _control(
        self,
        request: HelloRequest | InferRequest | CancelRequest | ShutdownRequest,
        request_id: str,
    ) -> bool:
        """Apply one request under ``lock``. True for shutdown."""
        if isinstance(request, CancelRequest):
            if request.target == self.active:
                self.cancelled = True
            self.emit(Acknowledged(request_id=request_id))
        elif isinstance(request, ShutdownRequest):
            self.shutdown = True
            self.cancelled = True
            self.emit(Acknowledged(request_id=request_id))
            if self.active is None:
                self.pending.put_nowait(None)
            return True
        elif isinstance(request, HelloRequest):
            self._greet(request_id)
        else:
            self._accept(request, request_id)
        return False

    def _greet(self, request_id: str) -> None:
        if self.active is not None:
            _invalid("Worker is busy")
        self.hello = True
        self.emit(HelloReply(request_id=request_id, **self.capabilities.model_dump()))

    def _accept(self, request: InferRequest, request_id: str) -> None:
        if not self.hello:
            _invalid("Handshake required before inference")
        if self.active is not None:
            _invalid("Worker is busy; only one inference call is allowed")
        self.active = request_id
        self.cancelled = False
        self.pending.put_nowait(request)

    # The model call loop, on the main thread.

    def run(self, message: InferRequest) -> None:
        """Run one accepted call; answer with its result or a Failure."""
        try:
            checksum, metadata = self._infer(message)
            with self.lock:
                cancelled = self.cancelled
                self.active = None
                self.emit(
                    InferenceResult(
                        request_id=message.request_id,
                        artifact=message.output,
                        checksum=checksum,
                        cancelled=cancelled,
                        metadata=metadata,
                    )
                )
        except Exception as exc:  # noqa: BLE001 -- one failed call becomes a protocol Failure; the worker stays up
            with self.lock:
                self.active = None
                self.emit(
                    Failure(
                        request_id=message.request_id,
                        code="inference_failed",
                        message=f"{exc}. Earlier evidence is retained; "
                        "retry with unchanged settings.",
                    )
                )

    def _infer(self, message: InferRequest) -> tuple[str, InferenceMetadata]:
        role = message.role
        source = safe_path(self.root, message.input)
        destination = safe_path(self.root, message.output)
        if destination.exists():
            _invalid("Output already exists; choose a new evidence artifact")
        image = _open_image(source)
        self.emit(Progress(request_id=message.request_id, step=role))
        prediction, metadata = self.backend.infer(role, image, message.settings)
        _check_prediction(role, image, prediction)
        return _publish(destination, prediction), metadata

    def stopping(self) -> bool:
        with self.lock:
            return self.shutdown


def serve(backend: Backend, *, cache_root: str, idle_seconds: float = 300) -> None:
    root = Path(cache_root)
    if not root.is_absolute():
        raise ValueError("Worker cache root must be native absolute")
    session = _Session(backend, root.resolve())
    threading.Thread(target=session.read, daemon=True).start()
    while True:
        try:
            message = session.pending.get(timeout=idle_seconds)
        except queue.Empty:
            return
        if message is None:
            return
        session.run(message)
        if session.stopping():
            return
