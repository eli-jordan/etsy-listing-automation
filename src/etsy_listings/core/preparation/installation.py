"""Native installer boundary. Only explicit setup/update calls reach downloads."""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
import time
import tomllib
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

from etsy_listings.core.preparation.runtime import Capability, SetupError
from etsy_listings.core.preparation.worker_client import Worker, WorkerError
from etsy_listings.core.workspace.atomic import write_json_atomic

_REPORT_CACHE: dict[Path, tuple[object, float, Capability]] = {}
CAPABILITY_CACHE_SECONDS = 300.0

PYTHON_VERSION = "3.12.14"
REVISIONS = (
    "09cfdd258cb281fa006cf1afcd2284376d16687d",
    "08c3930bb641abf786ba44ce92547507ebefbc16",
    "9571e7123e258cf052b4e54241f17971c290e9a8",
)


def _run(command: list[str], *, timeout: float = 1800) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=True,
        )
        return result.stdout
    except (OSError, subprocess.SubprocessError) as exc:
        details = getattr(exc, "stderr", "") or str(exc)
        raise SetupError(f"Marigold setup failed: {details[-8192:]}") from exc


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def worker_command(python: Path, weights: Path, cache_root: Path | None = None) -> list[str]:
    command = [str(python), "-m", "marigold_worker", "--weights", str(weights.resolve())]
    if cache_root is not None:
        command.extend(["--cache-root", str(cache_root.resolve())])
    return command


class CommandRunner(Protocol):
    def __call__(self, command: list[str], *, timeout: float = 1800) -> str: ...


class NativeInstaller:
    def __init__(self, *, command_runner: CommandRunner = _run) -> None:
        self._run = command_runner

    def install(self, target: Path, weights: Path, version: str) -> Capability:
        try:
            return self._install(target, weights, version)
        except (WorkerError, OSError, ValueError, KeyError, TypeError) as exc:
            raise SetupError(f"Native Marigold setup failed: {exc}") from exc

    def _install(self, target: Path, weights: Path, version: str) -> Capability:
        if platform.system() != "Windows" or platform.machine() != "AMD64":
            raise SetupError(
                "Marigold setup supports native Windows x64 with NVIDIA CUDA. WSL is not required."
            )
        uv = shutil.which("uv")
        if uv is None:
            raise SetupError("Install uv, then run etsy-listings marigold setup.")
        distribution = Path(__file__).with_name("distribution")
        shutil.copytree(
            distribution,
            target / "distribution",
            ignore=shutil.ignore_patterns(".venv", "__pycache__", "*.pyc"),
        )
        project = target / "distribution"
        self._run(
            [
                uv,
                "sync",
                "--frozen",
                "--no-dev",
                "--no-editable",
                "--link-mode",
                "copy",
                "--python",
                PYTHON_VERSION,
                "--project",
                str(project.resolve()),
            ]
        )
        python = project / ".venv" / "Scripts" / "python.exe"
        command = worker_command(python, weights)
        self._run([*command, "--install-weights"])
        capabilities: dict[str, Any] = json.loads(
            self._run([*command, "--capabilities"], timeout=120)
        )
        self._verify_packages(project, capabilities)
        evidence = target / "smoke"
        evidence.mkdir()
        Image.new("RGB", (128, 128), (110, 150, 90)).save(evidence / "crop.png")
        smoke = {}
        with Worker(
            worker_command(python, weights, evidence), cache_root=evidence, engine_version=version
        ) as worker:
            for role in ("normals", "lighting", "depth"):
                result = worker.infer(
                    request_id="setup-" + role,
                    role=role,
                    input="crop.png",
                    output=role + ".npz",
                    size=(128, 128),
                )
                smoke[role] = result["metadata"]
        verified = {}
        for revision in REVISIONS:
            manifest = json.loads(
                (weights / revision / "verified.json").read_text(encoding="utf-8")
            )
            if manifest["revision"] != revision:
                raise SetupError("Unexpected checkpoint revision")
            verified[revision] = manifest["files"]
        files = {
            p.relative_to(project).as_posix(): _digest(p)
            for p in project.rglob("*")
            if p.is_file() and ".venv" not in p.parts
        }
        write_json_atomic(
            target / "installation.json",
            {
                "schema_version": 1,
                "engine_version": version,
                "python": PYTHON_VERSION,
                "files": files,
                "weights": verified,
                "packages": capabilities["installed_packages"],
                "smoke": smoke,
            },
        )
        return Capability(
            True, None, engine_version=version, python=str(python), details=capabilities
        )

    def _verify_packages(self, project: Path, capabilities: dict[str, Any]) -> None:
        lock = tomllib.loads((project / "uv.lock").read_text(encoding="utf-8"))
        expected = {p["name"]: p["version"] for p in lock["package"]}
        installed = capabilities["installed_packages"]
        if installed != expected:
            raise SetupError("Installed packages do not match the complete worker lock")

    def inspect(self, target: Path, weights: Path, version: str) -> Capability:
        try:
            manifest_file = target / "installation.json"
            if manifest_file.stat().st_size > 1024 * 1024:
                raise SetupError("Runtime installation manifest exceeds size limit")
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            paths = [manifest_file]
            project = target / "distribution"
            for relative in manifest["files"]:
                path = project / relative
                if not path.resolve().is_relative_to(project.resolve()):
                    raise SetupError("Unsafe worker distribution path")
                paths.append(path)
            for revision, files in manifest["weights"].items():
                for relative in files:
                    path = weights / revision / relative
                    if not path.resolve().is_relative_to(weights.resolve()):
                        raise SetupError("Unsafe checkpoint path")
                    paths.append(path)
            paths.extend((project / ".venv/Lib/site-packages").glob("*.dist-info/METADATA"))
            signature = tuple(
                (str(path), path.stat().st_size, path.stat().st_mtime_ns) for path in paths
            )
            cached = _REPORT_CACHE.get(target)
            if (
                cached
                and cached[0] == signature
                and time.monotonic() - cached[1] < CAPABILITY_CACHE_SECONDS
            ):
                return cached[2]
            report = self._inspect(target, weights, version)
            _REPORT_CACHE[target] = (signature, time.monotonic(), report)
            return report
        except (OSError, ValueError, KeyError, TypeError, SetupError) as exc:
            return Capability(
                False, f"{exc}. Run etsy-listings marigold update.", engine_version=version
            )

    def _inspect(self, target: Path, weights: Path, version: str) -> Capability:
        try:
            manifest = json.loads((target / "installation.json").read_text(encoding="utf-8"))
            if manifest["schema_version"] != 1 or manifest["engine_version"] != version:
                raise SetupError("Unsupported runtime installation manifest")
            project = target / "distribution"
            for relative, checksum in manifest["files"].items():
                path = project / relative
                if (
                    not path.resolve().is_relative_to(project.resolve())
                    or _digest(path) != checksum
                ):
                    raise SetupError("Worker distribution integrity mismatch")
            if set(manifest["weights"]) != set(REVISIONS):
                raise SetupError("Incomplete pinned checkpoints")
            for revision, files in manifest["weights"].items():
                for relative, descriptor in files.items():
                    path = weights / revision / relative
                    if not path.resolve().is_relative_to((weights / revision).resolve()):
                        raise SetupError("Unsafe checkpoint path")
                    if (
                        path.stat().st_size != descriptor["size"]
                        or _digest(path) != descriptor["sha256"]
                    ):
                        raise SetupError("Pinned weights failed integrity verification")
            python = project / ".venv" / "Scripts" / "python.exe"
            capabilities = json.loads(
                self._run([*worker_command(python, weights), "--capabilities"], timeout=120)
            )
            self._verify_packages(project, capabilities)
            if capabilities["engine_version"] != version or capabilities["cuda"] is not True:
                raise SetupError("Native worker or CUDA capability is unavailable")
            return Capability(
                True, None, engine_version=version, python=str(python), details=capabilities
            )
        except (OSError, ValueError, KeyError, TypeError, SetupError) as exc:
            return Capability(
                False,
                f"{exc}. Run etsy-listings marigold setup/update to repair the runtime.",
                engine_version=version,
            )
