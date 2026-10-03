import type { ReactNode } from "react";
import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { CircleHalfIcon } from "@phosphor-icons/react/dist/csr/CircleHalf";
import { LinkBreakIcon } from "@phosphor-icons/react/dist/csr/LinkBreak";
import { LinkSimpleIcon } from "@phosphor-icons/react/dist/csr/LinkSimple";
import { cap, listNames, slotUsers, TILE, toneLabel, type Base, type Colour, type Design, type Tone } from "./_artwork";
import type { PickTarget } from "./_ArtworkEditorScreen";

/**
 * How the strip offers the choice between one design and a light/dark pair.
 * `segmented` is v1; the other five are the mode-switch round's options.
 */
export type ModeControl = "segmented" | "switch" | "link" | "menu" | "linked" | "select";

/** Base slots offer this many before the full list is needed -- the same
 * four the design strip offers today. */
const RECENT = 4;

export type SlotTarget = Exclude<PickTarget, { kind: "colour" }>;

const sameTarget = (a: SlotTarget | null, b: SlotTarget) =>
  a !== null && a.kind === b.kind && (a.kind === "one" || (b.kind === "slot" && a.tone === b.tone));

export function ArtworkStrip({
  control,
  base,
  colours,
  library,
  open,
  setOpen,
  onOne,
  onLightDark,
  onPick,
  onFind,
  onPreview,
}: {
  control: ModeControl;
  base: Base;
  colours: Colour[];
  library: Design[];
  /** The base slot whose Recent designs panel is open -- held by the screen,
   * so the preview card can open it too. */
  open: SlotTarget | null;
  setOpen: (t: SlotTarget | null) => void;
  onOne: () => void;
  onLightDark: () => void;
  onPick: (target: PickTarget, design: Design) => void;
  /** Opens the full design list for a target. */
  onFind: (target: PickTarget) => void;
  onPreview: (name: string) => void;
}) {
  const own = colours.filter((c) => c.enabled && c.own !== null);
  const split = base.mode === "light-dark";
  const toggleOpen = (t: SlotTarget) => setOpen(sameTarget(open, t) ? null : t);

  const current = (t: SlotTarget): Design | null =>
    t.kind === "one" ? (base.mode === "one" ? base.design : null) : base.mode === "light-dark" ? base[t.tone] : base.design;

  const ownNote = own.length > 0 && (
    <span className="ma-strip__own">
      Also printing their own design:{" "}
      {own.map((c, i) => (
        <span key={c.name}>
          {i > 0 && ", "}
          <button type="button" className="ma-link" onClick={() => onPreview(c.name)}>
            {cap(c.name)}
          </button>
        </span>
      ))}
    </span>
  );

  const switchMode = () => {
    setOpen(null);
    if (split) onOne();
    else onLightDark();
  };

  /* — the head line: the mode control itself, where it has one — */
  let head: ReactNode = null;
  if (control === "segmented") {
    head = (
      <div className="seg ma-mode" role="radiogroup" aria-label="Artwork">
        <label className="seg-opt">
          <input type="radio" name="ma-mode" checked={!split} onChange={onOne} />
          One design for all shirts
        </label>
        <label className="seg-opt">
          <input type="radio" name="ma-mode" checked={split} onChange={onLightDark} />
          Separate designs for light and dark shirts
        </label>
      </div>
    );
  } else if (control === "switch") {
    head = (
      <>
        <span className="section-label ma-strip__label">Artwork</span>
        <label className="ma-switch">
          <span>Separate designs for light and dark shirts</span>
          <button
            type="button"
            role="switch"
            aria-checked={split}
            aria-label="Separate designs for light and dark shirts"
            className={split ? "switch switch--on" : "switch"}
            onClick={switchMode}
          >
            <span className="switch__knob" />
          </button>
        </label>
      </>
    );
  } else if (control === "select") {
    head = (
      <label className="ma-sentence">
        <span className="section-label ma-strip__label">Artwork</span>
        <span className="ma-select-wrap">
          <select
            className="ma-select"
            value={split ? "light-dark" : "one"}
            onChange={(e) => (e.target.value === "one" ? onOne() : onLightDark())}
          >
            <option value="one">Same design on every shirt</option>
            <option value="light-dark">Different designs on light and dark shirts</option>
          </select>
          <CaretDownIcon weight="bold" aria-hidden="true" />
        </span>
      </label>
    );
  } else if (own.length > 0) {
    head = <span className="section-label ma-strip__label">Artwork</span>;
  }

  /* — the slots — */
  const slot = (t: SlotTarget, title: string | null, tile: string, users: string[] | null, extra?: Partial<SlotProps>) => (
    <Slot
      key={t.kind === "one" ? "one" : t.tone}
      title={title}
      design={current(t)}
      tile={tile}
      users={users}
      open={sameTarget(open, t)}
      missing={t.kind === "slot" && split && current(t) === null && (users?.length ?? 0) > 0}
      emptyText={t.kind === "one" ? "No design selected" : `Choose the design for ${toneLabel(t.tone)}`}
      onChange={() => toggleOpen(t)}
      {...extra}
    />
  );
  const users = (tone: Tone) => slotUsers(colours, tone).map((c) => c.name);

  let slots: ReactNode;
  if (control === "linked") {
    // Always two cards. Linked, the dark card mirrors the light one; picking a
    // different file for it is what splits them.
    slots = (
      <div className="ma-slots ma-slots--linked">
        {slot(split ? { kind: "slot", tone: "light" } : { kind: "one" }, "For light shirts", TILE.light, users("light"))}
        <button
          type="button"
          className={split ? "ma-chain" : "ma-chain ma-chain--on"}
          aria-pressed={!split}
          aria-label={split ? "Link: use one design for all shirts" : "Unlink: use a different design for dark shirts"}
          title={split ? "Use one design for all shirts" : "Use a different design for dark shirts"}
          onClick={switchMode}
        >
          {split ? <LinkBreakIcon weight="bold" aria-hidden="true" /> : <LinkSimpleIcon weight="bold" aria-hidden="true" />}
        </button>
        {slot({ kind: "slot", tone: "dark" }, "For dark shirts", TILE.dark, users("dark"), split ? {} : { mirrored: true })}
      </div>
    );
  } else if (split) {
    slots = (
      <div className="ma-slots">
        {slot({ kind: "slot", tone: "light" }, "For light shirts", TILE.light, users("light"))}
        {slot({ kind: "slot", tone: "dark" }, "For dark shirts", TILE.dark, users("dark"))}
      </div>
    );
  } else {
    slots = <div className="ma-slots ma-slots--one">{slot({ kind: "one" }, null, TILE.neutral, null)}</div>;
  }

  const modeLink = control === "link" && (
    <button type="button" className="ma-link ma-mode-link" onClick={switchMode}>
      <CircleHalfIcon weight="bold" aria-hidden="true" />
      {split ? "Use one design for all shirts" : "Use different designs on light and dark shirts"}
    </button>
  );

  return (
    <div className="design-select ma-strip">
      {(head !== null || (ownNote && control !== "segmented")) && (
        <div className="ma-strip__head">
          {head}
          {ownNote}
        </div>
      )}
      <div className={control === "link" && !split ? "ma-strip__row" : undefined}>
        {slots}
        {control === "link" && !split && modeLink}
      </div>
      {control === "link" && split && <div>{modeLink}</div>}

      {open !== null && (
        <RecentPanel
          target={open}
          label={open.kind === "one" ? null : `for ${toneLabel(open.tone)}`}
          designs={library.slice(0, RECENT)}
          current={current(open)}
          onPick={(d) => {
            onPick(open, d);
            setOpen(null);
          }}
          onFind={() => {
            onFind(open);
            setOpen(null);
          }}
          modeAction={
            control === "menu"
              ? {
                  label: split ? "Use one design for all shirts" : "Use separate designs for light and dark shirts",
                  run: switchMode,
                }
              : null
          }
        />
      )}
    </div>
  );
}

/* ── one base slot ───────────────────────────────────────────────────────── */

interface SlotProps {
  title: string | null;
  design: Design | null;
  tile: string;
  /** Colours printing this slot; `null` in one-design mode, where it is all of them. */
  users: string[] | null;
  open: boolean;
  missing?: boolean;
  /** Linked variant: showing the other card's file, not its own. */
  mirrored?: boolean;
  emptyText: string;
  onChange: () => void;
}

function Slot({ title, design, tile, users, open, missing = false, mirrored = false, emptyText, onChange }: SlotProps) {
  const usedBy =
    users === null ? null : users.length === 0 ? "Not used — no colour you sell needs it" : `Prints on ${listNames(users)}`;
  const cls = ["design-row", "ma-slot", missing ? "ma-slot--missing" : "", mirrored ? "ma-slot--mirrored" : "", open ? "ma-slot--open" : ""]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={cls}>
      {design !== null ? (
        <span className="design-thumb ma-tile" style={{ background: tile }}>
          <img src={design.url} alt="" />
        </span>
      ) : (
        <span className="design-thumb design-thumb--empty ma-tile--empty" />
      )}
      <div className="design-row__text">
        {title !== null && <div className="ma-slot__title">{title}</div>}
        {design !== null ? (
          <div className="design-row__name">
            {design.name}
            {mirrored && <span className="ma-slot__same"> · same as light shirts</span>}
          </div>
        ) : (
          <div className="design-row__name design-row__name--empty">{emptyText}</div>
        )}
        <div className={users !== null && users.length === 0 ? "ma-slot__users ma-slot__users--idle" : "ma-slot__users"}>
          {usedBy ?? design?.file ?? "Choose the artwork Variants and Listing Images are about"}
        </div>
      </div>
      <button type="button" className="design-row__change" aria-expanded={open} onClick={onChange}>
        {mirrored ? "Use a different one" : design === null ? "Choose" : "Change"} <CaretDownIcon weight="bold" aria-hidden="true" />
      </button>
    </div>
  );
}

/* ── the inline Recent designs panel, as today's strip has it ────────────── */

function RecentPanel({
  label,
  designs,
  current,
  onPick,
  onFind,
  modeAction,
}: {
  target: SlotTarget;
  label: string | null;
  designs: Design[];
  current: Design | null;
  onPick: (d: Design) => void;
  onFind: () => void;
  modeAction: { label: string; run: () => void } | null;
}) {
  return (
    <div className="add-panel ma-recent">
      <span className="section-label">Recent designs{label !== null && ` ${label}`}</span>
      <div className="template-grid">
        {designs.map((d) => (
          <button
            key={d.file}
            type="button"
            className={current?.file === d.file ? "template-card template-card--active" : "template-card"}
            onClick={() => onPick(d)}
          >
            <span className="template-card__name">{d.name}</span>
            <span className="template-card__kind">{d.file}</span>
          </button>
        ))}
      </div>
      <button type="button" className="btn-like btn-like--ghost btn-sm" onClick={onFind}>
        Find a design…
      </button>
      {modeAction !== null && (
        <div className="ma-recent__mode">
          <button type="button" className="ma-link ma-mode-link" onClick={modeAction.run}>
            <CircleHalfIcon weight="bold" aria-hidden="true" />
            {modeAction.label}
          </button>
        </div>
      )}
    </div>
  );
}
