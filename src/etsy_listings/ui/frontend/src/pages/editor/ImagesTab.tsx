import { useEffect, useState } from "react";
import { listTemplates, templateThumbnailUrl } from "../../api/calibrator";
import type { ListingDetail, MediaEntry, TemplateSummary } from "../../types";

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
 * There is also no endpoint (yet) that lists `common-media/`'s bare shared
 * assets, so the locator only browses mockup templates -- a bare-path media
 * entry can still exist (the fixture listing has one), it is just not
 * addable from this tab yet.
 */

interface Props {
  detail: ListingDetail;
  onUpdate: (patch: Record<string, unknown>) => void;
}

function kindLabel(kind: TemplateSummary["kind"]): string {
  if (kind === "colour-matrix") return "Colour matrix · one photo per colour";
  if (kind === "multiple") return "Multiple · several garments in one photo";
  if (kind === "single") return "Single · one fixed photo";
  return "";
}

function mediaLabel(entry: MediaEntry): string {
  if (typeof entry === "string") return entry;
  return entry.colour ? `${entry.template} · ${entry.colour}` : entry.template;
}

function isInMedia(media: MediaEntry[], template: string, colour: string | null): boolean {
  return media.some(
    (m) => typeof m !== "string" && m.template === template && (m.colour ?? null) === colour,
  );
}

export function ImagesTab({ detail, onUpdate }: Props) {
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [openTemplate, setOpenTemplate] = useState<string | null>(null);
  const [focusName, setFocusName] = useState<string | null>(null);
  const [dragIndex, setDragIndex] = useState<number | null>(null);

  useEffect(() => {
    listTemplates()
      .then(setTemplates)
      .catch(() => setStatus("failed to load templates"));
  }, []);

  const calibrated = templates.filter((t) => t.status === "calibrated");
  const filtered = calibrated.filter((t) => t.name.toLowerCase().includes(query.toLowerCase()));

  function addEntry(template: string, colour: string | null) {
    if (isInMedia(detail.media, template, colour)) return;
    onUpdate({ media: [...detail.media, { template, colour }] });
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

  return (
    <div className="images-tab">
      <div className="locator">
        <div className="locator__head">
          <span className="locator__title">Add images</span>
          <span className="locator__hint">Hover to preview · click to add</span>
        </div>

        <div className="locator__search">
          <input
            className="input"
            type="text"
            placeholder="Search templates…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>

        <div className="locator__list">
          {filtered.map((t) => (
            <div
              key={t.name}
              className={openTemplate === t.name ? "loc-tmpl loc-tmpl--open" : "loc-tmpl"}
            >
              <div
                className="loc-tmpl__head"
                onClick={() => setOpenTemplate((current) => (current === t.name ? null : t.name))}
                onMouseEnter={() => setFocusName(t.name)}
              >
                <span className="loc-tmpl__text">
                  <span className="loc-tmpl__name">{t.name}</span>
                  <span className="loc-tmpl__kind">{kindLabel(t.kind)}</span>
                </span>
                <span className="loc-tmpl__caret">{openTemplate === t.name ? "▴" : "▾"}</span>
              </div>

              {openTemplate === t.name && (
                <div className="loc-tmpl__body">
                  {t.kind === "colour-matrix" ? (
                    <div className="cchips">
                      {t.colours.map((colour) => {
                        const inListing = isInMedia(detail.media, t.name, colour);
                        return (
                          <button
                            key={colour}
                            type="button"
                            className={inListing ? "cchip cchip--in" : "cchip"}
                            onClick={() => addEntry(t.name, colour)}
                            onMouseEnter={() => setFocusName(t.name)}
                          >
                            {colour}
                          </button>
                        );
                      })}
                    </div>
                  ) : (
                    <button
                      type="button"
                      className="btn-like btn-like--primary btn-sm"
                      disabled={isInMedia(detail.media, t.name, null)}
                      onClick={() => addEntry(t.name, null)}
                    >
                      {isInMedia(detail.media, t.name, null) ? "Added" : "+ Add"}
                    </button>
                  )}
                </div>
              )}
            </div>
          ))}
          {filtered.length === 0 && (
            <p className="locator__empty">No template matches that search.</p>
          )}
        </div>
      </div>

      <div className="images-right">
        <div className="preview-pane">
          <span className="section-label">Preview</span>
          <div className="preview-stage preview-stage--images">
            {focusName ? (
              <img src={templateThumbnailUrl(focusName)} alt={focusName} />
            ) : (
              <div className="image-placeholder">
                <span>Point at a template on the left</span>
              </div>
            )}
          </div>
        </div>

        <div className="reel">
          <div className="reel__head">
            <span className="reel__title">Listing images</span>
            <span className="reel__count">{detail.media.length}</span>
            <span className="reel__hint">Drag to reorder — first tile is Etsy's thumbnail</span>
          </div>
          <div className="reel__track">
            {detail.media.map((entry, index) => (
              <div
                key={`${mediaLabel(entry)}-${index}`}
                className={dragIndex === index ? "rtile rtile--dragging" : "rtile"}
                draggable
                onDragStart={() => setDragIndex(index)}
                onDragOver={(event) => event.preventDefault()}
                onDrop={() => {
                  if (dragIndex !== null) reorder(dragIndex, index);
                  setDragIndex(null);
                }}
                onDragEnd={() => setDragIndex(null)}
              >
                <div className="rtile__face">
                  {typeof entry === "string" ? (
                    <span className="loc-img__name">{entry}</span>
                  ) : (
                    <img src={templateThumbnailUrl(entry.template)} alt={entry.template} />
                  )}
                  <span className="rtile__pos">{index + 1}</span>
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
            ))}
            {detail.media.length === 0 && (
              <p className="reel__empty">
                Nothing here yet -- add a mockup template from the left.
              </p>
            )}
          </div>
        </div>
      </div>

      <p role="status" className="app__status">
        {status}
      </p>
    </div>
  );
}
