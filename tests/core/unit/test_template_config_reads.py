"""Template reads remain fresh and isolated when parsing is reused."""

import os

import pytest

from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.render import MultipleTemplate

from tests.support.marigold import marigold_template


@pytest.mark.parametrize("padding", [0, 70_000])
def test_repeated_reads_do_not_share_mutable_placement_lists(workspace_root, padding):
    workspace = marigold_template(workspace_root, "multiple")
    if padding:
        path = workspace.template_config_file("shirt")
        path.write_text(
            "#" + "x" * padding + chr(10) + path.read_text(encoding="utf-8"), encoding="utf-8"
        )
    first = workspace.load_template_config("shirt")
    assert isinstance(first, MultipleTemplate)
    count = len(first.placements)
    first.placements.pop()
    second = workspace.load_template_config("shirt")
    assert isinstance(second, MultipleTemplate)
    assert len(second.placements) == count


def test_same_size_same_mtime_external_edit_is_read_and_invalidity_keeps_its_path(workspace_root):
    workspace = marigold_template(workspace_root)
    path = workspace.template_config_file("shirt")
    original = path.read_text(encoding="utf-8")
    initial = workspace.load_template_config("shirt")
    stamp = path.stat()
    changed = original.replace("fabric_texture: 0.25", "fabric_texture: 0.75")
    assert changed != original and len(changed) == len(original)
    path.write_text(changed, encoding="utf-8")
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    current = workspace.load_template_config("shirt")
    assert current != initial
    assert current.renderer.config.appearance.fabric_texture == 0.75
    path.write_text(chr(10).join(["kind: single", "renderer: invalid"]), encoding="utf-8")
    with pytest.raises(ConfigLoadError) as error:
        workspace.load_template_config("shirt")
    assert str(path) in str(error.value)
