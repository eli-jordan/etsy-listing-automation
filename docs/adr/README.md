# Architecture decisions

Accepted decisions extracted from the original PRD and implementation plan.
The numbering follows the commit that first introduced each decision, with
ties resolved by document order. Amendments are folded into the current
decision rather than given a second number.

Each linked file explains a decision and its rationale. This index contains no
second summary of the same decision. Smaller rules belong in the feature
specification or current reference that owns them.

Cite `ADR-NNNN` when a choice needs its rationale; keep the comment
self-contained when it already explains the rule. Historical decision ids
remain in the [original PRD](../history/prd.md) and
[original plan](../history/implementation-plan.md), which are frozen context.
When revisiting a decision, update its record explicitly and keep its history
so the trade-off remains visible.

| ADR | Decision | First recorded |
|---|---|---|
| 0001 | [Let Printify create the Etsy listing](0001-let-printify-create-the-etsy-listing.md) | 2026-09-03 |
| 0002 | [Converge through a lockfile and plan/apply](0002-converge-through-a-lockfile-and-plan-apply.md) | 2026-09-03 |
| 0003 | [AI proposes copy; the seller accepts it](0003-ai-proposes-copy-the-seller-accepts-it.md) | 2026-09-03 |
| 0004 | [Map mockup colours by filename convention](0004-map-mockup-colours-by-filename-convention.md) | 2026-09-03 |
| 0005 | [Resolve provider and blueprint references by stable names](0005-resolve-provider-and-blueprint-references-by-stable-names.md) | 2026-09-03 |
| 0006 | [Require an explicit currency on every price](0006-require-an-explicit-currency-on-every-price.md) | 2026-09-03 |
| 0007 | [Order stages in a fixed pipeline](0007-order-stages-in-a-fixed-pipeline.md) | 2026-09-03 |
| 0008 | [Store applied documents and emit shared changes](0008-store-applied-documents-and-emit-shared-changes.md) | 2026-09-03 |
| 0009 | [Keep writes synchronous and sequential](0009-keep-writes-synchronous-and-sequential.md) | 2026-09-03 |
| 0010 | [Separate behavioural fakes from wire contracts](0010-separate-behavioural-fakes-from-wire-contracts.md) | 2026-09-03 |
| 0011 | [Generate the frontend API contract](0011-generate-the-frontend-api-contract.md) | 2026-09-03 |
| 0012 | [Render with pure passes and pinned dependencies](0012-render-with-pure-passes-and-pinned-dependencies.md) | 2026-09-03 |
| 0013 | [Keep workspace data separate from the application](0013-keep-workspace-data-separate-from-the-application.md) | 2026-09-03 |
| 0014 | [Make mockup template kinds explicit](0014-make-mockup-template-kinds-explicit.md) | 2026-09-03 |
| 0015 | [Select mockups explicitly in listing media](0015-select-mockups-explicitly-in-listing-media.md) | 2026-09-03 |
| 0016 | [Isolate undocumented manufacturing costs](0016-isolate-undocumented-manufacturing-costs.md) | 2026-09-05 |
| 0017 | [Refuse automated garment replacement](0017-refuse-automated-garment-replacement.md) | 2026-09-08 |
| 0018 | [Gate design resolution against the print area](0018-gate-design-resolution-against-the-print-area.md) | 2026-09-08 |
| 0019 | [Send channel-currency minor units to Printify](0019-send-channel-currency-minor-units-to-printify.md) | 2026-09-08 |
| 0020 | [Keep retail currency unchanged during apply](0020-keep-retail-currency-unchanged-during-apply.md) | 2026-09-08 |
| 0021 | [Assign one writer to each remote field](0021-assign-one-writer-to-each-remote-field.md) | 2026-09-08 |
| 0022 | [Put real listing copy on the Printify product](0022-put-real-listing-copy-on-the-printify-product.md) | 2026-09-08 |
| 0023 | [Guard the create-success-then-crash window](0023-guard-the-create-success-then-crash-window.md) | 2026-09-08 |
| 0024 | [Share transport while separating client authority](0024-share-transport-while-separating-client-authority.md) | 2026-09-09 |
| 0025 | [Separate credentials from workspace configuration](0025-separate-credentials-from-workspace-configuration.md) | 2026-09-09 |
| 0026 | [Use minimal Etsy scopes and a fixed loopback callback](0026-use-minimal-etsy-scopes-and-a-fixed-loopback-callback.md) | 2026-09-09 |
| 0027 | [Persist rotating OAuth credentials before use](0027-persist-rotating-oauth-credentials-before-use.md) | 2026-09-09 |
| 0028 | [Declare the actual production partner explicitly](0028-declare-the-actual-production-partner-explicitly.md) | 2026-09-10 |
| 0029 | [Observe processing time without replacing inventory](0029-observe-processing-time-without-replacing-inventory.md) | 2026-09-10 |
| 0030 | [Choose variation images by an explicit template](0030-choose-variation-images-by-an-explicit-template.md) | 2026-09-10 |
| 0031 | [Sync media by hashes and an ordered image-id manifest](0031-sync-media-by-hashes-and-an-ordered-image-id-manifest.md) | 2026-09-10 |
| 0032 | [Assert the shipping profile on Etsy](0032-assert-the-shipping-profile-on-etsy.md) | 2026-09-10 |
| 0033 | [Resolve Etsy shop reference data once per run](0033-resolve-etsy-shop-reference-data-once-per-run.md) | 2026-09-10 |
| 0034 | [Thread newly created remote ids through the run](0034-thread-newly-created-remote-ids-through-the-run.md) | 2026-09-10 |
| 0035 | [Delete never-live listings; retire published ones](0035-delete-never-live-listings-retire-published-ones.md) | 2026-09-16 |
| 0036 | [Retract drafts through the connected Printify product](0036-retract-drafts-through-the-connected-printify-product.md) | 2026-09-16 |
| 0037 | [Record every successful stage of a partial apply](0037-record-every-successful-stage-of-a-partial-apply.md) | 2026-09-17 |
| 0038 | [Expose stage facts; let the frontend compose the view](0038-expose-stage-facts-let-the-frontend-compose-the-view.md) | 2026-09-17 |
| 0039 | [Replan before applying a reviewed fingerprint](0039-replan-before-applying-a-reviewed-fingerprint.md) | 2026-09-17 |
| 0040 | [Promote matching full-size previews during apply](0040-promote-matching-full-size-previews-during-apply.md) | 2026-09-17 |
| 0041 | [Run UI deployments as server-side resources](0041-run-ui-deployments-as-server-side-resources.md) | 2026-09-17 |
| 0042 | [Apply exactly the workspace set that was reviewed](0042-apply-exactly-the-workspace-set-that-was-reviewed.md) | 2026-09-21 |
| 0043 | [Save named listings even when incomplete](0043-save-named-listings-even-when-incomplete.md) | 2026-09-24 |
| 0044 | [Use market evidence for wording rather than facts](0044-use-market-evidence-for-wording-rather-than-facts.md) | 2026-09-24 |
| 0045 | [Model images and videos as one gallery](0045-model-images-and-videos-as-one-gallery.md) | 2026-09-25 |
| 0046 | [Use workspace and owner roots for path references](0046-use-workspace-and-owner-roots-for-path-references.md) | 2026-09-26 |
| 0047 | [Create ordinary listings from template snapshots](0047-create-ordinary-listings-from-template-snapshots.md) | 2026-09-27 |
| 0048 | [Dispatch batch AI through the existing runner](0048-dispatch-batch-ai-through-the-existing-runner.md) | 2026-09-27 |
| 0049 | [Keep the latest proposal in server cache](0049-keep-the-latest-proposal-in-server-cache.md) | 2026-09-27 |
| 0050 | [Give UI deploy precedence over AI work](0050-give-ui-deploy-precedence-over-ai-work.md) | 2026-09-27 |
| 0051 | [Bound uploads and inspect archive entries](0051-bound-uploads-and-inspect-archive-entries.md) | 2026-09-27 |
