# Finish brief

The message that continues PR n's agent once its build report is accepted.
It already has the context, so this carries only what changed and what "done"
means.

````markdown
Good work. Now finish PR <n>'s exit conditions. PR <n+1> is being built on
your tip <tip>, so from here **only add new commits: no amend, rebase or
force-push**.

1. **Fixes from review**, each a new commit with a test:
   <the orchestrator's decisions on the report's undone/uncertain items>
2. **Full gates.** `./scripts/check.sh` and `uv run pytest -m browser`. A
   failure not in the baseline (<baseline ids>) is yours to fix.
3. **Every success condition** in the plan's PR <n> section and every shared
   gate it lists, checked one by one. Anything you cannot meet goes in the
   PR description with the reason.
4. **Screenshots** (PRs that change UI). For every mockup frame the PR covers,
   capture the frame and the built screen at 1280×800 with <screenshot
   recipe>. Fix every significant difference before opening the PR. Host the
   PNGs on the orphan branch `pr-screenshots` under `<branch-slug>/`, never
   merged: fetch it, build a commit on a temporary `GIT_INDEX_FILE`
   (`read-tree <tip>`, `hash-object -w`, `update-index --add --cacheinfo`,
   `write-tree`, `commit-tree -p <tip>`), push it to
   `refs/heads/pr-screenshots`, and redo from the fetch if the push is
   rejected. Link images as
   `https://github.com/<owner>/<repo>/blob/pr-screenshots/<branch-slug>/<file>.png?raw=true`.
5. **Push and open the PR:** `gh pr create --base <PR n-1 branch> --head <branch>
   --title "<plan's title>"`. The description has:
   - scope, citing the plan section and its decisions;
   - size;
   - tests added and the check results;
   - the acceptance items closed and the tests proving each;
   - **Mockup vs app**: a table per screen, mockup left, app right, each
     intentional difference noted with its reason;
   - **Choices to review**;
   - the e2e run URL.
6. **CI.** `gh pr checks <number> --watch`; fix every failure with new commits
   until green.
7. **e2e.** Wait for any in-progress run (`gh run list --workflow e2e --limit
   5`), then `gh workflow run e2e --ref <branch>` and `gh run watch`. If the
   Etsy token is stale, stop and report.

Report: the PR URL, final tip and size, CI and e2e results with URLs, the
commits added in this pass, and anything still red.
````
