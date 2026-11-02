"""Shared outcome rules for local CLI providers. Command and envelope formats stay local."""

import json
import subprocess
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from etsy_listings.core.ai.errors import (
    ProviderCancelledError,
    ProviderGenerationError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    classify_process_failure,
)
from etsy_listings.core.ai.host import LOCAL_CLI_HOST, CliHost, CommandHost
from etsy_listings.core.ai.models import (
    Deadline,
    ProviderReadiness,
    ProviderTask,
    RawProviderResult,
    RepairContext,
)
from etsy_listings.core.ai.process import ProcessResult
from etsy_listings.core.ai.repair import prompt_text_for

READINESS_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class Invocation:
    task: ProviderTask
    deadline: Deadline
    prompt_text: str
    cancel_event: threading.Event | None


@dataclass
class LocalCliProvider(ABC):
    """One public provider contract; subclasses own their CLI command and response format."""

    workspace_root: Path
    binary: str
    model: str | None = None
    effort: str | None = None
    host: CliHost = field(default=LOCAL_CLI_HOST, repr=False, compare=False)
    """Where the CLI is looked up and run; tests pass a scripted machine."""
    provider_name: ClassVar[str]
    image_tool: ClassVar[str | None] = None

    def _resolved_binary(self) -> str:
        # Windows npm shims need PATHEXT resolution before CreateProcess.
        return self.host.which(self.binary) or self.binary

    def readiness(self) -> ProviderReadiness:
        return readiness(self.host, self.binary, self._check_authenticated, self._check_capability)

    @abstractmethod
    def _check_authenticated(self) -> ProviderReadiness | None: ...

    @abstractmethod
    def _check_capability(self) -> ProviderReadiness | None: ...

    def generate(
        self,
        task: ProviderTask,
        deadline: Deadline,
        *,
        repair: RepairContext | None = None,
        cancel_event: threading.Event | None = None,
    ) -> RawProviderResult:
        require_binary(self.host, self.provider_name, self.binary)
        prompt = prompt_text_for(task, repair, image_tool=self.image_tool)
        return self._generate(Invocation(task, deadline, prompt, cancel_event))

    @abstractmethod
    def _generate(self, invocation: Invocation) -> RawProviderResult: ...


def require_binary(host: CommandHost, provider: str, binary: str) -> None:
    if host.which(binary) is None:
        raise ProviderUnavailableError(provider, f"{binary} was not found on PATH")


def readiness(
    host: CommandHost,
    binary: str,
    authenticated: Callable[[], ProviderReadiness | None],
    capability: Callable[[], ProviderReadiness | None],
) -> ProviderReadiness:
    if host.which(binary) is None:
        return ProviderReadiness(ready=False, reason=f"{binary} was not found on PATH")
    for check in (authenticated, capability):
        unavailable = check()
        if unavailable is not None:
            return unavailable
    return ProviderReadiness(ready=True)


def json_object(provider: str, stdout: str) -> dict[str, Any]:
    try:
        envelope: Any = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ProviderGenerationError(provider, 0, f"stdout was not valid JSON: {exc}") from exc
    if not isinstance(envelope, dict):
        raise ProviderGenerationError(provider, 0, "stdout was not a JSON object")
    return envelope


def probe(
    host: CommandHost, binary: str, args: tuple[str, ...]
) -> subprocess.CompletedProcess[str] | ProviderReadiness:
    command = " ".join((binary, *args))
    try:
        return host.run([host.which(binary) or binary, *args], timeout=READINESS_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as exc:
        return ProviderReadiness(ready=False, reason=f"could not check `{command}`: {exc}")


def check_capability(
    host: CommandHost,
    binary: str,
    args: tuple[str, ...],
    required: tuple[str, ...],
    description: str,
) -> ProviderReadiness | None:
    result = probe(host, binary, args)
    if isinstance(result, ProviderReadiness):
        return result
    if result.returncode != 0:
        command = " ".join((binary, *args))
        return ProviderReadiness(ready=False, reason=f"`{command}` exited {result.returncode}")
    missing = [flag for flag in required if flag not in result.stdout]
    if missing:
        return ProviderReadiness(
            ready=False,
            reason=(
                f"the installed {binary} CLI does not support the required "
                f"{description} flags: {', '.join(missing)}"
            ),
        )
    return None


def auth_probe(
    host: CommandHost, binary: str, command: str
) -> subprocess.CompletedProcess[str] | ProviderReadiness:
    result = probe(host, binary, (command, "status"))
    if isinstance(result, ProviderReadiness):
        return result
    if result.returncode != 0:
        return ProviderReadiness(
            ready=False,
            reason=(
                f"{binary} is not authenticated "
                f"(`{binary} {command} status` exited {result.returncode})"
            ),
        )
    return result


def check_result(provider: str, result: ProcessResult) -> None:
    if result.cancelled:
        raise ProviderCancelledError(provider)
    if result.timed_out:
        raise ProviderTimeoutError(provider)
    if result.returncode != 0:
        raise classify_process_failure(
            provider,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
