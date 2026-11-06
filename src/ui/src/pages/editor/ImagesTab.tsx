import { type ReactNode, useEffect, useState } from "react";
import { listTemplates } from "../../api/calibrator";
import {
  listCommonMedia,
  listListingMediaFiles,
  listingDesignThumbnailUrl,
} from "../../api/listings";
import { listListingTemplateMediaFiles } from "../../api/listingTemplates";
import { Lightbox, type LightboxItem } from "../../components/Lightbox";
import {
  type Artwork,
  type MediaOwner,
  mediaKind,
  mediaLabel,
  pictureFor,
  refName,
  sceneSource,
} from "../../media";
import type { MediaFileSummary, ListingDetail, TemplateSummary } from "../../types";
import { MediaLocator } from "./MediaLocator";
import { MediaReel } from "./MediaReel";
import { representative } from "./artwork";
import { isBoolean, isNullableNumber, useViewState, viewScope } from "./editorView";
import {
  type Focus,
  type FocusRef,
  type FocusView,
  focusRef,
  isFocusRef,
  restoreFocus,
  viewFocus,
} from "./focus";
import * as edits from "./mediaEdits";
import { type Positions, positionSignature } from "./positions/document";
import { PositionControls, PositionNote } from "./positions/PositionControls";
import { PositionStage } from "./positions/PositionStage";
import {
  type Positioning,
  positionTarget,
  usePositioning,
  useSavedPositions,
} from "./positions/usePositioning";
import "./positions/positions.css";

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
 * with ADR-0030's swatch-source gate as a callback three levels inside it. The
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
  /** What the renders composite, when it is not the listing's own design:
   * the listing-template editor's preview design (UI doc §3). */
  artwork?: Artwork | null;
  /** Whose `./` files these are, when not the listing's: a listing
   * template's. One with `copies` is not saved yet and has no directory. */
  owner?: MediaOwner | null;
  /** Saves now rather than after the debounce: a position saves once per
   * completed gesture (interactions, *Saving*). */
  onFlush?: () => void;
}

/** Whose `./` files the tab shows: the given owner, else the listing --
 * none for a draft, which has no name yet. */
function mediaOwner(owner: MediaOwner | null | undefined, name: string): MediaOwner | null {
  if (owner !== undefined) return owner;
  return name ? { kind: "listing", name } : null;
}

/** The directory to list the owner's own files from. A draft has no
 * directory, and neither does an unsaved listing template (one with
 * `copies`), so neither has anything of its own to list. */
function ownDirectory(owner: MediaOwner | null): MediaOwner | null {
  return owner === null || owner.copies !== undefined ? null : owner;
}

export function ImagesTab({ detail, onUpdate, artwork, owner, onFlush }: Props) {
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [shared, setShared] = useState<MediaFileSummary[]>([]);
  const [local, setLocal] = useState<MediaFileSummary[]>([]);
  const [status, setStatus] = useState("");

  const listing = mediaOwner(owner, detail.name);
  const directory = ownDirectory(listing);
  const directoryKind = directory?.kind ?? null;
  const directoryName = directory?.name ?? null;
  const scope = directory === null ? null : viewScope(directory.kind, directory.name);

  /** What the seller pointed at since this tab opened. Until then the stage
   * shows what a refresh remembered, once the lists can say it still exists. */
  const [pointed, setPointed] = useState<Focus | null>(null);
  const [remembered, setRemembered] = useViewState<FocusRef | null>(
    scope,
    "focus",
    null,
    isFocusRef,
  );
  const [lightboxIndex, setLightboxIndex] = useViewState<number | null>(
    scope,
    "lightbox",
    null,
    isNullableNumber,
  );
  const [actualSize, setActualSize] = useViewState(scope, "actual-size", false, isBoolean);

  function pointAt(next: Focus) {
    setPointed(next);
    setRemembered(focusRef(next));
  }

  useEffect(() => {
    listTemplates()
      .then(setTemplates)
      .catch(() => setStatus("failed to load templates"));
    listCommonMedia()
      .then(setShared)
      .catch(() => setStatus("failed to load shared files"));
  }, []);

  useEffect(() => {
    if (directoryName === null) return;
    (directoryKind === "listing-template"
      ? listListingTemplateMediaFiles(directoryName)
      : listListingMediaFiles(directoryName)
    )
      .then(setLocal)
      .catch(() => setStatus("failed to load this listing's files"));
  }, [directoryKind, directoryName]);

  // Each layer resolved from the saved listing, multi-colour scenes too
  // (A35) -- or, in the listing-template editor, its preview design.
  const saved = useSavedPositions(detail);
  const scene: Artwork | null = artwork !== undefined ? artwork : listingScene(detail, saved);

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
    url: pictureFor(entry, scene, "full", listing),
    kind: mediaKind(entry),
  }));

  const files = directory === null ? shared : [...local, ...shared];
  const focus = pointed ?? restoreFocus(remembered, templates, files);
  const view = focus === null ? null : viewFocus(focus, detail, templates, scene, listing);
  // The reel highlights whatever the stage is showing, wherever the pointing
  // came from.
  const selectedIndex = view !== null && view.reelIndex >= 0 ? view.reelIndex : null;

  const target = positionTarget(
    focus,
    view?.inListing === true,
    artwork === undefined && owner === undefined && detail.name !== "",
  );
  const positioning = usePositioning({
    detail,
    ...target,
    summary: templates.find((t) => t.name === target.template),
    picture: view?.picture ?? "",
    saved,
    onUpdate,
    onFlush,
  });

  function toggleFocused() {
    if (focus === null) return;
    apply(
      focus.kind === "file"
        ? edits.toggleFile(detail, focus.asset.ref)
        : edits.toggleEntry(detail, focus.template, focus.colour),
    );
  }

  return (
    <div className="images-tab">
      <MediaLocator
        detail={detail}
        templates={templates}
        local={directory === null ? null : local}
        owner={listing}
        shared={shared}
        onToggleTemplate={(template, colour) => apply(edits.toggleEntry(detail, template, colour))}
        onToggleFile={(ref) => apply(edits.toggleFile(detail, ref))}
        onAddMissingColours={(template) => apply(edits.addEveryMissingColour(detail, template))}
        onToggleSwatchSource={(template) => apply(edits.toggleSwatchSource(detail, template))}
        onFocus={pointAt}
        scope={scope}
      />

      <div className="images-right">
        <PreviewPane
          view={view}
          positioning={positioning}
          artwork={overlayArtwork(detail)}
          onOpen={setLightboxIndex}
          onToggle={toggleFocused}
        />

        <MediaReel
          media={detail.media}
          scene={scene}
          swatchTemplate={detail.etsy.variation_images ?? null}
          selectedIndex={selectedIndex}
          listing={listing}
          files={files}
          onRemove={(index) => apply(edits.removeAt(detail, index))}
          onReorder={(from, to) => apply(edits.reorder(detail, from, to))}
          onFocus={pointAt}
          positioned={new Set(Object.keys(detail.template_positions ?? {}))}
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

/** The stage's picture, or what to say instead of a broken image: a positioned
 * Marigold scene cannot render while its template is being prepared. It loads
 * again by itself when preparation ends. */
function StagePicture({
  src,
  alt,
  positioning,
}: {
  src: string;
  alt: string;
  positioning: Positioning | null;
}) {
  const [failed, setFailed] = useState<string | null>(null);
  const attempt = `${positioning?.attempt ?? 0}:${src}`;
  if (failed === attempt) {
    return (
      <span className="image-placeholder">
        {positioning?.waiting === true
          ? "This picture will appear when preparation finishes"
          : "This picture could not load"}
      </span>
    );
  }
  return (
    <img
      key={attempt}
      src={src}
      alt={alt}
      onError={() => {
        setFailed(attempt);
        positioning?.recheck();
      }}
    />
  );
}

/** The stage and its foot: the picture being judged, and -- for a template
 * entry this listing may position -- Position mode in place of it. */
function PreviewPane({
  view,
  positioning,
  artwork,
  onOpen,
  onToggle,
}: {
  view: FocusView | null;
  positioning: Positioning | null;
  artwork: string | null;
  onOpen: (index: number) => void;
  onToggle: () => void;
}) {
  const adjusting = positioning?.on === true ? positioning : null;
  return (
    <div className="preview-pane">
      <div className="preview-stage preview-stage--large">
        {view === null && (
          <div className="image-placeholder">
            <span>Point at something on the left</span>
          </div>
        )}
        {view?.kind === "video" && (
          /* Its own controls, not the carousel button: a click on a
                clip is play or seek (ADR-0045). Keyed by the file, so
                pointing at another clip starts that one afresh. */
          <video
            key={view.picture}
            className="preview-stage__video"
            src={view.picture}
            aria-label={view.title}
            controls
            playsInline
            preload="metadata"
          />
        )}
        {view?.kind === "image" && adjusting !== null && (
          <PositionStage
            positioning={adjusting}
            picture={view.picture}
            title={view.title}
            artwork={artwork}
          />
        )}
        {view?.kind === "image" && adjusting === null && (
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
              if (view.reelIndex >= 0) onOpen(view.reelIndex);
            }}
          >
            <StagePicture src={view.picture} alt={view.title} positioning={positioning} />
          </button>
        )}
      </div>

      {/* Always there, so the reel below does not jump when the stage
            first gets something to show. */}
      <div className={positioning === null ? "preview-foot" : "preview-foot tp-foot"}>
        {view !== null && (
          <>
            <span className="preview-meta">
              <span className="preview-meta__title">{view.title}</span>
              <span className="preview-meta__path">{view.path}</span>
              {view.notes.map((note) => (
                <span
                  key={note.message}
                  className={`preview-meta__note preview-meta__note--${note.severity}`}
                >
                  {note.message}
                </span>
              ))}
              <PositionNote note={positioning?.note ?? null} />
            </span>
            <FootActions positioning={positioning}>
              <button
                type="button"
                className={
                  view.inListing
                    ? "btn-like btn-like--ghost btn-sm"
                    : "btn-like btn-like--primary btn-sm"
                }
                onClick={onToggle}
              >
                {view.inListing ? "Remove from listing" : "+ Add to listing"}
              </button>
            </FootActions>
          </>
        )}
      </div>
    </div>
  );
}

/** The saved listing's scenes, signed by each template's *saved* position
 * too, so the composite changes when a position save lands (ADR-0058). */
function listingScene(detail: ListingDetail, saved: Positions | null | undefined) {
  const signatures = Object.fromEntries(
    Object.entries(saved ?? {}).map(([template, entry]) => [template, positionSignature(entry)]),
  );
  return sceneSource(detail.name, detail.design_content_hash, signatures);
}

/** The listing's artwork, flat on the box while a position gesture is unsaved. */
function overlayArtwork(detail: ListingDetail): string | null {
  const design = representative(detail.design);
  return design === null ? null : listingDesignThumbnailUrl(refName(design));
}

/** The pane's own action, beside the position controls when the entry has them. */
function FootActions({
  positioning,
  children,
}: {
  positioning: Positioning | null;
  children: ReactNode;
}) {
  if (positioning === null) return <span className="preview-actions">{children}</span>;
  return <PositionControls positioning={positioning}>{children}</PositionControls>;
}
