# Static analysis implementation plan

Status: planned; no implementation PRs have been opened.

This plan delivers the [specification](spec.md) through the repository's
[implement-stack skill](../../../.claude/skills/implement-stack/SKILL.md). The
work has no UI, so no mockup or interactions document applies. PR 5 changes
frontend source only to satisfy lint rules; rendered behavior must not change.

The result is a codebase that passes the full rule set with zero violations
and no baseline, and a per-edit hook that holds agents to it.

## Stack and ownership

Use one isolated worktree and background implementer per PR. Each branch
starts at the preceding PR's reported build tip and targets that branch; PR 1
targets `t3/542c135f` (or `main`, once the planning commit has merged). Merge
bottom-up. After a build report, freeze that branch against rewrites, start
the next builder, then continue the same agent as finisher. Finishing adds
commits only.

Register every created or worked PR with `link_pull_request` when the thread
tool is available, and report a linking failure explicitly.

The planning commit contains `spec.md`, this plan and the
[docs index](../../README.md) row, staged by explicit path. Its full SHA is the
**stack base**; record it in `execution.md` before launching PR 1. The
measurements below were taken on `00e1e371` (main, 2026-10-31).

| PR | Conventional title | Spec | Depends on |
|---|---|---|---|
| 1 | `build: add poe task runner, agent lint hook and quality CI job` | S06–S10, S12 | Stack base |
| 2 | `style: enable mechanical ruff families and rename exceptions` | S01 | 1 |
| 3 | `refactor: enable judgment ruff families and argument limits` | S01, S02 (arguments) | 2 |
| 4 | `refactor: remove dead code and duplication` | S04, S05 | 3 |
| 5 | `refactor(ui): enable sonarjs recommended rules` | S02 (frontend), S03 | 4 |
| 6 | `refactor: reduce complexity in application and preparation` | S02 | 5 |
| 7 | `refactor: reduce complexity in engine and remaining packages; enable gates` | S02 | 6 |

Each PR enables its rules in the same change that removes their last
violation, so every layer is green and no temporary suppression is added.
There is no size limit per PR. A layer that grows unreviewable may still split
into named adjacent layers; update this table and the ledger before starting
its successor.

## Preflight environment block

Create `execution.md` beside this plan with the environment block, baseline,
per-PR ledger (branch, worktree, agent id, base SHA, build tip, final tip, PR
number/URL, state) and the hook verification results from PR 1. Paste the
environment block into every BUILD-BRIEF.

| Field | Required record |
|---|---|
| Plan/spec | Paths to this plan and the spec |
| Base | Stack base SHA and branch |
| Shell/worktree | Cygwin zsh; `cd` to the worktree after the login shell starts in `/home/Admin` |
| Toolchain | `uv sync` and `npm install` in `src/ui` succeed; any workaround; CI keeps `npm ci` |
| Baseline | Full non-browser, non-e2e pytest and full Vitest on the stack base; failing test ids, skips, counts |
| Golden renders | The golden test selection and its pass state on the stack base |
| GitHub | `gh auth status` and a push dry-run |
| Agents | Grok and Codex reachable through `delegate_task` (see `orchestrator_capabilities`) |
| Real shop | e2e workflow and credentials available; no run in progress |

## Measured starting point

All counts are for `src/etsy_listings` unless noted.

| Check | Violations |
|---|---|
| Mechanical ruff families (PR 2) | under 20 per family outside `RUF`, `PT` and `T20`; 44 `N818` exception renames |
| `FBT` / `ARG` / `SLF` (PR 3) | 29 / 44 / 37 in src; tests partly exempt |
| `PLC0415` / `PLR2004` (PR 3) | 38 / 50 |
| `PLR0913` / `PLR0917` (PR 3) | 57 / 8 |
| Vulture, confidence 90 (PR 4) | 1 (`core/config/money.py:84`) |
| jscpd, 50 tokens, app source (PR 4) | 41 clones: 26 Python, 15 TS |
| sonarjs recommended (PR 5) | 143: 84 `no-nested-conditional`, 30 `cognitive-complexity`, 29 other |
| Cognitive complexity > 10 (PRs 6–7) | 90 in src (application 19, preparation 18, engine 13, workspace 7, config 6, clients 6, ai 6, market 4, cli 4, batches 3, server 2, render 2), 9 in tests |
| `C901` > 8 (PRs 6–7) | 39 |

Builders re-measure on their own base; these numbers set expectations, not
scope. A rule's scope is "zero violations", whatever the count turns out to be.

## Shared gates and method

| Gate | Exit evidence |
|---|---|
| G1 — Targeted builder | BUILD-BRIEF's targeted checks pass, plus the rules this PR enables at zero violations |
| G2 — Full local | `uv run poe check` passes (`./scripts/check.sh` on the stack base), coverage floors unchanged |
| G3 — Browser | `ETSY_LISTINGS_REQUIRE_EVERY_LAYER=1 uv run pytest -m browser` passes against a built SPA |
| G4 — Golden renders | Golden render tests pass with no regenerated goldens; any golden diff is a defect |
| G5 — Hosted | PR open, linked, CI green on the final SHA |
| G6 — Live | Serial e2e green with its run URL, for PRs whose diff touches `core/clients`, `core/engine` or `core/application`; otherwise recorded as not required |

Every finisher runs G2–G5, and G6 where it applies. Refactors preserve
behavior. The existing suite and the 85% branch floors are the safety net, and
no characterization tests are required. A builder that finds a refactor target
with no covering test reports it rather than refactoring blind. No goldens are
regenerated, no thresholds lowered, no `pragma: no cover` added, and no rule
configuration is loosened to pass (spec S02). Suppressions follow S07: a
specific code and a ` -- reason`.

The hook from PR 1 runs for every later builder. It enforces only the rules
enabled at that point in the stack; its complexity step switches on in PR 7
together with the gates.

## PR 1 — Tooling and the agent feedback loop

**Scope:**

- **poethepoet (S09).** Add it to the dev group. Define tasks once in
  `pyproject.toml`: a fixing `check` that replaces `scripts/check.sh` (format,
  lint, types, imports, tests with coverage, frontend), and check-only tasks
  for CI. Carry over `unset ETSY_LISTINGS_ROOT` and the frontend skip when npm
  is absent. Delete `scripts/check.sh` and update every reference in README,
  AGENTS.md, `docs/` (current docs, not `docs/history/`) and skill briefs.
- **CI (S10).** Add a `quality` job on ubuntu running the check-only lint task
  (ruff format check, ruff check, mypy, Import Linter). The `python` matrix
  keeps only tests and coverage. CI calls poe tasks, and the
  "change one, change the other" comment is removed.
- **Agent hook (S06, S07).** `scripts/agent_lint.py`, called with the hook
  payload on stdin. For the edited file: safe fixes, remaining findings from
  ruff, dmypy and (for TS/TSX) ESLint, the suppression-reason check, then exit 2
  with up to 20 lines and an omitted count, or exit 0. Files outside the repo
  and non-source files exit 0. Complexipy is wired in but disabled until PR 7.
  Wire it from `.claude/settings.json` (`PostToolUse`, `Edit|Write`) and
  `.codex/hooks.json` (`PostToolUse`, `apply_patch|Edit|Write`).
- **dmypy lifecycle (S08).** `SessionStart` starts the daemon in the
  background with `--timeout 1800`; the edit hook restarts it if it has died
  and skips mypy until it is warm; `SessionEnd` stops it. Both configs.
- **Missing environment.** The hook uses `.venv` and `src/ui/node_modules`
  binaries directly. When they are missing, it falls back to `uv run` and
  `npx` rather than skipping a check.
- **Worktree setup script.** `t3.json` runs `./setup_worktree.sh` on worktree
  creation (`uv sync`, then `npm install` in `src/ui`). It works when run by
  hand but fails when T3 runs it. Use the `diagnosing-bugs` skill to find the
  cause (likely the shell T3 launches it in on Windows: Git Bash breaks the
  npm launcher, and `cmd` cannot run a `.sh`) and fix it so it works from both.
- **Documentation (S12).** An AGENTS.md section pointing to the spec: the hook
  exists, findings are fixed rather than suppressed, suppressions carry a
  reason, thresholds are not changed to pass.

**Entry points:** `scripts/check.sh`, `.github/workflows/ci.yml`,
`pyproject.toml`, `t3.json`, `setup_worktree.sh`, AGENTS.md, README.

**Exit conditions:**

- `uv run poe check` runs everything `check.sh` ran, with the same test
  selection and coverage floors; `check.sh` is gone and nothing references it.
- CI runs lint once in `quality` and tests on both OSes, through poe tasks.
- `agent_lint.py` has unit tests through its stdin/exit-code interface: a
  clean file exits 0; a lint error exits 2 with the finding; auto-fixable
  problems are fixed and exit 0; a `# noqa` without a reason exits 2; output
  is capped; a non-Python/TS file exits 0; a missing `.venv` falls back.
- A deliberate bad edit by the builder (a Claude agent) is reported by the
  hook in its own session.
- A warm hook run on one file completes in about two seconds.
- `setup_worktree.sh` succeeds when T3 creates a worktree (checked by the
  orchestrator, below).

**Orchestrator verification after the build report.** Before continuing the
finisher:

1. Create a fresh T3 worktree from PR 1's tip and confirm the setup script
   completes.
2. Send a Grok delegate, then a Codex delegate, through `delegate_task` into
   PR 1's worktree (trust the project for each). Ask each to add a function
   with a deliberate lint error and then report what it saw after the edit.
   Pass when its transcript shows the hook's findings and a follow-up fix.
3. Record both results in `execution.md`. If an agent does not receive the
   feedback, the finisher records the gap in spec S06 with the evidence.

## PR 2 — Mechanical ruff families and exception renames

**Scope (S01):** enable `RET`, `PIE`, `RSE`, `PERF`, `FURB`, `PTH`, `RUF`
(ignore `RUF001`–`RUF003`), `PGH`, `BLE`, `ERA`, `A`, `DTZ`, `T20`, `FAST`,
`PT`, `TRY` (ignore `TRY003`), `PLE`, `PLW` and `N`. Apply auto-fixes, fix the
rest by hand, delete stale `noqa` comments found by `RUF100`, and rename the 44
exception classes to end in `Error`, updating every reference including tests
and docs. `T20`: allow `print` where the CLI and `scripts/` print on purpose,
through per-file ignores. `FAST003` unused path parameters are fixed in the
route, not suppressed.

**Exit conditions:** `ruff check .` clean with these families enabled; no
behavior change; exception renames leave no old name in `src`, `tests` or
current docs (`git grep` evidence). Report auto-fix output separately from
hand edits.

## PR 3 — Judgment ruff families and argument limits

**Scope (S01, S02):** enable `FBT`, `ARG`, `SLF`, `PLC0415` (src), `PLR2004`
(src), `PLR0913` at 5 and `PLR0917`, with the S01 per-file ignores under
`tests/**`. Boolean positional parameters become keyword-only. Unused
arguments are removed, or kept with `@override` where an interface requires
them. Magic values become named constants. Inner imports move to module level;
any that must stay (an optional heavy dependency, a cycle Import Linter
already allows) keep a reasoned suppression. Functions over five arguments are
reshaped (parameter objects, keyword-only grouping, splitting) rather than
suppressed.

**Exit conditions:** `ruff check .` clean; Import Linter contracts unchanged
and passing; every remaining suppression in scope has a reason; no HTTP or CLI
signature change unless intended, in which case regenerate
`docs/openapi.json` and `src/ui/src/api/schema.ts` in the same commit.

## PR 4 — Dead code and duplication

**Scope (S04, S05):** add Vulture (min confidence 90, scope `src/etsy_listings`)
and jscpd (50 tokens; Python and TS under `src/etsy_listings` and
`src/ui/src`; excluding tests, `schema.ts`, `static/` and build output) as poe
tasks, run in `quality` and in `poe check`. Fix the Vulture hit and remove the
41 clones by extracting shared helpers or components.

**Exit conditions:** both tools pass in CI and locally; each removed clone's
callers still pass their tests; extracted helpers live in the owning module
under ADR-0052's import contracts.

## PR 5 — Frontend smells

**Scope (S03, S02):** add `eslint-plugin-sonarjs` with its recommended config
and `cognitive-complexity` at 10. Fix all 143 findings: nested ternaries
become early returns, lookup tables or small components; complex components and
hooks are split. Test-file findings are fixed too.

**Exit conditions:** `npm run lint` clean; typecheck, Vitest with the 85%
branch floor, prototype tests and the build pass; G3 passes with no rendered
change.

## PR 6 — Complexity in application and preparation

**Scope (S02):** bring every function in `core/application` and
`core/preparation` (including the Marigold worker under
`core/preparation/distribution`) under cognitive complexity 10, `C901` 8 and
the `PLR091x` limits (12 branches, 50 statements, 6 returns). Gates stay off
until PR 7; measure with `uvx complexipy` and `ruff check --select C901,PLR091`.

**Exit conditions:** zero findings in both packages at the target thresholds;
G4 passes; worker protocol tests pass.

## PR 7 — Complexity in engine and the rest; enable the gates

**Scope (S02):** the same refactor for `core/engine` (render stages are
golden-sensitive), the remaining packages, `cli`, `server`, `scripts` and the 9
test functions. Then enable complexipy at 10 (poe task, `quality` job, hook)
and `C901` at 8 with the `PLR091x` limits in ruff config.

**Exit conditions:** `poe check` and CI pass with every gate on; the hook
reports a deliberately complex new function; G4 passes with byte-identical
goldens; spec status updated to delivered with PR links in this plan.
