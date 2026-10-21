import { useEffect, useRef, useState } from "react";
import { designThumbnailUrl, listDesigns, uploadDesign } from "../../api/calibrator";
import { listingDesignThumbnailUrl, listListingDesigns } from "../../api/listings";
import type { DesignSummary, ListingDesignSummary } from "../../types";
import { type PreviewDesign, samePreview } from "./previewDesign";

/**
 * The design row above the tab strip in the listing-template editor (UI doc
 * §3; the `template-variants` mockup). A listing template has no artwork, so
 * the row picks what the previews are rendered with -- the calibrator's test
 * designs, bundled and uploaded, followed by the recent workspace designs --
 * and nothing it picks is saved. A listing's own artwork is the design strip
 * (`ArtworkStrip`), which edits `design:`.
 */

interface Props {
  preview: PreviewDesign;
  onPreview: (preview: PreviewDesign) => void;
}

/** How many recent workspace designs the picker offers beside the test
 * designs. Four fills one row of the picker grid. */
const RECENT = 4;

export function DesignSelect({ preview, onPreview }: Props) {
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
