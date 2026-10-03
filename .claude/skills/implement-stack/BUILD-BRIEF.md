# Build brief

The prompt for PR n's builder. Fill every `<…>`; delete nothing but the
brackets. The builder starts with an empty context, so the brief carries
everything.

````markdown
You are implementing **PR <n>** of a stacked PR series in an isolated git worktree. The main agent does GitHub: do not push or open a PR.

## Setup
1. `git checkout -b <branch> <base commit>`. <base commit> is the tip of
   `<PR n-1 branch>` (or the stack base). That branch may gain new commits,
   never rewrites; rebase onto it only when told.
2. <environment block from preflight: toolchain commands, workarounds,
   baseline failures by test id, screenshot recipe>

## Read before coding
- `<plan path>`, all of it. Your scope and success conditions are
  **"PR <n> — `<title>`"**, with <decisions it cites: A…, PRD …>.
- <spec and interactions sections this PR claims>
- <mockup frames for this PR's screens, if any>
- <code entry points the plan names, if any>

## How to work
- Use the `tdd` skill: red-green-refactor through public interfaces. Every
  acceptance test the plan names for this PR is seen failing before it passes.
- Cite decisions in commits and in comments where a choice looks arbitrary.
- If the HTTP surface changes, regenerate `docs/openapi.json` and
  `src/api/schema.ts` in the same commit as the change.
- A pre-existing bug or failing check you hit: fix it in its own commit and
  report it.
- Stay under the plan's size limit, measured with
  `git diff --shortstat <base commit>...HEAD`.
- Logical commits, conventional titles.

## Targeted checks, before returning
Run and make pass:
- the Python test files you added or touched, and the whole unit layer
  (`uv run pytest tests/core/unit tests/server/unit tests/cli/unit`);
- the vitest files you added or touched;
- `ruff format . && ruff check .`, `mypy src`, and in the frontend
  `npx prettier --check .`, `npx eslint .`, `npx tsc -b --noEmit`.

The full suite, coverage gates, browser layer, screenshots, CI and e2e come in
a later finish pass. Commit everything.

## Report
- branch, worktree path, tip commit, commit list, diffstat total;
- each scope item and success condition from the plan: done / partial / not
  started, with the test that proves it;
- the checks you ran and their results;
- pre-existing issues fixed;
- choices worth reviewing, and anything undone or uncertain.
````
