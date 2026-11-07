"""What a mockup template's saved state is: the one way to ask.

A template folder is in exactly one of four states, and a caller needs to tell
them apart. It has no ``template.yaml`` yet (absent: the normal start of a
folder of photos), it has one that will not load (unreadable: a hand edit or a
damaged file), a calibration transaction stands in the way (needs repair), or
it is loaded. Reading a state never raises for any of those, so one template
that does not load stays that template's problem. A caller names what it needs
from the answer:

``state.config``
    The config, or ``None``: for a read that skips what will not load.
``state.reason``
    Why there is no config, or ``None``: for a read that reports it, such as a
    stage's ``Blocked`` (ADR-0053) or a row of the calibrator's rail.
``state.require()``
    The config, or the state's refusal: for an operation that cannot go on
    without it. These refusals have categories, which a bare
    ``ConfigLoadError`` does not, because what this file not loading means is
    settled here.

Who may roll a transaction forward is the one distinction left to the caller,
and it is a real one. :func:`template_state` is the observer's read and writes
nothing, so the CLI, the engine and the listing checks can never finish a save
a server is in the middle of: locks do not reach another process, and a
transaction on disk may be live. It reads as needing repair until the server
recovers it. ``CalibrationStore.state`` is the owner's read, for the server's
calibrator and preparation: it rolls an interrupted transaction forward first
(ADR-0054), and that is the only difference between the two. Import this module
directly, as ``listing_documents`` is.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

import yaml
from pydantic import ValidationError

from etsy_listings.core.config.errors import ConfigLoadError, format_validation_error
from etsy_listings.core.errors import ConflictError, MissingError
from etsy_listings.core.render.config import AnyTemplate, load_template_config
from etsy_listings.core.workspace import locks

if TYPE_CHECKING:
    from etsy_listings.core.workspace.workspace import Workspace

_LARGE_TEMPLATE_BYTES = 64 * 1024


class TemplateConfigMissingError(MissingError):
    """The template has no ``template.yaml`` -- the normal state of a folder
    nobody has given a kind yet: absent, not broken."""

    def __init__(self, name: str, reason: str) -> None:
        super().__init__(reason)
        self.name = name


class TemplateConfigUnreadableError(ConflictError):
    """The template has a ``template.yaml`` that does not load. The message is
    the loader's, naming the file and what is wrong with it."""

    def __init__(self, name: str, reason: str) -> None:
        super().__init__(reason)
        self.name = name


class CalibrationRepairRequiredError(ConflictError):
    """A calibration transaction is active or its recovery payload is damaged."""


@dataclass(frozen=True)
class TemplateLoaded:
    config: AnyTemplate
    reason: None = None

    def require(self) -> AnyTemplate:
        return self.config


@dataclass(frozen=True)
class TemplateAbsent:
    name: str
    config: None = None

    @property
    def reason(self) -> str:
        return f"no template.yaml for {self.name!r} -- calibrate it with `ui` first"

    def require(self) -> NoReturn:
        raise TemplateConfigMissingError(self.name, self.reason)


@dataclass(frozen=True)
class TemplateUnreadable:
    name: str
    reason: str
    config: None = None

    def require(self) -> NoReturn:
        raise TemplateConfigUnreadableError(self.name, self.reason)


@dataclass(frozen=True)
class TemplateNeedsRepair:
    reason: str
    config: None = None

    def require(self) -> NoReturn:
        raise CalibrationRepairRequiredError(self.reason)


TemplateState = TemplateLoaded | TemplateAbsent | TemplateUnreadable | TemplateNeedsRepair


def template_state(workspace: Workspace, name: str) -> TemplateState:
    """``name``'s state as it stands, under its template lock. Writes nothing:
    a transaction reads as needing repair, whoever left it. An unusable name
    still refuses, as every layout accessor does (ADR-0013)."""
    with locks.hold(workspace, "mockup-template", name):
        if workspace.template_calibration_transaction(name).exists():
            return TemplateNeedsRepair(
                "Active calibration transaction; retry after server recovery"
            )
        path = workspace.template_config_file(name)
        if not path.is_file():
            return TemplateAbsent(name)
        try:
            return TemplateLoaded(_read(path))
        except ConfigLoadError as exc:
            return TemplateUnreadable(name, str(exc))


def _read(path: Path) -> AnyTemplate:
    """One ``template.yaml``, parsed into whichever of the three kinds it is.
    Anything that stops that is a :class:`ConfigLoadError` naming the file."""
    try:
        text = path.read_text(encoding="utf-8")
        if len(text.encode("utf-8")) > _LARGE_TEMPLATE_BYTES:
            return load_template_config(yaml.safe_load(text))
        # Frozen template models can still contain mutable placement lists.
        # Never expose the retained parse object to a caller.
        return _parsed(text).model_copy(deep=True)
    except yaml.YAMLError as exc:
        raise ConfigLoadError(path, f"not valid YAML: {exc}") from exc
    except ValidationError as exc:
        raise format_validation_error(path, exc) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigLoadError(path, f"cannot be read: {exc}") from exc


@lru_cache(maxsize=64)
def _parsed(text: str) -> AnyTemplate:
    # Key by actual contents, never timestamps. The reader still observes
    # every external edit and transaction before reusing the parse result.
    return load_template_config(yaml.safe_load(text))
