"""`Workspace`'s common-copy accessors and the one shared description
resolver (AI SEO implementation plan, PR2: "Description and common-copy
boundaries").

`common_copy_file` is the ref-traversal seam: a `description.ref` is a
portable, workspace-root-relative string that may resolve only beneath
`common-copy/`, the same "verify then resolve" shape `resolve()` already
enforces for `design:`/`pricing_plan:` refs. `load_common_copy` is the one
place a ref's bytes become a parsed document, and `compose_description` is
the one place that document's body reaches the pure joiner in
`config/description.py` -- so this is also where the "single shared
composition path" the plan requires is exercised end to end.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.config.description import DescriptionConfig
from etsy_listings.workspace.common_copy import CommonCopyError
from etsy_listings.workspace.workspace import PathEscapesWorkspaceError, Workspace

FRONT_MATTER = "title: Comfort Colors\ntargets: [description]\n"


def _write_common_copy(
    root: Path, name: str, *, front_matter: str = FRONT_MATTER, body: str
) -> Path:
    directory = root / "common-copy"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(f"---\n{front_matter}---\n{body}", encoding="utf-8")
    return path


def test_common_copy_dir_is_a_workspace_top_level_directory(workspace_root: Path) -> None:
    ws = Workspace.discover(root_override=workspace_root)
    assert ws.common_copy_dir() == ws.root / "common-copy"


class TestCommonCopyFile:
    def test_resolves_a_portable_ref(self, workspace_root: Path) -> None:
        ws = Workspace.discover(root_override=workspace_root)
        assert ws.common_copy_file("common-copy/comfort-colors.md") == (
            ws.root / "common-copy" / "comfort-colors.md"
        )

    def test_refuses_a_ref_outside_common_copy(self, workspace_root: Path) -> None:
        ws = Workspace.discover(root_override=workspace_root)
        with pytest.raises(PathEscapesWorkspaceError):
            ws.common_copy_file("designs/take-a-hike.png")

    def test_refuses_traversal_back_out_of_common_copy(self, workspace_root: Path) -> None:
        ws = Workspace.discover(root_override=workspace_root)
        with pytest.raises(PathEscapesWorkspaceError):
            ws.common_copy_file("common-copy/../listings/take-a-hike/listing.yaml")

    def test_refuses_an_absolute_ref(self, workspace_root: Path) -> None:
        ws = Workspace.discover(root_override=workspace_root)
        with pytest.raises(PathEscapesWorkspaceError):
            ws.common_copy_file("/etc/passwd")


class TestLoadCommonCopy:
    def test_loads_a_well_formed_file(self, workspace_root: Path) -> None:
        _write_common_copy(
            workspace_root, "comfort-colors.md", body="Printed to order on a heavyweight shirt."
        )
        ws = Workspace.discover(root_override=workspace_root)

        doc = ws.load_common_copy("common-copy/comfort-colors.md")

        assert doc.title == "Comfort Colors"
        assert doc.body == "Printed to order on a heavyweight shirt."

    def test_a_missing_file_is_a_common_copy_error_naming_the_ref(
        self, workspace_root: Path
    ) -> None:
        ws = Workspace.discover(root_override=workspace_root)
        with pytest.raises(CommonCopyError, match="common-copy/missing.md"):
            ws.load_common_copy("common-copy/missing.md")

    def test_malformed_front_matter_is_a_common_copy_error(self, workspace_root: Path) -> None:
        _write_common_copy(
            workspace_root, "broken.md", front_matter="targets: [description]\n", body="x"
        )
        ws = Workspace.discover(root_override=workspace_root)
        with pytest.raises(CommonCopyError, match="title"):
            ws.load_common_copy("common-copy/broken.md")

    def test_a_ref_that_escapes_common_copy_never_reads_the_file(
        self, workspace_root: Path
    ) -> None:
        with pytest.raises(PathEscapesWorkspaceError):
            Workspace.discover(root_override=workspace_root).load_common_copy(
                "common-copy/../shop.yaml"
            )


class TestComposeDescription:
    def test_a_text_body_composes_with_the_lead(self, workspace_root: Path) -> None:
        ws = Workspace.discover(root_override=workspace_root)
        description = DescriptionConfig(lead="A relaxed tee.", text="Printed to order.")

        assert ws.compose_description(description) == "A relaxed tee.\n\nPrinted to order."

    def test_a_ref_body_is_loaded_and_composed(self, workspace_root: Path) -> None:
        _write_common_copy(
            workspace_root, "comfort-colors.md", body="Printed to order on a heavyweight shirt."
        )
        ws = Workspace.discover(root_override=workspace_root)
        description = DescriptionConfig(lead="A relaxed tee.", ref="common-copy/comfort-colors.md")

        composed = ws.compose_description(description)

        assert composed == "A relaxed tee.\n\nPrinted to order on a heavyweight shirt."

    def test_a_lead_only_description_composes_to_the_lead(self, workspace_root: Path) -> None:
        ws = Workspace.discover(root_override=workspace_root)
        assert ws.compose_description(DescriptionConfig(lead="A relaxed tee.")) == "A relaxed tee."

    def test_a_bad_ref_raises_rather_than_silently_composing_without_it(
        self, workspace_root: Path
    ) -> None:
        ws = Workspace.discover(root_override=workspace_root)
        description = DescriptionConfig(lead="A relaxed tee.", ref="common-copy/missing.md")
        with pytest.raises(CommonCopyError):
            ws.compose_description(description)
