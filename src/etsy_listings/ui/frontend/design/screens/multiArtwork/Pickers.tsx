import { useState } from "react";
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { MagnifyingGlassIcon } from "@phosphor-icons/react/dist/csr/MagnifyingGlass";
import {
  cap,
  listNames,
  resolve,
  resolvedDesign,
  slotUsers,
  TILE,
  toneLabel,
  type Base,
  type Colour,
  type Design,
  type Tone,
} from "./artwork";
import type { PickTarget } from "./ArtworkEditorScreen";

/* ── picking a file from the design library ───────────────────────────────── */

export function ArtworkPicker({
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

export function BackToOneDialog({
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
