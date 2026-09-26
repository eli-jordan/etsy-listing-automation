"""Which design prints on which colour. A14, and the one rule two stages share.

Two stages put a design somewhere, and they must agree about which one: the
render stage composites it onto a mockup photo, and the product stage ships it
to Printify as the actual print file. A listing whose mockup shows the light
artwork and whose shirt arrives with the dark one is the failure this module
exists to make impossible -- and it is not a failure any test of either stage
alone would catch, because each stage would be self-consistent.

It lived as a private function inside the render stage, which the product
stage imported through the underscore. The leading underscore was the module
saying "don't", and there was nowhere else to go.

Beside ``gates`` rather than inside either stage, for the same reason ``gates``
is: it is stage-level knowledge that no single stage owns.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from etsy_listings.config.garment_profile import GarmentProfile
from etsy_listings.config.listing import Listing
from etsy_listings.engine.lock import hash_file
from etsy_listings.workspace.workspace import Workspace


class ArtworkResolutionError(ValueError):
    """Names *which* key was asked for and *who* asked for it.

    Without both, the message sends you to the wrong file. A template with
    ``artwork: on-light`` over a single-file design used to report only
    "colour 'white' needs an artwork but none resolves", which reads as a
    problem with the colour or the listing -- while the demand actually came
    from the template, and ``on-light`` appeared nowhere in the message.
    """

    def __init__(
        self,
        colour: str | None,
        tone: str | None,
        available: list[str],
        *,
        wanted: str | None = None,
        source: str = "",
    ) -> None:
        detail = f"colour {colour!r}" if colour is not None else "this template"
        tone_note = f" (tone: {tone})" if tone else ""
        if wanted is not None:
            super().__init__(
                f"{detail}{tone_note}: {source} asks for artwork {wanted!r}, which the "
                f"design does not have -- it offers {available!r}. Add {wanted!r} to the "
                f"listing's design:, or remove the override."
            )
        else:
            super().__init__(
                f"{detail}{tone_note} needs an artwork but none resolves -- design offers "
                f"{available!r}; add a listing.artwork override or a matching key"
            )


@dataclass(frozen=True)
class ArtworkGroup:
    """One design, and the garment colours it prints on.

    Colours rather than Printify variant ids: which ink a colour gets is a
    fact about the listing, and turning it into ids is the product stage's
    business. A group per artwork rather than one print area for everything,
    because PRD 30's ``on-light``/``on-dark`` split is exactly this -- two
    files on one product, partitioned by colour. A single-artwork listing is
    simply the one-group case.
    """

    artwork: str
    design: Path
    design_hash: str
    colours: tuple[str, ...]


@dataclass(frozen=True)
class DesignPlacement:
    """A listing's design map, resolved: which file, and which colour gets it.

    Built once per listing per stage and passed around, rather than each
    caller re-deriving it -- the answer that gets hashed has to be the answer
    that gets rendered and the answer that gets printed.
    """

    listing: Listing
    profile: GarmentProfile
    paths: dict[str, Path]
    """Artwork key -> the design file it names, resolved through
    :meth:`Workspace.resolve_ref` (PRD 73), so a ``design:`` ref cannot escape
    the root."""

    @classmethod
    def resolve(
        cls, workspace: Workspace, listing_name: str, listing: Listing, profile: GarmentProfile
    ) -> DesignPlacement:
        listing_dir = workspace.listing_dir(listing_name)
        return cls(
            listing=listing,
            profile=profile,
            paths={
                artwork: workspace.resolve_ref(ref, listing_dir=listing_dir)
                for artwork, ref in listing.design.items()
            },
        )

    def artwork_for(self, colour: str | None, *, template_override: str | None = None) -> str:
        """Resolution order (docs/multi-placement-rendering.md item 2):
        1. ``listing.artwork[colour]`` -- explicit per-design override, wins even
           over the template's own override (deliberately -- see the doc).
        2. The template/placement's own ``artwork`` override.
        3. ``on-{profile.colors[colour]}``, if that key exists in the design map.
        4. The design map's sole key, if it has exactly one entry.
        """
        keys = list(self.listing.design.keys())
        key_set = set(keys)

        candidate: str | None = None
        source = ""
        if colour is not None and colour in self.listing.artwork:
            candidate, source = self.listing.artwork[colour], f"the listing's artwork[{colour!r}]"
        elif template_override is not None:
            candidate, source = template_override, "the template's own artwork: override"
        elif colour is not None and colour in self.profile.colors:
            toned = f"on-{self.profile.colors[colour]}"
            if toned in key_set:
                candidate, source = toned, f"the garment profile's colors[{colour!r}]"

        if candidate is None and len(keys) == 1:
            candidate, source = keys[0], "the design's sole key"

        if candidate is None or candidate not in key_set:
            tone = self.profile.colors.get(colour) if colour is not None else None
            raise ArtworkResolutionError(
                colour, tone, sorted(keys), wanted=candidate, source=source
            )
        return candidate

    def design_for(self, colour: str | None, *, template_override: str | None = None) -> Path:
        return self.paths[self.artwork_for(colour, template_override=template_override)]

    def group_by_artwork(self, colours: Sequence[str]) -> tuple[ArtworkGroup, ...]:
        """Partition ``colours`` by which design file prints on them.

        Deduped in first-seen order, so the print areas come out in the order
        the listing's colours were written and a diff of them stays legible.
        """
        by_artwork: dict[str, list[str]] = {}
        for colour in dict.fromkeys(colours):
            by_artwork.setdefault(self.artwork_for(colour), []).append(colour)

        return tuple(
            ArtworkGroup(
                artwork=artwork,
                design=self.paths[artwork],
                design_hash=hash_file(self.paths[artwork]),
                colours=tuple(grouped),
            )
            for artwork, grouped in by_artwork.items()
        )
