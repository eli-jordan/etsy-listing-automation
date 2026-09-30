# ADR-0012: Render with pure passes and pinned dependencies

Compose pure render passes over arrays and frozen configuration, with explicit determinism controls and exact OpenCV and Pillow pins. Test both individual passes and complete output bytes so a changed golden identifies the responsible pass.

## Amendment

Multiple-placement rendering originally introduced a separate scene path to preserve the existing single-layer goldens. The current renderer exposes `render_scene()` for both deployment and calibration; the lasting requirement is the deterministic pixel contract, rather than two entry points that no longer exist.

First recorded 2026-09-03 in [commit 3959ee0](https://github.com/eli-jordan/etsy-listing-automation/commit/3959ee0c08172195bc726d81d2c98ed4a4f4efef).
