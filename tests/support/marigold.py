"""Controlled subprocess inference at the worker's model boundary."""

import sys
from pathlib import Path


def controlled_worker(tmp_path: Path, *, delay: float = 0.1, idle: float = 300) -> list[str]:
    source = Path(__file__).parents[2] / "src/etsy_listings/core/preparation/distribution/src"
    script = tmp_path / "controlled_worker.py"
    script.write_text(
        f"""import sys, time, threading
sys.path.insert(0, {str(source)!r})
import numpy as np
from marigold_worker.server import serve
class Backend:
    def capabilities(self):
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError('Native model startup must finish before the control reader')
        return dict(engine_version='1.0.0', roles=['normals','lighting','depth'], cuda=True)
    def infer(self, role, image, settings):
        time.sleep({delay!r})
        return np.full((1,image.height,image.width,1), 0.5, dtype=np.float32), dict(test=True)
serve(Backend(), cache_root={str(tmp_path)!r}, idle_seconds={idle!r})
""",
        encoding="utf-8",
    )
    return [sys.executable, str(script)]


def material_maps(size: tuple[int, int] = (16, 16)):
    import numpy as np

    from etsy_listings.core.render.material import MaterialMaps

    width, height = size
    yy, xx = np.mgrid[:height, :width].astype(np.float32)
    return MaterialMaps(
        np.stack([xx / (width - 1), yy / (height - 1)], -1),
        np.ones((height, width), np.float32),
        np.full((height, width, 3), 0.5, np.float32),
        np.full((height, width, 3), 1.5, np.float32),
        np.full((height, width), 1.1, np.float32),
        np.full((height, width, 3), 0.03, np.float32),
        np.ones((height, width), np.int32),
    )


def preparation_inputs(ids=(None,), size=(16, 16)):
    from etsy_listings.core.preparation.artifacts import PreparationInputs

    return PreparationInputs.model_validate(
        {
            "photo": {
                "file": "scene.png",
                "width": size[0],
                "height": size[1],
                "pixels": "a" * 64,
                "conversion": "pillow-rgb-v1",
            },
            "placements": [
                {
                    "id": placement_id,
                    "quad": [[0, 0], [15, 0], [15, 15], [0, 15]],
                    "mask": "b" * 64,
                    "evidence": "c" * 64,
                }
                for placement_id in ids
            ],
            "inference": {"num_inference_steps": 10, "ensemble_size": 3},
            "compatibility": "material-v1",
        }
    )


def rewrite_map_manifest(workspace, template, generation, document):
    """Corrupt or edit a fixture coherently, retaining the public pointer checksum."""
    import hashlib
    import json

    manifest = workspace.template_map_manifest(template, generation)
    data = json.dumps(document).encode("utf-8")
    manifest.write_bytes(data)
    path = workspace.template_map_current(template)
    pointer = json.loads(path.read_bytes())
    pointer["manifest_checksum"] = hashlib.sha256(data).hexdigest()
    path.write_text(json.dumps(pointer), encoding="utf-8")
