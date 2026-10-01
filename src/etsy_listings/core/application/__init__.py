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

``pricing_plans``
    ``load_candidate_pricing_plans``, ``pricing_plan_options`` /
    ``PricingPlanOption``, ``pricing_plan_ref``.
``listing_creation``
    ``create_listing``, ``write_listing``.
``refusals``
    ``ListingMissing``, ``ListingNameTaken``, ``PublishedListingDeletion``,
    ``InvalidListing``, ``field_errors_of``.
``dependencies``
    ``ListingLocks``: the interface listing operations take the UI process's
    write locks through until they move into core.
"""
