"""A warm JSON-lines v1 worker, without any model-package import."""

from __future__ import annotations

import io
import json
import os
import queue
import subprocess
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Any, Self, cast

from etsy_listings.core.preparation.predictions import cache_path, read_prediction

PROTOCOL = 1
CALL_TIMEOUT = 900.0
SHUTDOWN_TIMEOUT = 15.0
MAX_LINE = 64 * 1024


class WorkerError(RuntimeError):
    """A retryable worker failure. Settings and earlier evidence remain intact."""


class Worker:
    def __init__(
        self,
        command: Sequence[str],
        *,
        cache_root: Path,
        engine_version: str,
        timeout: float = CALL_TIMEOUT,
    ) -> None:
        self.cache_root = cache_root.resolve()
        self.engine_version = engine_version
        self.timeout = timeout
        self._messages: queue.Queue[dict[str, Any] | BaseException] = queue.Queue()
        self._diagnostics: deque[str] = deque(maxlen=32)
        self._controls: set[str] = set()
        self._write_lock = threading.Lock()
        self._call_lock = threading.Lock()
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
            bufsize=1,
        )
        self._stderr_thread = threading.Thread(target=self._stderr, daemon=True)
        self._stderr_thread.start()
        threading.Thread(target=self._stdout, daemon=True).start()
        try:
            request_id = self._send("hello")
            self.capabilities = self._receive(request_id, timeout=60)
            if (
                self.capabilities["type"] != "hello"
                or self.capabilities.get("engine_version") != engine_version
                or set(self.capabilities.get("roles", [])) != {"normals", "lighting", "depth"}
                or self.capabilities.get("cuda") is not True
            ):
                raise WorkerError("Worker capability mismatch; run etsy-listings marigold update.")
        except BaseException:
            self.close(force=True)
            raise

    def _stdout(self) -> None:
        assert self._process.stdout is not None
        try:
            while line := self._process.stdout.readline(MAX_LINE + 1):
                if len(line) > MAX_LINE or not line.endswith(chr(10)):
                    raise WorkerError("Worker emitted an oversized or incomplete protocol line")
                message = json.loads(line)
                if (
                    not isinstance(message, dict)
                    or message.get("protocol") != PROTOCOL
                    or not isinstance(message.get("request_id"), str)
                    or message.get("type") not in ("hello", "progress", "result", "error")
                ):
                    raise WorkerError("Malformed worker protocol message")
                self._messages.put(message)
            self._stderr_thread.join(timeout=0.2)
            raise WorkerError("Worker exited unexpectedly; retry preparation. " + self.diagnostics)
        except BaseException as exc:
            self._messages.put(exc)

    def _stderr(self) -> None:
        assert self._process.stderr is not None
        try:
            buffered = cast(io.BufferedReader, cast(io.TextIOWrapper, self._process.stderr).buffer)
            while chunk := buffered.read1(4096):
                self._diagnostics.append(chunk.decode("utf-8", errors="replace"))
        except (OSError, ValueError, UnicodeError):
            return

    @property
    def diagnostics(self) -> str:
        return "".join(self._diagnostics)[-8192:]

    def _send(self, kind: str, *, request_id: str | None = None, **body: Any) -> str:
        selected = request_id or uuid.uuid4().hex
        message = dict(protocol=PROTOCOL, type=kind, request_id=selected, **body)
        with self._write_lock:
            try:
                assert self._process.stdin is not None
                self._process.stdin.write(json.dumps(message) + chr(10))
                self._process.stdin.flush()
            except (OSError, ValueError) as exc:
                raise WorkerError("Worker is unavailable; retry preparation.") from exc
        return selected

    def _receive(
        self,
        request_id: str,
        *,
        timeout: float,
        progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            try:
                message = self._messages.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty as exc:
                self.close(force=True)
                raise WorkerError(
                    "Worker watchdog expired; retry preparation with unchanged settings."
                ) from exc
            if isinstance(message, BaseException):
                raise WorkerError(str(message)) from message
            if message["request_id"] in self._controls:
                self._controls.discard(message["request_id"])
                continue
            if message["request_id"] != request_id:
                raise WorkerError("Worker reply request ID does not match the active call")
            if message["type"] == "error":
                raise WorkerError(
                    str(message.get("message", "Inference failed; retry preparation."))
                )
            if message["type"] == "progress":
                if progress:
                    progress(message)
                continue
            return message

    def infer(
        self,
        *,
        request_id: str,
        role: str,
        input: str,
        output: str,
        size: tuple[int, int],
        num_inference_steps: int = 10,
        ensemble_size: int = 3,
        progress: Callable[[dict[str, Any]], None] | None = None,
        dispatch_guard: Callable[[], AbstractContextManager[None]] = nullcontext,
    ) -> dict[str, Any]:
        cache_path(self.cache_root, input, suffix=".png")
        destination = cache_path(self.cache_root, output, suffix=".npz")
        if not self._call_lock.acquire(blocking=False):
            raise WorkerError(
                "Worker is busy; additional calls must remain in the coordinator queue"
            )
        try:
            # The coordinator atomically rechecks cancellation with dispatch.
            # Do not hold its guard during handshake or model execution.
            with dispatch_guard():
                self._send(
                    "infer",
                    request_id=request_id,
                    role=role,
                    input=input,
                    output=output,
                    settings={
                        "num_inference_steps": num_inference_steps,
                        "ensemble_size": ensemble_size,
                    },
                )
            result = self._receive(request_id, timeout=self.timeout, progress=progress)
            if result["type"] != "result" or result.get("artifact") != output:
                raise WorkerError("Worker returned an unexpected artifact")
            read_prediction(destination, role=role, checksum=result.get("checksum", ""), size=size)
            return result
        finally:
            self._call_lock.release()

    @property
    def alive(self) -> bool:
        return self._process.poll() is None

    def cancel(self, request_id: str) -> None:
        """Control writes do not wait for the active inference response."""
        control = uuid.uuid4().hex
        self._controls.add(control)
        self._send("cancel", request_id=control, target=request_id)

    def close(self, *, force: bool = False) -> None:
        if self._process.poll() is None:
            if not force:
                try:
                    self._send("shutdown")
                    self._process.wait(timeout=SHUTDOWN_TIMEOUT)
                except (WorkerError, subprocess.TimeoutExpired):
                    force = True
            if force:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(self._process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=SHUTDOWN_TIMEOUT,
                        check=False,
                    )
                self._process.kill()
                self._process.wait(timeout=SHUTDOWN_TIMEOUT)
        for stream in (self._process.stdin, self._process.stdout, self._process.stderr):
            if stream:
                stream.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class WarmWorker:
    """Coordinator-owned adapter. Restart idle workers; never retry an active call.

    Hold one selected command for the job lifetime, so installing a newer engine
    cannot redirect recovered or running work to it (ADR-0053).
    """

    def __init__(
        self,
        command: Sequence[str],
        *,
        cache_root: Path,
        engine_version: str,
        timeout: float = CALL_TIMEOUT,
    ) -> None:
        self.command = tuple(command)
        self.cache_root = cache_root
        self.engine_version = engine_version
        self.timeout = timeout
        self._worker: Worker | None = None
        self._lock = threading.Lock()

    def infer(
        self,
        *,
        request_id: str,
        role: str,
        input: str,
        output: str,
        size: tuple[int, int],
        num_inference_steps: int = 10,
        ensemble_size: int = 3,
        progress: Callable[[dict[str, Any]], None] | None = None,
        dispatch_guard: Callable[[], AbstractContextManager[None]] = nullcontext,
    ) -> dict[str, Any]:
        if not self._lock.acquire(blocking=False):
            raise WorkerError("Worker is busy; keep additional work in the coordinator queue")
        try:
            if self._worker is None or not self._worker.alive:
                if self._worker:
                    self._worker.close()
                self._worker = Worker(
                    self.command,
                    cache_root=self.cache_root,
                    engine_version=self.engine_version,
                    timeout=self.timeout,
                )
            return self._worker.infer(
                request_id=request_id,
                role=role,
                input=input,
                output=output,
                size=size,
                num_inference_steps=num_inference_steps,
                ensemble_size=ensemble_size,
                progress=progress,
                dispatch_guard=dispatch_guard,
            )
        finally:
            self._lock.release()

    def cancel(self, request_id: str) -> None:
        if self._worker and self._worker.alive:
            self._worker.cancel(request_id)

    def close(self) -> None:
        if self._worker:
            self._worker.close()
            self._worker = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
