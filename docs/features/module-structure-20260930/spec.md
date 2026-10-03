# Module structure and shared application operations

Status: implemented. Agreed 2026-09-30; delivered by the stack in the [plan](plan.md).

The application exposes transport-independent operations that can be
tested without invoking Typer or constructing an HTTP request. The source tree
distinguishes core, server, CLI and React responsibilities while retaining
one repository and one Python distribution. This improves both navigation and
the interfaces through which callers exercise application behaviour.

## Source and test layout

```text
src/
    etsy_listings/
        core/
            application/
            engine/
            workspace/
            render/
            clients/
            config/
            ai/
            market/
            batches/
            listing_templates/
        server/
        cli/
    ui/
        package.json
        src/                    # React code and colocated TypeScript tests
tests/
    core/                       # unit, behaviour, golden, contract as needed
    server/                     # unit, behaviour, contract as needed
    cli/                        # unit, behaviour as needed
    browser/
    e2e/
    support/
    fixtures/
```

Existing domain subdivisions retain their responsibilities. Directly
testable, focused operations live in `core/application/` when they hide
workflow coordination; existing deep interfaces such as engine plan/apply
need no pass-through application wrapper. Shared client construction and
transport-independent errors also belong in core. The Python package root
remains lightweight, retaining package metadata rather than re-exporting all
capabilities.

Python tests are grouped by ownership first and test layer second. Browser
and real-service end-to-end tests remain shared. Builders, scripted prompts,
fakes and fixtures remain shared rather than being duplicated per area.
Project-wide build/CI tests may remain directly under `tests/`. TypeScript
tests stay beside their subjects under `src/ui/src/`, with shared Vitest setup
inside that npm project.

## Responsibility and dependency rules

Core includes file writes, external clients and background workflows; it is
transport-independent rather than universally pure. Render passes and other
pure submodules retain their existing purity. Application operations own
workflow validation, read/merge/write coordination, job state, scheduling,
cancellation rules, locks and application events. Dependencies arrive through
focused injectable interfaces. Results and refusals have application meaning
rather than HTTP status codes or terminal formatting.

Server owns FastAPI routing, wire schemas, HTTP status mapping, SSE framing
and disconnect handling, HTTP-oriented caches, static serving and app
startup/shutdown wiring. It constructs and manages the lifetime of core job
coordinators without owning their scheduling rules. A transport-independent
model may be reused as a wire payload when their meanings coincide; duplicate
DTOs are required only where the representations genuinely differ.

CLI owns Typer, prompts, terminal output, command options and interactive
auth/new/setup sequencing. Reusable creation, configuration and credential
operations belong in core and existing CLI commands adopt them where
applicable through direct Python calls. CLI does not gain server run-resource
semantics or queue coordination as a side effect of sharing operations.

Import Linter enforces these dependency and protected-implementation
contracts in local checks and CI:

| Importer | Allowed relationship |
|---|---|
| Core | Cannot depend on server, CLI, FastAPI, Typer or terminal/prompt adapters, including indirectly |
| Server | Uses declared core interfaces; cannot depend on CLI |
| Ordinary CLI commands | Use declared core interfaces; cannot depend on server |
| CLI `ui` launcher | May import the narrow server startup interface |
| Application callers | Cannot bypass protected implementation modules |

Internal core modules may collaborate through documented interfaces; this
does not impose an invented total ordering on the existing domain graph.
Python metadata and package `__init__.py` exports must not provide a hidden
route around the contracts.

## Preserved behaviour and intentional exception

CLI commands, HTTP request/response contracts, SSE event shapes and replay,
workspace files, deployment hashes, lockfiles, render bytes and installation
behaviour remain unchanged except for native-host removal. Old Python import
paths are intentionally removed without compatibility shims; repository
callers and tests move to the new paths.

`etsy-listings ui` serves HTTP in the foreground without opening a native
window or automatically launching a browser. Remove `--browser`, `--debug`,
pywebview and native-only code and tests. Retain the command, workspace
selection, host/port options and defaults, HTTP app lifecycle and orderly
shutdown. This explicitly replaces older native-window and flag instructions
where they appear in current documentation.

The React application continues to ship as built assets in the Python wheel.
Release builds use locked npm dependencies and rebuild current source;
installation needs no Node. Editable/Python-only development retains the
existing supported fallback behaviour. Moving npm source to `src/ui/` does
not require its installed asset location to mirror that source path.

Process-local locks, in-memory run retention, FIFO/sequential deployment,
per-run AI threads, batch limits, deploy precedence and cancellation semantics
are preserved. CLI apply still does not coordinate with the UI batch queue
(ADR-0050). Cross-process protection, persistent run history, remote hosting,
separate distributions and CLI-over-HTTP are outside this work.

## Authority and completion

This specification owns the agreed restructure requirements and explicit
native-host amendment. [ADR-0052](../../adr/0052-separate-core-from-transport-adapters.md)
records their architectural rationale; the [plan](plan.md) records delivery.
Where an older document assigns application logic to `ui` or command
packages, these ownership decisions govern. Unrelated engine, rendering,
workspace, credential and currency invariants remain in force.

[Architecture](../../architecture.md) describes the implemented tree. An
inconsistent legacy sentence found later must be replaced, not retained
alongside a contradictory new section. A conflicting ADR, if discovered, must
be amended in a separate documentation commit before the conflicting
implementation; the stack found none.
