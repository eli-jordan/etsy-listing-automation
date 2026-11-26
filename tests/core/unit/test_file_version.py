import os
from pathlib import Path

import pytest

from etsy_listings.core.workspace.file_version import file_version, tree_version


def test_file_versions_detect_same_size_writes_even_with_restored_mtime(tmp_path):
    path = tmp_path / "map.npz"
    path.write_bytes(b"original")
    original = path.stat()
    previous = file_version(path)
    assert file_version(path) == previous
    for value in [b"changed1", b"changed2", b"changed3"]:
        path.write_bytes(value)
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
        current = file_version(path)
        assert current != previous
        assert file_version(path) == current
        previous = current


def test_a_tree_version_holds_until_a_file_under_it_is_added_changed_or_removed(tmp_path):
    nested = tmp_path / "renderer" / "maps"
    nested.mkdir(parents=True)
    (tmp_path / "template.yaml").write_text("kind: single\n", encoding="utf-8")
    deep = nested / "current.json"
    deep.write_text("{}", encoding="utf-8")
    first = tree_version(tmp_path)
    assert tree_version(tmp_path) == first

    deep.write_text('{"generation": "b"}', encoding="utf-8")
    changed = tree_version(tmp_path)
    assert changed != first

    added = nested / "new.npz"
    added.write_bytes(b"x")
    assert tree_version(tmp_path) != changed

    added.unlink()
    assert tree_version(tmp_path) == changed


def test_a_tree_version_misses_a_same_size_rewrite_that_keeps_the_mtime(tmp_path):
    path = tmp_path / "template.yaml"
    path.write_bytes(b"kind: one\n")
    original = path.stat()
    before = tree_version(tmp_path)
    path.write_bytes(b"kind: two\n")
    os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
    assert tree_version(tmp_path) == before


def test_a_missing_directory_has_an_empty_tree_version(tmp_path):
    assert tree_version(tmp_path / "gone") == ()


def test_a_symlinked_directory_is_followed_once_and_sees_its_files_change(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "photo.png").write_bytes(b"one")
    template = tmp_path / "template"
    template.mkdir()
    try:
        (template / "alias").symlink_to(real, target_is_directory=True)
        (template / "loop").symlink_to(template, target_is_directory=True)
    except OSError:
        pytest.skip("this machine cannot create symlinks")
    before = tree_version(template)

    (real / "photo.png").write_bytes(b"three")

    assert [Path(path).name for path, _, _ in before] == ["photo.png"]
    assert tree_version(template) != before


def test_file_versions_detect_overwrites_while_another_writer_remains_open(tmp_path):
    path = tmp_path / "map.npz"
    path.write_bytes(b"original")
    original = path.stat()
    with path.open("r+b"):
        previous = file_version(path)
        for value in (b"changed1", b"changed2", b"changed3"):
            path.write_bytes(value)
            os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
            current = file_version(path)
            assert current != previous
            assert file_version(path) == current
            previous = current
