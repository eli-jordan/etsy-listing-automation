import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { LinkBreakIcon } from "@phosphor-icons/react/dist/csr/LinkBreak";
import { LinkSimpleIcon } from "@phosphor-icons/react/dist/csr/LinkSimple";
import { useEffect, useState } from "react";
import {
  listGarmentProfiles,
  listingDesignThumbnailUrl,
  listListingDesigns,
} from "../../api/listings";
import { refName } from "../../media";
import type { DesignMap, ListingDesignSummary } from "../../types";
import { ArtworkPicker } from "./ArtworkPicker";
import {
  cap,
  isLinked,
  linking,
  keepOne,
  listNames,
  pickFor,
  slotFile,
  slotUsers,
  TILE,
  toneLabel,
  unlinked,
  type SlotTarget,
  type Tone,
} from "./artwork";
import { ChooseBaseDialog } from "./ChooseBaseDialog";

/**
 * The design strip above the tabs: always two cards, for light and for dark
 * shirts, joined by a link (interactions Part 1 §1-§5, Part 2 §1-§4).
 *
 * It sits outside the tabs because the artwork is what both Variants and
 * Listing Images are *about*. Linked is one design (`design.default`), and
 * the dark card only mirrors the light one -- showing, before it is needed,
 * that light and dark shirts *can* differ. Unlinking, or choosing a different
 * file for dark shirts, splits the pair into `on-light` / `on-dark`; linking
 * again asks which file to keep when there are two. Every change is one
 * `onChange` with the whole new map, built by `artwork.ts`'s transitions.
 *
 * Which Recent designs panel is open is the shell's state, not the strip's,
 * so the card under the Variants stage can open a slot's panel too.
 */

interface Props {
  design: DesignMap;
  /** The colours the listing sells -- which ones each slot prints on. */
  colours: readonly string[];
  garmentProfile: string;
  open: SlotTarget | null;
  onOpen: (target: SlotTarget | null) => void;
  /** The new `design:` map, and the file a pick chose, if a pick made it. */
  onChange: (next: DesignMap, picked: string | null) => void;
  /** Previews a colour on the Variants stage: the own-design line's names. */
  onPreview: (colour: string) => void;
}

/** How many the strip offers before the full list is needed. Four fills one
 * row of the picker grid; the rest are a search away. */
const RECENT = 4;

const sameTarget = (a: SlotTarget | null, b: SlotTarget) =>
  a !== null && a.kind === b.kind && (a.kind === "one" || (b.kind === "slot" && a.tone === b.tone));

function targetLabel(target: SlotTarget): string {
  return target.kind === "one" ? "all shirts" : toneLabel(target.tone);
}

export function ArtworkStrip({
  design,
  colours,
  garmentProfile,
  open,
  onOpen,
  onChange,
  onPreview,
}: Props) {
  const [library, setLibrary] = useState<ListingDesignSummary[]>([]);
  const [tones, setTones] = useState<Record<string, Tone>>({});
  const [finding, setFinding] = useState<SlotTarget | null>(null);
  const [choosing, setChoosing] = useState<{ light: string; dark: string } | null>(null);

  useEffect(() => {
    listListingDesigns()
      .then(setLibrary)
      .catch(() => setLibrary([]));
  }, []);

  useEffect(() => {
    let current = true;
    listGarmentProfiles()
      .then((profiles) => {
        if (current) setTones(profiles.find((p) => p.name === garmentProfile)?.colors ?? {});
      })
      .catch(() => undefined);
    return () => {
      current = false;
    };
  }, [garmentProfile]);

  const split = !isLinked(design);
  const users = slotUsers(design, colours, tones);
  const own = colours.filter((c) => (design[c] ?? null) !== null);

  // Linked, the light card is the one design for every shirt.
  const lightTarget: SlotTarget = split ? { kind: "slot", tone: "light" } : { kind: "one" };
  const darkTarget: SlotTarget = { kind: "slot", tone: "dark" };

  function pick(target: SlotTarget, ref: string) {
    onChange(pickFor(design, target, ref), ref);
    onOpen(null);
    setFinding(null);
  }

  function link() {
    const outcome = linking(design);
    if (outcome.kind === "linked") onChange(outcome.design, null);
    else setChoosing({ light: outcome.light, dark: outcome.dark });
  }

  const everyShirt =
    own.length > 0
      ? "Prints on every colour without its own design"
      : "Prints on every colour you sell";

  const slot = (target: SlotTarget, tone: Tone) => {
    const mirrored = !split && tone === "dark";
    return (
      <Slot
        title={!split && tone === "light" ? "For all shirts" : `For ${toneLabel(tone)}`}
        target={target}
        file={slotFile(design, target)}
        tile={TILE[tone]}
        usedBy={
          split
            ? users[tone].length === 0
              ? null
              : `Prints on ${listNames(users[tone])}`
            : tone === "light"
              ? everyShirt
              : "Same as all shirts"
        }
        open={sameTarget(open, target)}
        missing={split && slotFile(design, target) === null && users[tone].length > 0}
        mirrored={mirrored}
        emptyText={split ? `Choose the design for ${toneLabel(tone)}` : "No design selected"}
        onChange={() => onOpen(sameTarget(open, target) ? null : target)}
      />
    );
  };

  return (
    <div className="design-select design-select--pair">
      {own.length > 0 && (
        <div className="design-select__head">
          <span className="design-select__own">
            Also printing their own design:{" "}
            {own.map((colour, i) => (
              <span key={colour}>
                {i > 0 && ", "}
                <button
                  type="button"
                  className="design-select__colour"
                  onClick={() => onPreview(colour)}
                >
                  {cap(colour)}
                </button>
              </span>
            ))}
          </span>
        </div>
      )}

      <div className="design-pair">
        {slot(lightTarget, "light")}
        <button
          type="button"
          className={split ? "design-link" : "design-link design-link--on"}
          aria-pressed={!split}
          title={split ? "Use one design for all shirts" : "Use a different design for dark shirts"}
          onClick={() => {
            onOpen(null);
            if (split) link();
            else onChange(unlinked(design), null);
          }}
        >
          {split ? (
            <LinkSimpleIcon weight="bold" aria-hidden="true" />
          ) : (
            <LinkBreakIcon weight="bold" aria-hidden="true" />
          )}
          <span>{split ? "Link" : "Unlink"}</span>
        </button>
        {slot(darkTarget, "dark")}
      </div>

      {open !== null && (
        <div className="add-panel">
          <span className="section-label">Recent designs for {targetLabel(open)}</span>
          <div className="template-grid">
            {library.slice(0, RECENT).map((d) => (
              <button
                key={d.file}
                type="button"
                className={
                  slotFile(design, open) === d.file
                    ? "template-card template-card--active"
                    : "template-card"
                }
                // PRD 73: a ref with no prefix is the workspace root, so the
                // design's workspace-relative path is already the ref.
                onClick={() => pick(open, d.file)}
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
              setFinding(open);
              onOpen(null);
            }}
          >
            Find a design…
          </button>
        </div>
      )}

      {finding !== null && (
        <ArtworkPicker
          title={`Design for ${targetLabel(finding)}`}
          hint={
            finding.kind === "one"
              ? "Every colour prints it, apart from any with their own design."
              : users[finding.tone].length > 0
                ? `Prints on ${listNames(users[finding.tone])}.`
                : "No colour you sell uses it right now."
          }
          tile={finding.kind === "one" ? TILE.neutral : TILE[finding.tone]}
          current={slotFile(design, finding)}
          library={library}
          onPick={(ref) => pick(finding, ref)}
          onClose={() => setFinding(null)}
        />
      )}

      {choosing !== null && (
        <ChooseBaseDialog
          light={choosing.light}
          dark={choosing.dark}
          onKeep={(ref) => {
            setChoosing(null);
            onChange(keepOne(design, ref), null);
          }}
          onCancel={() => setChoosing(null)}
        />
      )}
    </div>
  );
}

function Slot({
  title,
  target,
  file,
  tile,
  usedBy,
  open,
  missing,
  mirrored,
  emptyText,
  onChange,
}: {
  title: string;
  target: SlotTarget;
  file: string | null;
  tile: string;
  /** The "Prints on …" line; `null` when the slot is unused. */
  usedBy: string | null;
  open: boolean;
  /** Empty, and a colour the listing sells needs it. */
  missing: boolean;
  /** Linked: showing the light card's file, not its own. */
  mirrored: boolean;
  emptyText: string;
  onChange: () => void;
}) {
  const cls = [
    "design-row",
    "design-row--slot",
    missing ? "design-row--missing" : "",
    mirrored ? "design-row--mirrored" : "",
    open ? "design-row--open" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const label = targetLabel(target);
  const [verb, action] = mirrored
    ? ["Use a different one", `Use a different design for ${label}`]
    : file === null
      ? ["Choose", `Choose design for ${label}`]
      : ["Change", `Change design for ${label}`];
  return (
    <div className={cls}>
      {file !== null ? (
        <span className="design-thumb design-tile" style={{ background: tile }}>
          <img src={listingDesignThumbnailUrl(refName(file))} alt="" loading="lazy" />
        </span>
      ) : (
        <span className="design-thumb design-tile--empty" />
      )}
      <div className="design-row__text">
        <div className="design-row__title">{title}</div>
        {file !== null ? (
          <div className="design-row__name">
            {refName(file)}
            {mirrored && <span className="design-row__same"> · linked</span>}
          </div>
        ) : (
          <div className="design-row__name design-row__name--empty">{emptyText}</div>
        )}
        <div
          className={
            usedBy === null ? "design-row__users design-row__users--idle" : "design-row__users"
          }
        >
          {usedBy ?? "Not used — no colour you sell needs it"}
        </div>
      </div>
      <button
        type="button"
        className="design-row__change"
        aria-label={action}
        aria-expanded={open}
        onClick={onChange}
      >
        {verb} <CaretDownIcon weight="bold" aria-hidden="true" />
      </button>
    </div>
  );
}
