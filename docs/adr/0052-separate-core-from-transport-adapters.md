# ADR-0052: Separate core from transport adapters

Status: accepted; implemented by the [module-structure plan](../features/module-structure-20260930/plan.md).

Keep one Python distribution with `core`, `server` and `cli` under
`src/etsy_listings`, and move the React/npm project to `src/ui`. Core exposes
transport-independent operations, including side effects and background
coordination; server and CLI translate those operations into HTTP and terminal
interactions. Preserve existing domain modules and introduce focused
`core/application` modules where coordinating a workflow earns a shared
interface. Enforce dependency direction and protected implementation modules
with Import Linter, permitting only the CLI `ui` launcher to import the
server startup interface.

This separates rules from entry points so workflows can be reused and tested
directly. A directory-only reorganization would leave application rules tied
to requests and prompts. A strictly pure core would require another area to
own most real workflows; effects belong behind injectable interfaces instead.
Four separately arranged Python source roots would complicate the existing
single-distribution build without a current independent-release requirement.
Keeping the npm project under `src/ui` makes it accessible while keeping
application source together.

The HTTP host still owns worker lifetime, SSE transport and asset serving.
Moving scheduling into core does not change FIFO execution, AI cancellation,
batch dispatch, deploy precedence, process-local locks or in-memory run
retention (ADR-0041, ADR-0048, ADR-0050). CLI uses shared Python operations
without acquiring the server's queue or requiring a running server. Built
React assets still ship in the wheel, and public HTTP shapes remain generated
from FastAPI (ADR-0011). Old Python import paths have no compatibility shims.

Import Linter is preferred to custom import tests for explicit graph
contracts, including indirect dependencies, and to symbol-level interface
configuration because package-level interfaces are sufficient for this
migration. Import restrictions constrain architecture; behaviour, contract,
golden and browser tests remain necessary evidence of correctness.

The [module-structure specification](../features/module-structure-20260930/spec.md)
owns the detailed requirements, including removal of the unused native host.
That removal, exact folder names, test-directory ordering and the choice of
enforcement library do not each need a separate ADR. Their rationale is
recorded here or in the specification rather than creating redundant records.

First recorded 2026-09-30 from the confirmed module-structure design interview.
