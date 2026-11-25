"""Admin › Settings › Backup through the built SPA, the real API and restic
(workspace-backup plan, PR 6): set up backups on a copy of the fixture
workspace and see the first backup in the history.

The page's states, warnings and refusals are Vitest's
(``BackupSection.test.tsx``); the endpoints' rules are
``tests/server/behaviour/test_backup_api.py``'s. Per-user state lives under
``tmp_path`` (plan, P2) and restic is the pinned binary (P3).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from etsy_listings.core.application.backup_coordinator import BackupEnvironment
from etsy_listings.core.backup.binary import RESTIC_BINARY_ENV_VAR
from etsy_listings.core.config.secrets import BACKUP_PASSWORD_VAR

from tests.support.mobile import MOBILE_VIEWPORT, assert_mobile_page_fits

pytestmark = [pytest.mark.browser, pytest.mark.restic]

PASSWORD = "correct horse battery staple"
RESTIC_TIMEOUT_MS = 120_000
"""restic's init and first backup, under ``poe check``'s parallel, covered run."""


@pytest.fixture
def app_options(
    restic_binary: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """The real restic, with state and history under ``tmp_path``."""
    monkeypatch.setenv(RESTIC_BINARY_ENV_VAR, str(restic_binary))
    monkeypatch.delenv(BACKUP_PASSWORD_VAR, raising=False)
    return {"backup": BackupEnvironment(home=tmp_path / "home")}


@pytest.fixture
def expect(browser_type):
    from playwright.sync_api import expect as playwright_expect

    return playwright_expect


def test_setting_up_backups_makes_the_first_backup_and_lists_it(
    page, expect, calibrator_server: str, tmp_path: Path, workspace_root: Path
) -> None:
    repository = tmp_path / "backups"
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"{calibrator_server}/admin?section=backup")

    expect(page.get_by_role("heading", name="Backups are off")).to_be_visible()
    page.get_by_role("button", name="Set up backups").click()
    page.get_by_label("Backup storage folder").fill(str(repository))
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_label("Repeat password").fill(PASSWORD)
    page.get_by_role("checkbox").check()
    page.get_by_role("button", name="Create and back up now").click()

    expect(page.get_by_role("link", name="Status and history")).to_have_attribute(
        "aria-current", "page", timeout=RESTIC_TIMEOUT_MS
    )
    history = page.get_by_role("region", name="Backup history")
    expect(history.get_by_role("row").nth(1)).to_contain_text(
        "Backed up", timeout=RESTIC_TIMEOUT_MS
    )
    expect(history.get_by_role("row").nth(1)).to_contain_text("Recent")
    expect(page.get_by_role("heading", name="Backed up a moment ago")).to_be_visible()
    assert (repository / "config").is_file()
    assert "backup:" in (workspace_root / "settings.yaml").read_text(encoding="utf-8")


def test_backup_pages_fit_a_phone_through_set_up_history_and_restore(
    page, expect, calibrator_server: str, tmp_path: Path
) -> None:
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{calibrator_server}/admin?section=backup")

    expect(page.get_by_role("heading", name="Backups are off")).to_be_visible()
    assert_mobile_page_fits(page)

    page.get_by_role("button", name="Set up backups").click()
    page.get_by_label("Backup storage folder").fill(str(tmp_path / "backups"))
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_label("Repeat password").fill(PASSWORD)
    page.get_by_role("checkbox").check()
    assert_mobile_page_fits(page)
    page.get_by_role("button", name="Create and back up now").click()

    history = page.get_by_role("region", name="Backup history")
    expect(history.get_by_role("row").nth(1)).to_contain_text(
        "Backed up", timeout=RESTIC_TIMEOUT_MS
    )
    assert_mobile_page_fits(page)

    history.get_by_role("button", name="Restore…").first.click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    box = dialog.bounding_box()
    assert box is not None
    assert box["x"] >= 0, box
    assert box["x"] + box["width"] <= MOBILE_VIEWPORT["width"], box
    spill = dialog.evaluate(
        """(d) => [...d.querySelectorAll('*')]
            .filter((e) => e.getBoundingClientRect().right > d.getBoundingClientRect().right + 1)
            .map((e) => e.tagName + '.' + (e.getAttribute('class') || ''))"""
    )
    assert spill == [], spill
    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).to_be_hidden()

    page.get_by_role("navigation", name="Admin sections").get_by_role("link", name="Setup").click()
    page.get_by_role("heading", name="Backup settings").wait_for(state="visible")
    assert_mobile_page_fits(page)
