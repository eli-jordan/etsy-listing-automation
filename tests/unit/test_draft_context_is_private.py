"""The draft escape hatch stays where it was decided.

``Listing.draft`` waives one rule -- "set ``pricing_plan`` or ``prices``" -- for
a candidate the listings editor is still assembling. That waiver is safe only
because it is unreachable: every path that *writes* a listing goes through a
plain ``model_validate``, so nothing incomplete can reach disk. A second caller
of the context key would quietly end that, and nothing else would fail.

A grep, for the same reason ``test_no_bare_cv2.py`` is one: the rule is about
where a string may appear, and no runtime test can see the file that does not
call it yet.
"""

from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).parent.parent.parent / "src" / "etsy_listings"
OWNER = SRC / "config" / "listing.py"
KEY = "unsaved_draft"


def test_only_the_listing_model_knows_the_draft_context_key() -> None:
    offenders = [
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if path != OWNER and KEY in path.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        f"{KEY!r} appears outside config/listing.py: {offenders}. "
        f"Ask for a draft through Listing.draft()/empty_draft() -- the key is "
        f"private so that waiving the rule stays one decision, made in one place."
    )
