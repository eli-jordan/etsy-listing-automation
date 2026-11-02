"""Persisted job and event contract under ADR-0054."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from etsy_listings.core.preparation.artifacts import PlacementArtifact, PreparationInputs
from etsy_listings.core.preparation.evidence_reader import CropEvidence

Phase = Literal["queued", "running", "cancelling", "cancelled", "superseded", "failed", "completed"]
Action = Literal["prepare", "prepare_again", "retry"]
Quad = tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]
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


class Publication(Record):
    """The generation a completed job published."""

    generation_id: str
    content_digest: str


class Job(Record):
    schema_version: Literal[1] = 1
    id: str
    order: int
    template: str
    request_id: str
    request_digest: str
    receipts: dict[str, str] = Field(default_factory=dict)
    action: Action
    kind: Literal["prepare", "rebuild", "coverage"]
    """``coverage`` infers evidence for listing positions only and publishes
    no maps (option B, spec *Evidence coverage*)."""
    config_revision: str
    snapshot: PreparationInputs
    engine_version: str | None = None
    installation_id: str | None = None
    phase: Phase = "queued"
    step: str = "queued"
    created: float
    updated: float
    reset_masks_for_photo: bool = False
    cancel_intent: bool = False
    evidence: tuple[CropEvidence, ...] = ()
    placement_evidence: dict[str, str] = Field(default_factory=dict)
    planned_masks: dict[str, str] = Field(default_factory=dict)
    coverage: dict[str, Quad] = Field(default_factory=dict)
    """A coverage job's padded quad per placement key: the crops it infers."""
    cpu_checkpoints: dict[str, PlacementArtifact] = Field(default_factory=dict)
    placements_completed: int = 0
    result: Publication | None = None
    error: str | None = None
    events: tuple[Event, ...] = ()

    @field_validator("cpu_checkpoints", mode="before")
    @classmethod
    def _drop_damaged_checkpoints(cls, value: object) -> object:
        # A checkpoint only saves refitting its placement, so one that no
        # longer validates is dropped and refitted rather than making the
        # whole journal unreadable.
        if not isinstance(value, dict):
            return value
        kept: dict[str, PlacementArtifact] = {}
        for key, record in value.items():
            try:
                kept[key] = PlacementArtifact.model_validate(record)
            except ValidationError:
                continue
        return kept

    @property
    def last_event_sequence(self) -> int:
        return self.events[-1].sequence if self.events else 0
