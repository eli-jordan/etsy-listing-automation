# ADR-0013: Keep workspace data separate from the application

User data lives in a separate directory marked by `shop.yaml`, discovered by walking upward or selected with `--root` or `ETSY_LISTINGS_ROOT`. Only `workspace` knows the directory layout, and its path resolution and single-segment checks keep callers inside the intended roots. Centralising that boundary prevents CLI and HTTP code from disagreeing about where a listing lives or accepting an escaping path.

First recorded 2026-09-03 in [commit 3959ee0](https://github.com/eli-jordan/etsy-listing-automation/commit/3959ee0c08172195bc726d81d2c98ed4a4f4efef).
