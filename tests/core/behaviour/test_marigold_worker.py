import sys

import pytest

from etsy_listings.core.preparation.worker_client import WarmWorker, Worker


def test_worker_handshake_drains_stderr_independently(tmp_path):
    script = tmp_path / "worker.py"
    script.write_text(
        """import json, sys
for line in sys.stdin:
    message = json.loads(line)
    if message['type'] == 'hello':
        sys.stderr.write('diagnostic ' * 20000)
        sys.stderr.flush()
        print(json.dumps(dict(protocol=1, type='hello',
            request_id=message['request_id'], engine_version='1.0.0',
            roles=['normals','lighting','depth'], cuda=True)), flush=True)
    elif message['type'] == 'shutdown':
        print(json.dumps(dict(protocol=1, type='result',
            request_id=message['request_id'])), flush=True)
        break
""",
        encoding="utf-8",
    )
    with Worker(
        [sys.executable, str(script)], cache_root=tmp_path, engine_version="1.0.0"
    ) as worker:
        assert worker.capabilities["roles"] == ["normals", "lighting", "depth"]


def test_cancellation_completes_active_call_and_retains_valid_evidence(tmp_path):
    import threading

    from PIL import Image

    from tests.support.marigold import controlled_worker

    Image.new("RGB", (12, 8)).save(tmp_path / "crop.png")
    results = []
    with Worker(
        controlled_worker(tmp_path, delay=0.5), cache_root=tmp_path, engine_version="1.0.0"
    ) as worker:
        started = threading.Event()
        thread = threading.Thread(
            target=lambda: results.append(
                worker.infer(
                    request_id="active",
                    role="depth",
                    input="crop.png",
                    output="depth.npz",
                    size=(12, 8),
                    progress=lambda _: started.set(),
                )
            )
        )
        thread.start()
        assert started.wait(5)
        worker.cancel("active")
        thread.join(5)
        assert not thread.is_alive()
        assert results[0]["cancelled"] is True
        assert (tmp_path / "depth.npz").exists()
        assert (
            worker.infer(
                request_id="retry", role="depth", input="crop.png", output="retry.npz", size=(12, 8)
            )["cancelled"]
            is False
        )


def test_worker_refuses_a_second_call_instead_of_queuing_after_cancellation(tmp_path):
    import threading

    import pytest
    from PIL import Image

    from etsy_listings.core.preparation.worker_client import WorkerError

    from tests.support.marigold import controlled_worker

    Image.new("RGB", (12, 8)).save(tmp_path / "crop.png")
    started = threading.Event()
    with Worker(
        controlled_worker(tmp_path, delay=0.4), cache_root=tmp_path, engine_version="1.0.0"
    ) as worker:
        thread = threading.Thread(
            target=lambda: worker.infer(
                request_id="active",
                role="depth",
                input="crop.png",
                output="depth.npz",
                size=(12, 8),
                progress=lambda _: started.set(),
            )
        )
        thread.start()
        assert started.wait(5)
        with pytest.raises(WorkerError, match="busy"):
            worker.infer(
                request_id="remaining",
                role="depth",
                input="crop.png",
                output="remaining.npz",
                size=(12, 8),
            )
        worker.cancel("active")
        thread.join(5)
        assert not (tmp_path / "remaining.npz").exists()


def test_idle_exit_restarts_on_next_call_without_failed_attempt(tmp_path):
    import time

    from PIL import Image

    from etsy_listings.core.preparation.worker_client import WarmWorker

    from tests.support.marigold import controlled_worker

    Image.new("RGB", (12, 8)).save(tmp_path / "crop.png")
    with WarmWorker(
        controlled_worker(tmp_path, idle=0.1), cache_root=tmp_path, engine_version="1.0.0"
    ) as worker:
        worker.infer(
            request_id="first", role="depth", input="crop.png", output="first.npz", size=(12, 8)
        )
        time.sleep(0.3)
        assert (
            worker.infer(
                request_id="second",
                role="depth",
                input="crop.png",
                output="second.npz",
                size=(12, 8),
            )["artifact"]
            == "second.npz"
        )


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
    import threading
    from contextlib import contextmanager

    from PIL import Image

    from etsy_listings.core.preparation.worker_client import WorkerError

    from tests.support.marigold import controlled_worker

    Image.new("RGB", (12, 8)).save(tmp_path / "crop.png")
    reached = threading.Event()
    release = threading.Event()
    cancelled = threading.Event()
    errors = []

    @contextmanager
    def dispatch_guard():
        reached.set()
        assert release.wait(5)
        if cancelled.is_set():
            raise WorkerError("Cancelled before dispatch")
        yield

    with adapter(
        controlled_worker(tmp_path), cache_root=tmp_path, engine_version="1.0.0"
    ) as worker:

        def infer():
            try:
                worker.infer(
                    request_id="pending",
                    role="depth",
                    input="crop.png",
                    output="refused.npz",
                    size=(12, 8),
                    dispatch_guard=dispatch_guard,
                )
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=infer)
        thread.start()
        assert reached.wait(5)
        cancelled.set()
        worker.cancel("pending")
        release.set()
        thread.join(5)
        assert not thread.is_alive()
        assert len(errors) == 1
        assert isinstance(errors[0], WorkerError)
        assert "before dispatch" in str(errors[0])
        assert not (tmp_path / "refused.npz").exists()
        output = adapter.__name__ + ".npz"
        assert (
            worker.infer(
                request_id="retry", role="depth", input="crop.png", output=output, size=(12, 8)
            )["artifact"]
            == output
        )


def test_warm_startup_cancellation_is_rechecked_before_dispatch(tmp_path):
    import threading
    import time
    from contextlib import contextmanager

    from PIL import Image

    from etsy_listings.core.preparation.worker_client import WorkerError

    from tests.support.marigold import controlled_worker

    Image.new("RGB", (12, 8)).save(tmp_path / "crop.png")
    command = controlled_worker(tmp_path)
    script = tmp_path / "controlled_worker.py"
    source = script.read_text(encoding="utf-8")
    source = source.replace(
        "    def capabilities(self):",
        """    def capabilities(self):
        from pathlib import Path
        Path('startup-ready').touch()
        while not Path('startup-release').exists():
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
    errors = []

    @contextmanager
    def guard():
        if cancelled.is_set():
            raise WorkerError("Cancelled during startup")
        yield

    with WarmWorker(command, cache_root=tmp_path, engine_version="1.0.0") as worker:

        def infer():
            try:
                worker.infer(
                    request_id="starting",
                    role="depth",
                    input="crop.png",
                    output="refused.npz",
                    size=(12, 8),
                    dispatch_guard=guard,
                )
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=infer)
        thread.start()
        deadline = time.monotonic() + 5
        while not (tmp_path / "startup-ready").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert (tmp_path / "startup-ready").exists()
        cancelled.set()
        worker.cancel("starting")
        (tmp_path / "startup-release").touch()
        thread.join(5)
        assert not thread.is_alive()
        assert len(errors) == 1 and "during startup" in str(errors[0])
        assert not (tmp_path / "refused.npz").exists()
        assert (
            worker.infer(
                request_id="retry", role="depth", input="crop.png", output="retry.npz", size=(12, 8)
            )["artifact"]
            == "retry.npz"
        )
