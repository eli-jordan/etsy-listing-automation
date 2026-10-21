"""Application operations: workflows the server and the CLI share, and the
reusable operations behind the CLI's wizards.

ADR-0052 and the module-structure specification: an operation takes
application inputs and its dependencies, coordinates domain modules --
locks, read/merge/write, the stores a change touches -- and answers with a
domain result or a typed refusal. It knows no HTTP status, request object or
terminal. Domain rules stay where they are (``config/listing_validation.py``
for a listing's completeness, ``engine/status.py`` for its status); an
operation applies them rather than restating them.

Import each module directly; this package re-exports nothing, so a caller's
import names the module it depends on. Public interfaces:

``listing_reads``
    ``read_listing``, ``describe_draft`` -> ``ListingView``;
    ``list_listings``, ``listing_row`` -> ``ListingRow``; ``pricing_summary``
    (shared with listing templates) -> ``PricedSize``; ``Priced``.
``listing_edits``
    ``edit_listing``: an editor save's patch merged into ``listing.yaml``.
``listing_creation``
    ``create_listing``; the ``new`` wizard's stub --
    ``load_template_kind``, ``build_media_entries``, ``build_listing_stub``,
    ``validate_listing_stub``.
``listing_identity``
    ``rename_listing``, ``delete_listing`` -> ``Deletion``: everything keyed
    by a listing's name follows or goes with it (``core.listing_artifacts``).
``pricing_plans``
    ``load_candidate_pricing_plans``, ``pricing_plan_options`` /
    ``PricingPlanOption``, ``pricing_plan_ref``; a starting plan from live
    costs -- ``create_starting_pricing_plan`` -> ``StartingPricingPlan``,
    built from ``compute_starting_prices`` and ``write_pricing_plan``.
``garment_profiles``
    ``filter_blueprints_by_category``, ``local_blueprint_keys``,
    ``ensure_garment_profile`` -> ``SavedGarmentProfile``,
    ``listing_colours``, ``resolve_colour_slugs``, and the pieces of a
    profile (``build_garment_profile``, ``garment_profile_slug_for``,
    ``sort_sizes``, ``write_garment_profile_if_absent``).
``credentials``
    ``Credential`` (``PRINTIFY``, ``ETSY_APP_KEY``, ``ANTHROPIC``),
    ``stored`` / ``stored_values`` (environment over ``.env``), ``store``,
    ``verify_printify_token``, ``verify_etsy_app_key``,
    ``credential_status`` -> ``CredentialStatus`` / ``TokenSummary``, and
    the Etsy grant either side of the browser -- ``begin_etsy_sign_in`` ->
    ``EtsySignIn``, ``complete_etsy_sign_in`` -> ``SignedIn``.
``workspace_setup``
    ``create_directories``, ``sync_packaged_prompts`` -> ``PackagedPrompt``,
    ``read_shop_document``, ``SetupAnswers`` / ``POD_DEFAULTS``,
    ``shop_yaml_document``, ``render_shop_yaml``, ``save_setup``.
``shop_discovery``
    ``select_shop`` -> ``ShopSelection``; ``etsy_access`` -> ``EtsyAccess``,
    ``find_etsy_shop`` -> ``FoundShop``, ``lookup_etsy_shop`` ->
    ``ShopLookup``, ``return_policy_options`` -> ``ReturnPolicyOptions``,
    ``policy_terms``, ``currency_default``.
``mockup_templates``
    The calibrator: ``list_templates`` -> ``TemplateOverview``,
    ``colour_report``, ``assign_kind``, ``read_config`` / ``save_config``,
    ``save_calibration`` commits config and mask edits with an expected revision
    and idempotent request ID; ``template_photo``, ``template_swatch``, and the preview scene --
    ``saved_preview`` / ``unsaved_preview`` -> ``PreviewScene``,
    ``compose_preview``, ``scaled``. Images arrive decoded from the caller.
``preparation_views``
    Read-only authoring readiness and per-placement mask access.
``prepared_previews``
    CPU previews acquire one immutable map generation for the whole scene and
    return exact PNG bytes with a canonical scene identity for promotion.
``calibration_designs``
    The calibrator's uploaded test designs: ``save_uploaded_design`` (name
    and image checks, then the write), ``uploaded_design``.
``listing_template_library``
    ``list_listing_templates`` -> ``ListingTemplateCard``,
    ``read_listing_template`` / ``draft_listing_template`` ->
    ``ListingTemplateView``, ``create_listing_template`` /
    ``edit_listing_template`` -> ``TemplateSave``,
    ``rename_listing_template``, ``delete_listing_template``.
``batch_staging``
    ``stage_upload``, ``read_staging``, ``edit_staging``, ``cancel_staging``,
    ``staged_upload``: an upload's bytes and filenames arrive as
    ``batches.Upload`` streams; limits and archive safety stay ``batches``'.
``batch_workflow``
    ``confirm_batch``, ``retry_batch_row``, ``retry_batch``,
    ``cancel_batch``, ``resume_batch``, ``delete_batch``, ``rename_batch``,
    ``mark_reviewed``, ``read_batch``, ``batch_row_upload``,
    ``listing_batch`` -> ``ListingMembership``, ``recent_batches`` ->
    ``RecentBatch``, ``row_proposal``.
``refusals``
    ``ListingMissing``, ``ListingNameTaken``, ``PublishedListingDeletion``,
    ``InvalidListing``, ``field_errors_of``; the calibrator's ``Template*``
    refusals, ``DesignUploadRefused``, ``CalibrationDesignMissing``;
    ``ListingTemplateMissing``, ``ReservedListingTemplateName``,
    ``ListingTemplateSourceRefused``; ``StagingMissing``, ``StagedRowMissing``,
    ``BatchMissing``, ``BatchRowMissing``, ``BatchRowUploadMissing``,
    ``NothingToRetry``, ``BatchRowNotReviewable``, ``AiDraftingBlocked``;
    ``AiRunRefused`` -- ``ListingDeploying``, ``ListingDraftingInBatch``,
    ``AiNotReady``; ``ProposalMissing``, ``ProposalReplaced``;
    ``ReviewedPlanRefused``.
``workspace_locks``
    ``WorkspaceLocks``: the per-listing-template write locks every
    template check-then-write holds, one instance per application runtime;
    ``mockup_template(workspace, name)`` uses calibration storage's independent
    process-wide template lock for saved calibration and map publication.
``deploy``
    Deployment runs -- registry, FIFO executor and their event log; see the
    subpackage's own initialiser.
``ai``
    AI runs, the batch AI queue, readiness and proposals -- the coordinator,
    registry, runner and their events; see the subpackage's own initialiser.
``preparation``
    Durable Marigold authoring jobs through ``preparation.coordinator.Preparations``;
    public request/result models and host runtime/worker dependencies. The
    subpackage documents its protected journal, prediction and execution modules.
``dependencies``
    The seams a host fills: ``EtsyStates`` (the UI process's Etsy state memo,
    which stays in the server), ``ContextFactory`` (a deployment run's
    engine context) and ``MarketClientFactory`` / ``default_market_client``
    (the AI runs' Etsy market client).

Every module above is public. The implementation-only modules are inside
``deploy`` (``executor``, ``review``) and ``ai`` (``runner``), named in
their initialisers and protected by Import Linter so only their coordinator
imports them.
"""
