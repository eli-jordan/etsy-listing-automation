import { useEffect, useState } from "react";
import { listTemplates, templateThumbnailUrl } from "../../api/calibrator";
import { commonMediaThumbnailUrl, listCommonMedia } from "../../api/listings";
import type {
  CommonMediaSummary,
  ListingDetail,
  MediaEntry,
  TemplateMediaEntry,
  TemplateSummary,
} from "../../types";

/**
 * Locator (browse calibrated templates) + preview pane + reel (phase 5).
 *
 * The preview and the reel's tiles use `GET /templates/{name}/thumbnail` --
 * the template's own bare photo -- rather than `POST .../preview`: that
 * endpoint's `design` parameter only resolves against the calibrator's test-
 * design library (bundled targets and `test-designs/` uploads), never a
 * listing's real `designs/*.png` artwork, so rendering it here would show a
 * stand-in design, not the listing's own. A real photo with no ink on it is
 * still the "real render, not invented SVG art" the mockup asked for; a
 * design overlay would need the preview endpoint to grow a third way to
 * resolve `design`, which is out of scope for this pass.
 *
 * The thumbnail *is* asked for a colour, though (`?colour=`): without it a
 * colour-matrix set answers with the same photo every time, and a reel of
 * eight identical tiles labelled with eight different colours is worse than
 * no picture at all.
 *
 * The locator browses the two things `media:` can hold, and the segmented
 * control is which: **Mockup templates** (a `{template, colour}` entry,
 * rendered per listing) and **Images** (`common-media/`, a bare path uploaded
 * as-is -- a sizing chart, care instructions). They are one control rather
 * than two panels because they compete for the same twenty slots.
 */

interface Props {
  detail: ListingDetail;
  onUpdate: (patch: Record<string, unknown>) => void;
}

/** Etsy's ceiling on listing images, mirrored from `config/listing.py`'s
 * `MAX_MEDIA_ENTRIES`. Shown, not enforced -- the server refuses past it. */
const MAX_MEDIA = 20;

function kindLabel(kind: TemplateSummary["kind"]): string {
  if (kind === "colour-matrix") return "Colour matrix · one photo per colour";
  if (kind === "multiple") return "Multiple · several garments in one photo";
  if (kind === "single") return "Single · one fixed photo";
  return "";
}

/** A shared asset's name, from the bare ref a listing stores. Filename-derived
 * rather than looked up, so a reel tile still labels itself when the file has
 * been deleted from `common-media/` since the listing named it. */
function sharedName(ref: string): string {
  const file = ref.split("/").pop() ?? ref;
  return file.replace(/\.png$/i, "");
}

function mediaLabel(entry: MediaEntry): string {
  if (typeof entry === "string") return sharedName(entry);
  return entry.colour ? `${entry.template} · ${entry.colour}` : entry.template;
}

/** The file on disk this entry renders from. PRD 7a: a colour-matrix photo is
 * named for the slugified colour; the other two kinds have a fixed `scene.png`
 * because there is no per-colour name to derive one from. */
function scenePath(template: string, colour: string | null): string {
  const file = colour === null ? "scene" : colour;
  return `mockup-templates/${template}/${file}.png`;
}

function isInMedia(media: MediaEntry[], template: string, colour: string | null): boolean {
  return media.some(
    (m) => typeof m !== "string" && m.template === template && (m.colour ?? null) === colour,
  );
}

/** What the preview pane is pointing at: one of the two things `media:` can
 * hold. For a template, a `null` colour means its fixed scene, which is also
 * what a `multiple`/`single` template always is. */
type Focus =
  | { kind: "template"; template: string; colour: string | null }
  | { kind: "shared"; asset: CommonMediaSummary };

/** Which half of `media:` the locator is browsing. */
type LocatorMode = "templates" | "images";

export function ImagesTab({ detail, onUpdate }: Props) {
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [shared, setShared] = useState<CommonMediaSummary[]>([]);
  const [status, setStatus] = useState("");
  const [mode, setMode] = useState<LocatorMode>("templates");
  const [query, setQuery] = useState("");
  const [openTemplate, setOpenTemplate] = useState<string | null>(null);
  const [focus, setFocus] = useState<Focus | null>(null);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);

  useEffect(() => {
    listTemplates()
      .then(setTemplates)
      .catch(() => setStatus("failed to load templates"));
    listCommonMedia()
      .then(setShared)
      .catch(() => setStatus("failed to load shared images"));
  }, []);

  const calibrated = templates.filter((t) => t.status === "calibrated");
  const filtered = calibrated.filter((t) => t.name.toLowerCase().includes(query.toLowerCase()));
  const filteredShared = shared.filter((a) => a.name.toLowerCase().includes(query.toLowerCase()));
  const swatchTemplate = detail.etsy.variation_images ?? null;

  function entriesFor(template: string): number {
    return detail.media.filter((m) => typeof m !== "string" && m.template === template).length;
  }

  /** Colours this listing sells that `template` has no media entry for.
   * Driven by `colors:`, not by the template's own photo set -- a swatch is
   * owed for every colour on sale, and one the template cannot supply is
   * exactly what the coverage warning is for. */
  function missingColours(template: string): string[] {
    return detail.colors.filter((c) => !isInMedia(detail.media, template, c));
  }

  function toggleEntry(template: string, colour: string | null) {
    if (isInMedia(detail.media, template, colour)) {
      onUpdate({
        media: detail.media.filter(
          (m) => typeof m === "string" || m.template !== template || (m.colour ?? null) !== colour,
        ),
      });
      return;
    }
    if (detail.media.length >= MAX_MEDIA) return;
    onUpdate({ media: [...detail.media, { template, colour }] });
  }

  function addEveryMissingColour(template: string) {
    const additions: TemplateMediaEntry[] = missingColours(template)
      .slice(0, Math.max(0, MAX_MEDIA - detail.media.length))
      .map((colour) => ({ template, colour }));
    if (additions.length === 0) return;
    onUpdate({ media: [...detail.media, ...additions] });
  }

  /** Turning the swatch source on also adds the colours it lacks: PRD 56's
   * gate (`EtsyMediaStage.desired()`) refuses a `variation_images` template
   * whose colours the media does not carry, so naming one without filling it
   * in would write a listing the engine then refuses to apply. */
  function toggleSwatchSource(template: string) {
    if (swatchTemplate === template) {
      onUpdate({ etsy: { variation_images: null } });
      return;
    }
    const additions: TemplateMediaEntry[] = missingColours(template)
      .slice(0, Math.max(0, MAX_MEDIA - detail.media.length))
      .map((colour) => ({ template, colour }));
    onUpdate({
      media: [...detail.media, ...additions],
      etsy: { variation_images: template },
    });
  }

  /** A shared asset is a bare string in `media:`, not a `{template, colour}`
   * entry -- the same list, two shapes (`config/listing.py`'s `MediaEntry`). */
  function toggleShared(ref: string) {
    if (detail.media.includes(ref)) {
      onUpdate({ media: detail.media.filter((m) => m !== ref) });
      return;
    }
    if (detail.media.length >= MAX_MEDIA) return;
    onUpdate({ media: [...detail.media, ref] });
  }

  function removeAt(index: number) {
    onUpdate({ media: detail.media.filter((_, i) => i !== index) });
  }

  function reorder(from: number, to: number) {
    if (from === to) return;
    const next = [...detail.media];
    const moved = next[from];
    if (moved === undefined) return;
    next.splice(from, 1);
    next.splice(to, 0, moved);
    onUpdate({ media: next });
  }

  const focusInListing =
    focus === null
      ? false
      : focus.kind === "shared"
        ? detail.media.includes(focus.asset.ref)
        : isInMedia(detail.media, focus.template, focus.colour);

  const focusTitle =
    focus === null
      ? ""
      : focus.kind === "shared"
        ? focus.asset.name
        : mediaLabel({ template: focus.template, colour: focus.colour });

  // The file it would upload, or render from -- the same question either way,
  // and the reason the foot shows a path at all.
  const focusPath =
    focus === null
      ? ""
      : focus.kind === "shared"
        ? focus.asset.file
        : scenePath(focus.template, focus.colour);

  return (
    <div className="images-tab">
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
                    onClick={() => toggleShared(asset.ref)}
                    onMouseEnter={() => setFocus({ kind: "shared", asset })}
                  >
                    <span className="loc-img__face">
                      <img src={commonMediaThumbnailUrl(asset.name)} alt="" loading="lazy" />
                    </span>
                    <span className="loc-img__name">{asset.name}.png</span>
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
              const missing = missingColours(t.name);
              const uncovered = swatchTemplate === t.name ? missing : [];
              return (
                <div key={t.name} className={open ? "loc-tmpl loc-tmpl--open" : "loc-tmpl"}>
                  <div
                    className="loc-tmpl__head"
                    onClick={() =>
                      setOpenTemplate((current) => (current === t.name ? null : t.name))
                    }
                    onMouseEnter={() =>
                      setFocus({
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
                      {t.kind === "colour-matrix" ? (
                        <>
                          <div className="cchips">
                            {t.colours.map((colour) => {
                              const inListing = isInMedia(detail.media, t.name, colour);
                              return (
                                <button
                                  key={colour}
                                  type="button"
                                  className={inListing ? "cchip cchip--in" : "cchip"}
                                  aria-pressed={inListing}
                                  onClick={() => toggleEntry(t.name, colour)}
                                  onMouseEnter={() =>
                                    setFocus({ kind: "template", template: t.name, colour })
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
                              onClick={() => addEveryMissingColour(t.name)}
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
                                  onClick={() => toggleSwatchSource(t.name)}
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
                                      {uncovered.join(", ")}{" "}
                                      {uncovered.length === 1 ? "has" : "have"} no image here — Etsy
                                      keeps{" "}
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
                            onClick={() => toggleEntry(t.name, null)}
                          >
                            {isInMedia(detail.media, t.name, null)
                              ? "Remove from listing"
                              : "+ Add"}
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

      <div className="images-right">
        <div className="preview-pane">
          <span className="section-label">Preview</span>
          <div className="preview-stage preview-stage--images">
            {focus === null && (
              <div className="image-placeholder">
                <span>Point at something on the left</span>
              </div>
            )}
            {focus?.kind === "template" && (
              <>
                {focus.colour !== null && (
                  <span className="preview-stage__tag tag tag-neutral">{focus.colour}</span>
                )}
                <img
                  src={templateThumbnailUrl(focus.template, focus.colour)}
                  alt={mediaLabel({ template: focus.template, colour: focus.colour })}
                />
              </>
            )}
            {focus?.kind === "shared" && (
              <img src={commonMediaThumbnailUrl(focus.asset.name)} alt={focus.asset.name} />
            )}
          </div>

          {focus !== null && (
            <div className="preview-foot">
              <span className="preview-meta">
                <span className="preview-meta__title">{focusTitle}</span>
                <span className="preview-meta__path">{focusPath}</span>
              </span>
              <span className="preview-actions">
                <button
                  type="button"
                  className={
                    focusInListing
                      ? "btn-like btn-like--ghost btn-sm"
                      : "btn-like btn-like--primary btn-sm"
                  }
                  onClick={() =>
                    focus.kind === "shared"
                      ? toggleShared(focus.asset.ref)
                      : toggleEntry(focus.template, focus.colour)
                  }
                >
                  {focusInListing ? "Remove from listing" : "+ Add to listing"}
                </button>
              </span>
            </div>
          )}
        </div>

        <div className="reel">
          <div className="reel__head">
            <span className="reel__title">Listing images</span>
            <span className="reel__count">
              {detail.media.length} of {MAX_MEDIA}
            </span>
            <span className="reel__hint">
              {detail.media.length >= MAX_MEDIA
                ? `At Etsy's ${MAX_MEDIA}-image limit — remove one before adding another`
                : "Drag a tile to change the order Etsy shows them in"}
            </span>
          </div>
          <div className="reel__track">
            {detail.media.map((entry, index) => {
              const isTemplate = typeof entry !== "string";
              const suppliesSwatch =
                isTemplate &&
                swatchTemplate !== null &&
                entry.template === swatchTemplate &&
                entry.colour !== null;
              const className = [
                "rtile",
                selectedIndex === index ? "rtile--selected" : "",
                dragIndex === index ? "rtile--dragging" : "",
                dragOverIndex === index && dragIndex !== index ? "rtile--over" : "",
              ]
                .filter(Boolean)
                .join(" ");
              return (
                <div
                  key={`${mediaLabel(entry)}-${index}`}
                  className={className}
                  draggable
                  onDragStart={() => setDragIndex(index)}
                  onDragOver={(event) => {
                    event.preventDefault();
                    setDragOverIndex(index);
                  }}
                  onDrop={() => {
                    if (dragIndex !== null) reorder(dragIndex, index);
                    setDragIndex(null);
                    setDragOverIndex(null);
                  }}
                  onDragEnd={() => {
                    setDragIndex(null);
                    setDragOverIndex(null);
                  }}
                >
                  <div
                    className="rtile__face"
                    onClick={() => setSelectedIndex(index)}
                    onMouseEnter={() => {
                      if (isTemplate) {
                        setFocus({
                          kind: "template",
                          template: entry.template,
                          colour: entry.colour ?? null,
                        });
                        return;
                      }
                      // Only an asset still in common-media/ can be previewed;
                      // a ref whose file has gone keeps its tile and its
                      // label, which is how the user finds out it is missing.
                      const asset = shared.find((a) => a.ref === entry);
                      if (asset !== undefined) setFocus({ kind: "shared", asset });
                    }}
                  >
                    {isTemplate ? (
                      <img
                        src={templateThumbnailUrl(entry.template, entry.colour)}
                        alt={mediaLabel(entry)}
                        loading="lazy"
                      />
                    ) : (
                      <img
                        src={commonMediaThumbnailUrl(sharedName(entry))}
                        alt={sharedName(entry)}
                        loading="lazy"
                      />
                    )}
                    <span className="rtile__pos">{index + 1}</span>
                    {suppliesSwatch && (
                      <span className="rtile__swatch" title="Supplies this colour's Etsy swatch">
                        <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                          <path d="M12 2l10 10-10 10L2 12z" />
                        </svg>
                      </span>
                    )}
                    <span
                      className="rtile__x"
                      role="button"
                      aria-label={`Remove ${mediaLabel(entry)}`}
                      onClick={() => removeAt(index)}
                    >
                      ×
                    </span>
                    {index === 0 && <span className="rtile__first">Etsy thumbnail</span>}
                  </div>
                  <span className="rtile__label">{mediaLabel(entry)}</span>
                </div>
              );
            })}
            {detail.media.length === 0 && (
              <p className="reel__empty">Nothing here yet — add a mockup template from the left.</p>
            )}
          </div>
        </div>

        <p role="status" className="app__status">
          {status}
        </p>
      </div>
    </div>
  );
}
