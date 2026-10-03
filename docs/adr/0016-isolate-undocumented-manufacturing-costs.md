# ADR-0016: Isolate undocumented manufacturing costs

Status: accepted.

The `new` pricing-plan wizard may use Printify's undocumented per-variant manufacturing-cost endpoint to seed prices. Keep it outside the documented client protocols and the deployment engine, join it to catalog variant names, and fail softly to blank prices if it stops working. This gives the wizard useful starting values without making an unsupported endpoint a prerequisite for creating or deploying a listing; shipping uses the documented catalog endpoint.

First recorded 2026-09-05 in [commit ea924a2](https://github.com/eli-jordan/etsy-listing-automation/commit/ea924a219ac6bb74576b11529873faf7660164f8).
