"""Atomic journal writes precede observations and live notifications."""

import threading
import time
from typing import Any

from etsy_listings.core.application.preparation.models import Event, Job
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.atomic import write_bytes_atomic
from etsy_listings.core.workspace.calibration import json_bytes


class Store:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.condition = threading.Condition(threading.RLock())

    def read(self, identity: str) -> Job:
        path = self.workspace.preparation_job_file(identity)
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("Preparation journal exceeds size limit")
        record = Job.model_validate_json(path.read_bytes())
        if record.id != identity:
            raise ValueError("Preparation journal ID does not match its filename")
        self.workspace.template_dir(record.template)
        return record

    def jobs(self) -> list[Job]:
        with self.condition:
            return sorted(
                (self.read(v) for v in self.workspace.preparation_jobs()), key=lambda j: j.order
            )

    def write(self, job: Job, **changes: Any) -> Job:
        with self.condition:
            now = time.time()
            job = job.model_copy(update={**changes, "updated": now})
            event = Event(
                sequence=job.events[-1].sequence + 1 if job.events else 1,
                job_id=job.id,
                phase=job.phase,
                step=job.step,
                elapsed=max(0, now - job.created),
                placements_completed=job.placements_completed,
                placements_total=len(job.snapshot.placements),
                error=job.error,
            )
            last = job.events[-1] if job.events else None
            if last is None or (last.phase, last.step, last.placements_completed, last.error) != (
                event.phase,
                event.step,
                event.placements_completed,
                event.error,
            ):
                job = job.model_copy(update={"events": (*job.events, event)[-512:]})
            data = json_bytes(job.model_dump(mode="json"))
            if len(data) > 4 * 1024 * 1024:
                raise ValueError("Preparation journal exceeds size limit")
            write_bytes_atomic(self.workspace.preparation_job_file(job.id), data, durable=True)
            self.condition.notify_all()
            return job
