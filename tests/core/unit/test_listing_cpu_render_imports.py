"""Planning and rendering prepared listings do not load model dependencies."""

import json
import subprocess
import sys


def test_listing_render_imports_no_inference_runtime_or_model_library():
    probe = """
import json, sys
from etsy_listings.core.engine.stages.render import RenderStage
from etsy_listings.core.workspace import WorkspaceFacts
from etsy_listings.core.preparation.readiness import saved_readiness
forbidden = (
    'torch', 'diffusers', 'transformers',
    'etsy_listings.core.preparation.runtime',
    'etsy_listings.core.preparation.worker_client',
)
loaded = sorted(name for name in sys.modules if any(
    name == prefix or name.startswith(prefix + '.') for prefix in forbidden
))
print(json.dumps(loaded))
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip()) == []
