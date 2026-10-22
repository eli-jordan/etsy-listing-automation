import { useState } from "react";
import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { MagnifyingGlassIcon } from "@phosphor-icons/react/dist/csr/MagnifyingGlass";
import { StatusTag } from "../../../../src/components/StatusTag";
import { IssuesBanner } from "../../../../src/pages/editor/IssuesBanner";
import {
  artworkIssues,
  listNames,
  resolve,
  resolvedDesign,
  slotUsers,
  toneLabel,
  type Base,
  type Colour,
  type Design,
  type Resolution,
  type Tone,
} from "./_artwork";
import { ShirtPreview } from "./_ShirtPreview";
import "./multiArtwork.css";

/** What a picker is choosing a file for. */
export type PickTarget = { kind: "one" } | { kind: "slot"; tone: Tone } | { kind: "colour"; name: string };

export interface ArtworkEditorProps {
  listing: string;
  profile: string;
  library: Design[];
  base: Base;
  colours: Colour[];
  previewed: string;
  /** Open on arrival, so a frame can show the picker or the dialog. */
  picking?: PickTarget | null;
  leaving?: boolean;
}

/** Cloth shown behind a thumbnail: artwork is judged on the shirt it is for. */
const TILE = { light: "#efe6d2", dark: "#262626", neutral: "var(--color-neutral-200)" };

const cap = (s: string) => s[0].toUpperCase() + s.slice(1);

/**
 * The listing editor with the artwork map editable (docs/multi-artwork-ui.md):
 * the design strip above the tabs chooses one design or a light/dark pair, and
 * each Variants row shows -- and can override -- the file its colour prints.
 * Mirrors `ListingEditorShell` + `VariantsTab`; only the artwork parts are new.
 */
export function ArtworkEditorScreen(props: ArtworkEditorProps) {
  const [base, setBase] = useState<Base>(props.base);
  const [colours, setColours] = useState<Colour[]>(props.colours);
  const [previewed, setPreviewed] = useState(props.previewed);
  const [picking, setPicking] = useState<PickTarget | null>(props.picking ?? null);
  const [leaving, setLeaving] = useState(props.leaving ?? false);

  const issues = artworkIssues(base, colours, props.profile);
  const shown = colours.find((c) => c.name === previewed) ?? colours[0];

  function enterLightDark() {
    if (base.mode === "light-dark") return;
    setBase({ mode: "light-dark", light: base.design, dark: base.design });
  }

  function enterOne() {
    if (base.mode === "one") return;
    const kept = [base.light, base.dark].filter((d): d is Design => d !== null);
    const distinct = kept.filter((d, i) => kept.findIndex((k) => k.file === d.file) === i);
    // Nothing to choose between: switch without asking.
    if (distinct.length <= 1) setBase({ mode: "one", design: distinct[0] ?? null });
    else setLeaving(true);
  }

  function pick(target: PickTarget, design: Design) {
    if (target.kind === "one") setBase({ mode: "one", design });
    if (target.kind === "slot" && base.mode === "light-dark") setBase({ ...base, [target.tone]: design });
    if (target.kind === "colour") {
      setColours((cs) => cs.map((c) => (c.name === target.name ? { ...c, own: design } : c)));
      setPreviewed(target.name);
    }
    setPicking(null);
  }

  function useAutomatic(name: string) {
    setColours((cs) => cs.map((c) => (c.name === name ? { ...c, own: null } : c)));
  }

  function toggle(name: string) {
    // Turning a colour off drops its own design with it.
    setColours((cs) => cs.map((c) => (c.name === name ? { ...c, enabled: !c.enabled, own: c.enabled ? null : c.own } : c)));
  }

  const badge = issues.length;

  return (
    <div className="editor">
      <div className="page-head page-head--editor">
        <span className="page-head__crumb">Listings</span>
        <span className="page-head__sep">/</span>
        <h1 className="page-head__title">{props.listing}</h1>
        <StatusTag status="live" />
        <span className="page-head__meta">Saved a moment ago</span>
        <div className="page-head__actions dv-head-actions">
          <button className="btn btn-primary" type="button">
            Deploy changes →
          </button>
        </div>
      </div>

      <IssuesBanner issues={issues} activeTab="variants" onJumpTo={() => {}} />

      <ArtworkStrip
        base={base}
        colours={colours}
        onOne={enterOne}
        onLightDark={enterLightDark}
        onPick={setPicking}
        onPreview={setPreviewed}
      />

      <div className="tabs seg">
        <div className="seg-opt seg-opt--on">
          Variants
          {badge > 0 && <span className="tab-badge tab-badge--warn">{badge}</span>}
        </div>
        <div className="seg-opt">Pricing</div>
        <div className="seg-opt">Listing Images</div>
        <div className="seg-opt">Listing Details</div>
      </div>

      <div className="layout--variants">
        <fieldset>
          <legend>Variants</legend>
          <div className="field">
            <label htmlFor="ma-garment">Garment profile</label>
            <select id="ma-garment" defaultValue={props.profile}>
              <option>{props.profile}</option>
            </select>
          </div>
          <div className="field">
            <div className="colors-panel__head">
              <label style={{ margin: 0 }}>Colours</label>
              <span className="colors-panel__count">
                {colours.filter((c) => c.enabled).length} of {colours.length} included
              </span>
            </div>
            {colours.map((colour) => (
              <ColourRow
                key={colour.name}
                colour={colour}
                resolution={resolve(colour, base)}
                selected={colour.name === shown.name}
                onPreview={() => setPreviewed(colour.name)}
                onToggle={() => toggle(colour.name)}
                onPick={() => {
                  setPreviewed(colour.name);
                  setPicking({ kind: "colour", name: colour.name });
                }}
              />
            ))}
          </div>
        </fieldset>

        <div className="variants-preview">
          <div className="preview-stage preview-stage--large ma-stage">
            <ShirtPreview
              colour={shown.swatch}
              artwork={resolvedDesign(resolve(shown, base))?.url ?? null}
              label={`${cap(shown.name)} shirt preview`}
            />
          </div>
          <PrintsCard
            colour={shown}
            resolution={resolve(shown, base)}
            base={base}
            profile={props.profile}
            onPick={() => setPicking({ kind: "colour", name: shown.name })}
            onPickSlot={(tone) => setPicking({ kind: "slot", tone })}
            onAutomatic={() => useAutomatic(shown.name)}
          />
        </div>
      </div>

      {picking !== null && (
        <ArtworkPicker
          target={picking}
          base={base}
          colours={colours}
          library={props.library}
          onPick={(d) => pick(picking, d)}
          onClose={() => setPicking(null)}
        />
      )}

      {leaving && base.mode === "light-dark" && (
        <BackToOneDialog
          base={base}
          colours={colours}
          onKeep={(design) => {
            setBase({ mode: "one", design });
            setLeaving(false);
          }}
          onCancel={() => setLeaving(false)}
        />
      )}
    </div>
  );
}

/* ── the design strip above the tabs ─────────────────────────────────────── */

function ArtworkStrip({
  base,
  colours,
  onOne,
  onLightDark,
  onPick,
  onPreview,
}: {
  base: Base;
  colours: Colour[];
  onOne: () => void;
  onLightDark: () => void;
  onPick: (t: PickTarget) => void;
  onPreview: (name: string) => void;
}) {
  const own = colours.filter((c) => c.enabled && c.own !== null);
  return (
    <div className="design-select ma-strip">
      <div className="ma-strip__head">
        <div className="seg ma-mode" role="radiogroup" aria-label="Artwork">
          <label className="seg-opt">
            <input type="radio" name="ma-mode" checked={base.mode === "one"} onChange={onOne} />
            One design for all shirts
          </label>
          <label className="seg-opt">
            <input type="radio" name="ma-mode" checked={base.mode === "light-dark"} onChange={onLightDark} />
            Separate designs for light and dark shirts
          </label>
        </div>
        {own.length > 0 && (
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
        )}
      </div>

      {base.mode === "one" ? (
        <div className="ma-slots ma-slots--one">
          <Slot
            title={null}
            design={base.design}
            tile={TILE.neutral}
            users={null}
            emptyText="No design selected"
            onChange={() => onPick({ kind: "one" })}
          />
        </div>
      ) : (
        <div className="ma-slots">
          {(["light", "dark"] as const).map((tone) => {
            const users = slotUsers(colours, tone);
            return (
              <Slot
                key={tone}
                title={`For ${toneLabel(tone)}`}
                design={base[tone]}
                tile={TILE[tone]}
                users={users.map((c) => c.name)}
                missing={base[tone] === null && users.length > 0}
                emptyText={`Choose the design for ${toneLabel(tone)}`}
                onChange={() => onPick({ kind: "slot", tone })}
              />
            );
          })}
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
  missing = false,
  emptyText,
  onChange,
}: {
  title: string | null;
  design: Design | null;
  tile: string;
  /** Colours printing this slot; `null` in one-design mode, where it is all of them. */
  users: string[] | null;
  missing?: boolean;
  emptyText: string;
  onChange: () => void;
}) {
  const usedBy =
    users === null ? null : users.length === 0 ? "Not used — no colour you sell needs it" : `Prints on ${listNames(users)}`;
  return (
    <div className={missing ? "design-row ma-slot ma-slot--missing" : "design-row ma-slot"}>
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
          <div className="design-row__name">{design.name}</div>
        ) : (
          <div className="design-row__name design-row__name--empty">{emptyText}</div>
        )}
        <div className={users !== null && users.length === 0 ? "ma-slot__users ma-slot__users--idle" : "ma-slot__users"}>
          {usedBy ?? design?.file ?? "Choose the artwork Variants and Listing Images are about"}
        </div>
      </div>
      <button type="button" className="design-row__change" onClick={onChange}>
        {design === null ? "Choose" : "Change"} <CaretDownIcon weight="bold" aria-hidden="true" />
      </button>
    </div>
  );
}

/* ── Variants rows and the card under the preview ─────────────────────────── */

function ColourRow({
  colour,
  resolution,
  selected,
  onPreview,
  onToggle,
  onPick,
}: {
  colour: Colour;
  resolution: Resolution;
  selected: boolean;
  onPreview: () => void;
  onToggle: () => void;
  onPick: () => void;
}) {
  const design = resolvedDesign(resolution);
  const rowClass = ["color-row", selected ? "color-row--selected" : "", colour.enabled ? "" : "color-row--off"]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={rowClass}>
      <button type="button" className="color-row__text" aria-label={`Preview ${colour.name}`} onClick={onPreview}>
        <span className="color-row__swatch" style={{ background: colour.swatch }} aria-hidden="true" />
        <span className="color-row__name">{colour.name}</span>
        {resolution.kind === "own" && colour.enabled && <span className="tag tag-accent-2 ma-own-tag">own design</span>}
      </button>
      {colour.enabled && (
        <button
          type="button"
          className={[
            "ma-chip",
            resolution.kind === "own" ? "ma-chip--own" : "",
            design === null ? "ma-chip--empty" : "",
          ]
            .filter(Boolean)
            .join(" ")}
          style={design !== null ? { background: colour.swatch } : undefined}
          aria-label={`Select different design for ${colour.name}`}
          title="Select different design"
          onClick={onPick}
        >
          {design !== null && <img src={design.url} alt="" />}
        </button>
      )}
      {colour.tone !== null ? (
        <span className={colour.tone === "dark" ? "tag tag-neutral" : "tag tag-accent"}>{colour.tone}</span>
      ) : (
        <span className="tag tag-dirty">no tone</span>
      )}
      <button
        type="button"
        role="switch"
        aria-checked={colour.enabled}
        aria-label={colour.name}
        className={colour.enabled ? "switch switch--on" : "switch"}
        onClick={onToggle}
      >
        <span className="switch__knob" />
      </button>
    </div>
  );
}

function PrintsCard({
  colour,
  resolution,
  base,
  profile,
  onPick,
  onPickSlot,
  onAutomatic,
}: {
  colour: Colour;
  resolution: Resolution;
  base: Base;
  profile: string;
  onPick: () => void;
  onPickSlot: (tone: Tone) => void;
  onAutomatic: () => void;
}) {
  const name = cap(colour.name);
  if (!colour.enabled) {
    return <p className="variants-preview__hint">{name} isn&rsquo;t sold on this listing. Switch it on to choose what it prints.</p>;
  }

  let title: string;
  let why: string;
  if (resolution.kind === "unclassified") {
    title = `${name} can’t pick a design yet`;
    why = `The ${profile} garment profile doesn’t say whether ${colour.name} is a light or dark shirt. Mark it in garment-profiles/${profile}.yaml — this listing can’t decide it.`;
  } else if (resolution.kind === "own") {
    const fallback = base.mode === "one" ? base.design : colour.tone === null ? null : base[colour.tone];
    title = `${name} prints ${resolution.design.name}`;
    why =
      `Its own design, for ${name} only.` +
      (fallback !== null
        ? ` Back on automatic it would print ${fallback.name}${base.mode === "light-dark" && colour.tone !== null ? `, the design for ${toneLabel(colour.tone)}` : ""}.`
        : "");
  } else if (resolution.design === null) {
    title = `${name} has nothing to print`;
    why =
      resolution.kind === "slot"
        ? `It’s a ${resolution.tone} shirt, and no design for ${toneLabel(resolution.tone)} is chosen yet.`
        : "Choose a design above.";
  } else {
    title = `${name} prints ${resolution.design.name}`;
    why =
      resolution.kind === "slot"
        ? `Automatic: the design for ${toneLabel(resolution.tone)}, because ${profile} marks ${colour.name} ${resolution.tone}.`
        : "Automatic: the one design for all shirts.";
  }

  const design = resolvedDesign(resolution);
  return (
    <div className={resolution.kind === "unclassified" ? "ma-prints ma-prints--blocked" : "ma-prints"}>
      {design !== null ? (
        <span className="ma-prints__thumb" style={{ background: colour.swatch }}>
          <img src={design.url} alt="" />
        </span>
      ) : (
        <span className="ma-prints__thumb ma-tile--empty" />
      )}
      <div className="ma-prints__text">
        <div className="ma-prints__title">{title}</div>
        <div className="ma-prints__why">{why}</div>
        {design !== null && <div className="ma-prints__note">Listing Images and Printify use this same file.</div>}
      </div>
      {resolution.kind !== "unclassified" && (
        <div className="ma-prints__actions">
          {resolution.kind === "own" ? (
            <>
              <button type="button" className="btn-like btn-sm ma-btn" onClick={onPick}>
                Change
              </button>
              <button type="button" className="btn-like btn-like--ghost btn-sm ma-btn" onClick={onAutomatic}>
                Use automatic design
              </button>
            </>
          ) : resolution.kind === "slot" && resolution.design === null ? (
            <>
              <button type="button" className="btn-like btn-like--primary btn-sm ma-btn" onClick={() => onPickSlot(resolution.tone)}>
                Choose design for {toneLabel(resolution.tone)}
              </button>
              <button type="button" className="btn-like btn-like--ghost btn-sm ma-btn" onClick={onPick}>
                Select different design for {name}
              </button>
            </>
          ) : (
            <button type="button" className="btn-like btn-sm ma-btn" onClick={onPick}>
              Select different design
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/* ── picking a file from the design library ───────────────────────────────── */

function ArtworkPicker({
  target,
  base,
  colours,
  library,
  onPick,
  onClose,
}: {
  target: PickTarget;
  base: Base;
  colours: Colour[];
  library: Design[];
  onPick: (d: Design) => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  let title: string;
  let hint: string;
  let tile: string;
  let current: Design | null;
  if (target.kind === "colour") {
    const colour = colours.find((c) => c.name === target.name) as Colour;
    const siblings = colours.filter(
      (c) => c.enabled && c.own === null && c.name !== colour.name && (base.mode === "one" || c.tone === colour.tone),
    );
    title = `Design for ${cap(colour.name)}`;
    hint =
      `Only ${cap(colour.name)} changes.` +
      (siblings.length > 0
        ? ` ${listNames(siblings.map((c) => c.name))} keep${siblings.length === 1 ? "s" : ""} ${base.mode === "one" ? "the design for all shirts" : colour.tone === null ? "their design" : `the design for ${toneLabel(colour.tone)}`}.`
        : "");
    tile = colour.swatch;
    current = resolvedDesign(resolve(colour, base));
  } else if (target.kind === "slot") {
    title = `Design for ${toneLabel(target.tone)}`;
    const users = slotUsers(colours, target.tone);
    hint = users.length > 0 ? `Prints on ${listNames(users.map((c) => c.name))}.` : "No colour you sell uses it right now.";
    tile = TILE[target.tone];
    current = base.mode === "light-dark" ? base[target.tone] : null;
  } else {
    title = "Design for all shirts";
    hint = "Every colour prints it, apart from any with their own design.";
    tile = TILE.neutral;
    current = base.mode === "one" ? base.design : null;
  }
  const matches = library.filter((d) => d.name.includes(query.toLowerCase()));

  return (
    <div className="modal-root" role="dialog" aria-modal="true" aria-label={title}>
      <div className="modal-backdrop" onClick={onClose} aria-hidden="true" />
      <div className="modal-dialog ma-picker">
        <div className="modal-dialog__head">
          <h2 className="modal-dialog__title">{title}</h2>
          <button type="button" className="modal-dialog__close" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>
        <p className="ma-picker__hint">{hint}</p>
        <div className="ma-search">
          <MagnifyingGlassIcon weight="bold" aria-hidden="true" />
          <input
            className="input"
            type="text"
            placeholder="Search your designs…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="modal-dialog__list">
          {matches.map((d) => {
            const on = current?.file === d.file;
            return (
              <button
                key={d.file}
                type="button"
                className={on ? "modal-design-row ma-pick ma-pick--on" : "modal-design-row ma-pick"}
                onClick={() => onPick(d)}
              >
                <span className="modal-design-row__thumb ma-tile" style={{ background: tile }}>
                  <img src={d.url} alt="" />
                </span>
                <span className="ma-pick__text">
                  <span className="modal-design-row__name">{d.name}</span>
                  <span className="modal-design-row__file">{d.file}</span>
                </span>
                {on && (
                  <span className="ma-pick__current">
                    <CheckIcon weight="bold" aria-hidden="true" /> Current
                  </span>
                )}
              </button>
            );
          })}
          {matches.length === 0 && <p className="modal-empty">No designs match your search</p>}
        </div>
      </div>
    </div>
  );
}

/* ── leaving light/dark ──────────────────────────────────────────────────── */

function BackToOneDialog({
  base,
  colours,
  onKeep,
  onCancel,
}: {
  base: Extract<Base, { mode: "light-dark" }>;
  colours: Colour[];
  onKeep: (d: Design) => void;
  onCancel: () => void;
}) {
  const [choice, setChoice] = useState<Tone | null>(null);
  const own = colours.filter((c) => c.enabled && c.own !== null);
  return (
    <div className="modal-root" role="dialog" aria-modal="true" aria-labelledby="ma-leave-title">
      <div className="modal-backdrop" onClick={onCancel} aria-hidden="true" />
      <div className="modal-dialog confirm-dialog ma-leave">
        <h2 id="ma-leave-title" className="confirm-dialog__title">
          Which design should every shirt print?
        </h2>
        <p className="ma-leave__body">
          Pick the one to keep. The other stays in your design library.
        </p>
        <div className="ma-leave__options" role="radiogroup" aria-label="Design to keep">
          {(["light", "dark"] as const).map((tone) => {
            const d = base[tone] as Design;
            const on = choice === tone;
            return (
              <button
                key={tone}
                type="button"
                role="radio"
                aria-checked={on}
                className={on ? "template-card template-card--active ma-keep" : "template-card ma-keep"}
                onClick={() => setChoice(tone)}
              >
                <span className="design-thumb ma-tile" style={{ background: TILE[tone] }}>
                  <img src={d.url} alt="" />
                </span>
                <span className="ma-keep__text">
                  <span className="template-card__name">{d.name}</span>
                  <span className="template-card__kind">Now the design for {toneLabel(tone)}</span>
                </span>
              </button>
            );
          })}
        </div>
        {own.length > 0 && (
          <p className="ma-leave__note">
            {listNames(own.map((c) => c.name))} keep{own.length === 1 ? "s" : ""} {own.length === 1 ? "its" : "their"} own design.
          </p>
        )}
        <div className="confirm-dialog__actions">
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={choice === null}
            onClick={() => choice !== null && onKeep(base[choice] as Design)}
          >
            Use one design
          </button>
        </div>
      </div>
    </div>
  );
}
