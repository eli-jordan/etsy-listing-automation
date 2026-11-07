import { MagnifyingGlassIcon } from "@phosphor-icons/react/dist/csr/MagnifyingGlass";
import { useMemo, useState } from "react";
import { holdsLabels } from "../../components/labelRules";
import { LabelSearch } from "../../components/LabelSearch";
import { MutedClip } from "../../components/MutedClip";
import { useHoverPlay } from "../../hooks/useHoverPlay";
import { mediaKind, pictureFor, type MediaOwner } from "../../media";
import type { ListingDetail, MediaFileSummary, TemplateSummary } from "../../types";
import {
  isNullableString,
  isString,
  isStringList,
  useViewState,
  type ViewScope,
} from "./editorView";
import type { Focus } from "./focus";
import { LocatorTemplate } from "./LocatorTemplate";
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
 * *Files* is one list in two groups, one per root a ref can name:
 * *This listing* for the listing's own directory and *Shared* for
 * `common-media/`. The ref roots are an implementation detail rather than
 * useful navigation, and an empty root is omitted. Images and videos sit together, because `media:` is one
 * gallery; a video is drawn by a muted `<video>` from its own first
 * frame, carries its length, and plays on hover.
 *
 * Its own state is what it is *showing* (which half, the search and its label
 * pills, which template is expanded). What a click *means* belongs to `mediaEdits`, and where the
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
  /** Whose `./` files `local` are: the listing by default, or a listing
   * template, whose group reads *This template* (UI doc, *Existing
   * components the template editor needs*). */
  owner?: MediaOwner | null;
  /** Whose view a refresh comes back to, when there is one to come back to. */
  scope?: ViewScope;
}

/** Which half of `media:` the locator is browsing. */
type LocatorMode = "templates" | "files";

function isLocatorMode(value: unknown): value is LocatorMode {
  return value === "templates" || value === "files";
}

/** `0:06`, `1:15` -- a clip's length as the badge shows it. */
function clipLength(seconds: number): string {
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

interface FileTileProps {
  asset: MediaFileSummary;
  listing: MediaOwner | string | null;
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
  owner,
  scope = null,
}: Props) {
  const [mode, setMode] = useViewState<LocatorMode>(
    scope,
    "locator-mode",
    "templates",
    isLocatorMode,
  );
  const [query, setQuery] = useViewState(scope, "locator-query", "", isString);
  const [openTemplate, setOpenTemplate] = useViewState<string | null>(
    scope,
    "locator-template",
    null,
    isNullableString,
  );

  // Not reconciled with the labels in use: a pill the templates have lost stays on
  // show, because an empty list with no visible reason reads as a broken one.
  const [pills, setPills] = useViewState<string[]>(scope, "locator-labels", [], isStringList);

  // Calibrated only, here and in the box: it offers and counts what the locator
  // can list (spec *Listing Images*).
  const calibrated = useMemo(() => templates.filter((t) => t.status === "calibrated"), [templates]);
  const labelLists = useMemo(() => calibrated.map((t) => t.labels), [calibrated]);
  const term = query.trim().toLowerCase();
  const filtered = calibrated.filter(
    (t) => holdsLabels(t.labels, pills) && t.name.toLowerCase().includes(term),
  );
  const needle = query.toLowerCase();
  const matches = (a: MediaFileSummary) => a.name.toLowerCase().includes(needle);
  const listing = owner === undefined ? detail.name || null : owner;
  const groups = [
    ...(local === null
      ? []
      : [
          {
            label: owner?.kind === "listing-template" ? "This template" : "This listing",
            files: local,
          },
        ]),
    {
      label: "Shared",
      files: shared,
    },
  ].filter((group) => group.files.length > 0);
  const nothingMatches =
    groups.some((g) => g.files.length > 0) && groups.every((g) => !g.files.some(matches));
  const swatchTemplate = detail.etsy.variation_images ?? null;
  const videoLimitReached =
    detail.media.filter((entry) => mediaKind(entry) === "video").length >= MAX_VIDEOS;

  return (
    <div className="locator">
      <div className="locator__head">
        <span className="locator__title">Add media</span>
        <span className="locator__hint">Hover to preview · click to add</span>
      </div>

      <div className="seg locator__modes">
        {(["templates", "files"] as LocatorMode[]).map((m) => (
          <button
            key={m}
            type="button"
            className={mode === m ? "seg-opt seg-opt--on" : "seg-opt"}
            aria-pressed={mode === m}
            // The query is cleared on the way across: "flat" means nothing
            // in common-media/, and a list that looks empty because of a
            // search you cannot see reads as a list with nothing in it. Pills
            // stay: Files never shows them, and they are there on return.
            onClick={() => {
              setMode(m);
              setQuery("");
            }}
          >
            {m === "templates" ? "Mockup templates" : "Files"}
          </button>
        ))}
      </div>

      {mode === "templates" && (
        <>
          <LabelSearch
            items={labelLists}
            on={pills}
            onOn={setPills}
            query={query}
            onQuery={setQuery}
          />
          <div className="locator__result" role="status">
            {`${filtered.length} of ${calibrated.length} template${calibrated.length === 1 ? "" : "s"}`}
          </div>
        </>
      )}

      {mode === "files" && (
        <div className="locator__search">
          <MagnifyingGlassIcon className="locator__glass" weight="bold" />
          <input
            className="input"
            type="text"
            placeholder="Search files…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
      )}

      {mode === "files" && (
        <div className="locator__list">
          {videoLimitReached && (
            <p className="locator__limit" id="video-limit" role="status">
              {MAX_VIDEOS}-video limit reached — remove one before adding another.
            </p>
          )}
          {groups.map((g) => {
            const visible = g.files.filter(matches);
            if (visible.length === 0) return null;
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
              </div>
            );
          })}
          {nothingMatches && <p className="locator__empty">No file matches that search.</p>}
        </div>
      )}

      {mode === "templates" && (
        <div className="locator__list">
          {filtered.map((t) => (
            <LocatorTemplate
              key={t.name}
              template={t}
              detail={detail}
              open={openTemplate === t.name}
              onToggleOpen={() =>
                setOpenTemplate((current) => (current === t.name ? null : t.name))
              }
              swatchTemplate={swatchTemplate}
              actions={{ onToggleTemplate, onAddMissingColours, onToggleSwatchSource, onFocus }}
            />
          ))}
          {filtered.length === 0 && <p className="locator__empty">No template matches.</p>}
        </div>
      )}
    </div>
  );
}
