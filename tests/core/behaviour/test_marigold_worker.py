import sys
import threading

import pytest

from etsy_listings.core.preparation.worker_client import WarmWorker, Worker

from tests.support.gates import GATE_TIMEOUT


def test_worker_handshake_drains_stderr_independently(tmp_path):
    from tests.support.marigold import capabilities_document

    script = tmp_path / "worker.py"
    script.write_text(
        f"""import json, sys
for line in sys.stdin:
    message = json.loads(line)
    if message['type'] == 'hello':
        sys.stderr.write('diagnostic ' * 20000)
        sys.stderr.flush()
        print(json.dumps(dict(protocol=1, type='hello',
            request_id=message['request_id'], **{capabilities_document()!r})),
            flush=True)
    elif message['type'] == 'shutdown':
        print(json.dumps(dict(protocol=1, type='result',
            request_id=message['request_id'], acknowledged=True)), flush=True)
        break
""",
        encoding="utf-8",
    )
    with Worker(
        [sys.executable, str(script)], cache_root=tmp_path, engine_version="1.0.0"
    ) as worker:
        assert worker.capabilities.roles == ["normals", "lighting", "depth"]


def test_cancellation_completes_active_call_and_retains_valid_evidence(tmp_path):
    from PIL import Image

    from tests.support.gates import workers
    from tests.support.marigold import controlled_worker

    Image.new("RGB", (12, 8)).save(tmp_path / "crop.png")
    with Worker(
        controlled_worker(tmp_path, hold=True), cache_root=tmp_path, engine_version="1.0.0"
    ) as worker:
        started = threading.Event()
        with workers() as start:
            try:
                active = start(
                    "active inference",
                    lambda: worker.infer(
                        request_id="active",
                        role="depth",
                        input="crop.png",
                        output="depth.npz",
                        size=(12, 8),
                        progress=lambda _: started.set(),
                    ),
                )
                assert started.wait(GATE_TIMEOUT)
                # The model call is held until this cancel is acknowledged.
                worker.cancel("active")
                result = active.result()
            finally:
                (tmp_path / "infer-release").touch()
        assert result.cancelled is True
        assert (tmp_path / "depth.npz").exists()
        assert (
            worker.infer(
                request_id="retry", role="depth", input="crop.png", output="retry.npz", size=(12, 8)
            ).cancelled
            is False
        )


def test_worker_refuses_a_second_call_instead_of_queuing_after_cancellation(tmp_path):
    from PIL import Image

    from etsy_listings.core.preparation.worker_client import WorkerError

    from tests.support.gates import workers
    from tests.support.marigold import controlled_worker

    Image.new("RGB", (12, 8)).save(tmp_path / "crop.png")
    started = threading.Event()
    with Worker(
        controlled_worker(tmp_path, hold=True), cache_root=tmp_path, engine_version="1.0.0"
    ) as worker:
        with workers() as start:
            try:
                active = start(
                    "active inference",
                    lambda: worker.infer(
                        request_id="active",
                        role="depth",
                        input="crop.png",
                        output="depth.npz",
                        size=(12, 8),
                        progress=lambda _: started.set(),
                    ),
                )
                assert started.wait(GATE_TIMEOUT)
                with pytest.raises(WorkerError, match="busy"):
                    worker.infer(
                        request_id="remaining",
                        role="depth",
                        input="crop.png",
                        output="remaining.npz",
                        size=(12, 8),
                    )
                worker.cancel("active")
                active.result()
            finally:
                (tmp_path / "infer-release").touch()
        assert not (tmp_path / "remaining.npz").exists()


def test_idle_exit_restarts_on_next_call_without_failed_attempt(tmp_path):
    from PIL import Image

    from etsy_listings.core.preparation.worker_client import WarmWorker

    from tests.support.marigold import controlled_worker, wait_until, worker_pids

    Image.new("RGB", (12, 8)).save(tmp_path / "crop.png")
    with WarmWorker(
        controlled_worker(tmp_path, idle=0.1), cache_root=tmp_path, engine_version="1.0.0"
    ) as worker:
        worker.infer(
            request_id="first", role="depth", input="crop.png", output="first.npz", size=(12, 8)
        )
        [first] = worker_pids(tmp_path)
        # The idle exit is observed, not guessed: the process is gone (and
        # reaped) before the next call. Waiting only for ``serve`` to return
        # races the interpreter's own exit.
        idle = worker._worker
        assert idle is not None
        wait_until(lambda: not idle.alive, "the idle worker's exit")
        assert (
            worker.infer(
                request_id="second",
                role="depth",
                input="crop.png",
                output="second.npz",
                size=(12, 8),
            ).artifact
            == "second.npz"
        )
        starts = worker_pids(tmp_path)
        assert len(starts) == 2 and starts[0] == first and starts[1] != first


def test_worker_protocol_rejects_unsafe_paths_and_malformed_requests(tmp_path):
    import json
    import subprocess

    from tests.support.marigold import controlled_worker

    requests = [
        {"protocol": 1, "type": "hello", "request_id": "hello"},
        {
            "protocol": 1,
            "type": "infer",
            "request_id": "unsafe",
            "role": "depth",
            "input": "../outside.png",
            "output": "prediction.npz",
            "settings": {"num_inference_steps": 10, "ensemble_size": 3},
        },
        {"protocol": 1, "type": "shutdown", "request_id": "shutdown"},
    ]
    result = subprocess.run(
        controlled_worker(tmp_path),
        input="".join(json.dumps(message) + chr(10) for message in requests),
        capture_output=True,
        text=True,
        timeout=5,
    )
    messages = [json.loads(line) for line in result.stdout.splitlines()]
    assert any(
        m["request_id"] == "unsafe" and m["type"] == "error" and "path" in m["message"]
        for m in messages
    )
    assert not (tmp_path / "prediction.npz").exists()


def test_watchdog_fails_without_publishing_partial_artifact(tmp_path):
    import pytest
    from PIL import Image

    from etsy_listings.core.preparation.worker_client import WorkerError

    from tests.support.marigold import controlled_worker

    Image.new("RGB", (12, 8)).save(tmp_path / "crop.png")
    with Worker(
        controlled_worker(tmp_path, delay=10),
        cache_root=tmp_path,
        engine_version="1.0.0",
        timeout=0.1,
    ) as worker:
        with pytest.raises(WorkerError, match="watchdog"):
            worker.infer(
                request_id="hung",
                role="depth",
                input="crop.png",
                output="partial.npz",
                size=(12, 8),
            )
        assert not worker.alive
    assert not (tmp_path / "partial.npz").exists()


@pytest.mark.parametrize("adapter", [Worker, WarmWorker])
def test_dispatch_guard_refuses_cancelled_call_and_allows_later_retry(tmp_path, adapter):
    from contextlib import contextmanager

    from PIL import Image

    from etsy_listings.core.preparation.worker_client import WorkerError

    from tests.support.gates import Gate, workers
    from tests.support.marigold import controlled_worker

    Image.new("RGB", (12, 8)).save(tmp_path / "crop.png")
    dispatch = Gate("the dispatch guard")
    cancelled = threading.Event()

    @contextmanager
    def dispatch_guard():
        dispatch.hold()
        if cancelled.is_set():
            raise WorkerError("Cancelled before dispatch")
        yield

    with adapter(
        controlled_worker(tmp_path), cache_root=tmp_path, engine_version="1.0.0"
    ) as worker:
        with workers(dispatch) as start:
            pending = start(
                "pending inference",
                lambda: worker.infer(
                    request_id="pending",
                    role="depth",
                    input="crop.png",
                    output="refused.npz",
                    size=(12, 8),
                    dispatch_guard=dispatch_guard,
                ),
            )
            dispatch.wait_entered()
            cancelled.set()
            worker.cancel("pending")
            dispatch.release()
            error = pending.outcome()
        assert isinstance(error, WorkerError)
        assert "before dispatch" in str(error)
        assert not (tmp_path / "refused.npz").exists()
        output = adapter.__name__ + ".npz"
        assert (
            worker.infer(
                request_id="retry", role="depth", input="crop.png", output=output, size=(12, 8)
            ).artifact
            == output
        )


def test_warm_startup_cancellation_is_rechecked_before_dispatch(tmp_path):
    from contextlib import contextmanager

    from PIL import Image

    from etsy_listings.core.preparation.worker_client import WorkerError

    from tests.support.gates import workers
    from tests.support.marigold import controlled_worker, wait_until

    Image.new("RGB", (12, 8)).save(tmp_path / "crop.png")
    command = controlled_worker(tmp_path)
    script = tmp_path / "controlled_worker.py"
    source = script.read_text(encoding="utf-8")
    source = source.replace(
        "    def capabilities(self):",
        """    def capabilities(self):
        from pathlib import Path
        Path('startup-ready').touch()
        deadline = time.monotonic() + 15
        while not Path('startup-release').exists():
            if time.monotonic() > deadline:
                raise RuntimeError('held startup was never released')
            time.sleep(0.01)""",
    )
    source = source.replace(
        "import numpy as np",
        "import os"
        + chr(10)
        + "os.chdir("
        + repr(str(tmp_path))
        + ")"
        + chr(10)
        + "import numpy as np",
    )
    script.write_text(source, encoding="utf-8")
    cancelled = threading.Event()

    @contextmanager
    def guard():
        if cancelled.is_set():
            raise WorkerError("Cancelled during startup")
        yield

    with WarmWorker(command, cache_root=tmp_path, engine_version="1.0.0") as worker:
        with workers() as start:
            try:
                starting = start(
                    "starting inference",
                    lambda: worker.infer(
                        request_id="starting",
                        role="depth",
                        input="crop.png",
                        output="refused.npz",
                        size=(12, 8),
                        dispatch_guard=guard,
                    ),
                )
                wait_until((tmp_path / "startup-ready").exists, "the worker's held startup")
                cancelled.set()
                worker.cancel("starting")
            finally:
                (tmp_path / "startup-release").touch()
            error = starting.outcome()
        assert isinstance(error, WorkerError) and "during startup" in str(error)
        assert not (tmp_path / "refused.npz").exists()
        assert (
            worker.infer(
                request_id="retry", role="depth", input="crop.png", output="retry.npz", size=(12, 8)
            ).artifact
            == "retry.npz"
        )
