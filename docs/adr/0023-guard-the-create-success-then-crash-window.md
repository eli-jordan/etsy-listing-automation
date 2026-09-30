# ADR-0023: Guard the create-success-then-crash window

Status: accepted.

Use the lockfile's Printify product id as the primary creation guard. Only before a new create, walk the shop's entire product paginator and refuse a title-and-description match: the create endpoint has neither an idempotency key nor a conflict response, and the server accepts but ignores search filters. This protects the interval after a successful create but before its id is recorded without adding a full product walk to every no-op plan.

First recorded 2026-09-08 in [commit fbdf6db](https://github.com/eli-jordan/etsy-listing-automation/commit/fbdf6dbf98b80b6c12fd65d661b612da2ce34e95).
