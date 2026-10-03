# Test suite quality execution record

This is the orchestrator's record for running the [plan](plan.md). The plan
asks for it. It holds the preflight environment block, the baseline, the
per-PR ledger and the case replacement ledger. Builders and finishers add
rows here; the orchestrator owns the ledger states.

## Environment block

| Field | Record |
|---|---|
| Plan/spec/UI inputs | [plan.md](plan.md), [spec.md](spec.md), [interactions.md](interactions.md), [mockups.md](mockups.md), [coverage-map.md](coverage-map.md) |
| Base | Stack base is the commit that adds this file, on branch `test/improve-suite-pr112`, on top of planning commit `f1113be`. The audited application SHA is `b02208c38c0cc945aff218da44dfb56c079e1274`, which is the planning commit's parent, so the stack's code matches the audit. `origin/main` (`1f2d3cb`) also has PR #113, which adds 4 lines to `src/ui/src/pages/ListingTemplateEditorPage.test.tsx` (an unsaved-edit warning). No audited finding moved. |
| Shell/worktree | **macOS 26.7 with zsh, not Windows/cygwin.** Ignore AGENTS.md's cygwin-only instructions; run commands directly. Each PR uses its own worktree at `/Users/c72303a/.t3/worktrees/etsy-listing-automation/tsq-NN`. There is no `timeout` binary. |
| Toolchain | `uv sync` (uv 0.8.22, Python 3.13.7) and `npm install` in `src/ui` (Node 24.8.0) both succeed with no lockfile change. CI and release still use `npm ci`. |
| Baseline | `uv run pytest -m "not browser and not e2e"`: 2,875 collected, 2,865 passed, 0 failed, 10 skipped, 431 s. All 10 skips are platform skips: 8 Windows-only `test_userpath` cases, `test_workspace::test_resolve_rejects_symlink_escape`, and `test_proposal_store::test_listings_differing_only_in_case_keep_their_own_proposals` (the filesystem is case-insensitive). Vitest: 997/997 passed in 255 suites. |
| Discovery failures | `ETSY_LISTINGS_ROOT` is not set in this shell, so the audit's two `test_workspace` discovery failures do not reproduce here. PR 1 proves its fix by setting a conflicting override itself. |
| Host/environment | macOS 26.7 arm64, Python 3.13.7, Node 24.8.0. Playwright has chromium-1234 and headless shell installed. No `ETSY_*`, `PRINTIFY_*` or `ANTHROPIC_*` variables are set. Synthetic fixtures come from `scripts/generate_test_assets.py` and test builders. |
| GitHub | `gh` is logged in as `eli-jordan` over https. A dry-run push of `HEAD:refs/heads/stack/tsq-01-reliable-oracles` succeeds. Repo: `eli-jordan/etsy-listing-automation`. |
| UI capture | Design frames: run `npx marver dev` in `src/ui` (http://localhost:5321/), then `npx marver shot --scene <scene>`; PNGs land in `src/ui/design/.local/shots/`. This was checked for `listing-seo-v3` (5 frames). App: `npm run build` in `src/ui`, then `ETSY_LISTINGS_REQUIRE_EVERY_LAYER=1 uv run pytest -m browser tests/browser/test_calibrator_design.py` writes 1280×800 frames to `tests/browser/_screenshots/` (18 passed, 63 s). A real frame was verified. |
| Calibrator baseline (PR 8, G6) | `/var/folders/vv/y1sjmxns6k9dycqlvndv5wvr0000gp/T/opencode/baseline/calibrator/`: `phase1-colour-matrix`, `phase2-workbench`, `phase5-multiple-editor`, `phase6-preview-all`, `phase7-lightbox` (.png). Captured from the browser suite's synthetic workspace at 1280×800. |
| Real-shop serialization | The `e2e` workflow is dispatchable. Secrets `ETSY_KEYSTRING`, `ETSY_SHARED_SECRET`, `ETSY_TOKENS_JSON` and `PRINTIFY_API_TOKEN` are present. Last run: green on `main` (37113870607). Only one finisher dispatches at a time, and only when the orchestrator says so. |

## PR ledger

| PR | Branch | Worktree | Base | Build tip | Final tip | PR | State |
|---|---|---|---|---|---|---|---|
| 1 | `stack/tsq-01-reliable-oracles` | `tsq-01` | stack base | | | | pending |
| 2 | `stack/tsq-02-render-cache-contracts` | `tsq-02` | PR 1 tip | | | | pending |
| 3 | `stack/tsq-03-shared-wheel` | `tsq-03` | PR 2 tip | | | | pending |
| 4 | `stack/tsq-04-race-gates` | `tsq-04` | PR 3 tip | | | | pending |
| 5 | `stack/tsq-05-stage-fixtures` | `tsq-05` | PR 4 tip | | | | pending |
| 6 | `stack/tsq-06-cleanup-render-rules` | `tsq-06` | PR 5 tip | | | | pending |
| 7 | `stack/tsq-07-proposal-seeding` | `tsq-07` | PR 6 tip | | | | pending |
| 8 | `stack/tsq-08-calibration-geometry` | `tsq-08` | PR 7 tip | | | | pending |
| 9 | `stack/tsq-09-cli-ownership` | `tsq-09` | PR 8 tip | | | | pending |
| 10 | `stack/tsq-10-ui-clocks` | `tsq-10` | PR 9 tip | | | | pending |
| 11 | `stack/tsq-11-vitest-projects` | `tsq-11` | PR 10 tip | | | | pending |
| 12 | `stack/tsq-12-browser-opt-in` | `tsq-12` | PR 11 tip | | | | pending |
| 13 | `stack/tsq-13-live-journeys` | `tsq-13` | PR 12 tip | | | | pending |
| 14 | `stack/tsq-14-evidence` | `tsq-14` | PR 13 tip | | | | pending |

## Case replacement ledger

Each PR adds one row for every case it changed, moved or removed, and names the lower oracle and any retained seam witness that covers it (G8).

| PR | Original case | Action | Lower oracle | Retained witness |
|---|---|---|---|---|
| 1 | `test_workspace.py::test_discover_finds_root_from_nested_cwd` | Strengthened (T03): unsets `ETSY_LISTINGS_ROOT` via `monkeypatch` | Same case, now independent of the shell | `test_discover_env_var`, `test_discover_root_override_wins` keep the deliberate override |
| 1 | `test_workspace.py::test_discover_raises_when_not_found` | Strengthened (T03): unsets `ETSY_LISTINGS_ROOT` via `monkeypatch` | Same case | As above |
| 1 | `useAiSeoMode.test.ts` "asks the readiness endpoint once…" | Strengthened (F02): asserts the listing argument and a cleared reason | Same case | — |
| 1 | `useAiSeoMode.test.ts` "stays unavailable when the readiness endpoint says not ready" | Strengthened (F02): deferred response, checking → settled refusal reason | Same case, renamed "…, and says why" | — |
| 1 | `useAiSeoMode.test.ts` "stays unavailable when the readiness check itself fails" | Strengthened (F02): deferred rejection, checking → "Could not check AI setup." | Same case, renamed "…, and says so" | — |
| 1 | `DetailsTab.test.tsx` "keeps AI Mode disabled when the readiness endpoint says no" | Strengthened (F02): waits for the refusal reason in the hover card before checking disabled | Same case | `AiSeoControl.test.tsx` hover-card reason case |
| 1 | `QuadEditor.test.tsx` "scales from the box as it was when the gesture started, not compounding" | Strengthened (F03): controlled parent applies changes; requires exactly two `[0, doubled box]` calls | Same case | Shift-drag single-move case |
