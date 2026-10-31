import os

from etsy_listings.core.workspace.file_version import file_version


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
