"""Persisted job and event contract under ADR-0053."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from etsy_listings.core.preparation.artifacts import PreparationInputs

Phase = Literal["queued", "running", "cancelling", "cancelled", "superseded", "failed", "completed"]
Action = Literal["prepare", "prepare_again", "retry"]
TERMINAL = {"cancelled", "superseded", "failed", "completed"}


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Event(Record):
    sequence: int
    job_id: str
    phase: Phase
    step: str
    elapsed: float
    placements_completed: int
    placements_total: int
    error: str | None = None


class Prediction(Record):
    role: Literal["normals", "lighting", "depth"]
    path: str
    checksum: str


class CropEvidence(Record):
    id: str
    rectangle: tuple[int, int, int, int]
    size: tuple[int, int]
    identity: dict[str, str]
    predictions: tuple[Prediction, ...] = ()

    def semantic_digest(self) -> str:
        import hashlib

        from etsy_listings.core.workspace.calibration import json_bytes

        return hashlib.sha256(
            json_bytes({"rectangle": self.rectangle, "size": self.size, "identity": self.identity})
        ).hexdigest()


class Job(Record):
    schema_version: Literal[1] = 1
    id: str
    order: int
    template: str
    request_id: str
    request_digest: str
    receipts: dict[str, str] = Field(default_factory=dict)
    action: Action
    kind: Literal["prepare", "rebuild"]
    config_revision: str
    snapshot: PreparationInputs
    engine_version: str | None = None
    installation_id: str | None = None
    phase: Phase = "queued"
    step: str = "queued"
    created: float
    updated: float
    cancel_intent: bool = False
    evidence: tuple[CropEvidence, ...] = ()
    placement_evidence: dict[str, str] = Field(default_factory=dict)
    planned_masks: dict[str, str] = Field(default_factory=dict)
    cpu_checkpoints: dict[str, Any] = Field(default_factory=dict)
    placements_completed: int = 0
    result: dict[str, str] | None = None
    error: str | None = None
    events: tuple[Event, ...] = ()


def placement_key(value: str | None) -> str:
    return "" if value is None else value
