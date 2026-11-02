"""Common CLI outcome rules, independent of any provider's envelope format."""

import subprocess

import pytest

from etsy_listings.core.ai import cli_support
from etsy_listings.core.ai.errors import (
    ProviderCancelledError,
    ProviderGenerationError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from etsy_listings.core.ai.models import ProviderReadiness
from etsy_listings.core.ai.process import ProcessResult


def test_cancellation_takes_precedence_over_timeout_and_exit_status():
    result = ProcessResult(1, "", "not logged in", timed_out=True, cancelled=True)
    with pytest.raises(ProviderCancelledError):
        cli_support.check_result("test", result)


def test_timeout_takes_precedence_over_exit_status():
    result = ProcessResult(1, "", "not logged in", timed_out=True, cancelled=False)
    with pytest.raises(ProviderTimeoutError):
        cli_support.check_result("test", result)


def test_probe_reports_the_command_that_could_not_start(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("missing executable")

    monkeypatch.setattr("subprocess.run", fail)
    result = cli_support.probe("custom-cli", ("exec", "--help"))
    assert result.reason == "could not check `custom-cli exec --help`: missing executable"


@pytest.mark.parametrize("stdout", ["[]", "null", "not json"])
def test_only_json_objects_are_provider_envelopes(stdout):
    with pytest.raises(ProviderGenerationError):
        cli_support.json_object("test", stdout)


def test_capability_reports_missing_flags_in_declaration_order(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], 0, "--tools")
    )
    result = cli_support.check_capability(
        "test", ("--help",), ("--schema", "--tools", "--readonly"), "headless"
    )
    assert result.reason == (
        "the installed test CLI does not support the required headless flags: --schema, --readonly"
    )


def test_readiness_stops_before_capability_when_authentication_fails(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda binary: "/resolved/test")
    unavailable = ProviderReadiness(ready=False, reason="not authenticated")

    def capability():
        pytest.fail("capability probe must wait for authentication")

    assert cli_support.readiness("test", lambda: unavailable, capability) == unavailable


def test_generation_refuses_a_missing_binary_before_launch(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda binary: None)
    with pytest.raises(ProviderUnavailableError, match="custom-cli was not found on PATH"):
        cli_support.require_binary("test", "custom-cli")


def test_failed_auth_probe_preserves_command_and_exit_code(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], 7, "")
    )
    result = cli_support.auth_probe("custom-cli", "login")
    assert result.reason == ("custom-cli is not authenticated (`custom-cli login status` exited 7)")
