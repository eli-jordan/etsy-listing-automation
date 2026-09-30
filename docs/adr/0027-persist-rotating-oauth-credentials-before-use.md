# ADR-0027: Persist rotating OAuth credentials before use

Separate pure OAuth construction, the one-request loopback callback, token persistence and authenticated transport. Etsy refresh tokens rotate on use, so atomically persist the replacement before using the new access token; a crash before that write can destroy the only credential able to recover without a browser. Resolve credentials lazily, serialize refresh within the process, and re-read once after `invalid_grant` to detect another process's rotation.

First recorded 2026-09-09 in [commit 09b7ceb](https://github.com/eli-jordan/etsy-listing-automation/commit/09b7ceb2cfa57a9bf540fd6f44a5fb8ff88f1966).
