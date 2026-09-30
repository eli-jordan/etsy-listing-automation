# Documentation

Start with the [getting-started guide](guides/getting-started.md) to use the
tool, or [account and workspace setup](guides/setup.md) to connect a real shop.
The root [README](../README.md) covers installation and contributor commands;
[AGENTS.md](../AGENTS.md) holds instructions for coding agents.

| Kind | Purpose | Entry point |
|---|---|---|
| Guides | Tasks a person can follow | [Getting started](guides/getting-started.md), [setup](guides/setup.md) |
| Architecture | Current modules, data flow and development invariants | [Architecture](architecture.md) |
| Decisions | Rationale for choices that are costly to reverse | [ADR index](adr/README.md) |
| Reference | Current conventions needed to interpret configuration and deployment | [Reference index](reference/README.md) |
| Features | Requirements, optional interaction contracts and delivery plans | Feature table below |
| Research | Dated API investigations and measured findings | [Research table](#research) |
| History | Original broad plans preserved for context | [Historical documents](#history) |

## Features

A feature folder is named `<topic>-YYYYMMDD`, using the date its first document
was created. `spec.md` describes requirements, `interactions.md` describes the
optional UI contract, and `plan.md` records the implementation sequence. Shipped
plans stay beside their feature with links to the delivery PRs. Folder dates
identify the start of the work, not its release date.

| Feature | Specification | Interactions | Plan |
|---|---|---|---|
| Multi-placement rendering | [Spec](features/multi-placement-rendering-20260903/spec.md) | — | — |
| Etsy listing integration | [Spec](features/etsy-listing-20260910/spec.md) | — | — |
| Listings UI | [Spec](features/listings-ui-20260915/spec.md) | — | — |
| Listing lifecycle | [Spec](features/listing-lifecycle-20260916/spec.md) | — | — |
| Individual and workspace deploy | [Spec](features/deploy-20260917/spec.md) | [Interactions](features/deploy-20260917/interactions.md) | [Plan](features/deploy-20260917/plan.md) |
| AI SEO | — | [Interactions](features/ai-seo-20260922/interactions.md) | [Plan](features/ai-seo-20260922/plan.md) |
| Market-informed SEO | [Spec](features/market-seo-20260924/spec.md) | [Interactions](features/market-seo-20260924/interactions.md) | [Plan](features/market-seo-20260924/plan.md) |
| Listing videos | — | — | [Plan](features/listing-videos-20260925/plan.md) |
| Listing templates and batch creation | [Spec](features/batch-creation-20260927/spec.md) | [Interactions](features/batch-creation-20260927/interactions.md) | [Plan](features/batch-creation-20260927/plan.md) |

The AI SEO interactions are amended by market-informed SEO and durable batch
proposals; the video requirements also live in the Etsy integration spec.
Batch-creation interactions override that feature's spec where they differ.
An optional document is absent when no separate one was authored; the table
does not imply a missing implementation.

## Research

| Investigation | Contents |
|---|---|
| [Printify–Etsy integration](research/printify-etsy-integration.md) | Native integration, field ownership and API constraints |
| [API findings](research/api-findings.md) | Measured requests, responses and integration surprises |

Research records evidence from the investigation date. Consult the current
feature requirements and client code for application behaviour; a measurement
does not establish that a vendor endpoint behaves identically today.

## History

The [original PRD](history/prd.md) and [implementation plan](history/implementation-plan.md)
are frozen snapshots of the project-wide plan as of 2026-09-30. Their phases
are historical sequencing, not a statement of what is implemented. Keep their
decision ids intact while migrating existing citations; new requirements
belong with their feature and new rationale belongs in an ADR.

The ADR drafts are at the agreed review checkpoint. Citation conversion and
the final authority pointers follow that review, so existing PRD/A citations
still resolve during migration.

`openapi.json` is generated API reference, exported from FastAPI for the typed
frontend client. Regenerate it from the code rather than editing it here.
