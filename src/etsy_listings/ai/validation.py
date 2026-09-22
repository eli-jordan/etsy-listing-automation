"""Normalize a provider's raw JSON, then hard-validate it against the agreed
proposal contract before any UI response ever sees it (AI SEO implementation
plan, PR3, item 5; `docs/ui-listing-seo-interactions.md` section 8).

Two passes, always in this order:

1. **Normalize** (:func:`normalize_raw_proposal`) -- fix harmless formatting a
   model commonly produces (surrounding whitespace, a wrapping quote pair
   around an otherwise-fine string, doubled interior spaces) so it is never
   mistaken for a genuine content problem. Purely cosmetic: it never changes
   how many entries a list has, never drops or reorders one, and never
   touches ``intent``/``used_in`` enum values.
2. **Hard-validate** (:func:`validate_proposal`) -- exact counts, Etsy's
   title/tag limits (imported from `config/listing.py` rather than
   redeclared, per this codebase's "mirror rather than reinvent" rule for
   anything the listing editor already enforces), tag uniqueness, rationale
   shape, and the agreed affiliation/content checks. Every reason is
   collected, never just the first: the one allowed same-provider repair
   (PR4) is handed the whole list, and a repair prompt built from a single
   reason would waste that one attempt discovering the rest one at a time.

Trademark findings never raise :class:`ProposalValidationError`. They are
appended to the built proposal's own ``warnings`` as
:class:`~etsy_listings.ai.models.ProposalWarning` entries with
``kind="trademark"`` -- the settled decision is that these are warnings, not
a hard refusal, because accurate copy is allowed to name a real product,
character, or brand (`seo_prompt.md`: "Do not exclude an accurate,
buyer-relevant name merely because it may be a trademark"). The watchlist
below is deliberately narrow and deliberately excludes ordinary garment/print
brands (Comfort Colors, Gildan, Bella+Canvas, ...): those are expected,
legitimate mentions supplied as listing fact, not third-party IP risk, and
warning on every listing that correctly names its own garment would train
sellers to ignore the warning.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from etsy_listings.ai.models import PhraseRationale, ProposalWarning, SeoProposal
from etsy_listings.config.listing import MAX_TAG_LENGTH, MAX_TITLE_LENGTH

ALLOWED_INTENTS = frozenset({"core_product", "bottom_of_funnel", "style"})
ALLOWED_USED_IN = frozenset({"title", "tags", "description_lead"})

AFFILIATION_TERMS = frozenset(
    {
        "official",
        "officially",
        "authentic",
        "authentically",
        "licensed",
        "licenced",
        "certified",
        "endorsed",
        "endorsement",
        "sponsored",
        "affiliated",
        "affiliate",
        "authorized",
        "authorised",
    }
)
"""Words `seo_prompt.md` already tells a model never to use "simply to
increase search traffic," and never to use at all unless affiliation status
is explicitly supplied. Nothing in `SeoRequest` carries such a supplied
status (there is no listing fact for "we are an authorized reseller"), so
any occurrence is unconditionally wrong for this feature and is refused
outright rather than only warned about."""

TRADEMARK_WATCHLIST = frozenset(
    {
        "disney",
        "marvel",
        "star wars",
        "pokemon",
        "pokémon",
        "harry potter",
        "hogwarts",
        "nike",
        "adidas",
        "gucci",
        "hello kitty",
        "minecraft",
        "nintendo",
        "pixar",
        "barbie",
    }
)
"""A small, curated set of well-known third-party names -- not garment
brands, and not exhaustive. Its only job is to catch the common case and
prompt a human second look; it is not a trademark-clearance system."""

_WORD_RE = re.compile(r"[A-Za-z']+")
_WRAPPING_QUOTE_PAIRS: dict[str, str] = {
    '"': '"',
    "'": "'",
    "“": "”",
    "‘": "’",
}


class ProposalValidationError(ValueError):
    """Every reason a raw proposal failed hard validation, collected rather
    than reported one at a time. ``reasons`` is what a repair prompt
    (`ai/prompt.py.build_repair_prompt`) is built from; ``str(error)`` joins
    them for a log line or a generic caller that only wants one message."""

    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons: tuple[str, ...] = tuple(reasons)
        super().__init__("; ".join(self.reasons))


# ----------------------------------------------------------------- normalize


def _normalize_text(value: str) -> str:
    """Trim, drop one wrapping pair of matching quote characters, and
    collapse interior whitespace runs (including newlines a model sometimes
    inserts mid-sentence) to a single space. Applied only to the short,
    single-line fields (titles, tags, leads, rationale phrase/reason,
    warnings) -- never to ``observed_text``, whose own line breaks are part
    of what it is disclosing."""
    trimmed = value.strip()
    if len(trimmed) >= 2 and _WRAPPING_QUOTE_PAIRS.get(trimmed[0]) == trimmed[-1]:
        trimmed = trimmed[1:-1].strip()
    return re.sub(r"\s+", " ", trimmed)


def _normalize_string_list(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    return [_normalize_text(item) if isinstance(item, str) else item for item in value]


def _normalize_rationale_item(item: Any) -> Any:
    if not isinstance(item, Mapping):
        return item
    result = dict(item)
    for key in ("phrase", "reason"):
        value = result.get(key)
        if isinstance(value, str):
            result[key] = _normalize_text(value)
    return result


def normalize_raw_proposal(raw: Mapping[str, Any]) -> dict[str, Any]:
    """A new dict with harmless formatting fixed; ``raw`` itself is untouched.

    Never raises, and never changes list lengths or enum-like values --
    anything that needs a structural decision is hard validation's job, not
    this pass's.
    """
    normalized: dict[str, Any] = dict(raw)
    for field_name in ("titles", "tags", "description_leads", "warnings"):
        normalized[field_name] = _normalize_string_list(normalized.get(field_name))
    rationale = normalized.get("rationale")
    if isinstance(rationale, list):
        normalized["rationale"] = [_normalize_rationale_item(item) for item in rationale]
    observed_text = normalized.get("observed_text")
    if isinstance(observed_text, str):
        normalized["observed_text"] = observed_text.strip()
    return normalized


# ------------------------------------------------------------- hard validate


def _check_string_list(
    value: Any,
    name: str,
    *,
    expected_count: int,
    max_length: int | None = None,
    unique: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        return [f"{name}: expected a list of {expected_count} strings"]
    reasons: list[str] = []
    if len(value) != expected_count:
        reasons.append(f"{name}: expected exactly {expected_count} entries, got {len(value)}")
    seen: dict[str, str] = {}
    for i, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            reasons.append(f"{name}[{i}]: must be a non-empty string")
            continue
        if max_length is not None and len(item) > max_length:
            reasons.append(
                f"{name}[{i}]: {len(item)} characters, over Etsy's {max_length}-character limit"
            )
        if unique:
            key = item.casefold()
            if key in seen:
                reasons.append(
                    f"{name}: entries must be unique ignoring case ({item!r} repeats {seen[key]!r})"
                )
            else:
                seen[key] = item
    return reasons


def _check_rationale(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["rationale: expected a list of 7 entries"]
    reasons: list[str] = []
    if len(value) != 7:
        reasons.append(f"rationale: expected exactly 7 entries, got {len(value)}")
    for i, item in enumerate(value):
        if not isinstance(item, Mapping):
            reasons.append(f"rationale[{i}]: expected an object")
            continue
        phrase = item.get("phrase")
        if not isinstance(phrase, str) or not phrase.strip():
            reasons.append(f"rationale[{i}].phrase: must be a non-empty string")
        reason_text = item.get("reason")
        if not isinstance(reason_text, str) or not reason_text.strip():
            reasons.append(f"rationale[{i}].reason: must be a non-empty string")
        intent = item.get("intent")
        if intent not in ALLOWED_INTENTS:
            reasons.append(
                f"rationale[{i}].intent: {intent!r} is not one of {sorted(ALLOWED_INTENTS)}"
            )
        used_in = item.get("used_in")
        if not isinstance(used_in, list) or any(v not in ALLOWED_USED_IN for v in used_in):
            reasons.append(
                f"rationale[{i}].used_in: must be a list drawn from {sorted(ALLOWED_USED_IN)}"
            )
    return reasons


def _check_warnings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["warnings: expected a list of strings"]
    return [
        f"warnings[{i}]: must be a non-empty string"
        for i, item in enumerate(value)
        if not isinstance(item, str) or not item.strip()
    ]


def _check_observed_text(value: Any) -> list[str]:
    if not isinstance(value, str):
        return ["observed_text: expected a string"]
    return []


def _words(text: str) -> set[str]:
    return {w.casefold() for w in _WORD_RE.findall(text)}


def _check_affiliation(normalized: Mapping[str, Any]) -> list[str]:
    """The agreed hard affiliation/content check (implementation plan,
    "Validation"). Every hit across a field is named in one reason rather
    than one reason per word, since a repair prompt only needs to know which
    words to remove."""
    reasons: list[str] = []
    for field_name in ("titles", "description_leads"):
        values = normalized.get(field_name)
        if not isinstance(values, list):
            continue
        for i, item in enumerate(values):
            if not isinstance(item, str):
                continue
            hits = _words(item) & AFFILIATION_TERMS
            if hits:
                reasons.append(
                    f"{field_name}[{i}]: claims affiliation/authenticity "
                    f"({', '.join(sorted(hits))}) without it being supplied"
                )
    tags = normalized.get("tags")
    if isinstance(tags, list):
        tag_hits: set[str] = set()
        for item in tags:
            if isinstance(item, str):
                tag_hits |= _words(item) & AFFILIATION_TERMS
        if tag_hits:
            reasons.append(
                f"tags: claims affiliation/authenticity ({', '.join(sorted(tag_hits))}) "
                f"without it being supplied"
            )
    return reasons


def _hard_validation_reasons(normalized: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    reasons += _check_string_list(
        normalized.get("titles"), "titles", expected_count=3, max_length=MAX_TITLE_LENGTH
    )
    reasons += _check_string_list(
        normalized.get("tags"),
        "tags",
        expected_count=20,
        max_length=MAX_TAG_LENGTH,
        unique=True,
    )
    reasons += _check_string_list(
        normalized.get("description_leads"), "description_leads", expected_count=3
    )
    reasons += _check_rationale(normalized.get("rationale"))
    reasons += _check_warnings(normalized.get("warnings"))
    reasons += _check_observed_text(normalized.get("observed_text"))
    reasons += _check_affiliation(normalized)
    return reasons


# --------------------------------------------------------------- trademark


def _trademark_hits(text: str) -> set[str]:
    lowered = text.casefold()
    return {term for term in TRADEMARK_WATCHLIST if term in lowered}


def _trademark_warnings(
    titles: Sequence[str], tags: Sequence[str], leads: Sequence[str]
) -> tuple[ProposalWarning, ...]:
    hits: set[str] = set()
    for text in (*titles, *tags, *leads):
        hits |= _trademark_hits(text)
    return tuple(
        ProposalWarning(
            message=(
                f"mentions {term.title()!r} -- on the trademark watch list; double-check "
                f"this is accurate and does not imply affiliation, sponsorship, or "
                f"endorsement."
            ),
            kind="trademark",
        )
        for term in sorted(hits)
    )


# ------------------------------------------------------------------- build


def _build_proposal(normalized: Mapping[str, Any]) -> SeoProposal:
    titles = tuple(normalized["titles"])
    tags = tuple(normalized["tags"])
    leads = tuple(normalized["description_leads"])
    rationale = tuple(
        PhraseRationale(
            phrase=item["phrase"],
            intent=item["intent"],
            reason=item["reason"],
            used_in=tuple(item["used_in"]),
        )
        for item in normalized["rationale"]
    )
    provider_warnings = tuple(
        ProposalWarning(message=message, kind="general") for message in normalized["warnings"]
    )
    warnings = provider_warnings + _trademark_warnings(titles, tags, leads)
    return SeoProposal(
        titles=(titles[0], titles[1], titles[2]),
        tags=tags,
        description_leads=(leads[0], leads[1], leads[2]),
        rationale=rationale,
        warnings=warnings,
        observed_text=normalized["observed_text"],
    )


def validate_proposal(raw: Mapping[str, Any]) -> SeoProposal:
    """Normalize, then hard-validate ``raw`` -- a provider's already-JSON-
    decoded output -- into a complete :class:`SeoProposal`, or raise
    :class:`ProposalValidationError` naming every reason it cannot.

    Never partially builds a proposal: a caller either gets the full,
    contract-complete shape or an exception, so nothing downstream can
    mistake a still-invalid response for one that is safe to show
    (`docs/ui-listing-seo-interactions.md` section 8: "Do not reveal a
    partial proposal as though it were safe to use").
    """
    normalized = normalize_raw_proposal(raw)
    reasons = _hard_validation_reasons(normalized)
    if reasons:
        raise ProposalValidationError(reasons)
    return _build_proposal(normalized)
