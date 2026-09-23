from pathlib import Path


def edit(path, pairs):
    p = Path(path)
    t = p.read_text(encoding="utf-8")
    for old, new in pairs:
        assert t.count(old) == 1, (path, t.count(old), old[:70])
        t = t.replace(old, new)
    p.write_text(t, encoding="utf-8")


edit(
    "docs/prd.md",
    [
        (
            "| 69 | A design names an unnamed draft |",
            "| 70 | Naming writes it; nothing else withholds it | A named listing is written, full stop. Incompleteness is never a reason to withhold the file: no garment profile, no colours, no price source, no title, no lead, no images — all of them block *deployment* and none of them blocks the save. Before this, the price-source rule sat in `Listing` itself, so a seller could name a listing, attach a design and pick colours and still have nothing on disk, with the head explaining that the file would appear once they picked a plan. That is the tool withholding a file the seller plainly asked for, and it is the one incompleteness out of eight that behaved differently from the rest. The rule keeps its refusal — `plan` and `apply` still stop, as a `Blocked` from the stage that needs a price — and the banner keeps its sentence; only the write stops depending on it. What still refuses a write is a document that is *malformed* rather than incomplete: a title over Etsy's limit, a price in the wrong currency, a `media` entry naming a colour the listing does not sell. Those come back as `field_errors` on the field that caused them, as they already did. |\n"
            "| 69 | A design names an unnamed draft |",
        ),
        (
            "With this, the ordinary create flow is: open the editor, pick a design, pick a price source. |",
            "With this, and #70, the ordinary create flow is one gesture: open the editor and pick a design. |",
        ),
    ],
)

edit(
    "AGENTS.md",
    [("69 numbered product decisions in its appendix.", "70 numbered product decisions in its appendix.")],
)

edit(
    "docs/phase-5-listings-ui.md",
    [
        (
            """the model strict: **a named listing is written the moment it has a price
source, and not before.** Every other field tolerates an empty value, so a
listing can have a name, a design, a garment profile and colours and still not
exist on disk. The page head's meta line says so in those words rather than a
bland "Not saved", and names the price source as the one thing standing in the
way when it is.""",
            """the model strict: **a named listing is written the moment it has a price
source, and not before.** Every other field tolerates an empty value, so a
listing can have a name, a design, a garment profile and colours and still not
exist on disk. The page head's meta line says so in those words rather than a
bland "Not saved", and names the price source as the one thing standing in the
way when it is.

**Amended (PRD 70): naming writes it, and nothing else withholds it.** The
price-source rule was the only incompleteness out of eight that blocked the
*file* rather than only the deploy, which made it the one a seller met as the
tool refusing to save their work. It moved out of `Listing` entirely — the
model now describes an incomplete listing without complaint, `plan` and
`apply` refuse through `gates.check_price_source` like every other
prerequisite, and the banner keeps the sentence it always had. A write is
still refused for a document that is *malformed*: those are `field_errors`,
and they name a field.""",
        ),
        (
            """**Incompleteness is the issues banner's job, not a 400's.** Every refusal
`_stub()` used to raise is a block issue instead: no design selected, no
garment profile selected, no pricing plan and no prices. `_stub()` is gone.""",
            """**Incompleteness is the issues banner's job, not a 400's.** Every refusal
`_stub()` used to raise is a block issue instead: no design selected, no
garment profile selected, no pricing plan and no prices. `_stub()` is gone.
PRD 70 finished the thought: none of those three withholds the file either.""",
        ),
    ],
)

edit(
    "docs/getting-started.md",
    [
        (
            """design's filename without its extension — so creating a listing is: open the
editor, pick a design, pick a price source. A listing that already has a name
keeps it; changing its artwork never renames it.""",
            """design's filename without its extension — so creating a listing is: open the
editor and pick a design. A listing that already has a name keeps it, and one
you have started typing a name for keeps that; changing the artwork never
renames a listing.

The file is written as soon as it has a name. Everything still missing — a
garment profile, colours, a price source, a title, a lead, an image — is
listed in the issues banner and blocks **deploying** the listing, never
saving it.""",
        ),
    ],
)
print("ok")
