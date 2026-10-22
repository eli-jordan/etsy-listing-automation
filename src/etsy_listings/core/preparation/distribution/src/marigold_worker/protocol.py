"""Protocol v1: the JSON-lines contract between the application and this worker.

Every message on stdin and stdout is one of the models below, one JSON object
per line. The worker validates requests with ``REQUEST`` and the application
validates replies with ``REPLY``, so both sides share this single definition.
It depends only on pydantic: the application imports it from its embedded copy
of this distribution without installing or loading any model package.

The models describe the v1 bytes that 1.0.0 workers already emit. A change that
an installed worker would not understand needs a new ``PROTOCOL`` and engine
version, not an edit in place.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    StrictInt,
    Tag,
    TypeAdapter,
    ValidationError,
)

PROTOCOL: Final = 1
MAX_LINE: Final = 64 * 1024
"""Longest accepted line in either direction, newline included."""

Role = Literal["normals", "lighting", "depth"]
ROLES: Final[tuple[Role, ...]] = ("normals", "lighting", "depth")
RequestId = Annotated[str, Field(min_length=1, max_length=128)]


def _cache_file(suffix: str) -> AfterValidator:
    """A ``/``-separated path under the cache root. Containment in the actual
    root is checked by whoever resolves it; this rejects what is unsafe anywhere,
    including Windows drive and backslash forms on a non-Windows host."""

    def check(relative: str) -> str:
        if ":" in relative or chr(92) in relative:
            raise ValueError("Expected a relative cache path")
        if any(part in ("", ".", "..") for part in relative.split("/")):
            raise ValueError("Unsafe relative cache path")
        if not relative.endswith(suffix) or relative.rsplit("/", 1)[-1] == suffix:
            raise ValueError(f"Cache path must name a {suffix} file")
        return relative

    return AfterValidator(check)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Message(_Model):
    protocol: Literal[1] = PROTOCOL
    request_id: RequestId


class InferenceSettings(_Model):
    """The only caller-controlled sampling settings, bounded by this engine and
    always explicit."""

    num_inference_steps: Annotated[StrictInt, Field(ge=1, le=10)]
    ensemble_size: Annotated[StrictInt, Field(ge=1, le=3)]


# Requests: application to worker.


class HelloRequest(_Message):
    """Required once before inference. Answered with ``HelloReply``."""

    type: Literal["hello"] = "hello"


class InferRequest(_Message):
    """Predict ``role`` for the PNG crop at ``input``, writing an NPZ archive to
    ``output``. Answered with progress, then ``InferenceResult`` or ``Failure``."""

    type: Literal["infer"] = "infer"
    role: Role
    input: Annotated[str, _cache_file(".png")]
    output: Annotated[str, _cache_file(".npz")]
    settings: InferenceSettings


class CancelRequest(_Message):
    """Mark ``target`` cancelled. The active call still completes, and its
    result reports ``cancelled``. Acknowledged under its own request ID."""

    type: Literal["cancel"] = "cancel"
    target: str


class ShutdownRequest(_Message):
    """Acknowledge, then exit once any active call finishes."""

    type: Literal["shutdown"] = "shutdown"


Request = Annotated[
    HelloRequest | InferRequest | CancelRequest | ShutdownRequest,
    Field(discriminator="type"),
]
REQUEST: Final[TypeAdapter[Request]] = TypeAdapter(Request)


class Envelope(BaseModel):
    """The fields every message carries, read first so a request that fails
    full validation can still be answered under its own ID."""

    model_config = ConfigDict(extra="allow")

    protocol: Literal[1]
    request_id: RequestId


# Replies: worker to application.


class Capabilities(_Model):
    """What the installed engine provides. Printed by ``--capabilities`` and
    carried by ``HelloReply``."""

    engine_version: str
    roles: list[Role]
    cuda: bool
    gpu: str
    cuda_version: str
    model_ram_budget: int
    resident_models: int
    installed_packages: dict[str, str]
    """Every distribution in the worker environment, compared with its lock."""
    packages: dict[str, str]
    """The pinned model packages alone."""


class HelloReply(_Message, Capabilities):
    type: Literal["hello"] = "hello"


class Progress(_Message):
    type: Literal["progress"] = "progress"
    step: Role


class Transforms(_Model):
    original_crop_hw: list[int]
    processed_padded_hw: list[int]
    padding: list[int]
    output_pixel_centres: str


class InferenceMetadata(Capabilities):
    """Provenance and measurements for one prediction. Recorded as setup smoke
    evidence; preparation reads only the archive and its checksum."""

    checkpoint: str
    revision: str
    role: Role
    seed: int
    processing_resolution: int
    settings: InferenceSettings
    target_properties: dict[str, Any]
    """The diffusers pipeline's own description of its outputs."""
    normal_frame: str
    transforms: Transforms
    load_seconds: float
    inference_seconds: float
    warm_reuse: bool
    resident_model_bytes: int
    peak_allocated_bytes: int
    peak_reserved_bytes: int
    process_rss_bytes: int


class InferenceResult(_Message):
    """``artifact`` echoes the request's ``output``; ``checksum`` is the SHA-256
    of the archive bytes as written."""

    type: Literal["result"] = "result"
    artifact: str
    checksum: Annotated[str, Field(pattern="^[0-9a-f]{64}$")]
    cancelled: bool
    metadata: InferenceMetadata


class Acknowledged(_Message):
    """Answers a cancel or shutdown request."""

    type: Literal["result"] = "result"
    acknowledged: Literal[True] = True


class Failure(_Message):
    """``invalid_request`` refuses a message; ``inference_failed`` ends an
    accepted call without publishing its output."""

    type: Literal["error"] = "error"
    code: Literal["invalid_request", "inference_failed"]
    message: str


def _reply_tag(value: Any) -> str | None:
    # Inference results and acknowledgements share the "result" type in v1.
    if isinstance(value, dict):
        kind, acknowledged = value.get("type"), "acknowledged" in value
    else:
        kind, acknowledged = getattr(value, "type", None), isinstance(value, Acknowledged)
    if kind == "result":
        return "acknowledged" if acknowledged else "inference"
    return kind if isinstance(kind, str) else None


Reply = Annotated[
    Annotated[HelloReply, Tag("hello")]
    | Annotated[Progress, Tag("progress")]
    | Annotated[InferenceResult, Tag("inference")]
    | Annotated[Acknowledged, Tag("acknowledged")]
    | Annotated[Failure, Tag("error")],
    Discriminator(_reply_tag),
]
REPLY: Final[TypeAdapter[Reply]] = TypeAdapter(Reply)


def encode(message: _Message) -> str:
    """One protocol line, newline included."""
    return message.model_dump_json() + chr(10)


def describe(error: ValidationError) -> str:
    """A short, single-line account of why a message was refused."""
    return "; ".join(
        ".".join(str(part) for part in issue["loc"]) + ": " + issue["msg"]
        if issue["loc"]
        else issue["msg"]
        for issue in error.errors(include_url=False)
    )
