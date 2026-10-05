from pathlib import Path

from etsy_listings.core.preparation.runtime import Runtime


def test_inspection_of_missing_runtime_is_read_only(tmp_path):
    home = tmp_path / "home"
    report = Runtime(home=home).inspect()
    assert not report.available
    assert "etsy-listings marigold setup" in report.problem
    assert not home.exists()


def test_failed_update_keeps_previous_installation_and_engine_selection(tmp_path):
    import pytest

    from etsy_listings.core.preparation.runtime import Capability, SetupError

    class Installer:
        fail = False

        def install(self, target, weights, version):
            if self.fail:
                raise SetupError("GPU capability probe failed")
            (target / "python.exe").write_bytes(b"controlled worker")
            return Capability(True, None, engine_version=version, python=str(target / "python.exe"))

        def inspect(self, target, weights, version):
            return Capability(True, None, engine_version=version, python=str(target / "python.exe"))

    installer = Installer()
    runtime = Runtime(home=tmp_path, installer=installer)
    selected = runtime.setup()
    installer.fail = True
    with pytest.raises(SetupError, match="probe failed"):
        Runtime(home=tmp_path, installer=installer, engine_version="2.0.0").update()
    assert runtime.inspect().engine_version == "1.0.0"
    assert runtime.selection("1.0.0").engine_version == selected.engine_version


def test_engine_version_cannot_escape_global_installation(tmp_path):
    import pytest

    from etsy_listings.core.preparation.runtime import SetupError

    with pytest.raises(SetupError, match="engine version"):
        Runtime(home=tmp_path, engine_version="../outside")
    assert not (tmp_path / ".etsy-listings").exists()


def test_explicit_same_engine_repair_keeps_selected_installation(tmp_path):
    from etsy_listings.core.preparation.runtime import Capability

    class Installer:
        def install(self, target, weights, version):
            (target / "python.exe").write_bytes(b"valid")
            return Capability(True, None, engine_version=version, python=str(target / "python.exe"))

        def inspect(self, target, weights, version):
            valid = (target / "python.exe").read_bytes() == b"valid"
            return Capability(
                valid,
                None if valid else "damaged",
                engine_version=version,
                python=str(target / "python.exe"),
            )

    runtime = Runtime(home=tmp_path, installer=Installer())
    original = runtime.setup()
    Path(original.python).write_bytes(b"damaged")
    repaired = runtime.update()
    assert repaired.available
    assert repaired.installation_id != original.installation_id
    assert Path(original.python).read_bytes() == b"damaged"
    assert runtime.selection("1.0.0", installation_id=repaired.installation_id).available


def test_failed_post_rename_probe_leaves_previous_current_and_allows_retry(tmp_path):
    import pytest

    from etsy_listings.core.preparation.runtime import Capability, SetupError

    class Installer:
        rejected_versions = set()

        def install(self, target, weights, version):
            (target / "python.exe").write_bytes(b"valid")
            return Capability(True, None, engine_version=version, python=str(target / "python.exe"))

        def inspect(self, target, weights, version):
            valid = version not in self.rejected_versions
            return Capability(
                valid,
                None if valid else "post-rename probe failed",
                engine_version=version,
                python=str(target / "python.exe"),
            )

    installer = Installer()
    runtime = Runtime(home=tmp_path, installer=installer)
    previous = runtime.setup()
    installer.rejected_versions.add("2.0.0")
    newer = Runtime(home=tmp_path, installer=installer, engine_version="2.0.0")
    with pytest.raises(SetupError, match="post-rename"):
        newer.update()
    assert runtime.inspect().installation_id == previous.installation_id
    installer.rejected_versions.clear()
    assert newer.update().available
    assert runtime.selection("1.0.0", installation_id=previous.installation_id).available
