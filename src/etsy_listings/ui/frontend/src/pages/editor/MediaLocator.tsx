import { useState } from "react";
import { templateThumbnailUrl } from "../../api/calibrator";
import { MutedClip } from "../../components/MutedClip";
import { useHoverPlay } from "../../hooks/useHoverPlay";
import { isInMedia, mediaKind, missingColours, pictureFor } from "../../media";
import type { ListingDetail, MediaFileSummary, TemplateSummary } from "../../types";
import type { Focus } from "./focus";
import { MAX_VIDEOS } from "./mediaEdits";

/**
 * The half of the Listing Images tab that *offers* things: browse the two
 * things `media:` can hold, and add one.
 *
 * The segmented control is which half is being browsed -- **Mockup templates**
 * (a `{template, colour}` entry, rendered per listing) and **Files** (a file
 * ref uploaded as-is: a sizing chart, care instructions, a size-guide video).
 * One control rather than two panels because they fill the same gallery.
 *
 * *Files* is one list in two groups, one per root a ref can name (PRD 72):
 * *This listing · ./* for the listing's own directory and *Shared ·
 * common-media/*. Images and videos sit together, because `media:` is one
 * gallery (PRD 71); a video is drawn by a muted `<video>` from its own first
 * frame, carries its length, and plays on hover.
 *
 * Its own state is what it is *showing* (which half, the search, which template
 * is expanded). What a click *means* belongs to `mediaEdits`, and where the
 * preview is pointing belongs to the tab, because the preview pane and the reel
 * both read it.
 */

interface Props {
  detail: ListingDetail;
  templates: TemplateSummary[];
  /** The listing's own files, or `null` for a draft, which has no directory
   * yet and so no *This listing* group. */
  local: readonly MediaFileSummary[] | null;
  shared: readonly MediaFileSummary[];
  onToggleTemplate: (template: string, colour: string | null) => void;
  onToggleFile: (ref: string) => void;
  onAddMissingColours: (template: string) => void;
  onToggleSwatchSource: (template: string) => void;
  onFocus: (focus: Focus) => void;
}

/** Which half of `media:` the locator is browsing. */
type LocatorMode = "templates" | "files";

function kindLabel(kind: TemplateSummary["kind"]): string {
  if (kind === "colour-matrix") return "Colour matrix · one photo per colour";
  if (kind === "multiple") return "Multiple · several garments in one photo";
  if (kind === "single") return "Single · one fixed photo";
  return "";
}

/** `0:06`, `1:15` -- a clip's length as the badge shows it. */
function clipLength(seconds: number): string {
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

interface FileTileProps {
  asset: MediaFileSummary;
  listing: string | null;
  inListing: boolean;
  unavailable: string | null;
  onToggle: () => void;
  onFocus: () => void;
}

/** One file in the list: a picture for an image, a first frame and a length
 * for a video. */
function FileTile({ asset, listing, inListing, unavailable, onToggle, onFocus }: FileTileProps) {
  const { ref: clipRef, play, rest } = useHoverPlay();
  const [length, setLength] = useState<number | null>(null);
  const isVideo = asset.kind === "video";

  return (
    <button
      type="button"
      className={`loc-img${inListing ? " loc-img--in" : ""}${unavailable ? " loc-img--unavailable" : ""}`}
      aria-pressed={inListing}
      aria-describedby={unavailable === null ? undefined : "video-limit"}
      aria-label={asset.name}
      disabled={unavailable !== null}
      title={unavailable ?? undefined}
      onClick={onToggle}
      onMouseEnter={() => {
        onFocus();
        if (isVideo) play();
      }}
      onMouseLeave={isVideo ? rest : undefined}
    >
      <span className="loc-img__face">
        {isVideo ? (
          <>
            <MutedClip
              src={pictureFor(asset.ref, null, "full", listing)}
              clipRef={clipRef}
              onDuration={setLength}
            />
            <span className="loc-img__badge">
              {length === null ? "▶" : `▶ ${clipLength(length)}`}
            </span>
          </>
        ) : (
          <img src={pictureFor(asset.ref, null, "tile", listing)} alt="" loading="lazy" />
        )}
      </span>
      <span className="loc-img__name">{asset.name}</span>
    </button>
  );
}

export function MediaLocator({
  detail,
  templates,
  local,
  shared,
  onToggleTemplate,
  onToggleFile,
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
  const matches = (a: MediaFileSummary) => a.name.toLowerCase().includes(needle);
  const listing = detail.name || null;
  const groups = [
    ...(local === null
      ? []
      : [
          {
            label: "This listing · ./",
            files: local,
            empty: `Nothing in listings/${detail.name}/ yet — a close-up or a clip saved there appears here.`,
          },
        ]),
    {
      label: "Shared · common-media/",
      files: shared,
      empty:
        "Nothing in common-media/ yet — drop a sizing chart or a size-guide video there and it appears here.",
    },
  ];
  const nothingMatches =
    groups.some((g) => g.files.length > 0) && groups.every((g) => !g.files.some(matches));
  const swatchTemplate = detail.etsy.variation_images ?? null;
  const videoLimitReached =
    detail.media.filter((entry) => mediaKind(entry) === "video").length >= MAX_VIDEOS;

  function entriesFor(template: string): number {
    return detail.media.filter((m) => typeof m !== "string" && m.template === template).length;
  }

  return (
    <div className="locator">
      <div className="locator__head">
        <span className="locator__title">Add media</span>
        <span className="locator__hint">Hover to preview · click to add</span>
      </div>

      <div className="seg">
        {(["templates", "files"] as LocatorMode[]).map((m) => (
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
            {m === "templates" ? "Mockup templates" : "Files"}
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
          placeholder={mode === "templates" ? "Search templates…" : "Search files…"}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      {mode === "files" && (
        <div className="locator__list">
          {videoLimitReached && (
            <p className="locator__limit" id="video-limit" role="status">
              {MAX_VIDEOS}-video limit reached — remove one before adding another.
            </p>
          )}
          {groups.map((g) => {
            const visible = g.files.filter(matches);
            return (
              <div key={g.label} role="group" aria-label={g.label} className="loc-group">
                <span className="loc-group__label">{g.label}</span>
                {visible.length > 0 && (
                  <div className="loc-images">
                    {visible.map((asset) => (
                      <FileTile
                        key={asset.ref}
                        asset={asset}
                        listing={listing}
                        inListing={detail.media.includes(asset.ref)}
                        unavailable={
                          asset.kind === "video" &&
                          videoLimitReached &&
                          !detail.media.includes(asset.ref)
                            ? `Etsy allows at most ${MAX_VIDEOS} videos per listing`
                            : null
                        }
                        onToggle={() => onToggleFile(asset.ref)}
                        onFocus={() => onFocus({ kind: "file", asset })}
                      />
                    ))}
                  </div>
                )}
                {g.files.length === 0 && <p className="locator__empty">{g.empty}</p>}
              </div>
            );
          })}
          {nothingMatches && <p className="locator__empty">No file matches that search.</p>}
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
