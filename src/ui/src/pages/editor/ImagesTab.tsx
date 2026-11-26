import { type ReactNode, useCallback, useEffect, useState } from "react";
import { listTemplates, templatePhotoUrl } from "../../api/calibrator";
import { listCommonMedia, listListingMediaFiles, listingSceneArtworkUrl } from "../../api/listings";
import { listListingTemplateMediaFiles } from "../../api/listingTemplates";
import { maskUrl } from "../../api/preparation";
import { Lightbox, type LightboxItem } from "../../components/Lightbox";
import {
  type Artwork,
  type MediaOwner,
  mediaKind,
  mediaLabel,
  pictureFor,
  sceneSource,
} from "../../media";
import type { MediaFileSummary, ListingDetail, TemplateSummary } from "../../types";
import { MediaLocator } from "./MediaLocator";
import { MediaReel } from "./MediaReel";
import { PhoneScreen } from "../../phone/PhoneScreen";
import { PhoneSheet } from "../../phone/PhoneSheet";
import { useIsPhone, useIsPhoneLandscape } from "../../phone/usePhone";
import { isBoolean, isNullableNumber, useViewState, viewScope } from "./editorView";
import {
  type Focus,
  type FocusRef,
  type FocusView,
  firstFocus,
  focusRef,
  isFocusRef,
  restoreFocus,
  viewFocus,
} from "./focus";
import * as edits from "./mediaEdits";
import { type Positions, positionSignature } from "./positions/document";
import { PositionControls, PositionNote } from "./positions/PositionControls";
import { PositionStage } from "./positions/PositionStage";
import type { LiveSource } from "./positions/useLiveScene";
import {
  type Positioning,
  positionTarget,
  usePositioning,
  useSavedPositions,
} from "./positions/usePositioning";
import "./positions/positions.css";

interface Props {
  detail: ListingDetail;
  onUpdate: (patch: Record<string, unknown>) => void;
  artwork?: Artwork | null;
  owner?: MediaOwner | null;
  onFlush?: () => void;
}

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
  const landscape = useIsPhoneLandscape();
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

  const { adjusting, startAdjusting, stopAdjusting } = useAdjustSheet();

  function pointAt(next: Focus) {
    setPointed(next);
    setRemembered(focusRef(next));
    stopAdjusting();
  }

  const letGo = useCallback(() => {
    setPointed(null);
    setRemembered(null);
    stopAdjusting();
  }, [setRemembered, stopAdjusting]);

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

  const saved = useSavedPositions(detail);
  const scene: Artwork | null = artwork !== undefined ? artwork : listingScene(detail, saved);

  function apply(patch: Record<string, unknown> | null) {
    if (patch !== null) onUpdate(patch);
  }

  const lightboxItems: LightboxItem[] = detail.media.map((entry, index) => ({
    id: `${mediaLabel(entry)}-${index}`,
    label: mediaLabel(entry),
    url: pictureFor(entry, scene, "full", listing),
    kind: mediaKind(entry),
  }));

  const files = directory === null ? shared : [...local, ...shared];
  const phone = useIsPhone();
  const upright = isUpright(phone, landscape);
  const focus =
    pointed ??
    restoreFocus(remembered, templates, files) ??
    opening(upright, detail, templates, files);
  const view = focus === null ? null : viewFocus(focus, detail, templates, scene, listing);
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
    // Only Adjust's screen shows the pane on an upright phone.
    steady: upright,
  });

  const adjustable = adjustTarget(upright, selectedIndex, positioning);
  const [adding, setAdding] = useState(false);
  const closeAdding = useCallback(() => setAdding(false), []);
  const locator = (
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
  );

  const pane = (
    <PreviewPane
      view={view}
      positioning={positioning}
      source={liveSource(detail, focus)}
      onOpen={setLightboxIndex}
      onToggle={toggleFocused}
      phone={phone}
      steady={upright}
    />
  );

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
      {phone ? (
        <PhoneSheet
          open={adding}
          title="Add media"
          onClose={closeAdding}
          className="add-media-sheet"
        >
          {locator}
        </PhoneSheet>
      ) : (
        locator
      )}

      <div className="images-right">
        {upright ? null : pane}

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
          {...phoneReel(phone, {
            onAdd: () => setAdding(true),
            onView: setLightboxIndex,
            onDeselect: letGo,
            onAdjust: adjustHandler(adjustable, startAdjusting),
          })}
        />

        <p role="status" className="app__status">
          {status}
        </p>
      </div>

      <AdjustScreen open={adjusting} target={adjustable} view={view} onClose={stopAdjusting}>
        {pane}
      </AdjustScreen>

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

/** Adjust, on an upright phone: whether its screen is open, and its way in
 * -- straight into Position mode, since adjusting is what it is for. */
function useAdjustSheet() {
  const [adjusting, setAdjusting] = useState(false);
  const stopAdjusting = useCallback(() => setAdjusting(false), []);
  const startAdjusting = useCallback((positioning: Positioning) => {
    setAdjusting(true);
    if (!positioning.on) positioning.toggle();
  }, []);
  return { adjusting, startAdjusting, stopAdjusting };
}

/** What the stage shows before the seller points at anything: the reel's
 * first picture, so reviewing starts without a click. Not on an upright
 * phone, where there is no pane and a selection is only a moves bar. */
function opening(
  upright: boolean,
  detail: ListingDetail,
  templates: readonly TemplateSummary[],
  files: readonly MediaFileSummary[],
): Focus | null {
  return upright ? null : firstFocus(detail.media, templates, files);
}

function isUpright(phone: boolean, landscape: boolean): boolean {
  return phone && !landscape;
}

function adjustTarget(
  upright: boolean,
  selectedIndex: number | null,
  positioning: Positioning | null,
): Positioning | null {
  return upright && selectedIndex !== null ? positioning : null;
}

function phoneReel(
  phone: boolean,
  handlers: {
    onAdd: () => void;
    onView: (index: number) => void;
    onDeselect: () => void;
    onAdjust: (() => void) | undefined;
  },
) {
  if (!phone) return {};
  const { onAdjust, ...rest } = handlers;
  return onAdjust === undefined ? rest : { ...rest, onAdjust };
}

function adjustHandler(
  target: Positioning | null,
  start: (positioning: Positioning) => void,
): (() => void) | undefined {
  return target === null ? undefined : () => start(target);
}

function AdjustScreen({
  open,
  target,
  view,
  onClose,
  children,
}: {
  open: boolean;
  target: Positioning | null;
  view: FocusView | null;
  onClose: () => void;
  children: ReactNode;
}) {
  if (!open || target === null || view === null) return null;
  return (
    <PhoneScreen title={view.title} onClose={onClose} className="adjust-screen">
      {children}
    </PhoneScreen>
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

function emptyStageText(phone: boolean): string {
  return phone ? "Tap an image in the gallery to see it here" : "Point at something on the left";
}

function PreviewPane({
  view,
  positioning,
  source,
  onOpen,
  onToggle,
  phone,
  steady,
}: {
  view: FocusView | null;
  positioning: Positioning | null;
  source: LiveSource | null;
  onOpen: (index: number) => void;
  onToggle: () => void;
  phone: boolean;
  /** Adjust's screen: the foot the same with the switch on or off, so no
   * Add or Remove (the reel's bar removes) appearing as it turns off. */
  steady: boolean;
}) {
  const adjusting = positioning?.on === true ? positioning : null;
  return (
    <div className="preview-pane">
      <div className="preview-stage preview-stage--large">
        {view === null && (
          <div className="image-placeholder">
            <span>{emptyStageText(phone)}</span>
          </div>
        )}
        {view?.kind === "video" && (
          /* Its own controls, not the carousel button: a click on a
                clip is play or seek (ADR-0045). Keyed by the file, so
                pointing at another clip starts that one afresh. */
          <video
            key={view.picture}
            className="preview-stage__video"
            {...(phone ? { "data-swipe-ignore": "" } : {})}
            src={view.picture}
            aria-label={view.title}
            controls
            playsInline
            preload="metadata"
          />
        )}
        {view?.kind === "image" && adjusting !== null && source !== null && (
          <PositionStage
            positioning={adjusting}
            picture={view.picture}
            title={view.title}
            source={source}
          />
        )}
        {view?.kind === "image" && adjusting === null && (
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
            <FootActions positioning={positioning} steady={steady}>
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

function listingScene(detail: ListingDetail, saved: Positions | null | undefined) {
  const signatures = Object.fromEntries(
    Object.entries(saved ?? {}).map(([template, entry]) => [template, positionSignature(entry)]),
  );
  return sceneSource(detail.name, detail.design_content_hash, signatures);
}

function liveSource(detail: ListingDetail, focus: Focus | null): LiveSource | null {
  if (focus?.kind !== "template") return null;
  const { template, colour } = focus;
  const version = detail.design_content_hash ?? "";
  return {
    photo: templatePhotoUrl(template, colour),
    artwork: (placement) =>
      listingSceneArtworkUrl(detail.name, template, colour, placement, version),
    mask: (placement) => maskUrl(template, placement),
  };
}

function FootActions({
  positioning,
  steady,
  children,
}: {
  positioning: Positioning | null;
  steady: boolean;
  children: ReactNode;
}) {
  if (positioning === null) return <span className="preview-actions">{children}</span>;
  if (steady) return <PositionControls positioning={positioning} />;
  return <PositionControls positioning={positioning}>{children}</PositionControls>;
}
