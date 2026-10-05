"""Explicit versioned native Windows inference installation (ADR-0053)."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from etsy_listings.core.workspace.atomic import write_json_atomic
from etsy_listings.core.workspace.workspace import remove_tree

if TYPE_CHECKING:
    from etsy_listings.core.preparation.worker_client import WarmWorker

ENGINE_VERSION = "1.0.0"
_LOCK = threading.Lock()


class SetupError(RuntimeError):
    """Installation failed without switching the last verified runtime."""


def _segment(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value in (".", "..")
        or any(
            c not in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-"
            for c in value
        )
    ):
        raise SetupError("Invalid engine version or installation ID")


@dataclass(frozen=True)
class Capability:
    available: bool
    problem: str | None
    engine_version: str | None = None
    required_engine: str = ENGINE_VERSION
    python: str | None = None
    details: dict[str, object] | None = None
    installation_id: str | None = None
    max_num_inference_steps: int = 10
    max_ensemble_size: int = 3
    max_image_dimension: int = 4096

    @property
    def update_available(self) -> bool:
        return self.available and self.engine_version != self.required_engine


class Installer(Protocol):
    def install(self, target: Path, weights: Path, version: str) -> Capability: ...
    def inspect(self, target: Path, weights: Path, version: str) -> Capability: ...


class Runtime:
    def __init__(
        self,
        *,
        home: Path | None = None,
        installer: Installer | None = None,
        engine_version: str = ENGINE_VERSION,
    ) -> None:
        _segment(engine_version)
        self.root = (home or Path.home()) / ".etsy-listings" / "marigold"
        self.engine_version = engine_version
        if installer is None:
            from etsy_listings.core.preparation.installation import NativeInstaller

            installer = NativeInstaller()
        self.installer = installer

    def inspect(self) -> Capability:
        try:
            current = json.loads((self.root / "current.json").read_text(encoding="utf-8"))
            if not isinstance(current, dict) or current.get("schema_version") != 1:
                raise SetupError("Unsupported installation pointer schema")
            return self.selection(
                current["engine_version"], installation_id=current["installation_id"]
            )
        except FileNotFoundError:
            return Capability(
                False,
                "Run etsy-listings marigold setup to install the native worker.",
                required_engine=self.engine_version,
            )
        except (ValueError, KeyError, TypeError, OSError, SetupError) as exc:
            return Capability(
                False,
                f"Invalid Marigold installation: {exc}. Run etsy-listings marigold update.",
                required_engine=self.engine_version,
            )

    def selection(self, version: str, *, installation_id: str | None = None) -> Capability:
        """Persist both IDs per job. A repair never redirects its selected files."""
        _segment(version)
        if installation_id is None:
            pointer = json.loads(
                (self.root / "runtimes" / version / "current.json").read_text(encoding="utf-8")
            )
            if not isinstance(pointer, dict) or pointer.get("schema_version") != 1:
                raise SetupError("Invalid installation pointer schema")
            installation_id = pointer.get("installation_id")
            if not isinstance(installation_id, str):
                raise SetupError("Invalid installation ID")
        _segment(installation_id)
        target = self.root / "runtimes" / version / installation_id
        if not target.resolve().is_relative_to((self.root / "runtimes").resolve()):
            raise SetupError("Runtime directory escapes installation")
        report = self.installer.inspect(target, self.root / "weights", version)
        return replace(report, required_engine=self.engine_version, installation_id=installation_id)

    def worker(self, selected: Capability, *, cache_root: Path) -> WarmWorker:
        """Construct a lazy warm adapter for a retained, verified engine selection."""
        from etsy_listings.core.preparation.installation import worker_command
        from etsy_listings.core.preparation.worker_client import WarmWorker

        if not selected.engine_version or not selected.installation_id:
            raise SetupError(selected.problem or "Run etsy-listings marigold setup first.")
        verified = self.selection(selected.engine_version, installation_id=selected.installation_id)
        if not verified.available or not verified.python:
            raise SetupError(
                verified.problem or "Selected worker is unavailable; run marigold setup."
            )
        return WarmWorker(
            worker_command(Path(verified.python), self.root / "weights", cache_root),
            cache_root=cache_root,
            engine_version=selected.engine_version,
        )

    def setup(self) -> Capability:
        existing = self.inspect()
        if existing.available:
            return existing
        return self.update()

    def update(self) -> Capability:
        """Stage, validate, then switch. Keep failed and in-use installations immutable."""
        with _LOCK:
            try:
                existing = self.selection(self.engine_version)
                if existing.available:
                    write_json_atomic(
                        self.root / "current.json", self._pointer(existing.installation_id)
                    )
                    return existing
            except (OSError, ValueError, KeyError, SetupError):
                pass
            installation_id = uuid.uuid4().hex
            engine = self.root / "runtimes" / self.engine_version
            staging = engine / (".staging-" + installation_id)
            target = engine / installation_id
            staging.mkdir(parents=True)
            try:
                report = self.installer.install(staging, self.root / "weights", self.engine_version)
                if not report.available or report.engine_version != self.engine_version:
                    raise SetupError(report.problem or "Worker capability mismatch")
                staging.rename(target)
                report = self.selection(self.engine_version, installation_id=installation_id)
                if not report.available:
                    raise SetupError(report.problem or "Relocated worker is unavailable")
            except BaseException as exc:
                if staging.exists():
                    try:
                        remove_tree(staging)
                    except OSError as cleanup:
                        exc.add_note(
                            f"Unactivated staging remains for cleanup: {staging}: {cleanup}"
                        )
                # A failed relocated installation is unreferenced. Retain it for
                # diagnostics; the next explicit retry gets a new immutable ID.
                raise
            pointer = self._pointer(installation_id)
            write_json_atomic(engine / "current.json", pointer)
            write_json_atomic(self.root / "current.json", pointer)
            return report

    def _pointer(self, installation_id: str | None) -> dict[str, object]:
        return {
            "schema_version": 1,
            "engine_version": self.engine_version,
            "installation_id": installation_id,
        }
