# Core test audit

This review inventories every core test file and extracts every test's assertions and exception expectations. The highest-risk cases were then read with their fixtures, production interfaces, related lower-level coverage and current architecture. The inventory at the end distinguishes full body review from assertion-level review and targeted samples. No application or test files were changed.

## Measured scope and interpretation

| Layer | Files | Test definitions | Executed cases | Summed testcase seconds |
|---|---:|---:|---:|---:|
| unit | 78 | 1,098 | 1,318 | 35.976 |
| behaviour | 45 | 654 | 711 | 169.833 |
| contract | 9 | 164 | 174 | 0.298 |
| golden | 5 | 14 | 15 | 1.555 |
| Total | 137 | 1,930 | 2,218 | 207.662 |

The counts come from Python AST definitions and `reports/pytest-audit.xml`; parametrization expands definitions into cases. Durations include JUnit setup/call/teardown and are one local Windows run, not benchmarks or projected savings. The full hermetic run was 2,866 passed, two failed, seven skipped, 159 deselected, 565.23 seconds. Core had two failures, six skips. Core integration-like behaviour cases cost substantially more than the cassette contracts. Directory names also obscure real size: real process-tree tests live under unit, while direct fake smoke tests live under behaviour. No specific ideal percentage is warranted by the test pyramid.

Two failures are verified test-environment isolation defects: `tests/core/unit/test_workspace.py:39` (`test_discover_finds_root_from_nested_cwd`) and `:58` (`test_discover_raises_when_not_found`). The host has `ETSY_LISTINGS_ROOT` set; `Workspace._find_root` explicitly honors it before `start` (`src/etsy_listings/core/workspace/workspace.py:287`). These two tests assume it is unset, and `workspace_root` does not clear it. Running just both cases with `env -u ETSY_LISTINGS_ROOT uv run pytest <both nodeids> -q` passed both (13.91 seconds including test-session overhead). Preserve the behavior checks and clear the variable with `monkeypatch.delenv` in the discovery cases or a hermetic-only fixture. Do not clear the intentional e2e workspace environment globally. The environment value was not queried for the diagnosis.

## Ranked changes

### 1. Reduce full deployment setup around the proposal cleanup rule

**Priority high; confidence high on redundant setup, medium on attainable speed.** `tests/core/behaviour/test_proposal_cleanup.py` has eight cases totaling **12.069 seconds**. The predicate has a narrow public interface, `engine.run.fully_applied(outcome, lock)`, but even `test_full_success_needs_the_marker_clear_whatever_else_holds` (`:195`) builds a deployable context and plans all real stages before checking two booleans. The blocked, failure and incomplete conditions (`:92`, `:115`, `:128`) use real pipelines and large images to derive states that can be expressed directly. CLI (`:47`) and HTTP (`:68`) checks run the same real pipeline again through adapters.

Move the complete condition table (outcome error, planned absence, blocked stage, incomplete marker, all clear) to small unit tests of `fully_applied`, using the existing engine outcome/plan/lock value objects. Test cleanup orchestration with simple Stage implementations at the existing Stage protocol: success removes the on-disk proposal, failed/blocked/incomplete preserve it, and a stop after the last runnable stage still cleans up. Keep one real full-pipeline success integration and retain thin CLI/HTTP wiring checks to prove both adapters enter that shared engine path. Do not delete adapter integration simply because the predicate is covered. The stop case (`:160`) tests a distinct lifecycle rule and needs orchestration, not just a predicate assertion. Expected speed improvement is unmeasured.

### 2. Replace fixed sleep race orchestration with explicit gates

**Priority high; confidence high.** In `tests/core/behaviour/test_listing_operations.py`, `slow_writes` (`:442`) delays every `yaml.safe_dump` by 0.3 seconds, `slow_renames` (`:453`) delays `Path.replace`, and `_together` (`:468`) guesses worker acquisition order with a 0.1-second stagger. Template equivalents are `tests/core/behaviour/test_listing_template_operations.py:409`, `:420`, `:430`, patching `Path.rename` and global YAML serialization. Three listing and three template competing-write cases cost **2.447 seconds combined** in this run. The tests preserve important lost-update, rename/edit and create/rename conflict behavior; they are not deletion candidates.

Scheduling an earlier future does not guarantee it holds the lock first. The template rename/edit test asserts a particular winner based on that guess. The listing rename/edit case already waits for a `moving` event, which is better, but holds the critical section for a fixed period rather than until the contender is known to have started. Use a narrowly scoped blocking I/O double at the existing `ListingDocuments`/template persistence boundary. Signal `entered`; launch the contender after `entered.wait(timeout)`; release the holder explicitly in `finally`; collect both outcomes and assert the final persisted documents through application operations. Avoid blocking the main thread inside a contending synchronous edit before release: run both operations as workers. Share only a small gate helper in `tests/support`, not a general race framework. This increases determinism and removes artificial wait budget without changing the product concurrency contract.

### 3. Shrink oversized success fixtures instead of deleting meaningful stage tests

**Priority high for investigation; confidence high on cost, medium on savings.** `tests/core/behaviour/test_printify_product_stage.py` is the most expensive core file: **33 cases, 25.500 seconds**. Its `root` fixture (`:89`) always creates a **4500 × 5400** PNG; `PRINT_AREA` at `:55`, the catalog placeholder and checked-in garment profile all use those dimensions. Most cases check prices, adoption, idempotency, refusal messages or variant selection rather than pixels. `tests/support/pipeline.py` uses the same full-size print area for many deployment fixtures; the unit `test_product_gates.py` file itself costs 5.346 seconds.

Add a small, matched garment profile/catalog/design builder for non-resolution cases: for example matching 450 × 540 dimensions while preserving colors, sizes and placement. Write/edit the profile through the public workspace/application seam or fixture data, without bypassing validation. Keep exact-resolution, one-pixel/tolerance and undersized-image cases using their explicit independent dimensions; retain byte render goldens and representative real full-resolution smoke coverage if required. Do not mock the resolution function out of every stage test. The stable stage interfaces remain `build_plan`/`execute` plus client protocols. Benchmark the smaller fixture separately before reporting speed savings: the measured 25.5 seconds includes useful stage work, so it is an upper bound, not recoverable time.

### 4. Repair weak render/cache tests that permit the named behavior to disappear

**Priority medium-high; confidence high.** `tests/core/unit/test_render_maps.py:27`, `test_height_map_is_smoother_than_luminance`, uses a linear gradient and permits `variance(height differences) <= variance(luminance differences) + epsilon`. Returning the luminance unchanged satisfies that assertion. `test_height_map_accepts_even_ksize_by_rounding_up` (`:34`) only calls the function: it checks no exception, not rounding to the next odd kernel. `test_derived_map_cache_writes_and_reuses` (`:39`) compares output and file count; recomputing and overwriting the same file passes.

Use a deterministic high-frequency/impulse image with independently justified attenuation and nonidentity expectations for smoothing; compare the even-kernel public result to the expected next odd-kernel result. For reuse, observe persistence I/O: after the first fill, reject another `np.save` or install a distinguishable cached array and assert the second call loads it. Cache storage is the right interaction boundary; avoid asserting private hash strings or Gaussian helper invocation sequences. Retain source-change invalidation (`:54`) and add map-parameter invalidation to prevent reusing a height map with a different blur size. These six tests take only 0.035 seconds, so the benefit is detection quality, not runtime.

### 5. Make per-pass golden failures identify their actual subject

**Priority medium-high; confidence high.** `tests/core/golden/passes/test_passes_golden.py` says each pass runs in isolation, but the displace (`:40`), shade (`:49`) and export (`:58`) cases all call current `warp` first. A warp regression can therefore fail all four pass goldens, obscuring localization. Displace/shade also depend on current map-generation code.

Give each downstream pass a small, deterministic prewarped array or separately reviewed fixed input fixture; use explicit small height/luminance arrays for pass-specific tests. Keep warp's own golden and the complete render pipeline goldens in `golden/e2e/test_render_e2e_golden.py` to check composition. Direct private pass imports are intentional in this architecture and useful here; the problem is upstream dependency contamination, not their import visibility. Do not replace renderer byte baselines with implementation-generated expected output.

### 6. Exercise actual fresh reads and deadline boundaries

**Priority medium; confidence high.** `tests/core/unit/test_ai_brief.py:55`, `test_the_packaged_prompt_is_read_fresh_each_call`, compares two calls against unchanged packaged content. It proves repeatability, while the production function explicitly promises fresh reads; a cached constant passes. Change the resource boundary to return two distinct texts on successive reads, and assert public `default_brief_prompt_text()` sees first and second values. Use the `importlib.resources` resource/Traversable seam, not inspection of a cache implementation.

`tests/core/unit/test_ai_models.py:117` allows a wall-clock epsilon and `:132` sleeps to expire a deadline. Inject/patch monotonic time at the clock boundary for exact before/at/after cutoff checks, including nonnegative remaining time. The model source is intentionally a plain frozen dataclass, which supports this narrow clock substitution. Retain separate genuine repeatability/invariance tests where determinism is the contract; equality of two function calls is not automatically a tautology. For example, identical renders across independent preview and deployment paths serve a real consistency requirement.

### 7. Remove fake and DTO tests that only restate fixture construction

**Priority medium-low; confidence high for the four listed removals.** These cases consume negligible runtime but add obligations during interface changes without independent product validation:

* `tests/core/unit/test_ai_models.py:94`, `test_seo_proposal_holds_exactly_the_agreed_shape`, supplies counts 3/20/3/7 in `_proposal` and asserts those same lengths. `SeoProposal` is a plain dataclass; the test neither invokes nor proves count validation. Remove it. `test_ai_validation.py:66` constructs the shape from real parsed input and `:126` rejects wrong counts, so the actual contract remains covered. Keep default-value and frozen/copy semantics where they are meaningful; do not remove all model tests.
* `tests/core/unit/test_ai_providers.py:72`, `test_fake_provider_satisfies_the_provider_protocol`, assigns a typed variable and checks readiness's type. It is subsumed by `:32`'s exact default readiness and protocol type checking. Remove the duplicate; keep fake FIFO/exhaustion/task-recording tests because repair workflows depend on them.
* `tests/core/behaviour/test_etsy_market_fake.py:49`, `test_the_fake_satisfies_the_protocol`, assigns a protocol-typed fake then checks an unseeded search is empty. Merge its type assignment into `test_an_unseeded_query_finds_nothing` (`:67`) or rely on static checking; do not keep a second runtime test for the same empty default.
* `tests/core/unit/test_lock.py:322`, `test_a_clean_lockfile_writes_byte_identical_json_to_before_the_marker_existed`, only checks that the text lacks `incomplete`. It duplicates `test_write_omits_incomplete_when_unset` (`:302`) and cannot verify byte identity. Delete the duplicate or replace it with a literal pre-marker JSON baseline if byte compatibility is truly required. Do not derive the expected baseline using current serialization.

Other DTO storage-only cases (`test_ai_models.py:58`, `:109`, readiness/result constructors later in that file) are lower-confidence consolidation candidates, not automatic deletions: first preserve their defaults and downstream field-consumption checks. Fake fidelity suites have real value, especially Etsy detach/dangling-link/video budget semantics; do not remove them wholesale.

### 8. Align claimed test behavior with the assertion and layer

**Priority medium-low; confidence high.** `tests/core/behaviour/test_printify_product_stage.py:353`, `test_an_update_reads_the_product_before_writing_it`, merely asserts an update happened and only one product was created. It cannot distinguish a fresh read from reuse of stale previously obtained live state. Its docstring attributes all-variant payload coverage to this stage, but that expansion is the real adapter's responsibility, already asserted via real HTTP transport in `tests/core/contract/test_printify_products_http.py:311`.

Track public `get_product` calls through the injected client interface between operations or mutate the live fake product after the initial apply and prove the subsequent update uses the newly read state. Keep payload coverage at the HTTP contract; do not assert the Stage's `ProductSpec` contains adapter-expanded variants. If this case adds no unique read validation after that refactor, consolidate it with price-change apply (`:321`).

`tests/core/behaviour/test_publish_stage.py:195`, `test_a_changed_price_triggers_a_republish`, checks only the publish plan, not a second publish call. Rename it to say price changes plan publishing or execute the plan and assert the public fake's published count/body; the latter closes the claim's missing half. Keep unchanged second-apply no-write checks. `tests/core/unit/test_ai_process.py:395`, `:433`, `:498` launch real processes, so classify them as OS integration/behaviour, retaining the real process tests: doubles cannot prove descendants die or UTF-8 crosses the actual subprocess boundary. The two real process cleanup cases took 2.578 seconds combined.

### 9. Replace unjoined fake-process completion threads and guessed creation timing

**Priority medium-low; confidence high.** `tests/core/unit/test_ai_process.py:96`, `:118`, `:184` spawn completion threads that sleep 0.01 seconds and then index the fake-Popen list. A delayed factory can leave that list empty when the worker runs, producing a thread exception and a wait until the test deadline. They do not explicitly join the completion workers. Have the injected Popen factory signal a `created` event, then complete that returned fake; finish and join workers in teardown/finally. Existing cancellation-event tests and real process-tree integration should remain. These unit test sleeps are small; the purpose is reliability and failure clarity.

### 10. Push narrow format checks down without removing the seam checks

**Priority low; confidence high.** `tests/core/golden/test_market_block.py:82` exercises serialized field order, top-eight truncation, tags/leads, prompt-injection delimiters and restricted fields via an entire fake research run. Build an explicit `MarketResult` for these formatter-specific checks against exported `market_block`, leaving one research-to-block golden integration. Empty-block case (`:105`) can directly use an empty result. `test_market_research.py` and pure scoring/phrase tests already cover research and ranking; however, the single block golden also provides integration evidence and should remain. Runtime is 0.013 seconds for all three, so this is coupling reduction, not a meaningful speed optimization.

`tests/core/contract/test_catalog_http.py:255`, `:263` exercise local credential discovery, not HTTP. Move them to the unit Secrets subject; they cover Printify-specific guidance not guaranteed by existing Etsy-only examples. `:121` uses HTTP just to check largest-placeholder selection: move the varying-size value rule to a small model unit, retaining the real nested-placeholder decode at `:108`. Contract duration is already tiny (0.298 seconds total); layering here clarifies ownership.

## Good tests and constraints to preserve

* `tests/core/unit/test_product_diff.py:126` uses hand-authored old/new price values and checks exact `PriceChange` currency/amounts through the diff operation; it needs no workspace, API, or renderer. The color/artwork drift tests in the same file distinguish meaningful changes from unrelated fields.
* `tests/core/unit/test_market_scoring.py` checks percentiles, ties, missing values and explicit score arithmetic with independent worked examples. These are useful lower-layer replacements for repeating rank scenarios through complete research.
* `tests/core/unit/test_retry.py:49` checks that a POST whose response might have been lost is never retried; injected sleep/randomness makes safety checks fast. Counting attempts is necessary because duplicate external writes are the observable hazard.
* `tests/core/unit/test_lock.py:121`, `:132`, `:162`, `:225`, `:236` check replace-versus-merge, independent remote IDs, original immutability, future unknown fields, and invalid documents. A small representative document avoids coupling a storage test to every real engine stage.
* `tests/core/unit/test_scene_hash.py:70`, `:90`, `:109`, `:128` use changed own-scene inputs and unchanged unrelated-scene inputs. They independently specify invalidation boundaries rather than only comparing an unchanged call to itself.
* `tests/core/behaviour/test_printify_product_stage.py:300` asserts no writes on second apply; `:334` asserts omitted colors are actually disabled. These protect money-sensitive idempotency and provider semantics. Keep a workflow-level test even though pure diffs and HTTP contracts also exist.
* `tests/core/behaviour/test_render_outputs.py:42`, `:59` separately prove a missing render is planned and is restored by apply. Planning alone would leave the original regression half-fixed.
* `tests/core/contract/test_catalog_http.py:108` checks the real nesting of Printify placeholders inside variants. `tests/core/contract/test_printify_products_http.py:311`, `:331` inspect real HTTP bodies including server-only variants, explicit disabling and wire-only fields. Fakes do not replace these payload obligations.
* `tests/core/contract/test_fx_rate.py:83` checks real httpx redirect handling; simply mocking the decoded response would miss a transport configuration regression.
* `tests/core/golden/test_preview_promotion.py` compares render bytes across separately constructed preview/deploy workspaces. Preserve that cross-path consistency evidence alongside independent image goldens.
* `tests/core/unit/test_airuns_registry.py` predominantly uses public `AiRunRegistry` operations, event delivery and `wait_settled`; it does not justify a blanket claim of tests inspecting private registry state. Subscriber delivery outside the lock is a valid concurrency assertion.
* `tests/core/unit/test_workspace_facts.py` asserts request-scoped reads and lazy garment loading through the public Workspace boundary. These interactions specify documented I/O reuse, rather than arbitrary helper choreography.
* `tests/core/behaviour/test_etsy_listings_fake.py` detach/overwrite/dangling-link cases and `test_etsy_video_gallery_fake.py` capacity/budget cases keep the double honest about measured third-party behavior. Preserve them and periodically compare fake/HTTP/live probe transcripts; direct fake tests are not intrinsically low value.
* AI vendor argv tests belong at each adapter boundary: sandbox/read-only flags, image/schema arguments, authentication and transient-session options encode vendor contracts. Tests of a public provider should not care about those flags, but adapter tests correctly should.

## Suite-wide direction and limits

Extract smaller builders around stable exported protocols/value objects (Stage, provider/client, Workspace/ListingDocuments, application operation), not around the existing sequence of private helpers. Keep one representative integration per shared operation; express rule matrices as pure unit examples and transport payload/response matrices via real httpx cassettes. Reuse deterministic blocking gate and fake-clock helpers, with cleanup that joins worker threads. Keep genuine external no-write/no-retry interaction checks. Test double fidelity matters independently of feature coverage.

The core scan finds a substantial unit base; it does not establish that every `unit` case is a unit test or that every `behaviour` case is an integration. Parent report combines this scope with server/CLI/frontend/browser/e2e review. No coverage or mutation testing was run here, and deletion recommendations must retain the repository's 85% branch floor. The four confident deletion/consolidation cases save maintenance, not material wall time. Costs for image builders and full pipelines are measured baselines; predicted reductions remain unmeasured.

Read and apply the primary-source criteria in [python-research.md](python-research.md): behavior-focused output/state, independent oracle, fixture scope, clock/scheduling isolation, fake fidelity, and distinction between meaningful external interaction and helper choreography. Local assertion extraction is preserved in `core-scan-unit.txt`, `core-scan-behaviour.txt`, `core-scan-contract.txt`, `core-scan-golden.txt` for reproducibility.

## File review inventory

`Full` means the source bodies and fixture logic were read. `Assertions + samples` means all definitions/assertions/exception expectations/imports were extracted, with targeted body/production checks; it does not mean every body was read line by line. Test counts are definitions, not parametrized cases. Production code was traced for the findings above; no claim is made that every test was experimentally mutated.

| File | Definitions | Review |
|---|---:|---|
| `tests/core/behaviour/test_ai_coordinator.py` | 10 | Assertions + samples |
| `tests/core/behaviour/test_ai_readiness.py` | 13 | Assertions + samples |
| `tests/core/behaviour/test_ai_runner.py` | 29 | Assertions + samples |
| `tests/core/behaviour/test_apply_observer.py` | 6 | Assertions + samples |
| `tests/core/behaviour/test_batch_archive.py` | 25 | Assertions + samples |
| `tests/core/behaviour/test_batch_creation.py` | 15 | Assertions + samples |
| `tests/core/behaviour/test_batch_operations.py` | 32 | Assertions + samples |
| `tests/core/behaviour/test_batch_queue.py` | 10 | Assertions + samples |
| `tests/core/behaviour/test_batch_staging.py` | 19 | Assertions + samples |
| `tests/core/behaviour/test_calibration_designs.py` | 4 | Assertions + samples |
| `tests/core/behaviour/test_credential_operations.py` | 16 | Assertions + samples |
| `tests/core/behaviour/test_deploy_precedence.py` | 5 | Assertions + samples |
| `tests/core/behaviour/test_deployments.py` | 17 | Full |
| `tests/core/behaviour/test_etsy_callback.py` | 6 | Assertions + samples |
| `tests/core/behaviour/test_etsy_listing_stage.py` | 24 | Assertions + samples |
| `tests/core/behaviour/test_etsy_listings_fake.py` | 8 | Full |
| `tests/core/behaviour/test_etsy_market_fake.py` | 13 | Full |
| `tests/core/behaviour/test_etsy_media_stage.py` | 20 | Assertions + samples |
| `tests/core/behaviour/test_etsy_video_gallery_fake.py` | 20 | Assertions + samples |
| `tests/core/behaviour/test_etsy_videos_stage.py` | 19 | Assertions + samples |
| `tests/core/behaviour/test_garment_operations.py` | 5 | Assertions + samples |
| `tests/core/behaviour/test_lifecycle.py` | 18 | Assertions + samples |
| `tests/core/behaviour/test_listing_ai_inputs.py` | 2 | Assertions + samples |
| `tests/core/behaviour/test_listing_creation.py` | 11 | Assertions + samples |
| `tests/core/behaviour/test_listing_operations.py` | 33 | Assertions + samples |
| `tests/core/behaviour/test_listing_proposals.py` | 9 | Assertions + samples |
| `tests/core/behaviour/test_listing_template_discovery.py` | 3 | Assertions + samples |
| `tests/core/behaviour/test_listing_template_operations.py` | 28 | Assertions + samples |
| `tests/core/behaviour/test_market_cache.py` | 16 | Assertions + samples |
| `tests/core/behaviour/test_market_research.py` | 21 | Full |
| `tests/core/behaviour/test_migrate_refs_cost.py` | 1 | Assertions + samples |
| `tests/core/behaviour/test_mockup_template_operations.py` | 31 | Assertions + samples |
| `tests/core/behaviour/test_partial_apply.py` | 8 | Assertions + samples |
| `tests/core/behaviour/test_printify_product_stage.py` | 33 | Assertions + samples |
| `tests/core/behaviour/test_proposal_cleanup.py` | 8 | Full |
| `tests/core/behaviour/test_publish_stage.py` | 11 | Full |
| `tests/core/behaviour/test_render_outputs.py` | 10 | Assertions + samples |
| `tests/core/behaviour/test_render_preview.py` | 15 | Assertions + samples |
| `tests/core/behaviour/test_render_stage.py` | 11 | Assertions + samples |
| `tests/core/behaviour/test_run.py` | 22 | Assertions + samples |
| `tests/core/behaviour/test_runs_executor.py` | 12 | Assertions + samples |
| `tests/core/behaviour/test_should_stop.py` | 9 | Assertions + samples |
| `tests/core/behaviour/test_stage_remote_state.py` | 7 | Assertions + samples |
| `tests/core/behaviour/test_video_in_media.py` | 2 | Assertions + samples |
| `tests/core/behaviour/test_workspace_setup_operations.py` | 17 | Assertions + samples |
| `tests/core/contract/test_catalog_http.py` | 14 | Full |
| `tests/core/contract/test_etsy_auth_http.py` | 13 | Assertions + samples |
| `tests/core/contract/test_etsy_listings_http.py` | 39 | Assertions + samples |
| `tests/core/contract/test_etsy_market_http.py` | 30 | Assertions + samples |
| `tests/core/contract/test_etsy_shops_http.py` | 11 | Assertions + samples |
| `tests/core/contract/test_fx_rate.py` | 8 | Full |
| `tests/core/contract/test_printify_products_http.py` | 28 | Assertions + samples |
| `tests/core/contract/test_printify_shops_http.py` | 15 | Assertions + samples |
| `tests/core/contract/test_unofficial_variant_costs_http.py` | 6 | Assertions + samples |
| `tests/core/golden/e2e/test_render_e2e_golden.py` | 2 | Full |
| `tests/core/golden/passes/test_passes_golden.py` | 4 | Full |
| `tests/core/golden/test_ai_prompts.py` | 4 | Full |
| `tests/core/golden/test_market_block.py` | 3 | Full |
| `tests/core/golden/test_preview_promotion.py` | 1 | Full |
| `tests/core/unit/test_ai_brief.py` | 12 | Assertions + samples |
| `tests/core/unit/test_ai_claude.py` | 23 | Assertions + samples |
| `tests/core/unit/test_ai_codex.py` | 16 | Assertions + samples |
| `tests/core/unit/test_ai_errors.py` | 23 | Assertions + samples |
| `tests/core/unit/test_ai_grok.py` | 12 | Assertions + samples |
| `tests/core/unit/test_ai_market_queries.py` | 7 | Assertions + samples |
| `tests/core/unit/test_ai_models.py` | 11 | Full |
| `tests/core/unit/test_ai_orchestrator.py` | 20 | Assertions + samples |
| `tests/core/unit/test_ai_packaged_prompts.py` | 11 | Full |
| `tests/core/unit/test_ai_process.py` | 16 | Full |
| `tests/core/unit/test_ai_prompt.py` | 13 | Full |
| `tests/core/unit/test_ai_providers.py` | 6 | Full |
| `tests/core/unit/test_ai_validation.py` | 29 | Assertions + samples |
| `tests/core/unit/test_airuns_registry.py` | 19 | Full |
| `tests/core/unit/test_atomic.py` | 8 | Assertions + samples |
| `tests/core/unit/test_batch_naming.py` | 6 | Assertions + samples |
| `tests/core/unit/test_batch_status.py` | 14 | Assertions + samples |
| `tests/core/unit/test_batch_store.py` | 15 | Assertions + samples |
| `tests/core/unit/test_catalog.py` | 16 | Assertions + samples |
| `tests/core/unit/test_colour_property.py` | 8 | Assertions + samples |
| `tests/core/unit/test_common_copy.py` | 14 | Assertions + samples |
| `tests/core/unit/test_config_yaml_errors.py` | 1 | Assertions + samples |
| `tests/core/unit/test_connections.py` | 12 | Assertions + samples |
| `tests/core/unit/test_core_imports.py` | 2 | Assertions + samples |
| `tests/core/unit/test_defaults.py` | 18 | Assertions + samples |
| `tests/core/unit/test_description.py` | 12 | Assertions + samples |
| `tests/core/unit/test_etsy_oauth.py` | 19 | Assertions + samples |
| `tests/core/unit/test_etsy_pacing.py` | 7 | Assertions + samples |
| `tests/core/unit/test_etsy_shopcatalog.py` | 23 | Assertions + samples |
| `tests/core/unit/test_etsy_target.py` | 6 | Assertions + samples |
| `tests/core/unit/test_etsy_tokens.py` | 15 | Assertions + samples |
| `tests/core/unit/test_garment_profile.py` | 4 | Assertions + samples |
| `tests/core/unit/test_listing.py` | 47 | Assertions + samples |
| `tests/core/unit/test_listing_artifacts.py` | 9 | Assertions + samples |
| `tests/core/unit/test_listing_documents.py` | 21 | Assertions + samples |
| `tests/core/unit/test_listing_status.py` | 36 | Assertions + samples |
| `tests/core/unit/test_listing_template.py` | 7 | Assertions + samples |
| `tests/core/unit/test_listing_template_convert.py` | 13 | Assertions + samples |
| `tests/core/unit/test_listing_validation.py` | 72 | Assertions + samples |
| `tests/core/unit/test_lock.py` | 31 | Full |
| `tests/core/unit/test_market_lead.py` | 2 | Assertions + samples |
| `tests/core/unit/test_market_phrases.py` | 7 | Assertions + samples |
| `tests/core/unit/test_market_scoring.py` | 7 | Full |
| `tests/core/unit/test_market_snapshot.py` | 7 | Assertions + samples |
| `tests/core/unit/test_media.py` | 6 | Assertions + samples |
| `tests/core/unit/test_money.py` | 9 | Assertions + samples |
| `tests/core/unit/test_no_bare_cv2.py` | 1 | Assertions + samples |
| `tests/core/unit/test_plan_fingerprint.py` | 8 | Full |
| `tests/core/unit/test_preview.py` | 7 | Assertions + samples |
| `tests/core/unit/test_pricing_plan.py` | 9 | Assertions + samples |
| `tests/core/unit/test_product_diff.py` | 25 | Full |
| `tests/core/unit/test_product_document.py` | 11 | Assertions + samples |
| `tests/core/unit/test_product_gates.py` | 24 | Assertions + samples |
| `tests/core/unit/test_proposal_staleness.py` | 7 | Assertions + samples |
| `tests/core/unit/test_proposal_store.py` | 19 | Assertions + samples |
| `tests/core/unit/test_render_config.py` | 11 | Assertions + samples |
| `tests/core/unit/test_render_maps.py` | 6 | Full |
| `tests/core/unit/test_render_passes.py` | 14 | Full |
| `tests/core/unit/test_retry.py` | 20 | Full |
| `tests/core/unit/test_run_commands.py` | 3 | Full |
| `tests/core/unit/test_run_context.py` | 2 | Full |
| `tests/core/unit/test_run_events.py` | 15 | Assertions + samples |
| `tests/core/unit/test_runs_registry.py` | 27 | Assertions + samples |
| `tests/core/unit/test_scaffold.py` | 8 | Assertions + samples |
| `tests/core/unit/test_scene_hash.py` | 5 | Full |
| `tests/core/unit/test_secrets.py` | 5 | Full |
| `tests/core/unit/test_settings.py` | 12 | Assertions + samples |
| `tests/core/unit/test_setup_logic.py` | 26 | Assertions + samples |
| `tests/core/unit/test_slug.py` | 4 | Assertions + samples |
| `tests/core/unit/test_stage_outcome.py` | 2 | Full |
| `tests/core/unit/test_swatch.py` | 5 | Assertions + samples |
| `tests/core/unit/test_unofficial_variant_costs.py` | 3 | Assertions + samples |
| `tests/core/unit/test_userpath.py` | 6 | Assertions + samples |
| `tests/core/unit/test_variant_resolution.py` | 11 | Assertions + samples |
| `tests/core/unit/test_video_probe.py` | 8 | Assertions + samples |
| `tests/core/unit/test_workspace.py` | 76 | Assertions + samples |
| `tests/core/unit/test_workspace_common_copy.py` | 13 | Assertions + samples |
| `tests/core/unit/test_workspace_facts.py` | 13 | Full |
