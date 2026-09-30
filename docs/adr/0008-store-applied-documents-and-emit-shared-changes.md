# ADR-0008: Store applied documents and emit shared changes

Store each stage's last applied desired document verbatim in `state.lock.json`. Each stage compares its desired, applied and live documents through shared comparison helpers and emits the common `Change` vocabulary. The CLI and UI render those changes instead of maintaining independent diff rules, so the route used to deploy cannot change the meaning of drift.

First recorded 2026-09-03 in [commit 3959ee0](https://github.com/eli-jordan/etsy-listing-automation/commit/3959ee0c08172195bc726d81d2c98ed4a4f4efef).
