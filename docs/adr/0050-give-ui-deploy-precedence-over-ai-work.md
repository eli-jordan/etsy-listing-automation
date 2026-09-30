# ADR-0050: Give UI deploy precedence over AI work

Before planning or applying a listing in the UI, cancel its queued batch AI and stop and await any active AI run. Refuse new AI while deploy holds it, and do not resume rows marked `cancelled_by_deploy`. This prevents background brief drafting from racing reviewed deployment inputs. CLI apply deliberately does not coordinate with the UI queue. Every apply clears proposals only after full success, including no blocked stages and no incomplete lockfile.

First recorded 2026-09-27 in [commit c963e78](https://github.com/eli-jordan/etsy-listing-automation/commit/c963e78aa65ea254ac02886421a1b1607cce8845).
