# ADR-0053: Resolve artwork once per listing

Status: accepted; implemented by the [multi-artwork plan](../features/multi-artwork-20260928/plan.md).

A listing's `design:` is one map. Its reserved base is either `default` or the
`on-light`/`on-dark` pair; every other key is an enabled garment colour whose
file overrides the base. Which colour is light or dark stays a garment-profile
fact. One pure function, `core/config/artwork.py`, turns the map, a depicted
colour and the profile's tones into either a file or the reason there is none.
Listing validation, the render and Printify stages, the editor's previews and
the AI workflow all ask it, and a failed resolution reaches a stage as
`Blocked`, never as an exception. An artwork group, whether a render layer's
design identity or a Printify print area, is keyed by the resolved file's
content hash.

This replaces a rule with three sources of artwork: a separate
`listing.artwork` colour map, a template or placement override, and the tone
key. The template override was never passed to the Printify stage, so a mockup
could show a different print from the shirt that shipped. Resolving once at
listing level makes the file shown the file printed, and lets validation, the
API and the engine give identical answers rather than three copies of the
rule. Keying groups by content hash means reshaping the map without changing
what any garment prints, or renaming a file, produces no plan, which keeps
apply idempotent. Keying by source key (`default`, `on-dark`, a colour) would
turn every reshape into a re-render and a Printify update.

Rejected: rewriting the engine's `DesignPlacement` in place, which leaves the
editor and validation guessing; keeping template overrides as a rare escape
hatch, which is exactly the mismatch this removes; inferring tone from
Printify, whose catalog carries no colour value in this integration. The
[multi-artwork specification](../features/multi-artwork-20260928/spec.md) owns
the detailed requirements, including the blockers, the representative artwork
and the editor interactions. The superseded rule is A14 and PRD 30 in the
frozen [original plan](../history/implementation-plan.md) and
[PRD](../history/prd.md).

First recorded 2026-09-28.
