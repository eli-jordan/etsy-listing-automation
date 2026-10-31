# Runtime audit fixes

The 2026-10-31 Admin audit identified six Runtime and persistence issues in the
stack ending at `450ca963af43801aa2766da954e9eec46d7f3c53`. This delivery fixes
R2, S1, S2, S3, M1 and M2 on `fix/admin-audit-runtime`, based on
`feat/admin-6-ai-time-limits`. The State lane owns R1, Q1, Q2 and I1.

## Fixes and regressions

| ID | Change and commit | Regression |
|---|---|---|
| R2 | `26a9f5e0` preserves line boundaries when moving or inserting named provider rows at EOF. YAML parser/editor refusals become an actionable `InvalidSettingsEdit` and leave the source intact. `90e61b17` completes the boundary controls. | Real Settings owner and HTTP saves cover LF/CRLF with and without a final newline, reorder, insertion, comments, saved spelling and byte/file-identity no-ops. Merge keys and shared scalar aliases exercise safe refusal. |
| M1 | `bec96edc` gives the listing callback a deep copy of saved content, compares against the saved document, and returns the canonical document written after a change. | Public `ListingDocuments.edit` persists direct and nested in-place mutations. A mutate-then-undo callback leaves source bytes and file identity untouched, including legacy `design:` spelling. |
| S1 | `111a943a` uses the shared managed process runner for discovery, one overall probe budget and a lifespan-owned background startup attempt. Concurrent reads do not wait behind discovery. Windows cleanup itself is bounded. `e1cb26f4` covers the visible pending status in both color preferences. | A genuine local parent/descendant inherits captured pipes; advancing the discovery deadline kills the tree and stops its heartbeat. Cache expiry, explicit refresh, stale successful choices, concurrent reads, construction, cancellation and bounded stop have public-owner tests. Host tests serve health during a held probe and cancel it at shutdown. |
| S2 | `f6a017b9` maps invalid saved settings to existing readiness/start/batch refusals before registering a run. `dcfd8384` reports an actionable 422 when existing batch responses cannot load concurrency. | HTTP tests cover Admin settings, listing readiness, manual start, staging create/read/confirm, existing batch reads and controls. Invalid range/floor/provider values and malformed YAML retain file/key detail; no provider runs. An unrelated factory defect still propagates. |
| S3 | `6003e0b7` recognizes Claude's observed selected-model refusal and a structured `model_not_found` in the vendor error object. `90e61b17` adds structured-code and effort-envelope controls. | Adapter/process envelopes and stdout/stderr pass through the real orchestrator to a usable fallback, retaining the rejected preference. Incidental model mentions, telemetry and generation failures do not fall back. |
| M2 | `f28edc54` removes the generated UI Codex hooks from tracking and ignores that exact local artifact. | Ignore inspection and the ordinary portable frontend build/lint gates replace a filename-only test. |

The listing owner, Settings owner, application coordinator and HTTP response
models remain the existing interfaces. ADR-0055 still requires exact untouched
source and no-replace semantic no-ops. ADR-0056 keeps discovery advisory and
saved preferences intact. Generation's ADR-0057 timeout/fallback decisions are
unchanged. Discovery shares fifteen seconds across the two CLI probes, followed
by at most five seconds of managed cleanup; lifespan shutdown waits at most six
seconds. Catalog reads during an attempt carry an in-progress problem through
the existing wire field, with pinned Claude choices available immediately.

## Validation

The first full gate exposed an additional failure in unchanged `file_version`
code. Holding a real writable handle reproduced it deterministically: repeated
overwrites reused one USN even after `fsync`, while closing the last writer
advanced it. This is the accumulation behavior described by Microsoft's
[change-journal documentation](https://learn.microsoft.com/en-us/windows/win32/fileio/change-journal-records).
Commit `2280384a` trusts the fast USN path only while a short read-data metadata
handle excludes other writers, falling back to the existing content hash on a
sharing conflict. Attribute-only access does not enforce those checks; the
[CreateFileW sharing rules](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
also cover writable mappings. Atomic replacement remains shared. The extra
regression uses the public `file_version` interface with a real open writer.
All 79 targeted cache/storage tests pass, and a 2,000-write probe passes with
and without another writer. Quiescent checks retain USN tokens and averaged
about 0.000114 seconds in the local probe. This fixes a diagnosed gate defect;
the original failure is not dismissed as a flake.

Focused red/green runs reproduced the behavioral failures before their
corrections. The genuine discovery process case took about ten seconds before
the fix and under one second afterward, while asserting that its descendant's
heartbeat stopped. This is local regression evidence, not a provider benchmark.
The provider browser tests cover both color preferences at 1280 by 800,
including the in-progress status and explicit Refresh. No frontend layout or
mockup changed. OpenAPI and typed-client regeneration produces no schema diff.

The initial delivery at `2280384abd5bd3c9f2ebbe0636efed168dd95fc8` passes `./scripts/check.sh`
in Cygwin zsh. Python reports 3,767 passed, seven skipped and 55 deselected,
with 95.65% branch-enabled combined coverage and 90.44% of branches covered.
The frontend reports 1,283 passed across 97 files and 90.17% branch coverage.
Formatting, lint, strict typing and all eleven Import Linter contracts pass.
The separate `npm run test:design` run passes four tests; the full gate repeats
that design check successfully. `npm run build` passes. The separate
`ETSY_LISTINGS_REQUIRE_EVERY_LAYER=1 uv run pytest -m browser` run passes all
152 cases without skips, and the final full gate repeats that browser layer
after the Windows token correction. OpenAPI/client regeneration and final
inspection leave both generated files unchanged.

The final EOF control suite passes 66 Settings-owner/HTTP cases, the Claude
adapter suite passes 34 cases, and the cache/storage follow-up passes 79 cases.
Changes add 95 production Python SLOC and 540 test SLOC, measured with
`scripts/sloc.py`, excluding prose. The pending-discovery captures at 1280 by 800
were checked in both color preferences: the notice stays within its row and
the saved selectors remain visible. The app keeps its agreed single palette.

GitHub e2e dispatch belongs to the parent under its serial lock and remains
pending with independent review and CI. This lane never runs local real-shop
e2e, changes credentials or invokes live model generation.

Delivery: [PR #150](https://github.com/eli-jordan/etsy-listing-automation/pull/150).

## S1 follow-up: launcher exits before pipe EOF

The independent Standards review reproduced a residual lifecycle defect after
the initial delivery: a synthetic launcher exited successfully while its child
kept captured pipes open. `taskkill /T` could no longer find the exited launcher,
so discovery exhausted its cleanup allowance with the child and reader still
alive. The expected-correct public `ModelDiscovery.read` regression first
failed before implementation in 6.03 seconds. With the final launcher handshake,
it also fails against the published `19b39821` owner in 6.41 seconds with
“the descendant survived managed cleanup”; its `finally` cleanup stops the
synthetic process. That confirmation loaded the old owner from Git into the
current public discovery test without changing the checkout.

The shared process owner now attaches an unnamed, non-inherited Windows Job
Object atomically during `CreateProcessW`, before the child can execute. The
job disallows breakaway and has kill-on-close protection. It remains the owner
after launcher exit, so neither a descendant snapshot nor a helper process is
needed. Explicit handle inheritance is limited to stdin, stdout and stderr.
Cleanup terminates the job, drains and joins the readers, checks that the job
has no active processes, and waits for the pinned launcher handle within one
five-second allowance. Successful and failed launcher exits also end leftover
descendants without waiting for the generation/discovery deadline.

This uses the Windows 10+ `PROC_THREAD_ATTRIBUTE_JOB_LIST` contract documented
by Microsoft in
[process attributes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)
and [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).
POSIX retains a new session's unreaped leader with `waitid(WNOWAIT)` until
group termination, reserving its PID/PGID even after exit. The raw descendant
PID scan is removed. POSIX children must remain in their inherited group;
Windows job ownership also contains nested jobs and outlives the launcher.
The macOS Python 3.12 fallback uses libc's waitid contract and the constants in
Apple's [wait.h](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/wait.h).
Discovery and adapters contain no platform-specific cleanup code. ADR-0056's
advisory cache/lifecycle and ADR-0057's generation/fallback budgets are unchanged.

The real-process fixture holds the launcher behind an acknowledgment until the
test pins launcher and descendant identities. On Windows it uses the base
interpreter so a venv redirector cannot be mistaken for the CMD launcher.
It waits on that pinned launcher before triggering timeout or cancellation.
Assertions cover child
liveness, a stopped heartbeat, and joined reader threads. Early success and
error exits run with inherited and redirected pipes. The original still-running
launcher/descendant test remains and uses an actual synthetic executable.
Obsolete taskkill/private-helper wiring tests
are replaced by real public I/O tests for argument quoting, cwd, UTF-8 input,
failure output, simultaneous large streams and launch refusal. A red/green
argument control also preserves Popen's embedded-NUL refusal: native Windows
launch must reject that input instead of silently truncating the command.

Focused validation passes all 29 process, discovery and host-lifecycle cases.
The final `./scripts/check.sh` run passes in Cygwin zsh: 3,763 Python tests pass,
seven skip and 55 are deselected. Branch-enabled combined coverage is 95.47%;
3,832 of 4,250 branches are covered (90.16%). The frontend passes 1,283 tests
across 97 files with 90.15% branch coverage. Ruff formatting/lint, strict typing
and all eleven Import Linter contracts pass. Separate `npm run test:design`
passes four tests, and `npm run build` passes. The separate
`ETSY_LISTINGS_REQUIRE_EVERY_LAYER=1 uv run pytest -m browser` run passes all
152 cases without skips. The final full gate repeats its browser and design
layers successfully. Linux and macOS process-owner typing also passes; actual
local process execution is Windows evidence.

This follow-up adds 275 production Python SLOC and 54 test SLOC, measured with
`scripts/sloc.py`. The full PR adds 370 production Python SLOC and 594 test SLOC.
There are no UI, generated-schema, dependency-pin or file-mode changes in this
follow-up. The ignored UI hooks remain untracked. Shared mechanism documentation
changes are confined to `docs/architecture.md` and `core/ai/__init__.py`.

Linux execution, independent review of this new Runtime head and serial GitHub
e2e remain CI/parent work. No live provider or real-shop e2e ran here.
