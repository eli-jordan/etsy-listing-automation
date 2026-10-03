# Retired as drawn - the idea came back

This read named the five stages once for the whole run and counted listings behind a "Which"
disclosure. Two things were wrong with it: the listings were hidden, and a rolled-up stage
carries no progress - "Etsy images" cannot read _done_ run-wide until the last listing
finishes, because `apply_listings` walks listing by listing.

Both are fixed on [the live review page](goto:batch-deploy-lofi-v1/review-bottom-sheet): the run
checklist names every listing inside its stage row and checks each one off as that stage
finishes for it, and [the applying frame](goto:batch-deploy-lofi-v1/review-applying) shows it
mid-run. The per-listing answer moved to the bottom sheet, where it matches the individual
deploy page.

This frame is history; the shape it argued for is live.
