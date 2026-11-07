"""The label rules: what a label the app saves becomes, and what refuses it.

A label is free-form text a seller tags a mockup template with, for finding it
later (spec *Labels*). The rules bind only labels the template does not already
hold. The template model takes any list of strings, so a hand-edited label
that breaks them still loads, still shows, and cannot block a save; a typo in a
label cannot affect a pixel. The Labels bar keeps a copy of these rules so its
field can explain them before anything is sent, and the messages here are what
it shows.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from etsy_listings.core.errors import RefusedError

MAX_LABEL_LENGTH = 30
MAX_LABELS = 10

# ASCII, as in the approved prototype (`template-labels/_RailScreen.tsx`), whose
# rule the Labels bar copies: the two must agree on what "letters" means.
_ALLOWED = re.compile(r"[a-z0-9 :-]+")


class TemplateLabelRefusedError(RefusedError):
    """A label the template did not already hold breaks a rule. The message
    names the rule in the words the seller reads."""


def _tidied(label: str) -> str:
    return " ".join(label.lower().split())


def _refusal(label: str) -> str | None:
    """Why ``label``, already tidied, cannot be saved; None when it can."""
    if len(label) > MAX_LABEL_LENGTH:
        return f"Labels can be up to {MAX_LABEL_LENGTH} characters"
    if _ALLOWED.fullmatch(label) is None:
        return "Letters, numbers, spaces, hyphens and colons only"
    group, colon, rest = label.partition(":")
    if colon and not (group.strip() and rest.strip() and ":" not in rest):
        return "Use one colon with text on both sides, like theme:christmas"
    return None


def _new_label(label: str) -> str:
    tidied = _tidied(label)
    refusal = _refusal(tidied)
    if refusal is not None:
        raise TemplateLabelRefusedError(refusal)
    return tidied


def saved_labels(labels: Iterable[str], *, held: Sequence[str]) -> list[str]:
    """``labels`` as a template that holds ``held`` saves them: each new label
    tidied and checked, every held one left as written, duplicates dropped.

    The count is a rule on new labels too, so a template over the limit by
    hand keeps saving and can lose labels, but takes no new one.
    """
    saved: dict[str, None] = {}
    for label in labels:
        saved[label if label in held else _new_label(label)] = None
    if len(saved) > MAX_LABELS and not saved.keys() <= set(held):
        raise TemplateLabelRefusedError(f"Templates hold up to {MAX_LABELS} labels")
    return list(saved)
