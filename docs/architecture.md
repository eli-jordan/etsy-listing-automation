# Architecture

Companion to [prd.md](prd.md) (*what*) and [implementation-plan.md](implementation-plan.md)
(*how*). This document shows the mechanism that actually exists after Phase 0:
module boundaries and the plan/apply data flow. It grows as later phases land;
it is not a restatement of the directory listing.

## Package structure

```mermaid
graph TD
    subgraph cli["cli/"]
        App["app.py — Typer app"]
    end

    subgraph workspace["workspace/"]
        Workspace["Workspace — discover(), resolve(), cache()"]
    end

    subgraph config["config/"]
        Money["money.py — Money"]
        Slug["slug.py — slugify(), slug_map()"]
        Defaults["defaults.py — Defaults"]
        Profile["profile.py — Profile"]
        Listing["listing.py — Listing"]
        Exceptions["exceptions.py — ColourExceptions loader"]
    end

    subgraph catalog["catalog/"]
        CatalogClient["client.py — CatalogClient Protocol"]
        CatalogHttp["http.py — HttpCatalogClient"]
        CatalogCache["cache.py — CachedCatalogClient"]
        CatalogFakes["fakes.py — FakeCatalogClient"]
        Resolve["resolve.py — name → id"]
    end

    subgraph engine["engine/"]
        Stage["stage.py — Stage protocol"]
        Change["change.py — Change vocabulary"]
        Lock["lock.py — Lockfile, canonical_hash()"]
        Context["context.py — RunContext"]
        Plan["plan.py — build_plan()"]
        Apply["apply.py — execute()"]
        Stages["stages/ — STAGES (empty; Render() lands in Phase 1)"]
    end

    App --> Workspace
    App --> Listing
    App --> Profile
    App --> Exceptions
    App --> CatalogCache
    App --> Plan

    Listing --> Money
    Listing -. media colour refs .-> Slug

    CatalogCache --> CatalogHttp
    CatalogCache -. implements .-> CatalogClient
    CatalogFakes -. implements .-> CatalogClient
    CatalogHttp -. implements .-> CatalogClient
    Resolve --> CatalogClient

    Plan --> Stages
    Plan --> Context
    Plan --> Lock
    Plan --> Change
    Apply --> Stages
    Apply --> Lock
    Stages -. each conforms to .-> Stage
    Context --> Workspace
    Context --> CatalogClient
```

Only `engine` computes a diff (`plan.py` / `apply.py`, via each stage's own
`plan()`). The CLI's `format_plan()` renders the `Plan` / `StagePlan` / `Change`
objects that come back; it never compares state itself. A future UI JSON
serialiser will consume the same objects, which is what keeps the two surfaces
enforcing identical rules (A2).

## `plan` data flow

```mermaid
sequenceDiagram
    participant User
    participant CLI as cli/app.py
    participant WS as Workspace
    participant Cfg as config/*
    participant Ctx as RunContext
    participant Plan as engine/plan.py
    participant Stg as Stage (STAGES)
    participant Lock as state.lock.json

    User->>CLI: etsy-listings plan take-a-hike
    CLI->>WS: Workspace.discover(--root / ETSY_LISTINGS_ROOT / walk-up)
    WS-->>CLI: root, Defaults
    CLI->>Cfg: Listing.load(listing.yaml, currency=defaults.currency)
    Cfg-->>CLI: Listing (or ConfigLoadError — reported, batch continues)
    CLI->>Cfg: Profile.load(profiles/{name}.yaml)
    CLI->>Cfg: load_exceptions(exceptions.yaml)
    CLI->>Lock: Lockfile.read(state.lock.json)
    Lock-->>CLI: Lockfile (or empty)
    CLI->>Plan: build_plan(ctx, listing, lock, STAGES)
    loop for each stage in STAGES (pipeline order, A1)
        Plan->>Stg: desired(ctx, listing)
        Plan->>Stg: last_applied(lock)
        alt stage.local is False
            Plan->>Stg: read_live(ctx, lock)
        end
        Plan->>Stg: plan(desired, applied, live) → StagePlan
    end
    Plan-->>CLI: Plan(stage_plans=[...])
    CLI->>User: format_plan(plan) — "N to run, M to change, D drift warnings"
```

Phase 0's `STAGES` list is empty, so this loop runs zero times and `plan`
always reports "no stages configured" — the empty-plan skeleton the exit
criterion asks for. Phase 1 adds `Render()` as the first real stage; the loop
shape above does not change when it does.

## Three-way comparison (target shape, PRD)

Once a stage exists, its `plan()` compares three states using the shared
`engine/change.py` helpers (`scalar`, `sequence`, `drift`):

```mermaid
graph LR
    Desired["desired\n(config files + rendered mockups)"] -->|scalar/sequence| Diff{"stage.plan()"}
    Applied["last applied\n(state.lock.json → applied.{stage})"] -->|scalar/sequence| Diff
    Applied -->|drift| Diff
    Live["live\n(Printify + Etsy APIs;\nNone for local stages)"] -->|drift| Diff
    Diff --> StagePlan["StagePlan(will_run, changes, drift)"]
```

`desired ≠ applied` is a change you made locally; `applied ≠ live` is drift —
someone edited outside this tool. `read_live()` returning `None` (`stage.local
= True`) skips the drift comparison entirely rather than every stage having to
special-case it.

## Hashing (`engine/lock.py`)

Only the lockfile's `applied` subtree is hashed, through the single
`canonical_hash()` helper — `applied_at`, `tool_version`, `remote` and absolute
paths never enter it. Any path that does enter hashed content must first pass
through `to_workspace_relative_posix()`, which is what keeps the hash identical
between a Windows machine and a Linux CI runner for the same content.
