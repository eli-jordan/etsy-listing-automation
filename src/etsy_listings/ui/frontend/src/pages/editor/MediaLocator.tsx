import { useState } from "react";
import { templateThumbnailUrl } from "../../api/calibrator";
import { commonMediaThumbnailUrl } from "../../api/listings";
import { isInMedia, missingColours } from "../../media";
import type { CommonMediaSummary, ListingDetail, TemplateSummary } from "../../types";
import type { Focus } from "./focus";

/**
 * The half of the Listing Images tab that *offers* things: browse the two
 * things `media:` can hold, and add one.
 *
 * The segmented control is which half is being browsed -- **Mockup templates**
 * (a `{template, colour}` entry, rendered per listing) and **Images**
 * (`common-media/`, a bare path uploaded as-is: a sizing chart, care
 * instructions). One control rather than two panels because they compete for
 * the same twenty slots.
 *
 * Its own state is what it is *showing* (which half, the search, which template
 * is expanded). What a click *means* belongs to `mediaEdits`, and where the
 * preview is pointing belongs to the tab, because the preview pane and the reel
 * both read it.
 */

interface Props {
  detail: ListingDetail;
  templates: TemplateSummary[];
  shared: CommonMediaSummary[];
  onToggleTemplate: (template: string, colour: string | null) => void;
  onToggleShared: (ref: string) => void;
  onAddMissingColours: (template: string) => void;
  onToggleSwatchSource: (template: string) => void;
  onFocus: (focus: Focus) => void;
}

/** Which half of `media:` the locator is browsing. */
type LocatorMode = "templates" | "images";

function kindLabel(kind: TemplateSummary["kind"]): string {
  if (kind === "colour-matrix") return "Colour matrix · one photo per colour";
  if (kind === "multiple") return "Multiple · several garments in one photo";
  if (kind === "single") return "Single · one fixed photo";
  return "";
}

export function MediaLocator({
  detail,
  templates,
  shared,
  onToggleTemplate,
  onToggleShared,
  onAddMissingColours,
  onToggleSwatchSource,
  onFocus,
}: Props) {
  const [mode, setMode] = useState<LocatorMode>("templates");
  const [query, setQuery] = useState("");
  const [openTemplate, setOpenTemplate] = useState<string | null>(null);

  const needle = query.toLowerCase();
  const filtered = templates
    .filter((t) => t.status === "calibrated")
    .filter((t) => t.name.toLowerCase().includes(needle));
  const filteredShared = shared.filter((a) => a.name.toLowerCase().includes(needle));
  const swatchTemplate = detail.etsy.variation_images ?? null;

  function entriesFor(template: string): number {
    return detail.media.filter((m) => typeof m !== "string" && m.template === template).length;
  }

  return (
    <div className="locator">
      <div className="locator__head">
        <span className="locator__title">Add images</span>
        <span className="locator__hint">Hover to preview · click to add</span>
      </div>

      <div className="seg">
        {(["templates", "images"] as LocatorMode[]).map((m) => (
          <button
            key={m}
            type="button"
            className={mode === m ? "seg-opt seg-opt--on" : "seg-opt"}
            aria-pressed={mode === m}
            // The query is cleared on the way across: "flat" means nothing
            // in common-media/, and a list that looks empty because of a
            // search you cannot see reads as a list with nothing in it.
            onClick={() => {
              setMode(m);
              setQuery("");
            }}
          >
            {m === "templates" ? "Mockup templates" : "Images"}
          </button>
        ))}
      </div>

      <div className="locator__search">
        <svg viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="11" cy="11" r="7" />
          <path d="M20 20l-3.5-3.5" />
        </svg>
        <input
          className="input"
          type="text"
          placeholder={mode === "templates" ? "Search templates…" : "Search common-media…"}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      {mode === "images" && (
        <div className="locator__list">
          <div className="loc-images">
            {filteredShared.map((asset) => {
              const inListing = detail.media.includes(asset.ref);
              return (
                <button
                  key={asset.name}
                  type="button"
                  className={inListing ? "loc-img loc-img--in" : "loc-img"}
                  aria-pressed={inListing}
                  onClick={() => onToggleShared(asset.ref)}
                  onMouseEnter={() => onFocus({ kind: "shared", asset })}
                >
                  <span className="loc-img__face">
                    <img src={commonMediaThumbnailUrl(asset.name)} alt="" loading="lazy" />
                  </span>
                  <span className="loc-img__name">{asset.name}</span>
                </button>
              );
            })}
          </div>
          {filteredShared.length === 0 && (
            <p className="locator__empty">
              {shared.length === 0
                ? "Nothing in common-media/ yet — drop a sizing chart or care instructions there and it appears here."
                : "No shared image matches that search."}
            </p>
          )}
        </div>
      )}

      {mode === "templates" && (
        <div className="locator__list">
          {filtered.map((t) => {
            const open = openTemplate === t.name;
            const inCount = entriesFor(t.name);
            const missing = missingColours(detail.media, detail.colors, t.name);
            const uncovered = swatchTemplate === t.name ? missing : [];
            return (
              <div key={t.name} className={open ? "loc-tmpl loc-tmpl--open" : "loc-tmpl"}>
                <div
                  className="loc-tmpl__head"
                  onClick={() => setOpenTemplate((current) => (current === t.name ? null : t.name))}
                  onMouseEnter={() =>
                    onFocus({
                      kind: "template",
                      template: t.name,
                      colour: t.kind === "colour-matrix" ? (detail.colors[0] ?? null) : null,
                    })
                  }
                >
                  <span className="loc-tmpl__mini">
                    <img src={templateThumbnailUrl(t.name)} alt="" loading="lazy" />
                  </span>
                  <span className="loc-tmpl__text">
                    <span className="loc-tmpl__name">{t.name}</span>
                    <span className="loc-tmpl__kind">{kindLabel(t.kind)}</span>
                  </span>
                  {inCount > 0 && <span className="loc-tmpl__count">{inCount} in listing</span>}
                  <span className="loc-tmpl__caret" aria-hidden="true">
                    {open ? "▾" : "▸"}
                  </span>
                </div>

                {open && (
                  <div className="loc-tmpl__body">
                    {t.kind === "colour-matrix" && detail.colors.length === 0 ? (
                      // Nothing to offer: a colour-matrix entry needs a
                      // colour, and every colour it could name comes from
                      // the listing's own `colors:`. Adding one anyway would
                      // write `{template, colour: null}`, which is a block.
                      <p className="loc-tmpl__note">Pick colours on Variants first.</p>
                    ) : t.kind === "colour-matrix" ? (
                      <>
                        <div className="cchips">
                          {/* The listing's own colours, not `t.colours`:
                              a colour-matrix set's photos are named for
                              PRD 7a's slug, but a template with a shared
                              filename prefix (`{template}-{colour}.png`)
                              reports that whole prefixed stem as its
                              "colour" (`template_colours`'s enumeration
                              direction has no slug to match against,
                              unlike `template_base_image`'s lookup
                              direction, which resolves a bare slug against
                              exactly this fallback) -- so comparing against
                              `detail.colors` by string equality showed
                              nothing at all for such a template. `media[]`
                              always stores the listing's own bare slug
                              (confirmed by `isInMedia`), so that is what a
                              chip must offer, regardless of what the
                              template's own photos happen to be named. */}
                          {detail.colors.map((colour) => {
                            const inListing = isInMedia(detail.media, t.name, colour);
                            return (
                              <button
                                key={colour}
                                type="button"
                                className={inListing ? "cchip cchip--in" : "cchip"}
                                aria-pressed={inListing}
                                onClick={() => onToggleTemplate(t.name, colour)}
                                onMouseEnter={() =>
                                  onFocus({ kind: "template", template: t.name, colour })
                                }
                              >
                                {colour}
                                {inListing && (
                                  <svg
                                    className="cchip__tick"
                                    viewBox="0 0 24 24"
                                    strokeWidth="3.5"
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    aria-hidden="true"
                                  >
                                    <path d="M5 13l4 4L19 7" />
                                  </svg>
                                )}
                              </button>
                            );
                          })}
                        </div>

                        {missing.length > 1 && (
                          <button
                            type="button"
                            className="btn-like btn-like--ghost btn-sm"
                            onClick={() => onAddMissingColours(t.name)}
                          >
                            + Add all {missing.length} remaining colours
                          </button>
                        )}
                        {detail.colors.length > 0 && missing.length === 0 && (
                          <p className="loc-tmpl__note">
                            Every colour this listing sells is already in the reel.
                          </p>
                        )}

                        {inCount > 0 && (
                          <div className="tmpl-swatch">
                            <div className="tmpl-swatch__row">
                              <span className="tmpl-swatch__label" id={`swatch-${t.name}`}>
                                Use for Etsy colour swatches
                                <span className="tmpl-swatch__sub">
                                  {swatchTemplate === t.name
                                    ? "Etsy shows these beside each colour option"
                                    : swatchTemplate
                                      ? `Currently using ${swatchTemplate}`
                                      : "Off — no swatch images sent"}
                                </span>
                              </span>
                              <button
                                type="button"
                                role="switch"
                                aria-checked={swatchTemplate === t.name}
                                aria-labelledby={`swatch-${t.name}`}
                                className={
                                  swatchTemplate === t.name ? "switch switch--on" : "switch"
                                }
                                onClick={() => onToggleSwatchSource(t.name)}
                              >
                                <span className="switch__knob" />
                              </button>
                            </div>
                            {swatchTemplate === t.name && (
                              <>
                                <span
                                  className={
                                    uncovered.length > 0
                                      ? "swatch-status swatch-status--warn"
                                      : "swatch-status swatch-status--ok"
                                  }
                                >
                                  {uncovered.length > 0
                                    ? `${detail.colors.length - uncovered.length} of ${detail.colors.length} covered`
                                    : `All ${detail.colors.length} covered`}
                                </span>
                                {uncovered.length > 0 && (
                                  <p className="swatch-note">
                                    {uncovered.join(", ")} {uncovered.length === 1 ? "has" : "have"}{" "}
                                    no image here — Etsy keeps{" "}
                                    {uncovered.length === 1 ? "that swatch" : "those swatches"}{" "}
                                    empty.
                                  </p>
                                )}
                              </>
                            )}
                          </div>
                        )}
                      </>
                    ) : (
                      <>
                        <p className="loc-tmpl__note">
                          {t.kind === "multiple"
                            ? "One photo showing several colours at once — it carries no colour of its own."
                            : "One fixed photo, the same for every colour."}
                        </p>
                        <button
                          type="button"
                          className={
                            isInMedia(detail.media, t.name, null)
                              ? "btn-like btn-like--ghost btn-sm"
                              : "btn-like btn-like--primary btn-sm"
                          }
                          onClick={() => onToggleTemplate(t.name, null)}
                        >
                          {isInMedia(detail.media, t.name, null) ? "Remove from listing" : "+ Add"}
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            );
          })}
          {filtered.length === 0 && (
            <p className="locator__empty">No template matches that search.</p>
          )}
        </div>
      )}
    </div>
  );
}
