import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { useCallback, useRef, useState } from "react";
import type {
  SettingsChanges,
  SettingsOutcome,
  TemplatePositionLimits,
} from "../../api/workspaceSettings";
import { TemplateLimitsDialog } from "./TemplateLimitsDialog";
import { ROWS, toDraft, toLimits } from "./templateLimits";

type Confirmed = Promise<(SettingsOutcome & { revision?: string }) | null>;

/**
 * Settings > Template rendering (template positions PR 5; ADR-0058). Unlike
 * the rest of Admin these limits never save on blur: a change can block saved
 * listing positions and, for Marigold templates, may need preparation to run
 * again (option B), so edits stay a draft until the confirmation's Save. The
 * draft lives while the page stays mounted and drops on reload, when
 * `SettingsPanel` remounts this with the reloaded file.
 */
export function TemplatePositions({
  limits,
  active,
  onConfirm,
}: {
  limits: TemplatePositionLimits;
  /** Whether this subsection is shown; hidden, it keeps its draft. */
  active: boolean;
  onConfirm: (changes: SettingsChanges) => Confirmed;
}) {
  const [saved, setSaved] = useState(() => toDraft(limits));
  const [draft, setDraft] = useState(saved);
  const [reviewing, setReviewing] = useState(false);
  const reviewButton = useRef<HTMLButtonElement>(null);
  const title = useRef<HTMLHeadingElement>(null);
  const changed = ROWS.some(({ key }) => draft[key] !== saved[key]);

  const cancel = useCallback(() => {
    setReviewing(false);
    queueMicrotask(() => reviewButton.current?.focus());
  }, []);

  const save = async () => {
    const outcome = await onConfirm({ template_positions: toLimits(draft) });
    if (outcome?.kind === "saved") {
      const next = toDraft(outcome.settings.template_positions);
      setSaved(next);
      setDraft(next);
      setReviewing(false);
      // Review and save is disabled now; keep focus in the panel.
      queueMicrotask(() => title.current?.focus());
      return;
    }
    if (outcome === null || outcome.kind === "conflict")
      throw new Error(
        "settings.yaml changed on disk since this page loaded it. Nothing was overwritten. " +
          "Reload settings, then make your change again.",
      );
    throw new Error(Object.values(outcome.fieldErrors).join(" ") || outcome.message);
  };

  return (
    <section className="b-panel" aria-labelledby="tl-title">
      <div className="b-panel__head">
        <div>
          <h2 className="b-panel__title" id="tl-title" ref={title} tabIndex={-1}>
            Template positions
          </h2>
          <p className="b-panel__lede">
            How far a listing may move the design away from a mockup template's own box. Mockups
            only: Printify always prints centred at full size, so keep these small enough that the
            photo stays honest.
          </p>
        </div>
        {active && !changed && (
          <span className="adm-save adm-save--ok">
            <CheckCircleIcon size={14} /> Saved
          </span>
        )}
      </div>
      {ROWS.map((row) => (
        <div className="tl-row" key={row.key}>
          <div className="tl-row__label">
            <span>{row.label}</span>
            <span className="tl-row__hint">{row.hint}</span>
          </div>
          <div className="sp-slider">
            <span className="sp-slider__value" aria-hidden="true">
              <strong>
                {draft[row.key]}
                {row.unit}
              </strong>
            </span>
            <input
              type="range"
              min={row.min}
              max={row.max}
              step={row.step}
              value={draft[row.key]}
              aria-label={row.label}
              aria-valuetext={`${draft[row.key]}${row.unit} ${row.hint}`}
              style={{
                ["--sp-fill" as string]: `${((draft[row.key] - row.min) / (row.max - row.min)) * 100}%`,
              }}
              onChange={(event) =>
                setDraft((current) => ({ ...current, [row.key]: Number(event.target.value) }))
              }
            />
          </div>
        </div>
      ))}
      <div
        className={changed ? "adm-warn tl-cost tl-cost--live" : "tl-cost"}
        role={changed ? "alert" : undefined}
      >
        <WarningIcon size={18} />
        <span>
          <strong>Saving changes what every listing's position is checked against.</strong> Widening
          the limits may need Marigold preparation to run again; narrowing blocks any listing whose
          saved position falls outside.
        </span>
      </div>
      <div className="tl-foot">
        <button
          type="button"
          className="btn btn-ghost"
          disabled={!changed}
          onClick={() => setDraft(saved)}
        >
          Discard
        </button>
        <button
          ref={reviewButton}
          type="button"
          className="btn btn-primary"
          disabled={!changed}
          onClick={() => setReviewing(true)}
        >
          Review and save…
        </button>
      </div>
      {reviewing && (
        <TemplateLimitsDialog saved={saved} draft={draft} onCancel={cancel} onSave={save} />
      )}
    </section>
  );
}
