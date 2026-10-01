"""Application operations: workflows the server and the CLI share.

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
    ``edit_listing``: an editor save's locked read-merge-write.
``listing_creation``
    ``create_listing``, ``write_listing``.
``listing_identity``
    ``rename_listing``, ``delete_listing`` -> ``Deletion``: everything keyed
    by a listing's name follows or goes with it.
``pricing_plans``
    ``load_candidate_pricing_plans``, ``pricing_plan_options`` /
    ``PricingPlanOption``, ``pricing_plan_ref``.
``mockup_templates``
    The calibrator: ``list_templates`` -> ``TemplateOverview``,
    ``colour_report``, ``assign_kind``, ``read_config`` / ``save_config``,
    ``template_photo``, ``template_swatch``, and the preview scene --
    ``saved_preview`` / ``unsaved_preview`` -> ``PreviewScene``,
    ``compose_preview``, ``scaled``. Images arrive decoded from the caller.
``refusals``
    ``ListingMissing``, ``ListingNameTaken``, ``PublishedListingDeletion``,
    ``InvalidListing``, ``field_errors_of``; the calibrator's ``Template*``
    refusals.
``dependencies``
    ``ListingLocks``, ``ListingAiRuns`` / ``StoppableRun``, ``EtsyStates``:
    what operations take the UI process's write locks, AI run registry and
    Etsy state memo through while those live in the server.
"""
