---
name: implement-stack
description: Implement an implementation plan as a stacked PR pipeline - one background agent per PR.
disable-model-invocation: true
---

# Preconditions

If any of the below preconditions are not met, ask the user to supply them.
If not supplied abort.

* An implementation plan with multiple PRs called out, each with specific exit conditions.
* A product specification linked from the implementation plan
* If UI is involved:
  - A UI mockup
  - A UI interactions companion document

# Implement a stacked plan

You are the **orchestrator**. You write no feature code. You run a **pipeline**
over the plan's PRs: each PR is built by its own background **implementer**
agent, in its own git worktree, and finished by that same agent later.

```
PR n:    build ──► report ──► finish (full gates, PR, CI, e2e) ──► report
PR n+1:                   └─► build ──► report ──► finish ...
```

The builder works from targeted checks only; the finisher owns every
exit condition.

## 1. Preflight

Done when every item below is answered and written into an **environment
block** you will paste into every brief.

- The plan: its path, the PR list with titles, each PR's scope and success
  conditions, the shared gates (`G1`…), and the stack base (the commit the
  plan was committed on).
- The toolchain works here: `uv sync`, `npm install` in
  `src/ui`, and any workaround needed to make them work.
- A **baseline**: the full non-browser pytest and vitest on the stack base.
  Every failure there is pre-existing; record each by test id.
- GitHub reachable: `gh auth status`, and a push dry-run.
- Screenshots possible: the app (`etsy-listings ui`) and the mockups
  (`npx marver dev`) both serve, and a headless browser can capture a frame.
  Record the exact recipe that worked.

Any item that fails: fix it or stop and tell the user.

## 2. Launch PR n's builder

Start a background agent in an isolated worktree . Its prompt is
[BUILD-BRIEF.md](BUILD-BRIEF.md), filled in for this PR, branching from the
**tip** of PR n-1 (the stack base for PR 1).

Keep a ledger per PR: branch, worktree path, agent id, base commit, tip, PR
number, state (`building` / `finishing` / `open` / `green`).

## 3. When a build report arrives

1. Read it against the plan's section for this PR: every scope item and
   success condition has a status, and every "undone or uncertain" item has a
   decision from you (fix now, fix in the finish, defer to a named later PR).
   Spot-check the diff where the report is vague.
2. Record the reported tip. From now on that branch is **frozen**: new commits
   only, no amend, rebase or force-push, because the next builder stands on it.
3. In the same turn:
   - launch PR n+1's builder from that tip (step 2), and
   - continue PR n's agent with [FINISH-BRIEF.md](FINISH-BRIEF.md), carrying
     your decisions from 1.
4. Tell the user in a few lines: what PR n contains, its size, what it flagged,
   and that PR n+1 has started.

## 4. When a finish report arrives

Done when the PR is open, linked, and every check is green on its final
commit.

1. Verify, don't trust: `gh pr checks <n>` and the e2e run URL.
2. If the finish added commits, tell PR n+1's agent: fetch, then
   `git rebase --onto <new tip> <old base>`, at a convenient point. PR n+1's
   branch is not frozen until its own build report.

## Cross-cutting fixes

A bug found in PR k that exists lower in the stack is fixed on the **lowest**
branch that has it, as a new commit, and cherry-picked upward onto every open
branch above it; then re-run CI on each. An implementer that finds one reports
it; the orchestrator decides where it lands.

## Interruptions

After a restart or a spend-limit stop, inspect each live worktree (`git log`,
`git status`) before anything else, then continue the same agent with a
**resume** message: the branch, the commits it already has, the uncommitted
work, and which step it was on. Never relaunch fresh over a worktree with work
in it.

## e2e is serial

Every e2e run shares one real shop. Before dispatching, `gh run list --workflow
e2e --limit 5`; wait for any run in progress. Only one finisher dispatches at a
time -- say so in its brief when two could overlap.

## Done

Every PR in the plan is open, linked and CI is green.
Report the PR list with URLs, and every deviation from the plan the implementers recorded.
