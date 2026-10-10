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


class PreparationWorker:
    """Controlled model predictions, leaving queue, fitting and publication real."""

    def __init__(self, root):
        import threading

        self.root = root
        self.calls = []
        self.entered = threading.Event()
        self.dispatch_entered = threading.Event()
        self.dispatch_release = threading.Event()
        self.dispatch_release.set()
        self.release = threading.Event()
        self.release.set()
        self.cancelled = []
        self.closed = False
        self.failure = None

    def infer(self, *, request_id, role, input, output, size, **settings):
        import hashlib
        from contextlib import nullcontext

        import numpy as np

        self.dispatch_entered.set()
        assert self.dispatch_release.wait(20)
        guard = settings.pop("dispatch_guard", nullcontext)
        with guard():
            self.calls.append((role, input, settings))
            self.entered.set()
        assert self.release.wait(20)
        if self.failure:
            raise self.failure
        w, h = size
        array = np.full(
            (3 if role == "lighting" else 1, h, w, 1 if role == "depth" else 3), 0.5, np.float32
        )
        if role == "normals":
            array[:] = 0
            array[..., 2] = 1
        path = self.root / output
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, prediction=array)
        return {"checksum": hashlib.sha256(path.read_bytes()).hexdigest(), "artifact": output}

    def cancel(self, request_id):
        self.cancelled.append(request_id)

    def close(self):
        self.closed = True


class PreparationRuntime:
    def __init__(self):
        from etsy_listings.core.preparation.runtime import Capability

        self.capability = Capability(True, None, "1.0.0", installation_id="test")
        self.workers = []
        self.factory = PreparationWorker
        self.inspections = 0

    def inspect(self):
        self.inspections += 1
        return self.capability

    def selection(self, version, *, installation_id):
        from dataclasses import replace

        return replace(self.capability, engine_version=version, installation_id=installation_id)

    def worker(self, selected, *, cache_root):
        worker = self.factory(cache_root)
        self.workers.append(worker)
        return worker


def marigold_template(workspace_root, kind="single", name="shirt", renderer="marigold"):
    """Small deterministic garment photo for public HTTP/browser workflows."""
    from PIL import Image, ImageDraw

    from etsy_listings.core.render import load_template_config
    from etsy_listings.core.workspace import Workspace

    workspace = Workspace.discover(root_override=workspace_root)
    workspace.template_dir(name).mkdir()
    photo = Image.new("RGB", (64, 64), "white")
    ImageDraw.Draw(photo).rectangle((8, 8, 55, 55), fill="navy")
    photo.save(
        workspace.template_dir(name) / ("navy.png" if kind == "colour-matrix" else "scene.png")
    )
    if kind == "colour-matrix":
        second = Image.new("RGB", (64, 64), "white")
        ImageDraw.Draw(second).rectangle((8, 8, 55, 55), fill="ivory")
        second.save(workspace.template_dir(name) / "ivory.png")
    box = [{"x": x, "y": y} for x, y in [(12, 12), (51, 12), (51, 51), (12, 51)]]
    config = {"kind": kind, "renderer": {"type": renderer, "config": {}}}
    if kind == "multiple":
        config["placements"] = [
            {"id": identity, "colour": "Navy", "bounding_box": box}
            for identity in ["left-shirt", "right-shirt"]
        ]
    else:
        config["bounding_box"] = box
    workspace.save_template_config(name, load_template_config(config))
    return workspace
