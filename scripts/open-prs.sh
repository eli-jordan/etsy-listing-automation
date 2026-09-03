#!/usr/bin/env bash
# Pushes the Phase 0/1 branch stack and opens a PR for each.
#
# Run from cygwin zsh:  ./scripts/open-prs.sh
#
# Each branch builds on the one below it, so each PR is based on its parent
# rather than on main -- that way every PR shows only its own diff and nothing
# needs rebasing. Merge them bottom-up (plan, then phase 0, then phase 1).
#
# Safe to re-run: branches already pushed are just updated, and a branch that
# already has an open PR is skipped rather than erroring.
set -euo pipefail
cd "$(dirname "$0")/.."

open_pr() {
  local branch="$1" base="$2" title="$3" body="$4"

  echo "== $branch -> $base =="
  git push -u origin "$branch"

  if [ -n "$(gh pr list --head "$branch" --state open --json number --jq '.[].number')" ]; then
    echo "   PR already open, leaving it alone"
    return
  fi

  gh pr create --base "$base" --head "$branch" --title "$title" --body "$body"
}

open_pr "docs/implementation-plan" "main" \
  "Implementation plan for the PRD" \
"Companion to the PRD: module boundaries, core contracts and the order of work.

Settles ten architecture decisions (\`A1\`-\`A10\`) — the staged plan/apply
pipeline, the lockfile as the verbatim last-applied document, the workspace as
a separate data tree, and the renderer's purity and determinism rules — plus
the phase breakdown each later PR implements.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"

open_pr "feat/phase-0-foundations" "docs/implementation-plan" \
  "Phase 0: foundations" \
"Workspace discovery and path resolution, the config models, and the engine
primitives everything later builds on. No network, no credentials.

- \`Money\` rejects bare numbers and wrong currencies with errors that name the
  offending field (PRD 24)
- Colour slugification plus collision detection, with a sparse
  \`exceptions.yaml\` (PRD 7a)
- \`Workspace.resolve()\` refuses paths escaping the root — tested against
  \`..\`, POSIX and Windows-drive absolutes, drive-relative, UNC and symlinks
- Printify catalog behind a \`Protocol\`: real HTTP client, TTL cache, and an
  in-memory fake so no test ever hits the network
- \`Stage\` protocol, \`Change\` vocabulary, lockfile and the single
  \`canonical_hash()\` helper — timestamps, tool version and remote ids stay
  out of the hash, and hashed paths are workspace-relative and forward-slashed
- \`plan\` walks the (still empty) stage list and prints an empty plan

All three exit criteria are covered by named tests.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"

open_pr "feat/phase-1-renderer" "feat/phase-0-foundations" \
  "Phase 1: renderer, calibrator, and the new picker" \
"The render pipeline and the browser calibrator that configures it, plus the
follow-up work on toolchain, tests and module boundaries.

**Renderer.** warp -> displace -> shade -> export as pure functions over
ndarrays and frozen config (A7). Every \`cv2\` call passes explicit
interpolation/border arguments rather than version-dependent defaults, with a
test that greps for the ones that don't. Goldens live at two levels so a
regression names the guilty pass.

**No real assets required.** There is no garment photography or artwork in the
repo, so \`scripts/generate_test_assets.py\` procedurally generates a
grid/ruler design and a synthetic template set, deterministically.

**Calibrator.** FastAPI plus a React/TypeScript front end. Previews run the
*real* render pipeline server-side and stream back a PNG — there is no
approximate preview path. The typed API client is generated from the OpenAPI
schema, never hand-written (A5).

**Also in this stack:** the dependency upgrade that removed the \`click<8.2\`
pin and cleared the npm advisory; cygwin path handling for \`--root\`; a
playwright browser-test layer; an 80% branch-coverage gate; and a refactor
making \`workspace\` the single owner of the directory layout.

152 tests, mypy strict and ruff clean, TypeScript strict and ESLint clean.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"

echo
echo "Done. Merge bottom-up: implementation-plan, then phase 0, then phase 1."
