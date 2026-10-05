import hashlib
import json

from etsy_listings.core.preparation.installation import REVISIONS, NativeInstaller


def test_status_reuses_verified_report_and_changed_weights_invalidate_it(tmp_path):
    target = tmp_path / "installation"
    project = target / "distribution"
    project.mkdir(parents=True)
    (project / "uv.lock").write_text(
        '[[package]]\nname="etsy-marigold-worker"\nversion="1.0.0"', encoding="utf-8"
    )
    weights = tmp_path / "weights"
    descriptors = {}
    for revision in REVISIONS:
        folder = weights / revision
        folder.mkdir(parents=True)
        path = folder / "weights.safetensors"
        path.write_bytes(b"valid pinned weights")
        descriptors[revision] = {
            "weights.safetensors": {
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        }
    (target / "installation.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "engine_version": "1.0.0",
                "files": {},
                "weights": descriptors,
            }
        ),
        encoding="utf-8",
    )
    calls = []
    packages = {"etsy-marigold-worker": "1.0.0"}

    def runner(command, **kwargs):
        calls.append(command)
        return json.dumps(
            {
                "engine_version": "1.0.0",
                "cuda": True,
                "installed_packages": packages,
            }
        )

    installer = NativeInstaller(command_runner=runner)
    assert installer.inspect(target, weights, "1.0.0").available
    assert installer.inspect(target, weights, "1.0.0").available
    assert len(calls) == 1
    packages["unlocked-library"] = "9.9.9"
    manifest_file = target / "installation.json"
    manifest_file.write_text(manifest_file.read_text() + " ", encoding="utf-8")
    assert not installer.inspect(target, weights, "1.0.0").available
    (weights / REVISIONS[0] / "weights.safetensors").write_bytes(b"damaged")
    report = installer.inspect(target, weights, "1.0.0")
    assert not report.available
    assert "integrity" in report.problem
