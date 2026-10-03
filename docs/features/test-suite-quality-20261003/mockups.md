# UI references for the test stack

The stack preserves the existing UI. These checked-in mockups satisfy the
implement-stack UI-reference input without designing a replacement interface.
Read `src/ui/design/AGENTS.md` before rendering or changing design files; no
frame changes are planned.

| Surface | Existing mockup | Preserved contract |
|---|---|---|
| AI unavailable and suggestions | [Readiness](../../../src/ui/design/scenes/listing-seo-v3/readiness.tsx), [review](../../../src/ui/design/scenes/listing-seo-v3/review.tsx), [failure](../../../src/ui/design/scenes/listing-seo-v3/failed.tsx) | Settled refusal, current fields, explicit acceptance and recovery |
| Market progress and content | [States](../../../src/ui/design/scenes/market-seo/states.tsx), [ready](../../../src/ui/design/scenes/market-seo/ready.tsx) | Focus/content preservation, visible workflow outcomes |
| Media editor | [Images](../../../src/ui/design/scenes/batch-create-lofi-v3/template-images.tsx) | Reel order, browse modes, cap messages and preview |
| Save and editor actions | [Header](../../../src/ui/design/scenes/editor-header/header.tsx), [file card](../../../src/ui/design/scenes/editor-header/header-file-card.tsx) | Current saved state, focus and action wiring |
| Reviewed deployment | [Review](../../../src/ui/design/scenes/batch-deploy-lofi-v4/review-bottom-sheet.tsx) | Reviewed-plan binding and completion/leave behavior |

There is no current dedicated calibrator mockup in these scenes. The executor
must capture the shipped calibrator with deterministic synthetic fixtures
during preflight, before PR 1, and use that frame as the preservation baseline
for PR 8. It records the
fixture, viewport, route and screenshot recipe in `execution.md`, alongside
the rendered design references. The existing
`uv run pytest -m browser tests/browser/test_calibrator_design.py` capture
cases provide an initial app-capture recipe to verify in that preflight;
they write `tests/browser/_screenshots/` and become opt-in in PR 12.
Capture color-matrix, multiple and single
kind surfaces as exercised by the existing browser suite, plus the repeated
scale gesture at a non-identity screen/image scale.

The stack preflight starts `npx marver dev` in `src/ui` and records the printed
URL. It also verifies the app and a supported screenshot path. A generic T3
snapshot failure is not a successful screenshot recipe: the audit encountered
that limitation despite working navigation/DOM inspection. For application
inspection prefer the T3 preview tools. For design frames follow the design
contract's file-based/headless capture path; do not automate the canvas UI.

If reference frames and current app differ, record those existing differences
before implementation. This refactor is not authorization to redesign the app
to match an older frame. PRs changing runtime UI code include before/after
evidence and the skill's mockup/app comparison, with differences explained.
