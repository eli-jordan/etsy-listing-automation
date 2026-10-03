# ADR-0010: Separate behavioural fakes from wire contracts

Status: accepted.

Expose each API through a narrow protocol returning pydantic models. Use in-memory fakes to test behaviour over time and cassette replay through the real HTTP clients to pin payload shape. Separating those jobs prevents a permissive fake from certifying an invalid request and avoids making behaviour tests depend on network access; env-gated e2e tests exercise the real integrations.

First recorded 2026-09-03 in [commit 3959ee0](https://github.com/eli-jordan/etsy-listing-automation/commit/3959ee0c08172195bc726d81d2c98ed4a4f4efef).
