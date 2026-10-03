import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { LinkBreakIcon } from "@phosphor-icons/react/dist/csr/LinkBreak";
import { LinkSimpleIcon } from "@phosphor-icons/react/dist/csr/LinkSimple";
import { cap, listNames, slotUsers, TILE, toneLabel, type Base, type Colour, type Design, type Tone } from "./artwork";
import type { PickTarget } from "./ArtworkEditorScreen";

/** Base slots offer this many before the full list is needed -- the same
 * four the design strip offers today. */
const RECENT = 4;

export type SlotTarget = Exclude<PickTarget, { kind: "colour" }>;

const sameTarget = (a: SlotTarget | null, b: SlotTarget) =>
  a !== null && a.kind === b.kind && (a.kind === "one" || (b.kind === "slot" && a.tone === b.tone));

/**
 * The design strip above the tabs: always two cards, for light and for dark
 * shirts, joined by a link. Linked is one design (`design.default`) -- the
 * dark card mirrors the light one. Unlinking, or choosing a different file for
 * dark shirts, splits them into `on-light` / `on-dark`; linking again asks
 * which file to keep.
 */
export function ArtworkStrip({
  base,
  colours,
  library,
  open,
  setOpen,
  onLink,
  onUnlink,
  onPick,
  onFind,
  onPreview,
}: {
  base: Base;
  colours: Colour[];
  library: Design[];
  /** The slot whose Recent designs panel is open -- held by the screen, so
   * the preview card can open it too. */
  open: SlotTarget | null;
  setOpen: (t: SlotTarget | null) => void;
  onLink: () => void;
  onUnlink: () => void;
  onPick: (target: PickTarget, design: Design) => void;
  /** Opens the full design list for a target. */
  onFind: (target: PickTarget) => void;
  onPreview: (name: string) => void;
}) {
  const own = colours.filter((c) => c.enabled && c.own !== null);
  const split = base.mode === "light-dark";
  const toggleOpen = (t: SlotTarget) => setOpen(sameTarget(open, t) ? null : t);
  const users = (tone: Tone) => slotUsers(colours, tone).map((c) => c.name);

  const current = (t: SlotTarget): Design | null =>
    t.kind === "one" ? (base.mode === "one" ? base.design : null) : base.mode === "light-dark" ? base[t.tone] : base.design;

  // Linked, the light card is the one design for every shirt.
  const lightTarget: SlotTarget = split ? { kind: "slot", tone: "light" } : { kind: "one" };
  const darkTarget: SlotTarget = { kind: "slot", tone: "dark" };

  // Linked, the light card's design prints on every shirt, and says so; the
  // dark card only mirrors it.
  const everyShirt = own.length > 0 ? "Prints on every colour without its own design" : "Prints on every colour you sell";
  const slot = (t: SlotTarget, tone: Tone, mirrored: boolean) => (
    <Slot
      title={!split && tone === "light" ? "For all shirts" : `For ${toneLabel(tone)}`}
      design={current(t)}
      tile={TILE[tone]}
      users={users(tone)}
      usedBy={
        split ? null : tone === "light" ? everyShirt : "Same as all shirts"
      }
      open={sameTarget(open, t)}
      missing={split && current(t) === null && users(tone).length > 0}
      mirrored={mirrored}
      emptyText={split ? `Choose the design for ${toneLabel(tone)}` : "No design selected"}
      onChange={() => toggleOpen(t)}
    />
  );

  return (
    <div className="design-select ma-strip">
      {own.length > 0 && (
        <div className="ma-strip__head">
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
        </div>
      )}

      <div className="ma-slots ma-slots--linked">
        {slot(lightTarget, "light", false)}
        <button
          type="button"
          className={split ? "ma-chain" : "ma-chain ma-chain--on"}
          aria-pressed={!split}
          title={split ? "Use one design for all shirts" : "Use a different design for dark shirts"}
          onClick={() => {
            setOpen(null);
            if (split) onLink();
            else onUnlink();
          }}
        >
          {split ? <LinkSimpleIcon weight="bold" aria-hidden="true" /> : <LinkBreakIcon weight="bold" aria-hidden="true" />}
          <span>{split ? "Link" : "Unlink"}</span>
        </button>
        {slot(darkTarget, "dark", !split)}
      </div>

      {open !== null && (
        <div className="add-panel ma-recent">
          <span className="section-label">
            Recent designs{open.kind === "slot" ? ` for ${toneLabel(open.tone)}` : " for all shirts"}
          </span>
          <div className="template-grid">
            {library.slice(0, RECENT).map((d) => (
              <button
                key={d.file}
                type="button"
                className={current(open)?.file === d.file ? "template-card template-card--active" : "template-card"}
                onClick={() => {
                  onPick(open, d);
                  setOpen(null);
                }}
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
              onFind(open);
              setOpen(null);
            }}
          >
            Find a design…
          </button>
        </div>
      )}
    </div>
  );
}

function Slot({
  title,
  design,
  tile,
  users,
  usedBy: usedByText,
  open,
  missing,
  mirrored,
  emptyText,
  onChange,
}: {
  title: string;
  design: Design | null;
  tile: string;
  users: string[];
  /** Overrides the "Prints on …" line -- linked, both cards speak for every shirt. */
  usedBy: string | null;
  open: boolean;
  missing: boolean;
  /** Linked: showing the light card's file, not its own. */
  mirrored: boolean;
  emptyText: string;
  onChange: () => void;
}) {
  const usedBy = usedByText ?? (users.length === 0 ? "Not used — no colour you sell needs it" : `Prints on ${listNames(users)}`);
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
        <div className="ma-slot__title">{title}</div>
        {design !== null ? (
          <div className="design-row__name">
            {design.name}
            {mirrored && <span className="ma-slot__same"> · linked</span>}
          </div>
        ) : (
          <div className="design-row__name design-row__name--empty">{emptyText}</div>
        )}
        <div className={usedByText === null && users.length === 0 ? "ma-slot__users ma-slot__users--idle" : "ma-slot__users"}>{usedBy}</div>
      </div>
      <button type="button" className="design-row__change" aria-expanded={open} onClick={onChange}>
        {mirrored ? "Use a different one" : design === null ? "Choose" : "Change"} <CaretDownIcon weight="bold" aria-hidden="true" />
      </button>
    </div>
  );
}
