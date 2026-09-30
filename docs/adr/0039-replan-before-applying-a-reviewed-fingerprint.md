# ADR-0039: Replan before applying a reviewed fingerprint

Fingerprint the serialised plan without snapshots and require a matching fresh plan before executing a reviewed UI apply. Executing a cached plan would miss remote changes and file edits after review; hashing only desired state would let newly appeared drift through. A changed fingerprint returns the new plan before any stage executes. The CLI and manual edits share the same files, so a browser-local lock cannot provide this guarantee.

First recorded 2026-09-17 in [commit c455e61](https://github.com/eli-jordan/etsy-listing-automation/commit/c455e616bc59c0340ab410d3c2b813bb61f466a3).
