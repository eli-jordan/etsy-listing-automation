# ADR-0026: Use minimal Etsy scopes and a fixed loopback callback

Use `listings_r`, `listings_w` and `shops_r`, with the registered callback `http://localhost:8517/oauth/callback`. The fixed port follows Etsy's exact redirect-string matching: an ephemeral port cannot be registered in advance, so a busy port is an error. `listings_d` is absent because draft retraction uses Printify's cascade and the tool never calls Etsy listing deletion. Refresh tokens are refreshed on demand, with an expiry warning.

First recorded 2026-09-09 in [commit 09b7ceb](https://github.com/eli-jordan/etsy-listing-automation/commit/09b7ceb2cfa57a9bf540fd6f44a5fb8ff88f1966).
