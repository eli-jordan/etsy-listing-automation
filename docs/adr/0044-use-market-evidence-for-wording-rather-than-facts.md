# ADR-0044: Use market evidence for wording rather than facts

Generate buyer queries, research comparable active Etsy listings, then use ranked phrases and examples to inform an SEO proposal. Market evidence chooses wording and priority, never product facts. Query or search failure fails the request; no comparables continues with a warning. One server-side AI run owns brief, research and proposal, outside the deployment worker, and caches the latest research snapshot for inspection and reattachment.

First recorded 2026-09-24 in [commit 46066e6](https://github.com/eli-jordan/etsy-listing-automation/commit/46066e62bcc63b714be2fbaf8ff9608ef8ad87c2).
