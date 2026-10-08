"""The native validation driver creates independent diagnostic artwork."""

import importlib.util
from pathlib import Path

import numpy as np
from PIL import Image


def test_diagnostic_artwork_covers_opaque_and_transparent_print(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "validation", Path(__file__).parents[1] / "scripts/validate_marigold.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    design = tmp_path / "real.png"
    Image.new("RGBA", (7, 9), (20, 30, 40, 100)).save(design)
    cases = module.artwork_cases(design)
    assert set(cases) == {"white", "saturated", "fine", "transparent", "real"}
    assert np.all(cases["white"] == 255)
    assert tuple(cases["saturated"][200, 200]) == (255, 0, 255, 255)
    assert cases["fine"][..., 3].min() == 0
    assert cases["fine"][..., 3].max() == 255
    assert tuple(cases["transparent"][256, 256]) == (0, 255, 255, 220)
    assert tuple(cases["real"][0, 0]) == (20, 30, 40, 100)
    assert cases["real"].shape == (9, 7, 4)


def test_validation_refuses_output_inside_read_only_input(tmp_path):
    import pytest

    spec = importlib.util.spec_from_file_location(
        "validation", Path(__file__).parents[1] / "scripts/validate_marigold.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / "read-only-source"
    source.mkdir()
    output = source / "measurements"
    with pytest.raises(ValueError, match="source"):
        module.run(source, output)
    assert not output.exists()


def test_watchdog_identifies_only_its_native_worker_despite_blank_wmic_rows(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "watchdog", Path(__file__).parents[1] / "scripts/validate_marigold_watchdog.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cache = tmp_path / "unique-cache"
    listing = (
        "Node,CommandLine,ProcessId\n\n"
        f'HOST,python -m marigold_worker --cache-root "{cache.resolve()}",42\n'
        "\nHOST,python -m marigold_worker --cache-root other,43\n"
        "HOST" + chr(10) + "HOST,,99\n"
    )
    monkeypatch.setattr(module.subprocess, "check_output", lambda *a, **kw: listing)
    assert module.owned_pid(cache) == 42


def test_watchdog_selects_backend_child_of_its_verified_venv_launcher(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "watchdog", Path(__file__).parents[1] / "scripts/validate_marigold_watchdog.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cache = tmp_path / "unique-cache"
    command = f'python -m marigold_worker --cache-root "{cache.resolve()}"'
    listing = chr(10).join(
        [
            "Node,CommandLine,ParentProcessId,ProcessId",
            f"HOST,{command},11,42",
            f"HOST,{command},42,44",
        ]
    )
    monkeypatch.setattr(module.subprocess, "check_output", lambda *a, **kw: listing)
    assert module.owned_pid(cache) == 44
