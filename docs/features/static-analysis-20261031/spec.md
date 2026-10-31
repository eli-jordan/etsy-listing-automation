# Static analysis specification

Status: planned; implementation has not started.

Coding agents (Claude, Codex and Grok, run through T3 Code) write most of the
code in this repository. Today they see lint results only when they run
`scripts/check.sh` or when CI fails. This work widens the checks to cover
complexity, size, dead code and duplication, and feeds the results back to the
agent on every edit, so problems are fixed while the agent still has the code
in context.

This specification changes development tooling and code structure, not
application behavior. Refactors made to satisfy the new rules preserve
behavior; render refactors keep golden hashes byte-identical (ADR-0012).
Existing ADRs remain in force, particularly ADR-0052's import contracts.

## Decisions

| Question | Decision | Rejected |
|---|---|---|
| Add pylint? | No. Ruff's `PL` family ports the useful checks; pylint mostly duplicates ruff and mypy and is too slow for the edit loop. | Full pylint; pylint for `duplicate-code` only (jscpd covers duplication) |
| Complexity metric | Cognitive complexity via complexipy, plus ruff's per-function limits. | xenon (cyclomatic only, overlaps `C901`); Radon Maintainability Index (a blended score an agent cannot act on) |
| Feedback to agents | A per-edit hook, backed by `poe check` locally and CI. | `check.sh` and CI only |
| Task runner | poethepoet, declared in `pyproject.toml`. | `scripts/check.py`; prek/pre-commit |
| Existing violations | Fixed during rollout. No baseline, snapshot or temporary `noqa`. | Baseline with per-line `noqa`; per-file ignores |

## Requirements

### S01 — Ruff rule set

Add these families to `[tool.ruff.lint] select`, on top of the current
`E F W I B UP ANN C4 SIM`:

| Family | Purpose | Exceptions |
|---|---|---|
| `C90` | Cyclomatic complexity per function | — |
| `PL` | Pylint port: size limits, magic values, globals, loop-variable reuse, `subprocess.run` without `check` | `PLC0415` (inner imports) applies to `src` |
| `ARG` | Unused arguments | — |
| `FBT` | Boolean positional parameters | — |
| `SLF` | Access to another object's private members | — |
| `RET`, `PIE`, `RSE` | Redundant returns, `pass` and raise parentheses | — |
| `PERF`, `FURB` | Performance and modernisation idioms | — |
| `PTH` | `pathlib` over `os.path` | — |
| `RUF` | Ruff's own rules, including `RUF100` (stale `noqa`) | `RUF001`–`RUF003` ignored: the code uses `×` and `–` on purpose |
| `PGH` | Blanket `# noqa` / `# type: ignore` without codes | — |
| `BLE` | `except Exception:` | — |
| `ERA` | Commented-out code | — |
| `TRY` | Exception hygiene (`raise` inside `try`, `try`/`else`, `raise ... from`) | `TRY003` ignored |
| `PT` | pytest style | — |
| `N` | PEP 8 naming, including `N818` (exception names end in `Error`) | — |
| `A` | Shadowed builtins | — |
| `DTZ` | Naive datetimes | — |
| `T20` | `print` | Allowed where the CLI and `scripts/` print on purpose |
| `FAST` | FastAPI route mistakes | — |

Not enabled: `EM` and `TRY003` (message style, no quality gain), `TC` (pydantic
and FastAPI resolve annotations at runtime), `S` (mostly false positives here),
`INP` (`tests/` is a namespace package by design), `D` (agents would write
filler docstrings), `COM`/`Q`/`ISC` (the formatter owns these), and
`TID251` banned-api.

Under `tests/**`, also ignore `PLR2004`, `ARG`, `SLF001`, `FBT003`, `PLC0415`,
`T20` and `PLR0913`. Every other rule, including the complexity limits,
applies to tests.

### S02 — Complexity and size limits

| Limit | Tool | Value | Scope |
|---|---|---|---|
| Cognitive complexity | complexipy | 10 | `src`, `tests`, `scripts` |
| Cognitive complexity | `eslint-plugin-sonarjs` `cognitive-complexity` | 10 | frontend |
| Cyclomatic complexity | ruff `C901` | 8 | all Python |
| Arguments | ruff `PLR0913` | 5 | `src` |
| Branches | ruff `PLR0912` | 12 | all Python |
| Statements | ruff `PLR0915` | 50 | all Python |
| Returns | ruff `PLR0911` | 6 | all Python |

Thresholds and rule configuration are never loosened to make a check pass.

### S03 — Frontend smells

Enable `eslint-plugin-sonarjs`'s recommended configuration in the frontend
ESLint config, with `cognitive-complexity` set to 10 (S02).

### S04 — Dead code

Vulture runs over `src` at minimum confidence 90. False positives (FastAPI
routes, pydantic validators, Typer commands, protocol methods) are suppressed
inline at the definition, with a reason (S07). There is no whitelist file.

### S05 — Duplication

jscpd runs over `src` (Python and TypeScript, excluding generated files such as
`src/ui/src/api/schema.ts` and build output) and fails on any clone of 50 or
more tokens. Tests are excluded, because arrange blocks repeat legitimately.

### S06 — Per-edit agent hook

`scripts/agent_lint.py` is the only hook implementation. Two configs call it:

- `.claude/settings.json`: Claude Code `PostToolUse` matching `Edit|Write`.
  Grok Build reads this file too and maps Claude's tool names.
- `.codex/hooks.json`: Codex `PostToolUse` matching `apply_patch|Edit|Write`.
  Project hooks load only once the project is trusted in Codex.

For the edited file only, the hook:

1. Applies safe fixes. For Python, `ruff format` and `ruff check --fix`. For
   TS/TSX, `eslint --fix` and `prettier --write`.
2. Checks what remains. For Python, ruff, complexipy and mypy (through dmypy,
   S08). For TS/TSX, ESLint including sonarjs.
3. Rejects any newly added suppression that has no reason (S07).
4. Exits 0 when clean. Otherwise it exits 2 with the remaining findings on
   stderr, capped at 20 lines with a count of what was omitted.

The hook calls tools from the project `.venv` and `node_modules` directly
rather than through `uv run` or `npx`, so it stays within one to two seconds
of a warm run. When either is missing it falls back to `uv run` or `npx`
rather than skipping a check. New T3 worktrees get both from
`setup_worktree.sh`, which `t3.json` runs on worktree creation and which must
work when T3 launches it. Whole-program checks (Vulture, jscpd, Import Linter) run in
`poe check` and CI only.

Grok's PostToolUse feedback path is undocumented. Implementation verifies
whether Grok returns the hook's stderr to the model. If it does not, Grok is
still covered by `poe check` and CI, and this specification records the gap.

### S07 — Suppressions carry a reason

A new `# noqa: <codes>`, `# type: ignore[<code>]` or Vulture suppression must
end with ` -- <reason>`. The hook rejects one without a reason. `PGH` forbids
blanket suppressions and `RUF100` removes stale ones. AGENTS.md states the
policy.

### S08 — dmypy lifecycle

- A `SessionStart` hook starts `dmypy` in the background for the worktree,
  with `--timeout 1800`, so an orphaned daemon exits after 30 idle minutes.
- The edit hook restarts the daemon if it has died. Until the daemon is warm
  it skips the mypy step rather than block on a cold start (about 34s; Grok's
  default hook timeout is 5s).
- A `SessionEnd` hook runs `dmypy stop`.

### S09 — poethepoet is the single source of checks

Tasks in `pyproject.toml` define each check once. `poe check` formats and
fixes in place, then runs every gate, replacing `scripts/check.sh`, which is
deleted. Check-only tasks serve CI. The `unset ETSY_LISTINGS_ROOT` behavior and
the frontend skip when npm is absent move into the task configuration. README
and AGENTS.md command references are updated.

### S10 — CI layout

- A new `quality` job on ubuntu runs the check-only lint task: ruff format
  check, ruff check, mypy, Import Linter, complexipy, Vulture and jscpd.
- The `python` matrix (ubuntu and windows) keeps only tests and coverage.
- The `frontend` job runs ESLint with sonarjs through its existing lint step.
- CI invokes poe tasks instead of listing commands, so the
  "change one, change the other" note in `ci.yml` is removed.

### S11 — Rollout

Tooling lands first, so later work runs under the hook. Each subsequent PR
enables its rules at zero violations, so main stays green and no temporary
suppression is added. Complexity refactors come last, and their gates switch
on once every function in scope is under the limit. The [plan](plan.md) gives
the PR sequence.

Measured on 2026-10-31 in `src`: 90 functions over cognitive complexity 10,
39 over `C901` 8, 57 `PLR0913`, 44 `N818`. Tests: 9 functions over cognitive
complexity 10.

### S12 — Documentation

AGENTS.md gets a short section pointing to this specification: the hook
exists, findings must be fixed rather than suppressed, suppressions need a
reason, and thresholds are not changed to pass a check.

## Sources

- [Ruff FAQ: Ruff and Pylint](https://docs.astral.sh/ruff/faq/#how-does-ruffs-linter-compare-to-pylint)
- [complexipy](https://github.com/rohaquinlop/complexipy)
- [Codex hooks](https://learn.chatgpt.com/docs/hooks)
- [Grok Build hooks](https://docs.x.ai/build/features/hooks)
- [Vulture](https://pypi.org/project/vulture)
- [Claude Code hooks for linting](https://hackernoon.com/claude-code-hooks-how-to-stop-ai-agents-from-breaking-your-code)
