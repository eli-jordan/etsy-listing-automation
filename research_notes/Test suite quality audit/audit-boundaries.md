# Boundary, transport and infrastructure audit

Audit date: 2026-10-03. Scope: `tests/cli`, `tests/server`, `tests/browser`, `tests/e2e`, `tests/support`, `tests/conftest.py`, six root `tests/test_*.py` files, and CI selection/workflows. No application or test changes were made. Research preceded inspection; see `pyramid-research.md` and the other research notes.

## Main conclusions, ordered by impact

The strongest improvements in this scope are removing repeated real packaging builds without losing the packaging contract, controlling real concurrency through gates instead of elapsed time, and retaining HTTP adapter validation while seeding legitimate application state directly. Some browser tests reproduce backend rules already thoroughly covered by units; those should be reduced while retaining real DOM, asset decoding, pointer geometry, autosave and workflow wiring. Five browser functions produce useful human screenshots but their only oracle is that a file exists: these belong in an explicit artifact workflow, outside the ordinary automated regression gate.

The source audit did not find a reason to delete architecture guards, packaging smoke tests, cache identity checks, or broad live integration tests simply because they inspect structure or require setup. Their documented contracts matter. Real e2e sources were reviewed but not executed because they mutate remote shops. Separate browser baseline: 97 passed in 189.84s. Screenshot-only cases totaled 8.753s; fallback 1.551s; malformed retry 1.549s; common-copy deploy 3.041s. These are measured case times, not predicted net savings.

### 1. Reuse the same successful built wheel across compatible packaging scenarios

**Priority high for feedback time; confidence high; refactor before removing work.** `tests/test_wheel_frontend.py:81` (`test_wheel_rebuilds_stale_assets_from_current_source`), `:89` (`test_wheel_ships_built_assets_but_no_npm_project`), and `:166` (`test_installed_wheel_serves_the_spa_without_node_or_the_checkout`) each build the same tiny npm project into a wheel. The latter installs it and removes the checkout, which is essential validation. The invalid-build case and sdist-to-wheel case have different inputs and must remain separate real builds.

Measured XML case times: stale-assets 36.072s; shipped-assets 36.449s; no-index failure 32.439s; sdist 36.977s; installed-wheel 50.416s. Total **192.353s**, equivalent to **34.0% of the 565.23s hermetic run wall time** (case-time sums include their fixtures). This is the largest demonstrated runtime opportunity in this scope. Compatible reuse avoids two of five builds, but it does not remove all 86s of those cases: installation/serving still runs. Do not promise a saving without measuring the refactor.

Use a module-scoped immutable `BuiltWheel` fixture returning the artifact plus expected built marker; stale-asset and archive-content assertions inspect it, and installation uses a copied artifact and its own environment. The fixture should create a deliberately stale `dist` before building so all consumers validate the fresh-source build. Preserve independent fresh projects for the missing-index and sdist cases. Installed-wheel must still launch outside the checkout with node absent and assert that the real SPA is served. No mocking of Hatch/npm is an equivalent replacement.

### 2. Replace scheduler assumptions with gates in HTTP concurrency tests

**Priority high for reliability; confidence high; improve, do not delete.** `tests/server/contract/test_runs_api.py:214` (`test_workspace_apply_requires_a_ready_workspace_plan`) posts a plan and immediately applies it, assuming the plan has not become ready. `:249` (`test_create_is_refused_409_when_the_listing_is_already_active`) assumes the first plan still holds its listing when the second request arrives. `:327` (`test_cancel_a_queued_plan_run`) assumes a second listing's run remains queued when cancellation arrives. The fixture starts the real worker during app lifespan; `core/application/deploy/executor.py:105` can dequeue and execute between these requests. A sufficiently fast worker can make the requested state disappear without any product defect. This is a source-supported possibility, **not a claim of observed flakes** in the audit run.

Inject a `ContextFactory` that sets a started event and blocks on a release event. Wait for first-run start, issue the refusal/cancellation request while that event is held, assert the existing public HTTP status/body and the second run's state, then release in `finally`. For the queued case use two different listings so conflict validation does not mask queue validation. The same file's `test_closing_the_stream_does_not_cancel_the_run` at `:463` already demonstrates a legitimate gated host seam. Core `test_deployments.py` validates state rules with a coordinator that has not started; retain those lower tests and retain a small real HTTP translation/worker integration here.

`tests/server/behaviour/test_listing_writes_api.py:50` makes every `Path.replace` sleep 0.3s, while `_together` at `:67` separates requests by sleep 0.1s. The PATCH-behind-rename test correctly waits for a started event at :90, but only holds its lock for elapsed 0.3s; create-versus-rename at :98 uses timing-only `_together`. Elapsed delays cannot guarantee overlap under load and globally delay unrelated replacements. Gate the specific owned document/artifact operation, wait for its entry, start the competing HTTP request, then release; assert the same no-torn-files/conflict outcomes. Coordinate with `tests/core/behaviour/test_listing_operations.py:466` using a similar timing pattern. Keep the real file locks and HTTP operations; do not simulate successful locking in a fake.

### 3. Seed durable proposals for HTTP mapping tests; retain generation/restart/cancel integrations

**Priority medium for setup clarity and speed; confidence high; replacement prerequisite.** `tests/server/contract/test_proposals_api.py:54` `_generate` creates an AI run, polls with real time, researches through the market fake and retrieves its generated proposal. Nine test functions call this helper, with ten calls including the regenerated conflict case. Reads, resolution status validation, stale reasons and rename mapping need a valid durable proposal, not repetition of the generating pipeline. E.g. `test_an_unknown_resolution_is_422` at `:157` should not require any model task execution to validate the request schema.

The lower application tests in `tests/core/behaviour/test_listing_proposals.py:49` already arrange correct saved state through `ProposalStore.put`, using `ListingAiInputs.read(...).prepare().snapshot` and a deterministic timestamp. Promote this state builder to shared support, accept listing/origin/timestamp overrides, use two explicit timestamps for replacement, and drive the same public proposal GET/PATCH endpoints. `tests/support/ai_runs.py:228` currently has `seed_proposal` with an empty synthetic snapshot and `origin='batch'`; it must be extended or complemented, not reused blindly for the fresh/manual assertions.

Use a no-lifespan `TestClient` for pure proposal endpoint cases so unrelated deployment and batch workers are not started. Preserve `test_a_run_leaves_its_proposal_current_and_every_section_pending` at `:82`, generation/replay behavior where run events are the subject, deletion cancellation at `:193` with its SEO gate, and `tests/server/behaviour/test_durable_proposals.py`'s two genuine new-app/restart checks. Keep HTTP schemas and refusal mapping even when core covers the business rule.

Measured whole file: **13 cases, 11.721s**. Generated cases are about 1.05s each; no-generation cases about 0.54s. This is modest latency, not slow AI. Deployment shutdown polls its idle queue with timeout 0.5s and starts on every lifespan, so unnecessary worker lifecycle is a visible contributor. The table supports a targeted fixture simplification; it does not justify asserting that every millisecond comes from `_generate` or extrapolating enormous savings.

### 4. Reduce backend duplication in browser AI tests and strengthen its expected description

**Priority medium; confidence high; mixed deletion/refactor actions.** `tests/browser/test_ai_seo_browser.py:873` (`test_codex_unavailable_falls_through_to_claude`) starts a real browser/server to assert provider call counts plus Claude output. `tests/core/unit/test_ai_orchestrator.py:95` already validates provider fallback and `test_ai_market_queries.py:110` validates the market query form. The full browser workflow at `:360` already shows results in real suggestion drawers. Remove the browser provider-order matrix after ensuring no fallback-specific warning is a required UI behavior; if one is introduced, cover its accessible presentation at the component layer and keep at most one wiring smoke. Retain the unit fallback tests.

`test_malformed_output_is_repaired_once_then_try_again_recovers` at `:824` also asserts the provider's repair history. **Keep its unique failure-to-Try-again browser journey**, no-write-before-accept checks and visible recovered suggestions, but leave the exact same-provider repair count/payload to `test_ai_orchestrator.py:130Ã¢â‚¬â€œ160`. Arrange the browser provider as failed run then successful run, rather than mutating internal queued answer state to control a decoder test in the browser.

`test_common_copy_description_composes_into_the_printify_desired_document` at `:1036` configures a large render design, full variant catalog, publishing fixture and full deploy simply to verify description composition. Its expected value is calculated with production `compose_description` at `:1100`, so the browser preview and deployment can agree on the same wrong separator. The later substring checks catch lost copy but not a faulty joining rule. Use a literal expected lead + `\n\n` + body. The lower `tests/core/behaviour/test_printify_product_stage.py:394` asserts precisely that literal final product description through fake-client output; `test_etsy_listing_stage.py:108` covers the Etsy reader and `test_workspace_common_copy.py:107` covers loading/joining.

Reduce this browser case to source picker, literal visible preview, and saved YAML `description.ref`/lead after autosave. Keep the product-stage lower tests and general browser deployment/reattach flows in `test_deploy_view.py`. This removes unrelated publish setup only after the autosave/ref proof is explicitly retained. Browser calibrator decoded PNGs, true-space SVG geometry, actual drag and YAML writes validate behavior that jsdom/API calls cannot replace.

### 5. Move manual screenshot production out of the automatic regression gate

**Priority medium; confidence high; move rather than erase artifact capability.** Five functions in `tests/browser/test_calibrator_design.py`: `test_capture_full_page_screenshot` `:180`; `test_capture_preview_all_screenshot` `:190`; `test_capture_lightbox_screenshot` `:209`; `test_capture_multiple_editor_screenshot` `:227`; `test_capture_workbench_screenshot` `:240`. Each oracle is only `target.stat().st_size > 0`. The module itself says these are artifacts for human review, not appearance assertions. This is not a screenshot comparison system and these artifacts are gitignored. No assertion can detect an incorrectly colored or displaced UI once a nonempty screenshot is written.

Keep a named opt-in screenshot capture command/marker with the same scenes, make the generated artifacts discoverable for manual PR review, and remove those five from ordinary pass/fail collection. If automated visual regressions are required, introduce baseline images and reviewed comparison thresholds explicitly instead of pretending file existence validates appearance. Existing `test_calibrator_browser.py` covers Preview/full-size decode/lightbox/approval and real template writes, so retain it. The computed-style checks in the other 13 design tests can protect actual styling requirements; they are not automatically redundant or invalid because they assert colors.

### 6. Improve two cache oracles without discarding legitimate identity contracts

**Priority medium; confidence high; improve in place.** `tests/server/unit/test_preview_imagecache.py:139` (`test_the_least_recently_used_entry_goes_first`) uses a budget that holds only one image, asks for a second, then checks the first was evicted. FIFO, random or arbitrary eviction all pass. Arrange room for two equal small images: load A/B, touch A, load C, then assert B reloads, A remains cached and `held_bytes <= budget`. Assert through `PreviewImages` and existing same-array identity; do not reach into `_entries` or `_held`.

`test_editing_the_photo_invalidates_it` at `:85` writes black pixels and changes mtime but asserts only object inequality. A freshly allocated copy of stale pixels passes. Also assert the new image is black and differs in pixels from the first. Preserve read-only mutation refusal, byte budget, missing-file behavior, correct scaled size/rounding and race accounting tests.

Source explicitly states that concurrent callers get the same array and that byte accounting counts it once (`server/api/imagecache.py:109`), so these identity assertions are justified observable performance contracts. Likewise `ScaledBase` is explicitly frozen. Do not classify those as implementation coupling merely because they use `is` or `FrozenInstanceError`.

### 7. Remove one safe CLI duplicate; put formatter arithmetic at the CLI unit boundary

**Priority low-to-medium; confidence high.** `tests/cli/behaviour/test_cli_surface.py:212` (`test_the_ansi_escapes_survive_to_the_terminal`) uses exactly the same `FORCE_COLOR`/stdout path and first RGB escape asserted by `test_each_swatch_is_styled_with_the_colour_the_stage_sampled` at `:188`. The richer test also asserts the second color, order and output suffix. **Delete the single-swatch duplicate safely**, preserving the richer emitted-output oracle, nonterminal/NO_COLOR/encoding cases and ordinary text output.

Seven `test_plan_reporting.py:55Ã¢â‚¬â€œ111` cases repeatedly run the same CLI plan of the fixture listing for distinct formatting pieces. Later `:282`, `:311`, `:333` already build real `Plan`/`StagePlan` inputs and call `format_plan`. Shift warning/count/indentation matrices to that pure formatter interface with explicit stage plans. Keep one public `CliRunner` refusal output case, help/env flags, batch continuation and apply-output smoke. `:192`, `:202`, `:213` each renders to check overlapping apply output; retain one real CLI apply integration and move repeated formatting assertions below it.

`tests/cli/behaviour/test_new_picker.py` is a misleading layer/owner bucket: many of its 45 source functions directly test pure garment-profile, pricing and listing-creation application operations, not a CLI journey. These are valuable small tests: move by subject into their core owner/unit or behavior layer, and retain picker choice presentation under CLI. This improves ownership/navigation and pyramid reporting; moving files alone makes no runtime improvement.

### 8. Repair misleading live probes and e2e state dependence

**Priority medium for live suite signal; confidence high for named defects; source-only.** `tests/e2e/test_printify_product_e2e.py:692` (`test_a_sku_we_set_is_kept_verbatim`) never sets a SKU: it reads generated nonempty SKUs. Application code does not set SKU, so the function does not protect its claimed behavior. Delete it from normal e2e or retain as an explicitly named exploratory API probe if ongoing provider research needs it. This needs no replacement application test.

`:585` (`test_a_failed_publish_leaves_the_product_unlocked`) performs no publish and relies on preceding `:563`'s disconnected-shop failure. Running it alone can pass without a failed publish ever happening. Merge the unlocked-state GET into the failure test that actually causes the error, or arrange failed publish within its own setup. Preserve the meaningful external provider failure/unlock semantics.

`:741` (`test_limit_and_page_are_honoured_even_though_filters_are_not`) sends only limit=1, never page, and asserts length <=1, which passes for an empty answer. Cover pagination through public client contract tests with two explicit pages and asserted aggregate IDs; keep at most one meaningful live pagination smoke with seeded known products and nonempty distinct results if this provider behavior needs recurring verification. `:713` already separately checks paginator shape.

`tests/e2e/test_printify_catalog_e2e.py:264` pins the current vendor garment title even though brand/model is the declared resolver contract. `:256` asserts a no-trademark input resolves but mixes in a constant assertion. Existing live brand/model resolution `:248` plus unit resolver/slug normalization retain application value; remove vendor-title trivia from the normal live gate and consolidate repeated catalog resolution fetches. Raw live placeholder-shape checks are useful evidence of fake/cassette fidelity and must remain as a narrow client integration smoke: do not delete all raw JSON probes indiscriminately.

The nine functions in `tests/e2e/test_phase3_publish_e2e.py` share a progressively mutated product/listing and depend on declaration order. This remote workflow is valuable but selected tests cannot all arrange their own preconditions. Express one deliberate end-to-end journey with named steps, or share a prepared deployed fixture only across independently valid assertions; keep remote cleanup and refusal-on-any-Blocked. Do not recreate nine full remote products simply to make each step isolated. The `test_ai_run_e2e.py:73` exact repeated market-active notification is a candidate for ordered milestones rather than incidental duplicate progress, but confirm the SSE event contract before changing it; final persisted market/proposal data and terminal state remain essential.

## Suite-level changes

Use natural state builders (`ProposalStore`, staging records, typed `Plan`s) and host seams (`ContextFactory`, provider gates). Read/write real files where disk semantics are the behavior. Retain a few vertical flows and avoid running a model/deploy/render chain to arrange unrelated adapter status codes. App creation without lifespan is already intentionally used in `test_batches_api.py:59` to hold queued rows; use it where startup itself is not under test. Tests of startup recovery, interruption/cancellation, queue order and deployed resources must still start the lifecycle.

`tests/support/ai_runs.py:83` routes fake tasks using response-schema identity (`is`) and treats every unrecognized schema as SEO. An equivalent copied schema can be valid at the provider protocol but be misrouted by the double. Compare stable boundary schema content or recognized shape, and explicitly reject unknown schemas. Preserve its excellent gates and started events. Keep shared doubles focused on what the external dependency promises, not production worker state. Do not add new production task identifiers solely to make a fake convenient.

Consolidate browser semantic locators while keeping genuine geometry/animation checks in the browser. Calibrator helpers already expose a documented `data-template` hook but still require `.template-rail__item` classes; role/name or explicit test hooks can make refactors safer. CSS properties asserted as appearance contracts and SVG geometry used for actual pointer placement are legitimate; do not mechanically replace them all with text checks. Polling for a real autosave/response condition is not equivalent to fixed elapsed sleeps and should remain bounded condition polling.

Organize the pyramid by actual boundaries, not names. `server/contract` here means adapter HTTP contracts with in-process real FastAPI, file state and sometimes worker chains; it does not mean remote cassette replay. Core `contract` uses real HTTP transport/cassettes. Many CLI behavior files call pure application operations, and core units include real child processes. Promote clarity about isolation, not numerical quotas. Current CI keeps live writes out of PRs; keep the separate main/manual e2e job and required-browser-layer setting.

## Good tests to retain as exemplars

* `tests/test_import_contracts.py`: synthetic allowed control plus forbidden direct/transitive edges exercise real Import Linter configuration. This proves the guard catches architectural violations; it is a documented ADR-0052 contract, not gratuitous source inspection.
* `tests/test_protected_test_imports.py`: enforces permitted test ownership of protected worker modules. The owner exception mapping is deliberate; public workflow tests should not use workers to arrange every state.
* `tests/test_ci_selection.py`: collects tests with the actual workflow selection and checks owner suites selected, browser/live e2e absent. Cheap source string checks alone would not prove actual marker behavior.
* `tests/test_export_openapi.py`: public schema is independent of whether built SPA assets happen to exist; the catchall must not enter the generated API schema.
* `tests/test_wheel_frontend.py`: installed artifact serving with no checkout/node, required build index and sdist completeness validate deployment contracts unavailable at lower layers; reuse compatible builds, retain assertions.
* `tests/test_migrate_workspace_refs.py`: byte-preservation/CRLF, dry-run, idempotency, escaped ref refusal and untouched lockfile directly protect a migration's user-visible output. Exact bytes are the contract here.
* `tests/server/behaviour/test_media_files_api.py`: URL/path traversal and protected listing-local YAML/lockfile boundaries through real files and HTTP. Keep genuine security integration even where workspace path unit tests overlap.
* `tests/server/contract/test_runs_api.py:365`, `:393`, `:414`: HTTP/SSE IDs, replay and output events against real fake-backed planning/application protect a public stream. One cannot replace routing/content-type/replay with a core-only unit.
* `tests/server/contract/test_ai_runs_api.py`: explicit gates hold provider work for conflict/cancel/preemption assertions; tangible no-proposal/no-write outcomes cover cancellation at the right observable boundary.
* `tests/server/behaviour/test_durable_proposals.py`: new application instances recover cached output; no reliance on old in-memory registries.
* `tests/browser/test_calibrator_browser.py`: browser-decoded WebP/PNG, source-space overlay/drag and `template.yaml` persistence span the actual SPA/server/render boundary. Keep representative kind coverage.
* `tests/browser/test_listing_template_editor_browser.py`: incomplete draft off disk, navigation warning and independent saved clone validate frontend state-to-storage behavior.
* `tests/cli/behaviour/test_new.py:125`: genuine plain-input terminal fallback end-to-end locally, asserting files users receive. It guards Windows/cygwin behavior that a mocked picker cannot prove.
* `tests/cli/behaviour/test_cli_surface.py:188`: actual terminal ANSI output instead of only arguments to a styler; the output stripping regression occurs after styling.
* `tests/e2e/test_market_search_e2e.py`: public research against real Etsy and an HTTP event hook prohibiting write methods, with scored/ranked persisted evidence.

## Measured run and inventory method

Hermetic baseline: **2875 selected**, **2866 passed**, **7 skipped**, **2 failed**, **159 browser/e2e deselected**, **565.23s**. The failures are root discovery from nested cwd/not-found in core workspace tests, outside this audit's ownership and being investigated by the core auditor. These results are not a clean baseline. XML/test logs are `reports/pytest-audit.xml` and `reports/pytest-audit.log`. CLI 236 collected cases total 13.120s; server 382 total 127.580s; six root files 39 total 206.19s; core 2218 cases. Timing sums include test fixture time and are only one machine/run, not forecasts.

Inventory uses AST function definitions (includes methods and async methods; no multiplication for parametrization) separately from collected pytest cases. Scope source counts: CLI 15 files /217 definitions; server17/349; browser11 including conftest /97; e2e7 including conftest /61; support11/0; six root tests and root conftest. Every file was inventoried; first/middle/last function assertions and names were sampled in every test file. All suspicious findings were inspected deeply with related production modules and lower-layer equivalents. **The table distinguishes complete reads from targeted deep reads plus assertion samples; it does not claim every assertion in the repository was manually reviewed.**

The full file inventory follows in the appended table. `Complete` means the complete source/fixtures was read; `Targeted + sampled` means selected bodies were deeply inspected and other assertions sampled; `Sampled` means names/first-middle-last assertion samples plus module/setup review. Support/fixture/CI entries are separate from case counts.


## File-by-file coverage inventory

68 Python files; 747 source test function definitions in this scope. These are not collected parametrized case counts.

| File | Source test definitions | Review depth |
|---|---:|---|
| `tests/browser/conftest.py` | 0 | Complete |
| `tests/browser/test_ai_seo_browser.py` | 21 | Targeted + sampled |
| `tests/browser/test_batch_creation_browser.py` | 4 | Sampled |
| `tests/browser/test_calibrator_browser.py` | 38 | Targeted + sampled |
| `tests/browser/test_calibrator_design.py` | 18 | Complete |
| `tests/browser/test_deploy_view.py` | 2 | Complete |
| `tests/browser/test_listing_template_editor_browser.py` | 3 | Sampled |
| `tests/browser/test_listing_templates_browser.py` | 3 | Sampled |
| `tests/browser/test_listing_videos_browser.py` | 2 | Complete |
| `tests/browser/test_listings_browser.py` | 5 | Sampled |
| `tests/browser/test_mobile_layout.py` | 1 | Complete |
| `tests/cli/behaviour/test_auth.py` | 14 | Sampled |
| `tests/cli/behaviour/test_cli_surface.py` | 23 | Targeted + sampled |
| `tests/cli/behaviour/test_closed_stdout.py` | 1 | Complete |
| `tests/cli/behaviour/test_new.py` | 6 | Targeted + sampled |
| `tests/cli/behaviour/test_new_picker.py` | 45 | Targeted + sampled |
| `tests/cli/behaviour/test_plan_reporting.py` | 20 | Complete |
| `tests/cli/behaviour/test_plan_skeleton.py` | 5 | Complete |
| `tests/cli/behaviour/test_setup_command.py` | 29 | Targeted + sampled |
| `tests/cli/behaviour/test_setup_prompts.py` | 11 | Complete |
| `tests/cli/behaviour/test_ui_command.py` | 3 | Complete |
| `tests/cli/behaviour/test_unlock_command.py` | 4 | Complete |
| `tests/cli/unit/test_auth_logic.py` | 11 | Targeted + sampled |
| `tests/cli/unit/test_cli_imports.py` | 3 | Complete |
| `tests/cli/unit/test_prompts.py` | 30 | Targeted + sampled |
| `tests/cli/unit/test_terminal.py` | 12 | Complete |
| `tests/conftest.py` | 0 | Complete |
| `tests/e2e/conftest.py` | 0 | Complete |
| `tests/e2e/test_ai_run_e2e.py` | 1 | Complete |
| `tests/e2e/test_batch_deploy_e2e.py` | 1 | Sampled |
| `tests/e2e/test_market_search_e2e.py` | 1 | Complete |
| `tests/e2e/test_phase3_publish_e2e.py` | 9 | Sampled |
| `tests/e2e/test_printify_catalog_e2e.py` | 17 | Complete |
| `tests/e2e/test_printify_product_e2e.py` | 32 | Targeted + sampled |
| `tests/server/behaviour/test_batch_review.py` | 10 | Targeted + sampled |
| `tests/server/behaviour/test_calibrator_api.py` | 63 | Sampled |
| `tests/server/behaviour/test_durable_proposals.py` | 2 | Complete |
| `tests/server/behaviour/test_listing_preview_api.py` | 9 | Complete |
| `tests/server/behaviour/test_listing_writes_api.py` | 2 | Complete |
| `tests/server/behaviour/test_listings_api.py` | 87 | Targeted + sampled |
| `tests/server/behaviour/test_media_files_api.py` | 21 | Targeted + sampled |
| `tests/server/contract/test_ai_runs_api.py` | 25 | Complete |
| `tests/server/contract/test_ai_seo_api.py` | 4 | Complete |
| `tests/server/contract/test_batches_api.py` | 32 | Targeted + sampled |
| `tests/server/contract/test_listing_templates_api.py` | 23 | Targeted + sampled |
| `tests/server/contract/test_market_api.py` | 6 | Complete |
| `tests/server/contract/test_proposals_api.py` | 13 | Complete |
| `tests/server/contract/test_runs_api.py` | 25 | Complete |
| `tests/server/unit/test_etsy_state_memo.py` | 7 | Complete |
| `tests/server/unit/test_preview_imagecache.py` | 19 | Complete |
| `tests/server/unit/test_server_imports.py` | 1 | Complete |
| `tests/support/__init__.py` | 0 | Complete |
| `tests/support/ai_runs.py` | 0 | Complete |
| `tests/support/batches.py` | 0 | Complete |
| `tests/support/builders.py` | 0 | Sampled |
| `tests/support/doubles.py` | 0 | Complete |
| `tests/support/http.py` | 0 | Complete |
| `tests/support/listings.py` | 0 | Complete |
| `tests/support/pipeline.py` | 0 | Complete |
| `tests/support/refusals.py` | 0 | Complete |
| `tests/support/scripted.py` | 0 | Complete |
| `tests/support/server.py` | 0 | Complete |
| `tests/test_ci_selection.py` | 1 | Complete |
| `tests/test_export_openapi.py` | 1 | Complete |
| `tests/test_import_contracts.py` | 3 | Complete |
| `tests/test_migrate_workspace_refs.py` | 9 | Complete |
| `tests/test_protected_test_imports.py` | 4 | Complete |
| `tests/test_wheel_frontend.py` | 5 | Complete |

| Configuration | Review depth |
|---|---|
| `AGENTS.md` | Complete, actual worktree version |
| `.github/workflows/ci.yml` | Complete |
| `.github/workflows/e2e.yml` | Complete |
| `pyproject.toml` | Targeted pytest/coverage/Import Linter configuration |
| `scripts/check.sh` | Targeted test/layer selection |

Measured hermetic directory labels: core/unit1318, core/behaviour711, core/contract174, core/golden15; CLI/unit66, CLI/behaviour170; server/unit27, server/behaviour219, server/contract136; root39. Browser97 cases ran separately; e2e62 collected but not run. Counting folder labels alone gives1411 named unit,1410 behavior/contract,15 golden,39 root,97 browser,62 e2e. These sum3034. Several named unit/behavior tests cross real filesystem/process boundaries, and browser tests here use hermetic server/client fakes, so these are **label counts, not proven small/medium/large or strict unit/integration/e2e counts**.
