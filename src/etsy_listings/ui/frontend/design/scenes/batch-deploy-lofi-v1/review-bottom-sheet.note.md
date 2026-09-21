# Two reads of the stages, one per question

The page answers "what will this run do?"; the sheet answers "what will this listing do?".
Same five stages from `engine/stages/__init__.py`, shown twice because the questions differ.

## Top of the page: the run checklist

One row per stage, and inside it every listing that stage covers, each with a checkbox.
Nothing is ticked before apply. During the run each listing is checked off its stage as that
stage finishes for it, and the row counts "3 of 4 done" - so the checklist tracks real
progress even though `apply_listings` walks listing by listing rather than stage by stage.
Click any listing chip to open its sheet.

## The bottom sheet: one listing's step strip

Open a row and it carries that listing's step strip - stages filled if they run, hollow if
skipped, each with its reason and actions - plus the before/after. The same experience
`src/pages/deploy/StepStrip.tsx` gives an individual deployment, unchanged. On
[the applying frame](goto:batch-deploy-lofi-v1/review-applying) the same strip wears live state:
done, running, not yet.

A deletion walks `RetractStage()` alone (`lifecycle.walk`), so its sheet shows one stage, not
five, and it gets its own checklist row - "Remove from Etsy · 1 listing".

## What we tried

[The stage matrix](goto:archive/batch-deploy-review-stage-matrix) put six listings against
five stage columns - correct, and it read as a spreadsheet; retired.
[A strip per listing](goto:batch-deploy-lofi-v1/review-stages-per-listing) repeated the stage
names six times; [one strip for the whole run](goto:batch-deploy-lofi-v1/review-stages-whole-run)
named them once and hid which listing did what. The checklist above is that run-level read
rebuilt to name its listings and carry per-listing progress.
