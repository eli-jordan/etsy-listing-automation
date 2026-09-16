import { useEffect, useState } from "react";
import { listTemplates } from "../../api/calibrator";
import { listCommonMedia } from "../../api/listings";
import { Lightbox, type LightboxItem } from "../../components/Lightbox";
import { mediaLabel, pictureFor, singleDesignName } from "../../media";
import type { CommonMediaSummary, ListingDetail, TemplateSummary } from "../../types";
import { MediaLocator } from "./MediaLocator";
import { MediaReel } from "./MediaReel";
import { type Focus, viewFocus } from "./focus";
import * as edits from "./mediaEdits";

/**
 * Listing Images: a locator to add from, a preview pane to judge by, and the
 * reel that is the listing's actual `media:`.
 *
 * This module is the three of them side by side and the state they share --
 * what the preview is pointing at, which tile is selected, whether the
 * carousel is open. Everything else belongs to one of them: browsing is
 * `MediaLocator`'s, the drag is `MediaReel`'s, what a picture's URL is is
 * `media`'s, and what a click *changes* is `mediaEdits`'s.
 *
 * It was one 733-line function holding all of that, thirteen `useState` deep,
 * with PRD 56's swatch-source gate as a callback three levels inside it. The
 * split is by question: the rule about what `media:` may contain is now
 * callable without a DOM, and a test that clicks one × no longer has to mount
 * a template picker first.
 *
 * The **preview pane** and the reel's tiles ask for deliberately different
 * pictures. A tile is the template's bare photo, downscaled, because a tile is
 * picked out of a row and running the real pipeline once per tile would cost a
 * render per listing image just to open the tab. The pane is the opposite
 * question: one image, the listing's real artwork composited onto the
 * template's saved geometry at the photo's own resolution, large enough to
 * judge -- and clicking it opens the whole reel in the calibrator's lightbox,
 * where arrow keys walk the set and `1:1` stops the browser downsampling it.
 * Comparing neighbours is the point: the fault worth catching is usually "this
 * one colour is wrong".
 */

interface Props {
  detail: ListingDetail;
  onUpdate: (patch: Record<string, unknown>) => void;
}

export function ImagesTab({ detail, onUpdate }: Props) {
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [shared, setShared] = useState<CommonMediaSummary[]>([]);
  const [status, setStatus] = useState("");
  const [focus, setFocus] = useState<Focus | null>(null);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);
  const [actualSize, setActualSize] = useState(false);

  useEffect(() => {
    listTemplates()
      .then(setTemplates)
      .catch(() => setStatus("failed to load templates"));
    listCommonMedia()
      .then(setShared)
      .catch(() => setStatus("failed to load shared images"));
  }, []);

  const design = singleDesignName(detail.design);

  /** Every edit is a patch or nothing: a rule that declines (the twentieth
   * image is already there) returns `null` rather than an unchanged document,
   * so an autosave is never armed for a change that did not happen. */
  function apply(patch: Record<string, unknown> | null) {
    if (patch !== null) onUpdate(patch);
  }

  /** The reel, as the lightbox reads it. Its order is the order Etsy will
   * show the images in, which is the order worth stepping through. */
  const lightboxItems: LightboxItem[] = detail.media.map((entry, index) => ({
    id: `${mediaLabel(entry)}-${index}`,
    label: mediaLabel(entry),
    url: pictureFor(entry, design),
  }));

  const view = focus === null ? null : viewFocus(focus, detail, templates, design);

  function toggleFocused() {
    if (focus === null) return;
    apply(
      focus.kind === "shared"
        ? edits.toggleShared(detail, focus.asset.ref)
        : edits.toggleEntry(detail, focus.template, focus.colour),
    );
  }

  return (
    <div className="images-tab">
      <MediaLocator
        detail={detail}
        templates={templates}
        shared={shared}
        onToggleTemplate={(template, colour) => apply(edits.toggleEntry(detail, template, colour))}
        onToggleShared={(ref) => apply(edits.toggleShared(detail, ref))}
        onAddMissingColours={(template) => apply(edits.addEveryMissingColour(detail, template))}
        onToggleSwatchSource={(template) => apply(edits.toggleSwatchSource(detail, template))}
        onFocus={setFocus}
      />

      <div className="images-right">
        <div className="preview-pane">
          <div className="preview-stage preview-stage--large">
            {view === null && (
              <div className="image-placeholder">
                <span>Point at something on the left</span>
              </div>
            )}
            {view !== null && (
              /* A button, not a bare `<img onClick>`: opening the carousel
                  is an action, and the keyboard has to be able to take it. */
              <button
                type="button"
                className="preview-stage__open"
                title={
                  view.inListing
                    ? "Open the listing's images at full size"
                    : "Add it to the listing to open it at full size"
                }
                onClick={() => {
                  if (view.reelIndex >= 0) setLightboxIndex(view.reelIndex);
                }}
              >
                <img src={view.picture} alt={view.title} />
              </button>
            )}
          </div>

          {view !== null && (
            <div className="preview-foot">
              <span className="preview-meta">
                <span className="preview-meta__title">{view.title}</span>
                <span className="preview-meta__path">{view.path}</span>
              </span>
              <span className="preview-actions">
                <button
                  type="button"
                  className={
                    view.inListing
                      ? "btn-like btn-like--ghost btn-sm"
                      : "btn-like btn-like--primary btn-sm"
                  }
                  onClick={toggleFocused}
                >
                  {view.inListing ? "Remove from listing" : "+ Add to listing"}
                </button>
              </span>
            </div>
          )}
        </div>

        <MediaReel
          media={detail.media}
          design={design}
          swatchTemplate={detail.etsy.variation_images ?? null}
          selectedIndex={selectedIndex}
          shared={shared}
          onOpen={(index) => {
            setSelectedIndex(index);
            setLightboxIndex(index);
          }}
          onRemove={(index) => apply(edits.removeAt(detail, index))}
          onReorder={(from, to) => apply(edits.reorder(detail, from, to))}
          onFocus={setFocus}
        />

        <p role="status" className="app__status">
          {status}
        </p>
      </div>

      {lightboxIndex !== null && lightboxItems[lightboxIndex] !== undefined && (
        <Lightbox
          items={lightboxItems}
          index={lightboxIndex}
          actualSize={actualSize}
          onActualSizeChange={setActualSize}
          onIndexChange={setLightboxIndex}
          onClose={() => setLightboxIndex(null)}
        />
      )}
    </div>
  );
}
