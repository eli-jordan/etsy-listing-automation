"""Common CLI outcome rules, independent of any provider's envelope format."""

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

from tests.support.cli_host import ScriptedCliHost, completed


def test_cancellation_takes_precedence_over_timeout_and_exit_status():
    result = ProcessResult(1, "", "not logged in", timed_out=True, cancelled=True)
    with pytest.raises(ProviderCancelledError):
        cli_support.check_result("test", result)


def test_timeout_takes_precedence_over_exit_status():
    result = ProcessResult(1, "", "not logged in", timed_out=True, cancelled=False)
    with pytest.raises(ProviderTimeoutError):
        cli_support.check_result("test", result)


def test_probe_reports_the_command_that_could_not_start():
    host = ScriptedCliHost(runs={(): OSError("missing executable")})
    result = cli_support.probe(host, "custom-cli", ("exec", "--help"))
    assert result.reason == "could not check `custom-cli exec --help`: missing executable"


def test_probe_runs_the_resolved_binary_within_the_readiness_timeout():
    host = ScriptedCliHost(installed={"custom-cli": "/bin/custom-cli"}, runs={(): completed()})
    cli_support.probe(host, "custom-cli", ("--help",))
    (call,) = host.run_calls
    assert call.argv == ["/bin/custom-cli", "--help"]
    assert call.timeout == cli_support.READINESS_TIMEOUT_SECONDS


@pytest.mark.parametrize("stdout", ["[]", "null", "not json"])
def test_only_json_objects_are_provider_envelopes(stdout):
    with pytest.raises(ProviderGenerationError):
        cli_support.json_object("test", stdout)


def test_capability_reports_missing_flags_in_declaration_order():
    host = ScriptedCliHost(runs={(): completed("--tools")})
    result = cli_support.check_capability(
        host, "test", ("--help",), ("--schema", "--tools", "--readonly"), "headless"
    )
    assert result.reason == (
        "the installed test CLI does not support the required headless flags: --schema, --readonly"
    )


def test_readiness_stops_before_capability_when_authentication_fails():
    host = ScriptedCliHost(installed={"test": "/resolved/test"})
    unavailable = ProviderReadiness(ready=False, reason="not authenticated")

    def capability():
        pytest.fail("capability probe must wait for authentication")

    assert cli_support.readiness(host, "test", lambda: unavailable, capability) == unavailable


def test_generation_refuses_a_missing_binary_before_launch():
    with pytest.raises(ProviderUnavailableError, match="custom-cli was not found on PATH"):
        cli_support.require_binary(ScriptedCliHost(), "test", "custom-cli")


def test_failed_auth_probe_preserves_command_and_exit_code():
    host = ScriptedCliHost(runs={(): completed(returncode=7)})
    result = cli_support.auth_probe(host, "custom-cli", "login")
    assert result.reason == ("custom-cli is not authenticated (`custom-cli login status` exited 7)")
