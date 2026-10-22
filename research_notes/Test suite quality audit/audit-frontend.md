# Frontend test audit

Audit scope: all 75 first-party Vitest files (74 under `src/ui/src`, one design-screen file), helpers/setup/config, runtime JSON and selected corresponding production modules. No tests or application code changed. All files were inventoried and screened for assertions, test names, mocks, timing and DOM coupling; 13 files were read in full, while large suites and the other files received targeted/outline review. Findings below come from complete test bodies, not names alone. Do not equate inventory coverage with 997 individually deep-read cases. No snapshot matcher finding was identified; snapshot advice in research is prospective, not a current repository defect.

## Runtime and classification

`reports/vitest-audit.json`: 75 files, 997 tests passed, zero failed. Vitest's `numTotalTestSuites=255` counts describe groups and is not a file count. Start time 1791018698400. This was one instrumented exploratory run on this Windows/Cygwin machine, with cold dependencies and an overlapping hermetic Python run at its beginning. Durations describe this run; they are not a clean benchmark or predicted savings. The JSON exposes assertion durations and per-file first/last times, not separate environment/setup/hook CPU attribution.

Largest file envelopes: ListingEditorPage 7.46s/46 tests; useAiSeoMode 6.02s/40; DetailsTab 3.71s/45; App 3.70s/14; DeployPage 2.83s/10; BatchDeployPage 2.69s/11; usePreview 2.49s/8; ListingsPage 2.40s/31; MarketListingsPanel 2.33s/20; ImagesTab 2.31s/48; ColourMatrixEditor 2.10s/8. Envelopes can overlap and must not be summed as wall-clock runtime.

The 26 `.test.ts` files are not all pure unit tests: five exercise React hooks, saveMeta renders React, legacyProposals uses Storage and API/SSE tests exercise adapters. Conversely DOM component files are predominantly frontend integration tests regardless of calling the whole frontend layer unit. Eleven clearly non-DOM rule/projection/formatting files contain 172 cases: dates, media, batchDeployPresentation, batchDeployState, comparison, deployState, listingRunState, wordDiff, colourSelection, focus and mediaEdits. Seven API adapter files contain 50 cases; SSE runStream has six. These can be considered separately from DOM suites when assessing the pyramid.

## Ranked findings

### F1 — False passing async refusal tests (high impact, high confidence)

`src/ui/src/pages/editor/aiSeo/useAiSeoMode.test.ts:133` **stays unavailable when the readiness endpoint says not ready** and `:148` **stays unavailable when the readiness check itself fails** await `available === false`. Production `useAiSeoMode.ts:121` initializes remoteReady false; its `:199-200` availability/reason distinguish initial checking from a settled refusal. The tests can complete before the promised response/rejection matters. Changing the result handler so it enables the button incorrectly after rejection can escape these immediate assertions. Related `:124` **asks the readiness endpoint once name/design/brief are present, and reflects its answer** asserts only availability, never call count or listing argument despite the name.

Action: retain these behaviors; use a deferred response, confirm checking state, resolve/reject it inside act, await the distinctive settled refusal/failure reason and assert unavailable. Assert readiness called with the correct listing; only assert once if that is an intentional request contract. For failure, use the production error reason (`useAiSeoMode.ts:174` vicinity) as the settled signal. A focused DOM harness showing disabled/enabled AI Mode is also valid. Do not remove the refusal cases merely because DetailsTab has a disabled-button check at `DetailsTab.test.tsx:697`: that test only waits for the endpoint invocation before its negative assertion, so the same settlement concern needs review.

### F2 — Equal missing callbacks make a geometry regression green (high impact, high confidence)

`src/ui/src/components/QuadEditor.test.tsx:597` **scales from the box as it was when the gesture started, not compounding** fires two pointer moves then `:607` compares `calls.at(-1)` and `calls.at(-2)`. If neither movement emits onChangeBox both are undefined and the assertion passes. This is a vacuous oracle even though the named behavior is valuable.

Action: require exactly two emitted changes, verify both target index 0, and assert each concrete doubled box `[(0,0),(200,0),(200,200),(0,200)]`; equality can remain supplemental. Sibling **shift-drag scales the whole box about the opposite corner** at `:536` already asserts this expected coordinate result once. Retain the two-move regression because it validates gesture anchoring, but make its oracle independent and nonempty.

### F3 — Delayed behavior tested by elapsed wall time (medium/high impact, high confidence)

`usePreview.test.ts:69,84,99,123,142` sleeps for 150–250ms, five literal sleeps totaling 1.1s across eight tests; six completed preview requests also pay the real 120ms production debounce (`hooks/usePreview.ts` constant). File envelope 2.49s. `PreviewPanel.test.ts:47,79` adds 2x100ms to negative request-count checks; `ColourMatrixEditor.test.ts:148` adds 250ms for empty colours. App's autosave at `App.test.tsx:185` was 0.94s; its two-edit stale-refresh case at `:205` was 1.76s. ListingEditorPage design/new naming cases each approach 0.9–1.0s. DeployPage `:326` and BatchDeployPage `:547` each wait 800ms to prove a mark-seen timer was cancelled. These protect valuable request coalescing, latest-response and route-exit behavior, but elapsed sleeps unnecessarily couple them to scheduler/debounce margins.

Action: reuse the local fake-timer approach already demonstrated by `useAutosave.test.ts` and `AiWorkflowIndicator.test.tsx`. Advance through public timing behavior, explicitly resolve pending network work, and assert request history plus final URL/state. For mark-seen tests, leave the page, advance beyond the mark-seen deadline, then assert it was not called. For preview failures, await the actual failed request's completion before asserting the previous URL persists. Preserve one full page edit-to-save integration check, but control its clock. Do not claim the 1.1s literal waits equal wall-clock savings; parallel execution changes the critical path.

### F4 — API mock claims 404 behavior without a 404 (medium impact, high confidence)

`src/ui/src/api/calibrator.test.ts:46` **returns null on a 404 (no template.yaml yet)** provides `{data:undefined,error:'not found'}` via `as never`, without any Response/status. Production `api/calibrator.ts:50` returns null for every error, not specifically 404. The test therefore cannot distinguish missing configuration from a 500/auth/network failure; its name gives false assurance about discrimination. Other success wrappers at calibrator `:31,:74` return fixture data without checking method/path/body, so a wrong generated-client endpoint can still pass those cases.

Action: retain endpoint/error semantics but provide actual 404 and 500 Responses and validate the intended public behavior against current requirements before changing production. If all errors intentionally map to null, rename accurately and stop claiming status discrimination. For adapter coverage use a controlled fetch/HTTP transport boundary to assert URL/method/body/status decoding, or at least assert the current stable generated API call contract. `api/market.test.ts:23` and `api/seo.test.ts:54` are better local examples: they include Response statuses and separate 404 from other failures. Thin pass-through success tests need not be called tautological automatically; assess whether they cover a real adapter contract before deletion.

### F5 — Negative waitFor does not prove Reset avoided a later refetch (medium impact, high confidence)

`src/ui/src/App.test.tsx:275` **does not re-fetch to do it -- the last saved config is already held** compares getTemplateConfig call count to its pre-click count inside waitFor at `:284`. The predicate is already true immediately after click, so an asynchronous refetch scheduled later can escape. It also constrains a private cache strategy: a refetch that restores the same saved config might preserve Reset behavior.

Action: delete this implementation-policy test if avoiding network work is not a settled product/performance requirement. Sibling `:266` **throws away unsaved edits and goes back to what is on disk** already asserts the changed slider returns to 0; preserve and strengthen it with the last successfully saved config after a completed save, not only initial load. If request suppression is required, explicitly complete/advance effects after Reset then assert no refetch. A negative waitFor is not that barrier.

### F6 — Geometry rule matrices require a simulated SVG/DOM (medium impact, high confidence)

QuadEditor test setup `:320-335` replaces createSVGPoint/getScreenCTM with an identity mapping; menu tests `:170-235` patch Element.prototype rectangles based on CSS class and inline styles. Drag/resize cases `:364-607` then assert coordinate math and use nth class-selected handle. The expectations are mostly independent and valuable, but testing scale projection and menu clamping through SVG events costs elaborate setup and doesn't establish real CTM conversion or actual clipping.

Production already separates local pure calculations (`QuadEditor.tsx:114 centre`, `:131 scaledAbout`, `:162 labelAnchor`) from event/DOM adapters (`:196 positionMenu`, `:244 toImageSpace`). Action: extract a small cohesive geometry module with stable operations (move/corner-scale/clamp), test inputs→coordinates without React or SVG shims, and keep a few component tests for selecting/starting/ending a gesture, modifiers and callback routing. Preserve the browser calibration case for non-identity screen/template scaling and real clipping. Do not replace meaningful real geometry browser evidence with these identity stubs.

### F7 — Duplicate parent presentation assertions (medium/low impact, high confidence)

ImagesTab's `:166` **shows the empty-reel hint**, `:198` **counts the reel against Etsy's 20-image limit**, `:209` **says what to do at the limit** all mount a parent and stub catalogue/files to test outputs already owned/tested by MediaReel (`MediaReel.test.tsx:89` empty, `:58` counts, `:83` ceiling advice). Pure `mediaEdits.test.ts` has 47 rule cases, including caps, swatches, video slots and reorder refusals. This is an existing successful downward move; parent presentation cases still remain.

Action: deletion candidates are these three parent tests after keeping a single parent renders-reel check. Keep ImagesTab add/remove/swatches/preview wiring tests because they prove callbacks and propagation the child/pure tests cannot. The parent swatch case at `:421` also proves deriving swatchTemplate from the listing, so not automatically duplicate of MediaReel `:258` which receives it directly. Likewise positions at parent `:133` are not fully covered by the child thumbnail-only assertion at `:78`; move exact position labels down before deleting that part.

### F8 — CSS and dead-class tests don't establish the claimed user behavior (low impact, high confidence)

Deletion candidate: QuadEditor `:610` **puts nothing over the photograph to explain itself** queries only historical `.quad-editor__status`, `__hint`, `__readout` classes, which do not occur in production. Any unwanted overlay with a renamed class passes. Existing real calibration/browser render tests cover the view; if obstruction itself remains a requirement, add a targeted visual/layout check rather than preserving obsolete selectors.

Deletion candidate: MediaLocator `:186` **marks its two modes as a control that fills the locator width** asserts only Files button parent's `locator__modes` class. jsdom performs no layout, so this does not validate width. Drop it or test the meaningful mode switching (already ImagesTab `:463` browses templates until Files is requested); verify layout in a focused existing browser/visual flow only if it is a consequential requirement.

Refactor, not necessarily delete: DetailsTab `:855` claims fields keep width but checks no `.mkt-layout` ancestor, and `:863` insists on exact two-child wrapper order. Its `:876` focus-preservation case is the better stable contract: same input remains focused when market panel arrives. Keep focus and content behavior, use layout evidence for width. Class assertions supporting a deliberate animation state (AiWorkflowIndicator) or an explicit styling API can be meaningful; this finding is not a blanket ban on classes.

## Suite-wide refactors

1. Make reusable typed fixture builders in `src/ui/src/test`: ListingDetail is rebuilt locally in autosave, editor, DetailsTab, ImagesTab, VariantsTab, PricingTab, AI hooks, deployment pages and control tests. A field addition should change the default fixture once. Keep overrides explicit at each case; do not introduce a giant render-everything helper. Existing stagePlan/runSummary/runDetail helpers are good examples. Avoid `as never` for HTTP responses when status/error semantics are the subject.
2. Treat public hook output as a contract where hooks are intentionally cohesive modules. useAutosave's inputs→patch order→saved values are valuable; deleting every renderHook case for being internal would force expensive page tests and erase race coverage. Thin wrappers asserting aliases (`useAiSeoMode.test.ts:171` startedAt equals run.startedAt) are low-value consolidation candidates when no independent behavior exists.
3. Give pure non-DOM tests a Node Vitest project/config and move DOM-only cleanup, object URL and pointer shims into the jsdom project. Current `vitest.config.ts:10` sets jsdom for everything and `setupFiles` imports React Testing Library cleanup for all tests. At least 172 pure cases don't need it. This can reduce environment initialization cost, but benchmark before/after; JSON cannot attribute current hook/environment time.
4. Prefer userEvent setup for buttons, typing, keyboard and selects where browser semantics matter; keep explicit fireEvent for unsupported SVG/pointer/media load/error simulation. There are no grounds to rewrite every low-level event mechanically. DetailsTab already uses userEvent for AI choices; legacy editor tests often use fireEvent for typing/blur and should be upgraded when refactored.
5. Centralize deferred promise/event helpers for concurrency tests; preserve separate sequence assertions where ordering is a real contract (rename must drain save, no concurrent patches, last response wins). Replace arbitrary Promise.resolve repetitions with a returned operation promise or observable completion.
6. Keep test setup lifecycle explicit: the `sequence.hooks='list'` choice is justified by cleanup-before-mock-restore, and global afterEach cleanup prevents late preview work. Do not remove cleanup to improve times; move it into the correct DOM layer. Consider deterministic timestamps in aiRunSummary/marketSnapshot and per-fake sequence ownership to simplify reproducibility; current volatile builders are not themselves a proven failure.
7. Preserve one real browser check per distinct interaction/render seam plus focused frontend wiring tests, while rule tables remain pure. Browser agent covers overlap in detail. The 4 design-screen tests test a prototype and are collected by default Vitest though coverage include is production src only; separate prototype validation from the production gate if its independent ownership is intentional. Do not claim those four replace shipping editor tests.

## Good tests and examples to preserve

- `mediaEdits.test.ts:24` small MediaState fixture, `:171-184` reorder cases, `:257-276` featured-video promotion/last-thumbnail preservation and `:293-349` invalid reorder permutations: direct stable rule interfaces, independent ordered outputs, no DOM/network setup. Exactly the desired downward move.
- `colourSelection.test.ts:66` drops missing-colour media; `:94` removes artwork/pricing overrides; corresponding VariantsTab `:282` proves actual switch sends cascade patch. Pure rule plus integration wiring is a sound pairing.
- `wordDiff.test.ts:48` reconstructs original before/after text from emitted tokens and adds independent expected unchanged words. This is a meaningful invariant, not tautology: dropped/duplicated words fail.
- `useAutosave.test.ts:252` no concurrent patches, `:291` deferred retry merges old/new edits, `:381` older response cannot erase newly adopted brief, `:493` create keeps an in-flight edit, `:598` rename drains save: important race/order behaviors at the hook/transport seam with controlled timers.
- `AiWorkflowIndicator.test.tsx:166-214` asserts ready message persists then disappears at controlled time, reduced-motion behavior, warnings/failures remaining and next-run restart. Some style checks are incidental; the time/content contract is strong and fake timers avoid a real 4.3s wait.
- `DetailsTab.test.tsx:743` returns focus after drawers resolve and `:876` keeps seller's title focus when market panel appears. These are user-observable accessibility/state preservation, not component-tree assertions.
- `api/aiRuns.test.ts:151` feeds streamed events and checks ordered seq output; `pages/deploy/runStream.test.ts:67` a frame split across chunks and `:80` Last-Event-ID restoration validate a stable protocol boundary with no browser needed.
- `ListingEditorPage.test.tsx:292` tab switch flushes pending edit; `:649` naming creates once and replaces route; `:793` rename follows the new URL. Retain these thin user-flow witnesses even though hooks separately test save/rename mechanics.
- `BatchDeployPage.test.tsx:225` applies exactly the reviewed workspace plan; `DeployPage.test.tsx:469` sends reviewed fingerprint; state projection tests preserve reviewed plans when apply supplies a new stale one. These assert business-safe review/apply binding rather than arbitrary call plumbing.
- `BatchCandidateControl.test.tsx:20` keyboard focus exposes candidate tooltip/counts and accessible name. A small component test covers this behavior cheaply; do not promote it to a full shop/browser journey.

## Per-file inventory

Depth legend: **full** = full test source read; **targeted** = complete bodies of selected cases/sections plus file outline; **outline** = test names/assertion/mock/event patterns and runtime inventory reviewed. Classification records dependency shape, not an endorsement/deletion verdict. An outline-only file has no assertion that every case was deeply audited.

| File (relative to src/ui) | Cases | Dependency class | Depth |
|---|---:|---|---|
| design/screens/ListingSeoReviewScreen.test.tsx | 4 | DOM/component integration | targeted |
| src/App.test.tsx | 14 | DOM/component integration | full |
| src/api/aiRuns.test.ts | 12 | API/SSE adapter | targeted |
| src/api/batches.test.ts | 8 | API/SSE adapter | targeted |
| src/api/calibrator.test.ts | 9 | API/SSE adapter | full |
| src/api/listingTemplates.test.ts | 7 | API/SSE adapter | full |
| src/api/listings.test.ts | 2 | API/SSE adapter | full |
| src/api/market.test.ts | 3 | API/SSE adapter | full |
| src/api/seo.test.ts | 9 | API/SSE adapter | full |
| src/components/EditableName.test.tsx | 11 | DOM/component integration | outline |
| src/components/KindPicker.test.tsx | 15 | DOM/component integration | outline |
| src/components/Lightbox.test.tsx | 10 | DOM/component integration | outline |
| src/components/PreviewPanel.test.tsx | 10 | DOM/component integration | targeted |
| src/components/PrintRealismPanel.test.tsx | 12 | DOM/component integration | outline |
| src/components/QuadEditor.test.tsx | 32 | DOM/component integration | targeted |
| src/components/TemplateRail.test.tsx | 17 | DOM/component integration | targeted |
| src/components/TestDesignPicker.test.tsx | 7 | DOM/component integration | outline |
| src/components/ViewTabs.test.tsx | 1 | DOM/component integration | outline |
| src/dates.test.ts | 1 | pure rule/projection | full |
| src/editors/ColourMatrixEditor.test.tsx | 8 | DOM/component integration | targeted |
| src/editors/EditorShell.test.tsx | 7 | DOM/component integration | outline |
| src/editors/MultipleEditor.test.tsx | 5 | DOM/component integration | outline |
| src/editors/SingleEditor.test.tsx | 3 | DOM/component integration | outline |
| src/hooks/useAutosave.test.ts | 31 | hook + adapter | targeted |
| src/hooks/usePreview.test.ts | 8 | hook + adapter | full |
| src/media.test.ts | 45 | pure rule/projection | targeted |
| src/pages/BatchDeployPage.test.tsx | 11 | DOM/component integration | targeted |
| src/pages/BatchSummaryPage.test.tsx | 17 | DOM/component integration | outline |
| src/pages/DashboardPage.test.tsx | 4 | DOM/component integration | outline |
| src/pages/DeployPage.test.tsx | 10 | DOM/component integration | targeted |
| src/pages/ListingEditorPage.test.tsx | 46 | DOM/component integration | targeted |
| src/pages/ListingTemplateEditorPage.test.tsx | 11 | DOM/component integration | outline |
| src/pages/ListingTemplatesPage.test.tsx | 14 | DOM/component integration | targeted |
| src/pages/ListingsPage.test.tsx | 31 | DOM/component integration | outline |
| src/pages/NewBatchPage.test.tsx | 6 | DOM/component integration | outline |
| src/pages/RecentBatches.test.tsx | 3 | DOM/component integration | outline |
| src/pages/StagingPage.test.tsx | 10 | DOM/component integration | outline |
| src/pages/batchDeploy/BatchAggregateStages.test.tsx | 3 | DOM/component integration | outline |
| src/pages/batchDeploy/BatchCandidateControl.test.tsx | 3 | DOM/component integration | outline |
| src/pages/batchDeploy/BatchListingDrawer.test.tsx | 5 | DOM/component integration | targeted |
| src/pages/batchDeploy/BatchListingGroups.test.tsx | 1 | DOM/component integration | outline |
| src/pages/batchDeploy/batchDeployPresentation.test.ts | 11 | pure rule/projection | targeted |
| src/pages/batchDeploy/batchDeployState.test.ts | 8 | pure rule/projection | targeted |
| src/pages/deploy/ApplyFooter.test.tsx | 21 | DOM/component integration | outline |
| src/pages/deploy/Callouts.test.tsx | 7 | DOM/component integration | outline |
| src/pages/deploy/ComparisonView.test.tsx | 7 | DOM/component integration | outline |
| src/pages/deploy/PriceTable.test.tsx | 3 | DOM/component integration | outline |
| src/pages/deploy/StepStrip.test.tsx | 7 | DOM/component integration | outline |
| src/pages/deploy/comparison.test.ts | 23 | pure rule/projection | targeted |
| src/pages/deploy/deployState.test.ts | 9 | pure rule/projection | targeted |
| src/pages/deploy/listingRunState.test.ts | 2 | pure rule/projection | targeted |
| src/pages/deploy/runStream.test.ts | 6 | API/SSE adapter | targeted |
| src/pages/deploy/wordDiff.test.ts | 6 | pure rule/projection | full |
| src/pages/editor/DeployControl.test.tsx | 12 | DOM/component integration | outline |
| src/pages/editor/DesignSelect.test.tsx | 9 | DOM/component integration | outline |
| src/pages/editor/DetailsTab.test.tsx | 45 | DOM/component integration | targeted |
| src/pages/editor/ImagesTab.test.tsx | 48 | DOM/component integration | targeted |
| src/pages/editor/MediaLocator.test.tsx | 17 | DOM/component integration | targeted |
| src/pages/editor/MediaReel.test.tsx | 23 | DOM/component integration | targeted |
| src/pages/editor/PricingTab.test.tsx | 4 | DOM/component integration | outline |
| src/pages/editor/VariantsTab.test.tsx | 25 | DOM/component integration | targeted |
| src/pages/editor/aiSeo/AiChoiceDrawer.test.tsx | 7 | DOM/component integration | outline |
| src/pages/editor/aiSeo/AiSeoControl.test.tsx | 13 | DOM/component integration | outline |
| src/pages/editor/aiSeo/AiTagsDrawer.test.tsx | 10 | DOM/component integration | outline |
| src/pages/editor/aiSeo/AiWorkflowIndicator.test.tsx | 13 | DOM/component integration | targeted |
| src/pages/editor/aiSeo/legacyProposals.test.ts | 2 | DOM/component integration | full |
| src/pages/editor/aiSeo/useAiRun.test.ts | 31 | hook + adapter | targeted |
| src/pages/editor/aiSeo/useAiSeoMode.test.ts | 40 | hook + adapter | targeted |
| src/pages/editor/colourSelection.test.ts | 8 | pure rule/projection | full |
| src/pages/editor/focus.test.ts | 12 | pure rule/projection | full |
| src/pages/editor/market/MarketListingsPanel.test.tsx | 20 | DOM/component integration | outline |
| src/pages/editor/market/useMarketPanel.test.ts | 13 | hook + adapter | targeted |
| src/pages/editor/mediaEdits.test.ts | 47 | pure rule/projection | targeted |
| src/pages/editor/saveMeta.test.ts | 13 | DOM/component integration | full |
| src/shell/AppShell.test.tsx | 9 | DOM/component integration | outline |

JSON first-start to latest file end envelope: 49.01s (not a clean benchmark; excludes additional reporter/process teardown).
