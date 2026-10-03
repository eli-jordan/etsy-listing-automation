# ADR-0025: Separate credentials from workspace configuration

Status: accepted.

`auth` captures credentials and writes `.env` and `.auth/`; `setup` discovers ids and writes workspace configuration. The boundary is the kind of value rather than the vendor or whether obtaining it opens a browser, so a seller has one place to manage every credential. Auth can run before `shop.yaml` exists, writes secret exclusions first, and precedes setup's discovery calls. Etsy's app key includes both keystring and shared secret in `x-api-key`.

First recorded 2026-09-09 in [commit 09b7ceb](https://github.com/eli-jordan/etsy-listing-automation/commit/09b7ceb2cfa57a9bf540fd6f44a5fb8ff88f1966).
