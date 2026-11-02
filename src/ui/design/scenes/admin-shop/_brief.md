Approved Admin prototype, reviewed 2026-10-30. Thirteen frames share one clickable Shop and Settings page with different starting states.

## What the prototype does

- Connected shops: Etsy and Printify shops read-only. Danger zone holds only Change currency, which opens a
  red warning modal (no conversion, existing listings keep their currency, shop sells in USD); Change stays
  disabled until "I understand prices won't be converted" is ticked. Confirming updates the row.
- Listing defaults: Print on demand / Custom. Print on demand shows its three values as text; Custom shows the
  three selectors in place. No Advanced settings expander. Production partner sits in "Fulfilment and
  policies" with shipping, returns, renewal and print provider, editable whatever the tier.
- Create links: shipping profile, return policy and production partner go to Etsy; preferred
  print provider goes to Printify. The prototype stands in for the other tab with a dialog; "Come back with a
  new one" adds an item to the list, marks it "· new", and offers "Use it" (it is never auto-selected).
- Info cards: every ⓘ toggles its popover; clicking elsewhere closes it.
- Any change shows Saving… then Saved.

Retired: directions A, B and C from round 2 and every shop-switching flow.

## Settings tab (_settings.tsx)

- AI time limits: whole-minute sliders, 1–15 per step and 5–60 for the run. The run minimum is enabled providers times the step limit, with a five-minute floor. Increasing the step limit or enabling a provider raises the run limit when needed; reducing either leaves the chosen run limit alone.
- Model discovery: Refresh lists shows a busy state, then refreshed options. Failure keeps saved choices and Account default available.
- Recovery frames cover disconnected shops, failed shop lookups, a settings revision conflict and an invalid settings file. Recovery actions simulate successful rereads; production must use server responses.

- Round 1's direction B, made live: AI providers as a numbered fallback chain. Drag a step by its handle (or
  arrow keys on the handle) to reorder; clicking a step's number turns it off and clicking the dash turns it
  back on (no switches; the last one on refuses with "At least one provider stays on");
  model and reasoning pick per provider; a model the CLI no longer offers shows "(not offered)" plus a warning
  until another is picked.
- Batch AI: a 1-8 slider with tick labels; saves when released.
- Market SEO scoring: one bar of six segments with draggable dividers (pointer or arrow keys, Shift for 5)
  sharing out 100%; dividers stacked by a 0% signal pick by drag direction. Reset to defaults.
  Weights are saved as whole percentages that add up to 100.
