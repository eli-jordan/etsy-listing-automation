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
