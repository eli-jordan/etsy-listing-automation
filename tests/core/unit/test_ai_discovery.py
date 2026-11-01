"""Installed CLI formats, advisory failures, expiry and explicit refresh."""

import threading

import pytest

from etsy_listings.core.ai.discovery import ModelDiscovery

from tests.support.ai_processes import ModelCli
from tests.support.gates import GATE_TIMEOUT, Gate, workers


@pytest.fixture
def cli(monkeypatch):
    cli = ModelCli()
    monkeypatch.setattr("etsy_listings.core.ai.discovery.shutil.which", lambda name: name)
    monkeypatch.setattr("etsy_listings.core.ai.discovery.run_managed", cli)
    return cli


def test_discovery_reads_catalogs_once_until_expiry_or_refresh(cli):
    now = [0.0]
    discovery = ModelDiscovery(monotonic=lambda: now[0])
    first = discovery.read()
    assert [m.id for m in first.providers["codex"].models] == ["sol"]
    assert first.providers["codex"].models[0].efforts == ("high",)
    assert [m.id for m in first.providers["grok"].models] == ["grok-4.7", "grok-4.6"]
    assert first.providers["grok"].efforts == ("low", "medium", "high")
    assert [m.id for m in first.providers["claude"].models] == [
        "claude-opus-5-5",
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
    ]
    assert cli.calls == [["codex", "debug", "models"], ["grok", "models"]]
    now[0] = 1799
    assert discovery.read() == first
    assert len(cli.calls) == 2
    now[0] = 1800
    discovery.read()
    assert len(cli.calls) == 4
    discovery.read(refresh=True)
    assert len(cli.calls) == 6


def test_failure_retains_last_catalog_and_is_cached(cli):
    now = [0.0]
    discovery = ModelDiscovery(monotonic=lambda: now[0])
    discovery.read()
    now[0] = 1800
    cli.failure = True
    failed = discovery.read()
    assert failed.providers["codex"].models[0].id == "sol"
    assert failed.providers["codex"].problem
    assert failed.providers["grok"].problem
    discovery.read()
    assert len(cli.calls) == 4


@pytest.mark.parametrize(
    "output", ["null", "{}", '{"models": [1]}', '{"models": []}', '{"models": [{"slug": 1}]}']
)
def test_changed_or_malformed_cli_formats_are_advisory_failures(cli, output):
    cli.codex = cli.grok = output
    catalog = ModelDiscovery().read()
    assert catalog.providers["codex"].problem
    assert catalog.providers["grok"].problem


def test_the_refresh_budget_is_shared_by_all_probes(cli):
    now = [0.0]

    def spend_budget(deadline, cancel):
        now[0] = 16.0

    cli.during = spend_budget
    catalog = ModelDiscovery(monotonic=lambda: now[0]).read()
    assert cli.calls == [["codex", "debug", "models"]]
    assert catalog.providers["grok"].problem


def test_busy_refresh_reads_keep_successful_choices_without_waiting_on_a_probe(cli):
    discovery = ModelDiscovery()
    first = discovery.read()
    gate = Gate("refresh")
    cli.during = lambda deadline, cancel: gate.hold()
    with workers(gate) as start:
        refresh = start("refresh", lambda: discovery.read(refresh=True))
        gate.wait_entered()
        busy = discovery.read()
        assert busy.providers["codex"].models == first.providers["codex"].models
        assert "in progress" in busy.providers["codex"].problem
        assert discovery.read(refresh=True) == busy
        assert len(cli.calls) == 3, "concurrent refreshes must share one probe"
        gate.release()
        assert refresh.result() == first


def test_construction_starts_no_thread_and_stop_cancels_the_started_probe(cli):
    entered, exited = threading.Event(), threading.Event()

    def until_cancelled(deadline, cancel):
        entered.set()
        assert cancel.wait(GATE_TIMEOUT)
        exited.set()

    cli.during = until_cancelled
    before = set(threading.enumerate())
    discovery = ModelDiscovery()
    assert set(threading.enumerate()) == before
    assert cli.calls == []
    discovery.start()
    try:
        assert entered.wait(GATE_TIMEOUT)
        discovery.start()  # idempotent while the first attempt is active
        pending = discovery.read()
        assert pending.providers["codex"].models == ()
        assert pending.providers["claude"].models
        assert "in progress" in pending.providers["codex"].problem
    finally:
        discovery.stop()
    assert exited.is_set()
    assert len(cli.calls) == 1
    assert "stopped" in discovery.read(refresh=True).providers["codex"].problem
    discovery.stop()


def test_shutdown_wait_is_bounded_even_if_a_process_substitute_ignores_cancellation(cli):
    gate = Gate("uncooperative external process")
    cli.during = lambda deadline, cancel: gate.hold()
    discovery = ModelDiscovery()
    discovery.start()
    try:
        gate.wait_entered()
        discovery.stop(timeout=0.01)
        assert "stopped" in discovery.read().providers["grok"].problem
    finally:
        gate.release()
        discovery.stop()
