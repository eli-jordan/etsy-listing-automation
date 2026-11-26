"""What a mockup template's saved state is: absent, unreadable, needs repair or
loaded. The one way to ask; reading never raises."""

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
    def __init__(self, name: str, reason: str) -> None:
        super().__init__(reason)
        self.name = name


class TemplateConfigUnreadableError(ConflictError):
    def __init__(self, name: str, reason: str) -> None:
        super().__init__(reason)
        self.name = name


class CalibrationRepairRequiredError(ConflictError): ...


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
    try:
        text = path.read_text(encoding="utf-8")
        if len(text.encode("utf-8")) > _LARGE_TEMPLATE_BYTES:
            return load_template_config(yaml.safe_load(text))
        # A copy: frozen models still hold mutable placement lists.
        return _parsed(text).model_copy(deep=True)
    except yaml.YAMLError as exc:
        raise ConfigLoadError(path, f"not valid YAML: {exc}") from exc
    except ValidationError as exc:
        raise format_validation_error(path, exc) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigLoadError(path, f"cannot be read: {exc}") from exc


@lru_cache(maxsize=64)
def _parsed(text: str) -> AnyTemplate:
    return load_template_config(yaml.safe_load(text))
