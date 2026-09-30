import { useEffect, useRef, useState } from "react";
import { designThumbnailUrl, listDesigns, uploadDesign } from "../../api/calibrator";
import { listingDesignThumbnailUrl, listListingDesigns } from "../../api/listings";
import { refName } from "../../media";
import type { DesignSummary, ListingDesignSummary } from "../../types";
import { type PreviewDesign, samePreview } from "./previewDesign";

/**
 * The design-select strip above the tab strip, from the mockup.
 *
 * It sits outside the tabs because the artwork is what both Variants and
 * Listing Images are *about* -- which garment colours suit it, and which
 * mockups show it. Deferring the choice to "+ New listing" (the first pass)
 * made `design:` write-once from the UI, while `check_design_resolution` kept
 * reporting a design too small for the print area: an issue banner pointing
 * at a tab with no control to fix it.
 *
 * Multi-artwork listings are read-only here. `design:` keyed
 * `on-light`/`on-dark` is resolved per colour and garment by the render stage
 * (PRD's artwork resolution order), so there is no single "the design" to
 * swap, and offering one would silently drop the other.
 */

type Props =
  | {
      /** `Listing.design` verbatim: artwork key -> ref (PRD 73). */
      design: Record<string, string>;
      /** The new ref, ready to PATCH as `{ design: ref }`. */
      onPick: (ref: string) => void;
      preview?: undefined;
    }
  | {
      /** Preview mode, for a listing template (UI doc §3; the
       * `template-variants` mockup): it picks what the previews are rendered
       * with, not artwork, and nothing it picks is saved. */
      preview: PreviewDesign;
      onPreview: (preview: PreviewDesign) => void;
      design?: undefined;
    };

/** How many the strip offers before the modal is needed. Four fills one row
 * of the picker grid; the rest are a search away. */
const RECENT = 4;

export function DesignSelect(props: Props) {
  if (props.preview !== undefined) {
    return <PreviewDesignSelect preview={props.preview} onPreview={props.onPreview} />;
  }
  return <ArtworkSelect design={props.design} onPick={props.onPick} />;
}

function ArtworkSelect({
  design,
  onPick,
}: {
  design: Record<string, string>;
  onPick: (ref: string) => void;
}) {
  const [designs, setDesigns] = useState<ListingDesignSummary[]>([]);
  const [picking, setPicking] = useState(false);
  const [searching, setSearching] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    listListingDesigns()
      .then(setDesigns)
      .catch(() => setDesigns([]));
  }, []);

  const keys = Object.keys(design);
  const single = keys.length === 1 ? (design[keys[0] as string] as string) : null;
  const multi = keys.length > 1;

  function pick(chosen: ListingDesignSummary) {
    // PRD 73: a ref with no prefix is the workspace root, so the design's
    // workspace-relative path is already the ref `new` writes.
    onPick(chosen.file);
    setPicking(false);
    setSearching(false);
    setQuery("");
  }

  const matches = designs.filter((d) => d.name.toLowerCase().includes(query.toLowerCase()));

  return (
    <div className="design-select">
      <div className="design-row">
        {single !== null ? (
          <img
            className="design-thumb"
            src={listingDesignThumbnailUrl(refName(single))}
            alt=""
            loading="lazy"
          />
        ) : (
          <span className="design-thumb design-thumb--empty" />
        )}

        <div className="design-row__text">
          {multi ? (
            <>
              <div className="design-row__name">{keys.length} artworks</div>
              <div className="design-row__file">{keys.join(", ")} — edit these in listing.yaml</div>
            </>
          ) : single !== null ? (
            <>
              <div className="design-row__name">{refName(single)}</div>
              <div className="design-row__file">{single}</div>
            </>
          ) : (
            <>
              <div className="design-row__name design-row__name--empty">No design selected</div>
              <div className="design-row__file">
                Choose the artwork Variants and Listing Images are about
              </div>
            </>
          )}
        </div>

        {!multi && (
          <button
            type="button"
            className="design-row__change"
            aria-label="Change design"
            aria-expanded={picking}
            onClick={() => setPicking((open) => !open)}
          >
            Change ▾
          </button>
        )}
      </div>

      {picking && !multi && (
        <div className="add-panel">
          <span className="section-label">Recent designs</span>
          <div className="template-grid">
            {designs.slice(0, RECENT).map((d) => (
              <button
                key={d.name}
                type="button"
                className={
                  single !== null && refName(single) === d.name
                    ? "template-card template-card--active"
                    : "template-card"
                }
                onClick={() => pick(d)}
              >
                <span className="template-card__name">{d.name}</span>
                <span className="template-card__kind">{d.file}</span>
              </button>
            ))}
          </div>
          <button
            type="button"
            className="btn-like btn-like--ghost btn-sm"
            onClick={() => {
              setSearching(true);
              setQuery("");
            }}
          >
            Find a design…
          </button>
        </div>
      )}

      {searching && (
        <div className="modal-root" role="dialog" aria-modal="true" aria-label="Find a design">
          <div className="modal-backdrop" onClick={() => setSearching(false)} aria-hidden="true" />
          <div className="modal-dialog">
            <div className="modal-dialog__head">
              <h2 className="modal-dialog__title">Find a design</h2>
              <button
                type="button"
                className="modal-dialog__close"
                aria-label="Close"
                onClick={() => setSearching(false)}
              >
                ×
              </button>
            </div>
            <input
              className="input"
              type="text"
              placeholder="Search designs…"
              value={query}
              autoFocus
              onChange={(event) => setQuery(event.target.value)}
            />
            <div className="modal-dialog__list">
              {matches.map((d) => (
                <button
                  key={d.name}
                  type="button"
                  className="modal-design-row"
                  onClick={() => pick(d)}
                >
                  <img
                    className="modal-design-row__thumb"
                    src={listingDesignThumbnailUrl(d.name)}
                    alt=""
                    loading="lazy"
                  />
                  <span>
                    <span className="modal-design-row__name">{d.name}</span>
                    <span className="modal-design-row__file">{d.file}</span>
                  </span>
                </button>
              ))}
              {matches.length === 0 && <p className="modal-empty">No designs match your search</p>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/** The same strip, previewing a listing template: *Preview design: …*, and a
 * picker of the calibrator's test designs (bundled and uploaded, with the
 * calibrator's own upload) followed by the recent workspace designs -- the
 * `PreviewDesign` of the mockup's `_TemplateEditor.tsx`. */
function PreviewDesignSelect({
  preview,
  onPreview,
}: {
  preview: PreviewDesign;
  onPreview: (preview: PreviewDesign) => void;
}) {
  const [tests, setTests] = useState<DesignSummary[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const [designs, setDesigns] = useState<ListingDesignSummary[]>([]);
  const [picking, setPicking] = useState(false);
  const [status, setStatus] = useState("");

  useEffect(() => {
    listDesigns()
      .then(setTests)
      .catch(() => setTests([]));
    listListingDesigns()
      .then(setDesigns)
      .catch(() => setDesigns([]));
  }, []);

  const label =
    preview.kind === "test"
      ? (tests.find((d) => d.id === preview.id)?.label ?? preview.id)
      : preview.name;

  function pick(next: PreviewDesign) {
    onPreview(next);
    setPicking(false);
  }

  function upload(file: File | undefined) {
    if (!file) return;
    setStatus("uploading…");
    uploadDesign(file)
      .then((added) => {
        setTests((current) =>
          current.some((d) => d.id === added.id) ? current : [...current, added],
        );
        setStatus("");
        pick({ kind: "test", id: added.id });
      })
      .catch(() => setStatus("upload failed"));
  }

  const isOn = (candidate: PreviewDesign) => samePreview(candidate, preview);

  return (
    <div className="design-select">
      <div className="design-row">
        <img
          className="design-thumb"
          src={
            preview.kind === "test"
              ? designThumbnailUrl(preview.id)
              : listingDesignThumbnailUrl(preview.name)
          }
          alt=""
          loading="lazy"
        />
        <div className="design-row__text">
          <div className="design-row__name">Preview design: {label}</div>
          <div className="design-row__file">
            Only for previewing this template — each listing in a batch gets its own design
          </div>
        </div>
        <button
          type="button"
          className="design-row__change"
          aria-label="Change preview design"
          aria-expanded={picking}
          onClick={() => setPicking((open) => !open)}
        >
          Change ▾
        </button>
      </div>

      {picking && (
        <div className="add-panel">
          <span className="section-label">Preview designs</span>
          <div className="template-grid">
            {tests.map((d) => {
              const candidate: PreviewDesign = { kind: "test", id: d.id };
              return (
                <button
                  key={`test-${d.id}`}
                  type="button"
                  className={
                    isOn(candidate) ? "template-card template-card--active" : "template-card"
                  }
                  onClick={() => pick(candidate)}
                >
                  <span className="template-card__name">{d.label}</span>
                  <span className="template-card__kind">
                    {d.source === "bundled" ? "bundled test design" : "uploaded test design"}
                  </span>
                </button>
              );
            })}
            {designs.slice(0, RECENT).map((d) => {
              const candidate: PreviewDesign = { kind: "design", name: d.name, file: d.file };
              return (
                <button
                  key={`design-${d.name}`}
                  type="button"
                  className={
                    isOn(candidate) ? "template-card template-card--active" : "template-card"
                  }
                  onClick={() => pick(candidate)}
                >
                  <span className="template-card__name">{d.name}</span>
                  <span className="template-card__kind">{d.file}</span>
                </button>
              );
            })}
          </div>
          <button
            type="button"
            className="btn-like btn-like--ghost btn-sm"
            onClick={() => input.current?.click()}
          >
            Upload a PNG to preview…
          </button>
          <input
            ref={input}
            type="file"
            accept="image/png"
            hidden
            aria-label="Upload a PNG to preview…"
            onChange={(event) => {
              upload(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
          {status && (
            <span className="bc-small bc-muted" role="status">
              {status}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
