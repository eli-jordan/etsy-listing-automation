# ADR-0002: Converge through a lockfile and plan/apply

Status: accepted.

Keep the last applied state in a per-listing lockfile and compare desired, applied and live state before writing. This distinguishes seller edits from remote drift and makes an unchanged rerun a no-op. Hash desired inputs separately from produced files so a renderer upgrade can require an upload without pretending the configuration changed.

First recorded 2026-09-03 in [commit 086df20](https://github.com/eli-jordan/etsy-listing-automation/commit/086df2096d7b293ccbad394c9891b661a9a194b9).
