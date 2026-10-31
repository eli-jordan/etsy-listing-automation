"""Installed CLI formats, advisory failures, expiry and explicit refresh."""

import json
import subprocess

import pytest

from etsy_listings.core.ai.discovery import ModelDiscovery


def test_discovery_reads_catalogs_once_until_expiry_or_refresh(monkeypatch):
    calls = []
    now = [0.0]

    def run(argv, **kwargs):
        calls.append(argv)
        output = (
            json.dumps(
                {
                    "models": [
                        {
                            "slug": "sol",
                            "display_name": "Sol",
                            "supported_reasoning_levels": [{"effort": "high"}, {"effort": "ultra"}],
                        },
                        {"slug": "hidden", "visibility": "hide"},
                    ]
                }
            )
            if "codex" in argv[0]
            else "You are logged in with grok.com.\n\nDefault model: grok-4.7\n\n"
            "Available models:\n  * grok-4.7 (default)\n  - grok-4.6\n"
        )
        return subprocess.CompletedProcess(argv, 0, output, "")

    monkeypatch.setattr("etsy_listings.core.ai.discovery.shutil.which", lambda name: name)
    monkeypatch.setattr("etsy_listings.core.ai.discovery.subprocess.run", run)
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
    assert calls == [["codex", "debug", "models"], ["grok", "models"]]
    now[0] = 1799
    assert discovery.read() == first
    assert len(calls) == 2
    now[0] = 1800
    discovery.read()
    assert len(calls) == 4
    discovery.read(refresh=True)
    assert len(calls) == 6


def test_failure_retains_last_catalog_and_is_cached(monkeypatch):
    now = [0.0]
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if now[0]:
            raise subprocess.TimeoutExpired(argv, 15)
        return subprocess.CompletedProcess(
            argv,
            0,
            json.dumps({"models": [{"slug": "sol", "supported_reasoning_levels": []}]})
            if "codex" in argv[0]
            else "Available models:\n - grok-4.7\n",
            "",
        )

    monkeypatch.setattr("etsy_listings.core.ai.discovery.shutil.which", lambda name: name)
    monkeypatch.setattr("etsy_listings.core.ai.discovery.subprocess.run", run)
    discovery = ModelDiscovery(monotonic=lambda: now[0])
    discovery.read()
    now[0] = 1800
    failed = discovery.read()
    assert failed.providers["codex"].models[0].id == "sol"
    assert failed.providers["codex"].problem
    assert failed.providers["grok"].problem
    discovery.read()
    assert len(calls) == 4


@pytest.mark.parametrize(
    "output", ["null", "{}", '{"models": [1]}', '{"models": []}', '{"models": [{"slug": 1}]}']
)
def test_changed_or_malformed_cli_formats_are_advisory_failures(monkeypatch, output):
    monkeypatch.setattr("etsy_listings.core.ai.discovery.shutil.which", lambda name: name)
    monkeypatch.setattr(
        "etsy_listings.core.ai.discovery.subprocess.run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, output, ""),
    )
    catalog = ModelDiscovery().read()
    assert catalog.providers["codex"].problem
    assert catalog.providers["grok"].problem
