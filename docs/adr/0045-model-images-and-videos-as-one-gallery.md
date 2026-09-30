# ADR-0045: Model images and videos as one gallery

Keep videos in the ordered `media` gallery rather than a separate list. Etsy exposes no video rank, but measured attachment order selects the featured video and anchors the second after the images present at attachment. A separate video stage follows image sync and temporarily changes image associations to place the second video, then restores them and swatches. Reattach by id for layout changes; upload for changed or missing bytes.

## Consequences

Manual video moves are invisible to plan, and association calls consume Etsy's daily per-listing allowance. Local checks enforce supported format, duration and dimensions because API acceptance is too permissive to validate the asset. Send `is_multi_video=true` explicitly; the measured placement details remain in the Etsy integration spec.

First recorded 2026-09-25 in [commit fe99b45](https://github.com/eli-jordan/etsy-listing-automation/commit/fe99b45f288f4619503017b919ddebd8fc2a720c).
