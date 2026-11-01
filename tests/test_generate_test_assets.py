"""The asset generator writes where the app and tests read."""

from scripts import generate_test_assets


def test_bundled_designs_are_written_to_the_directory_the_server_serves() -> None:
    bundled = generate_test_assets.BUNDLED_DIR
    assert (bundled / "bundled-test-design.png").is_file(), bundled
