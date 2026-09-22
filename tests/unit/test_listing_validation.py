"""The listings UI's local-only health check (phase 5): does a listing's own
configuration make sense, without asking Etsy or Printify anything.

Table-driven, and pure -- no workspace, no fake client. Everything that needs
a real file on disk (design resolution) uses `tmp_path` the same way
`test_product_gates.py` does; everything else is built from in-memory
`Listing`/`GarmentProfile` objects.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from etsy_listings.config.description import DescriptionConfig
from etsy_listings.config.garment_profile import BlueprintRef, GarmentProfile, PrintArea
from etsy_listings.config.listing import EtsyListingConfig, Listing, TemplateMediaEntry
from etsy_listings.config.listing_validation import (
    Issue,
    TemplateInfo,
    check_lifecycle_verb,
    check_listing,
    check_listing_yaml_present,
)

PROFILE = GarmentProfile(
    blueprint=BlueprintRef(brand="Comfort Colors", model="1717"),
    print_provider="Monster Digital",
    placeholder="front",
    print_area=PrintArea(width=100, height=100),
    sizes=["S", "M", "L"],
    colors={"black": "dark", "white": "light"},
)

FLAT_LAY = TemplateInfo(kind="colour-matrix", colours=frozenset({"black", "white"}))
CHART = TemplateInfo(kind="multiple", colours=frozenset())
SIZING = TemplateInfo(kind="single", colours=frozenset())


def _design(tmp_path: Path, size: tuple[int, int] = (100, 100)) -> Path:
    path = tmp_path / "design.png"
    Image.new("RGBA", size, (0, 0, 0, 0)).save(path)
    return path


def _listing(
    *,
    garment_profile: str = "comfort-colors-1717",
    colors: list[str] | None = None,
    media: list[TemplateMediaEntry | str] | None = None,
    title: str = "Take A Hike Tee",
    description: str = "A retro sunset scene.",
    tags: list[str] | None = None,
    variation_images: str | None = None,
    lifecycle: str | None = None,
) -> Listing:
    return Listing(
        garment_profile=garment_profile,
        design="designs/take-a-hike.png",
        colors=colors if colors is not None else ["black", "white"],
        brief="A retro sunset mountain scene.",
        prices={"S": "349 NOK"},
        media=media
        if media is not None
        else [TemplateMediaEntry(template="flat-lay-01", colour="black")],
        etsy=EtsyListingConfig(
            title=title,
            description=DescriptionConfig(lead=description),
            tags=tags if tags is not None else ["hiking"],
            variation_images=variation_images,
        ),
        **({"lifecycle": lifecycle} if lifecycle is not None else {}),
    )


def _check(
    listing: Listing,
    *,
    garment_profile: GarmentProfile | None = PROFILE,
    garment_profile_names: list[str] | None = None,
    design_paths: dict[str, Path] | None = None,
    templates: dict[str, TemplateInfo] | None = None,
    published: bool | None = None,
    description_ref_error: str | None = None,
) -> list[Issue]:
    return check_listing(
        listing,
        garment_profile=garment_profile,
        garment_profile_names=(
            garment_profile_names if garment_profile_names is not None else ["comfort-colors-1717"]
        ),
        design_paths=design_paths if design_paths is not None else {},
        templates=templates if templates is not None else {"flat-lay-01": FLAT_LAY},
        published=published,
        description_ref_error=description_ref_error,
    )


def _where(issues: list[Issue], tab: str) -> list[Issue]:
    return [i for i in issues if i.tab == tab]


class TestCopyIsConcrete:
    def test_an_empty_title_blocks_and_names_the_title(self) -> None:
        issues = _check(_listing(title=""))
        blocking = [i for i in issues if i.severity == "block" and i.tab == "details"]
        assert len(blocking) == 1
        assert blocking[0].where == "Listing Details › Title"

    def test_an_empty_lead_blocks_and_names_the_description_not_the_title(
        self,
    ) -> None:
        """A real regression: the description's own failure used to be
        reported under the Title field, so fixing the title never cleared an
        issue that was actually about the description."""
        issues = _check(_listing(description=""))
        blocking = [i for i in issues if i.severity == "block" and i.tab == "details"]
        assert len(blocking) == 1
        assert blocking[0].where == "Listing Details › Description"

    def test_both_empty_blocks_on_both_independently(self) -> None:
        issues = _check(_listing(title="", description=""))
        wheres = {i.where for i in issues if i.severity == "block" and i.tab == "details"}
        assert wheres == {"Listing Details › Title", "Listing Details › Description"}

    def test_real_copy_raises_no_issue(self) -> None:
        assert _check(_listing()) == []

    def test_a_non_empty_body_does_not_excuse_an_empty_lead(self) -> None:
        """The lead is required regardless of the body (PRD's description
        model) -- a listing-specific `text` filled in must not quiet the
        lead's own block."""
        listing = _listing()
        etsy = listing.etsy.model_copy(
            update={"description": DescriptionConfig(lead="", text="Printed to order.")}
        )
        issues = _check(listing.model_copy(update={"etsy": etsy}))
        blocking = [i for i in issues if i.severity == "block" and i.tab == "details"]
        assert any(i.where == "Listing Details › Description" for i in blocking)


class TestDescriptionRef:
    def _with_ref(self, ref: str) -> Listing:
        listing = _listing()
        etsy = listing.etsy.model_copy(
            update={"description": DescriptionConfig(lead="A retro sunset scene.", ref=ref)}
        )
        return listing.model_copy(update={"etsy": etsy})

    def test_a_ref_error_blocks_and_names_the_description(self) -> None:
        listing = self._with_ref("common-copy/missing.md")
        issues = _check(listing, description_ref_error="'common-copy/missing.md': file not found")
        blocking = [i for i in issues if i.severity == "block" and i.tab == "details"]
        assert any(
            i.where == "Listing Details › Description" and "file not found" in i.message
            for i in blocking
        )

    def test_no_ref_error_raises_no_issue(self) -> None:
        listing = self._with_ref("common-copy/comfort-colors.md")
        issues = _check(listing, description_ref_error=None)
        assert not any("file not found" in i.message for i in issues)

    def test_a_ref_error_is_ignored_when_the_listing_has_no_ref(self) -> None:
        """The caller only attempts the load when a ref is actually set; this
        guards the shape even if it ever passed one anyway."""
        issues = _check(_listing(), description_ref_error="should never be used")
        assert not any("should never be used" in i.message for i in issues)


class TestDesignResolution:
    def test_a_design_too_small_blocks_and_names_the_key(self, tmp_path: Path) -> None:
        path = _design(tmp_path, (10, 10))
        issues = _check(_listing(), design_paths={"default": path})
        blocking = [i for i in issues if i.severity == "block" and i.tab == "variants"]
        assert len(blocking) == 1
        assert "10" in blocking[0].message

    def test_a_resolvable_design_raises_no_issue(self, tmp_path: Path) -> None:
        path = _design(tmp_path)
        assert _check(_listing(), design_paths={"default": path}) == []

    def test_no_garment_profile_skips_the_design_check_entirely(self, tmp_path: Path) -> None:
        """Design resolution needs a print area to check against -- with no
        profile resolved there is nothing to check it against, and the
        missing-profile block below is the one issue that matters."""
        path = _design(tmp_path, (1, 1))
        issues = _check(_listing(), garment_profile=None, design_paths={"default": path})
        assert not any(i.tab == "variants" and "design" in i.message.lower() for i in issues)


class TestMediaPresence:
    def test_no_media_blocks(self) -> None:
        issues = _check(_listing(media=[]))
        assert any(i.severity == "block" and i.tab == "images" for i in issues)

    def test_some_media_raises_no_media_issue(self) -> None:
        issues = _check(_listing())
        assert not any("no listing images" in i.message.lower() for i in issues)


class TestColoursEnabled:
    def test_no_colours_blocks(self) -> None:
        issues = _check(_listing(colors=[], media=["common-media/size-guide.png"]))
        assert any(i.severity == "block" and i.tab == "variants" for i in issues)

    def test_some_colours_raises_no_issue_here(self) -> None:
        issues = _check(_listing())
        assert not any("no colours" in i.message.lower() for i in issues)


class TestGarmentProfileExists:
    def test_an_unknown_garment_profile_blocks(self) -> None:
        issues = _check(_listing(garment_profile="does-not-exist"), garment_profile_names=[])
        assert any(
            i.severity == "block" and i.tab == "variants" and "does-not-exist" in i.message
            for i in issues
        )

    def test_a_known_garment_profile_raises_no_issue(self) -> None:
        issues = _check(_listing())
        assert not any("garment profile" in i.message.lower() for i in issues)


class TestTemplateKindColourMismatch:
    def test_a_colour_matrix_entry_with_no_colour_blocks(self) -> None:
        issues = _check(
            _listing(media=[TemplateMediaEntry(template="flat-lay-01", colour=None)]),
        )
        assert any(i.severity == "block" and i.tab == "images" for i in issues)

    def test_a_multiple_entry_naming_a_colour_blocks(self) -> None:
        issues = _check(
            _listing(media=[TemplateMediaEntry(template="colour-chart-01", colour="black")]),
            templates={"colour-chart-01": CHART},
        )
        assert any(i.severity == "block" and i.tab == "images" for i in issues)

    def test_a_single_entry_naming_a_colour_blocks(self) -> None:
        issues = _check(
            _listing(media=[TemplateMediaEntry(template="sizing-chart", colour="black")]),
            templates={"sizing-chart": SIZING},
        )
        assert any(i.severity == "block" and i.tab == "images" for i in issues)

    def test_a_correctly_shaped_entry_raises_no_issue(self) -> None:
        issues = _check(
            _listing(media=[TemplateMediaEntry(template="sizing-chart", colour=None)]),
            templates={"sizing-chart": SIZING},
        )
        assert issues == []

    def test_a_bare_image_path_entry_is_never_a_kind_mismatch(self) -> None:
        issues = _check(_listing(media=["common-media/size-guide.png"]), templates={})
        assert not any(i.tab == "images" and "kind" in i.message.lower() for i in issues)


class TestVariationImages:
    def test_unset_raises_no_issue(self) -> None:
        assert _check(_listing(variation_images=None)) == []

    def test_a_template_not_in_media_blocks(self) -> None:
        issues = _check(
            _listing(variation_images="flat-lay-01", media=["common-media/size-guide.png"])
        )
        assert any(
            i.severity == "block" and i.tab == "images" and "flat-lay-01" in i.message
            for i in issues
        )

    def test_full_colour_coverage_raises_no_warning(self) -> None:
        issues = _check(
            _listing(
                colors=["black", "white"],
                media=[
                    TemplateMediaEntry(template="flat-lay-01", colour="black"),
                    TemplateMediaEntry(template="flat-lay-01", colour="white"),
                ],
                variation_images="flat-lay-01",
            ),
        )
        assert not any(i.severity == "warn" and i.tab == "images" for i in issues)

    def test_a_colour_missing_from_the_swatch_template_warns_with_its_name(self) -> None:
        issues = _check(
            _listing(
                colors=["black", "white"],
                media=[TemplateMediaEntry(template="flat-lay-01", colour="black")],
                variation_images="flat-lay-01",
            ),
        )
        warnings = [i for i in issues if i.severity == "warn" and i.tab == "images"]
        assert len(warnings) == 1
        assert "white" in warnings[0].message


class TestTags:
    def test_no_tags_warns(self) -> None:
        issues = _check(_listing(tags=[]))
        assert any(i.severity == "warn" and i.tab == "details" for i in issues)

    def test_some_tags_raises_no_issue(self) -> None:
        assert not any("no tags" in i.message.lower() for i in _check(_listing()))


class TestColourInGarmentProfile:
    def test_a_colour_the_profile_does_not_classify_warns(self) -> None:
        issues = _check(_listing(colors=["black", "forest"]))
        warnings = [i for i in issues if i.severity == "warn" and i.tab == "variants"]
        assert len(warnings) == 1
        assert "forest" in warnings[0].message

    def test_every_colour_classified_raises_no_warning(self) -> None:
        issues = _check(_listing(colors=["black", "white"]))
        assert not any(i.severity == "warn" and i.tab == "variants" for i in issues)

    def test_no_garment_profile_skips_this_check(self) -> None:
        issues = _check(
            _listing(colors=["not-a-real-colour"], media=["common-media/size-guide.png"]),
            garment_profile=None,
        )
        assert not any("classif" in i.message.lower() for i in issues)


class TestIndependentChecks:
    def test_a_clean_listing_has_no_issues(self) -> None:
        assert _check(_listing()) == []

    def test_multiple_problems_all_surface_together(self) -> None:
        issues = _check(
            _listing(colors=[], media=[], tags=[], title=""),
            garment_profile_names=[],
        )
        tabs = {i.tab for i in issues}
        assert tabs == {"variants", "images", "details"}


class TestNothingChosenYet:
    """The state a listing starts in, now that the editor *is* the create form.
    Each of these is a block, because each is something that has to be picked
    before the listing can mean anything -- and the banner is where an unsaved
    listing is told so."""

    def test_no_garment_profile_says_so_rather_than_quoting_an_empty_name(self) -> None:
        issues = _check(_listing(garment_profile=""))
        blocking = [i for i in issues if i.severity == "block" and i.where.endswith("profile")]
        assert len(blocking) == 1
        assert "no garment_profile set" in blocking[0].message

    def test_a_whitespace_only_garment_profile_is_unchosen_not_missing(self) -> None:
        """The divergence that put the two rule modules back together: a name of
        one space passed the engine's pre-flight (`.strip()`) and failed the
        banner's (`not listing.garment_profile`), so `apply` and the editor
        disagreed about one file on disk."""
        issues = _check(_listing(garment_profile=" "))
        blocking = [i for i in issues if i.severity == "block" and i.where.endswith("profile")]
        assert len(blocking) == 1
        assert "no garment_profile set" in blocking[0].message
        assert "' '" not in blocking[0].message

    def test_a_named_profile_that_does_not_exist_still_quotes_it(self) -> None:
        """A different mistake with a different remedy: one is unfinished, the
        other is wrong, and saying "not selected" about a typo would send the
        user looking in the wrong place."""
        issues = _check(_listing(garment_profile="no-such"), garment_profile_names=["other"])
        blocking = [i for i in issues if i.severity == "block" and i.where.endswith("profile")]
        assert len(blocking) == 1
        assert "'no-such'" in blocking[0].message

    def test_no_design_blocks(self) -> None:
        listing = _listing().model_copy(update={"design": {}})
        blocking = [i for i in _check(listing) if i.severity == "block" and i.where == "Design"]
        assert len(blocking) == 1
        assert "No design selected" in blocking[0].message

    def test_a_design_that_is_set_does_not_block(self) -> None:
        assert not [i for i in _check(_listing()) if i.where == "Design"]

    def test_no_price_source_blocks_on_the_details_tab(self) -> None:
        """The one rule shared with `Listing` itself, which refuses to *write*
        a listing in this state and waives it only for an unsaved draft. This
        is the sentence that explains the refusal."""
        listing = _listing().model_copy(update={"prices": {}, "pricing_plan": None})
        blocking = [i for i in _check(listing) if i.severity == "block" and i.tab == "details"]
        assert [i for i in blocking if "Pricing" in i.where]

    def test_a_pricing_plan_alone_satisfies_it(self) -> None:
        listing = _listing().model_copy(
            update={"prices": {}, "pricing_plan": "../../pricing-plans/tee.yaml"}
        )
        assert not [i for i in _check(listing) if "Pricing" in i.where]


class TestLifecycleVerb:
    """PRD 62: wrong verb is Blocked, never rewritten as the right one."""

    def test_deleted_on_a_published_listing_blocks_and_says_to_retire(self) -> None:
        issues = check_lifecycle_verb("deleted", published=True)
        assert len(issues) == 1
        first, *rest = issues[0].message.splitlines()
        assert first == (
            "this listing has been published; retracting it would discard its history."
        )
        assert any("retire" in line.lower() for line in rest)
        assert issues[0].severity == "block"

    def test_retired_on_a_never_live_listing_blocks_and_says_there_is_nothing_to_pause(
        self,
    ) -> None:
        issues = check_lifecycle_verb("retired", published=False)
        assert len(issues) == 1
        first, *rest = issues[0].message.splitlines()
        assert "never been for sale" in first
        assert "nothing to pause" in first
        assert issues[0].severity == "block"

    def test_deleted_on_a_never_live_listing_is_the_right_verb(self) -> None:
        assert check_lifecycle_verb("deleted", published=False) == []

    def test_retired_on_a_published_listing_is_the_right_verb(self) -> None:
        assert check_lifecycle_verb("retired", published=True) == []

    def test_omitted_lifecycle_is_never_the_wrong_verb(self) -> None:
        assert check_lifecycle_verb(None, published=True) == []
        assert check_lifecycle_verb(None, published=False) == []

    def test_check_listing_surfaces_the_wrong_verb_when_it_knows_published(self) -> None:
        issues = _check(_listing(lifecycle="deleted"), published=True)
        blocking = [i for i in issues if i.severity == "block" and i.where == "lifecycle"]
        assert blocking


class TestMissingListingYaml:
    def test_a_missing_file_is_not_consent(self) -> None:
        issues = check_listing_yaml_present(present=False)
        assert len(issues) == 1
        assert "listing.yaml" in issues[0].message
        assert "not consent" in issues[0].message
        assert issues[0].severity == "block"

    def test_a_present_file_is_silent(self) -> None:
        assert check_listing_yaml_present(present=True) == []
