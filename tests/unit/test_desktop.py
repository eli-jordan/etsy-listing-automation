"""How the calibrator is served: native window wrapping the HTTP app.

Unit-level because the interesting behaviour is orchestration -- which URL
the window opens, that the server is stopped when the window returns, that a
missing GUI backend is a message rather than a traceback -- not the WebView2
process itself. Opening a real native window is not a test this layer can
run; ``open_window`` takes an injectable backend so it never tries.
"""

from __future__ import annotations

import socket
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from etsy_listings.errors import UserFacingError
from etsy_listings.ui import desktop
from etsy_listings.workspace.workspace import Workspace


class FakeWebview:
    """Records ``create_window`` / ``start`` and optionally raises."""

    def __init__(self, *, fail: Exception | None = None) -> None:
        self.fail = fail
        self.windows: list[tuple[str, str, dict[str, Any]]] = []
        self.starts: list[dict[str, Any]] = []

    def create_window(self, title: str, url: str, **kwargs: Any) -> None:
        if self.fail is not None:
            raise self.fail
        self.windows.append((title, url, kwargs))

    def start(self, **kwargs: Any) -> None:
        self.starts.append(kwargs)


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


class TestPageUrl:
    def test_loopback_is_left_alone(self) -> None:
        assert desktop.page_url("127.0.0.1", 8000) == "http://127.0.0.1:8000"

    def test_wildcard_bind_opens_on_loopback(self) -> None:
        """WebView2 cannot navigate to 0.0.0.0; the page is on 127.0.0.1."""
        assert desktop.page_url("0.0.0.0", 9000) == "http://127.0.0.1:9000"
        assert desktop.page_url("::", 9000) == "http://127.0.0.1:9000"


class TestOpenWindow:
    def test_passes_the_url_title_and_debug_flag(self) -> None:
        backend = FakeWebview()
        desktop.open_window("http://127.0.0.1:9", debug=True, webview=backend)
        assert backend.windows[0][0] == desktop.WINDOW_TITLE
        assert backend.windows[0][1] == "http://127.0.0.1:9"
        assert backend.windows[0][2]["width"] == desktop.WINDOW_WIDTH
        assert backend.windows[0][2]["text_select"] is True
        assert backend.windows[0][2]["easy_drag"] is False
        assert backend.starts == [{"debug": True}]

    def test_a_backend_failure_is_user_facing(self) -> None:
        backend = FakeWebview(fail=RuntimeError("no WebView2"))
        with pytest.raises(UserFacingError, match="--browser") as caught:
            desktop.open_window("http://127.0.0.1:9", webview=backend)
        assert "no WebView2" in str(caught.value)

    def test_imports_webview_when_no_backend_is_passed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = FakeWebview()
        monkeypatch.setattr(desktop, "_import_webview", lambda: backend)
        desktop.open_window("http://127.0.0.1:9")
        assert backend.starts == [{"debug": False}]

    def test_missing_pywebview_is_user_facing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom() -> Any:
            raise UserFacingError(
                "pywebview is not installed. Run `uv sync`, or pass --browser "
                "to serve the calibrator in a regular browser."
            )

        monkeypatch.setattr(desktop, "_import_webview", boom)
        with pytest.raises(UserFacingError, match="--browser"):
            desktop.open_window("http://127.0.0.1:9")

    def test_user_facing_errors_are_not_wrapped(self) -> None:
        backend = FakeWebview(fail=UserFacingError("already explained"))
        with pytest.raises(UserFacingError, match="^already explained$"):
            desktop.open_window("http://127.0.0.1:9", webview=backend)


class TestImportWebview:
    def test_import_error_names_the_escape_hatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "webview" or name.startswith("webview."):
                raise ImportError("nope")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(UserFacingError, match="--browser"):
            desktop._import_webview()


class TestRunCalibrator:
    def test_browser_mode_runs_uvicorn_in_the_foreground(
        self, monkeypatch: pytest.MonkeyPatch, workspace: Workspace
    ) -> None:
        seen: list[dict[str, Any]] = []

        def fake_run(app: object, **kwargs: Any) -> None:
            seen.append(kwargs)
            assert app is not None

        monkeypatch.setattr(desktop.uvicorn, "run", fake_run)
        desktop.run_calibrator(workspace, host="127.0.0.1", port=8000, browser=True)
        assert seen == [{"host": "127.0.0.1", "port": 8000}]

    def test_windowed_mode_opens_the_page_then_stops_the_server(
        self,
        monkeypatch: pytest.MonkeyPatch,
        workspace: Workspace,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        stopped: list[bool] = []
        opened: list[tuple[str, bool]] = []

        class Handle:
            def stop(self) -> None:
                stopped.append(True)

        monkeypatch.setattr(desktop, "FRONTEND_DIST", Path("."))
        monkeypatch.setattr(desktop, "start_server", lambda app, host, port: Handle())
        monkeypatch.setattr(
            desktop, "open_window", lambda url, *, debug: opened.append((url, debug))
        )

        desktop.run_calibrator(workspace, host="127.0.0.1", port=8000, debug=True)

        assert opened == [("http://127.0.0.1:8000", True)]
        assert stopped == [True]
        assert "http://127.0.0.1:8000" in capsys.readouterr().out

    def test_windowed_mode_stops_the_server_if_the_window_fails(
        self, monkeypatch: pytest.MonkeyPatch, workspace: Workspace
    ) -> None:
        stopped: list[bool] = []

        class Handle:
            def stop(self) -> None:
                stopped.append(True)

        monkeypatch.setattr(desktop, "FRONTEND_DIST", Path("."))
        monkeypatch.setattr(desktop, "start_server", lambda app, host, port: Handle())

        def boom(url: str, *, debug: bool) -> None:
            raise UserFacingError("could not open a native window")

        monkeypatch.setattr(desktop, "open_window", boom)
        with pytest.raises(UserFacingError, match="native window"):
            desktop.run_calibrator(workspace)
        assert stopped == [True]

    def test_windowed_mode_refuses_without_a_built_frontend(
        self, monkeypatch: pytest.MonkeyPatch, workspace: Workspace, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(desktop, "FRONTEND_DIST", tmp_path / "missing-dist")
        with pytest.raises(UserFacingError, match="npm run build"):
            desktop.run_calibrator(workspace)


class TestStartServer:
    def test_serves_and_stop_closes_the_port(self) -> None:
        app = FastAPI()

        @app.get("/ping")
        def ping() -> dict[str, bool]:
            return {"ok": True}

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port: int = sock.getsockname()[1]

        server = desktop.start_server(app, "127.0.0.1", port)
        try:
            response = httpx.get(f"http://127.0.0.1:{port}/ping", timeout=2)
            assert response.json() == {"ok": True}
        finally:
            server.stop()
        # A refused connection is the honest proof, but on Windows the port
        # can linger in TIME_WAIT and httpx then times out rather than
        # ConnectError. The thread going quiet is the thing we control.
        assert not server._thread.is_alive()

    def test_a_dead_thread_is_user_facing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class DeadServer:
            started = False
            should_exit = False

            def run(self) -> None:
                return None

        monkeypatch.setattr(desktop.uvicorn, "Server", lambda config: DeadServer())
        with pytest.raises(UserFacingError, match="failed to start"):
            desktop.start_server(FastAPI(), "127.0.0.1", 9)

    def test_a_server_that_never_starts_times_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Hang:
            started = False
            should_exit = False

            def run(self) -> None:
                while not self.should_exit:
                    time.sleep(0.01)

        monkeypatch.setattr(desktop, "_SERVER_START_TIMEOUT_SECONDS", 0)
        monkeypatch.setattr(desktop.uvicorn, "Server", lambda config: Hang())
        with pytest.raises(UserFacingError, match="did not start"):
            desktop.start_server(FastAPI(), "127.0.0.1", 9)
