import { useEffect, useRef, useState } from "react";
import {
  getTemplatePositionImpact,
  type TemplatePositionImpact,
} from "../../api/workspaceSettings";
import { type LimitDraft, ROWS, toLimits } from "./templateLimits";
import { AlarmDialog } from "./AlarmDialog";

type Impact =
  | { kind: "loading" }
  | { kind: "read"; impact: TemplatePositionImpact }
  | { kind: "failed"; message: string };

/**
 * The template limits confirmation (interactions, *Settings: Template
 * rendering*; option B). Opening it reads the candidate limits' impact and
 * writes nothing. It reuses the currency dialog's alarm header and keyboard
 * rules: Keep current limits, the close button, Escape and the backdrop
 * cancel and keep the draft; focus stays inside. A failed save stays open
 * with its reason.
 */
export function TemplateLimitsDialog({
  saved,
  draft,
  onCancel,
  onSave,
}: {
  saved: LimitDraft;
  draft: LimitDraft;
  onCancel: () => void;
  /** Resolves once saved; rejects with the reason to show. */
  onSave: () => Promise<void>;
}) {
  const [impact, setImpact] = useState<Impact>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const keep = useRef<HTMLButtonElement>(null);
  const candidate = useRef(toLimits(draft));

  useEffect(() => keep.current?.focus(), []);
  useEffect(() => {
    let active = true;
    getTemplatePositionImpact(candidate.current).then(
      (read) => active && setImpact({ kind: "read", impact: read }),
      (reason: unknown) =>
        active &&
        setImpact({
          kind: "failed",
          message: reason instanceof Error ? reason.message : "the read failed",
        }),
    );
    return () => {
      active = false;
    };
  }, []);

  const inference = impact.kind === "read" ? impact.impact.templates_needing_inference : [];
  const changes = ROWS.filter(({ key }) => saved[key] !== draft[key]).map(
    ({ key, label, unit }) => `${label}: ${saved[key]}${unit} → ${draft[key]}${unit}`,
  );

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSave();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save settings.yaml");
      setBusy(false);
    }
  };

  return (
    <AlarmDialog
      titleId="tl-confirm"
      title={inference.length > 0 ? `Refit ${templates(inference.length)}?` : "Save new limits?"}
      lede={
        inference.length > 0
          ? "It runs in the background. You can keep working."
          : "Listings are checked against them the next time they render or deploy."
      }
      onCancel={onCancel}
    >
      <div className="sa-modal__body">
        <ul className="sp-modal__facts">
          <li>
            <strong>{changes.join("; ")}.</strong>
            {inference.length > 0 && (
              <>
                {" "}
                {listed(inference)} {inference.length === 1 ? "needs its" : "need their"}{" "}
                preparation extended to cover the wider limits; the Marigold model runs once per
                template in the background.
              </>
            )}
          </li>
          <li>
            <Outside impact={impact} />
          </li>
        </ul>
        {error !== null && (
          <p className="adm-error-text" role="alert">
            {error}
          </p>
        )}
      </div>
      <div className="sa-modal__foot sd-foot">
        <button ref={keep} type="button" className="btn btn-ghost" onClick={onCancel}>
          Keep current limits
        </button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy || impact.kind === "loading"}
          onClick={() => void confirm()}
        >
          {inference.length > 0 ? "Save and refit" : "Save"}
        </button>
      </div>
    </AlarmDialog>
  );
}

function Outside({ impact }: { impact: Impact }) {
  if (impact.kind === "loading") return <span role="status">Checking saved positions…</span>;
  if (impact.kind === "failed")
    return (
      <>
        <strong>Could not check saved positions.</strong> {impact.message}. The next plan still
        blocks any listing outside the new limits.
      </>
    );
  const { outside } = impact.impact;
  if (outside.length === 0)
    return (
      <>
        <strong>Nothing else changes.</strong> Saved positions stay as they are; none fall outside
        the new limits.
      </>
    );
  return (
    <>
      <strong>
        {outside.length === 1 ? "1 listing falls" : `${outside.length} listings fall`} outside the
        new limits:
      </strong>{" "}
      {listed(outside.map((row) => row.listing))}; they will block deploying until edited.
    </>
  );
}

function templates(count: number): string {
  return count === 1 ? "1 Marigold template" : `${count} Marigold templates`;
}

/** "a", "a and b", "a, b and c". */
function listed(names: readonly string[]): string {
  if (names.length < 2) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
}
