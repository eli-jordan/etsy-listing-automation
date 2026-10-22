"""The picture a scene preview should be, composed from render primitives.

The expected image is built here from the file each test names for each
colour, never by asking the resolver: a test that resolved through
``config/artwork.py`` to check a preview that resolves through
``config/artwork.py`` would agree with any bug in it. Shared by the scene
preview's API tests, the render stage's *previews = print* tests and the
artwork browser tests, which all compare a picture against the same thing.
"""

from __future__ import annotations

from pathlib import Path

from etsy_listings.core.render import (
    ColourMatrixTemplate,
    Layer,
    MultipleTemplate,
    encode_png,
    load_design,
    load_template_base,
    luminance_map,
    render_scene,
)
from etsy_listings.core.workspace.workspace import Workspace


def expected_scene(
    root: Path, template: str, colour: str | None, files: dict[str | None, str]
) -> bytes:
    """``template``'s scene at full size, each layer printing ``files`` for the
    colour it depicts; a colour ``files`` does not name is left bare."""
    workspace = Workspace.discover(root_override=root)
    config = workspace.load_template_config(template)
    if isinstance(config, MultipleTemplate):
        specs = [(p.colour, config.render_config_for(p)) for p in config.placements]
    else:
        specs = [
            (colour if isinstance(config, ColourMatrixTemplate) else None, config.render_config())
        ]
    base = load_template_base(workspace.scene_photo(template, colour).path)
    layers = [Layer(design=load_design(root / files[c]), cfg=cfg) for c, cfg in specs if c in files]
    assert not any(cfg.displace.enabled for _, cfg in specs)
    return encode_png(render_scene(base, layers, luminance=luminance_map(base)))
